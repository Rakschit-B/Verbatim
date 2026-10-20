"""Precise word timing by CTC forced alignment (the WhisperX idea, without PyTorch).

Whisper writes good text but its word times are estimates. Here a separate acoustic model —
Meta's Omnilingual ASR 300M CTC (1,600+ languages incl. Hindi and all Indian languages, Apache-2.0),
run through ONNX Runtime — listens again and pins every character of the known text to the
audio frames (20 ms). Word start/end come from where its first/last character is heard.

Words that cannot be aligned (numbers written as digits, symbols, or text the model never hears)
keep their original times, interpolated between aligned neighbours.
"""
from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import numpy as np

from .model import Transcript, Word

MODEL_NAME = "sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-int8-2025-11-12"
MODEL_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{MODEL_NAME}.tar.bz2"
SIZE_MB = 330
FRAME = 0.02          # seconds per output frame (320 samples at 16 kHz)
BLANK = 0
SPACE = 4
MAX_WINDOW = 28.0     # seconds of audio per forward pass
PAD = 0.25


def model_dir(root: Path | None = None) -> Path:
    from .platform_info import models_dir

    return (Path(root) if root else models_dir() / "align") / MODEL_NAME


def is_installed(root: Path | None = None) -> bool:
    d = model_dir(root)
    return (d / "model.int8.onnx").exists() and (d / "tokens.txt").exists()


def ensure(progress=None, root: Path | None = None) -> Path:
    d = model_dir(root)
    if is_installed(root):
        return d
    import tarfile

    from .download import fetch

    d.parent.mkdir(parents=True, exist_ok=True)
    tmp = d.parent / f"{MODEL_NAME}.tar.bz2"
    fetch(MODEL_URL, tmp, progress, "word-timing model")
    with tarfile.open(tmp) as t:
        members = [m for m in t.getmembers() if "test_wavs" not in m.name]
        try:
            t.extractall(d.parent, members=members, filter="data")
        except TypeError:
            t.extractall(d.parent, members=members)
    tmp.unlink(missing_ok=True)
    return d


class Aligner:
    _session = None
    _vocab: dict[str, int] | None = None

    def __init__(self, root: Path | None = None, progress=None):
        d = ensure(progress, root)
        if Aligner._session is None:
            import onnxruntime as ort

            so = ort.SessionOptions()
            so.intra_op_num_threads = max(1, min(8, os.cpu_count() or 2))
            Aligner._session = ort.InferenceSession(str(d / "model.int8.onnx"), so,
                                                    providers=["CPUExecutionProvider"])
            vocab = {}
            for line in (d / "tokens.txt").read_text(encoding="utf-8").splitlines():
                tok, _, idx = line.rpartition(" ")
                if tok and idx.isdigit():
                    vocab[tok] = int(idx)
            Aligner._vocab = vocab

    # ---------------------------------------------------------------- acoustic model
    def log_probs(self, audio: np.ndarray) -> np.ndarray:
        x = audio.astype(np.float32)
        x = (x - x.mean()) / (x.std() + 1e-7)
        logits = self._session.run(None, {"x": x[None]})[0][0]
        m = logits.max(-1, keepdims=True)
        return logits - m - np.log(np.exp(logits - m).sum(-1, keepdims=True))

    def tokens_for(self, word: str) -> list[int]:
        s = unicodedata.normalize("NFC", word.lower().strip())
        out = []
        for ch in s:
            i = self._vocab.get(ch)
            if i is not None and i > 4:
                out.append(i)
        return out

    # ---------------------------------------------------------------- public
    def align(self, audio: np.ndarray, t: Transcript, sr: int = 16000, progress=None) -> dict:
        """Re-time every word in place. Returns stats {aligned, total, windows}."""
        words = [w for s in t.segments for w in s.words if w.text.strip()]
        if not words:
            return {"aligned": 0, "total": 0, "windows": 0}
        windows = _windows(t, len(audio) / sr)
        aligned = 0
        for k, (ws, we, seg_ws) in enumerate(windows):
            a0, a1 = int(ws * sr), int(we * sr)
            if a1 - a0 < sr * 0.2:
                continue
            lp = self.log_probs(audio[a0:a1])
            aligned += self._align_words(lp, ws, [w for s in seg_ws for w in s.words if w.text.strip()])
            if progress:
                progress((k + 1) / len(windows), f"Precise word timing: {k + 1} of {len(windows)}")
        for s in t.segments:  # keep segment bounds consistent with their words
            if s.words:
                s.start = s.words[0].start
                s.end = max(s.words[-1].end, s.start + 0.05)
        return {"aligned": aligned, "total": len(words), "windows": len(windows)}

    def _align_words(self, lp: np.ndarray, offset: float, words: list[Word]) -> int:
        targets, owner = [], []
        for wi, w in enumerate(words):
            ids = self.tokens_for(w.text)
            if not ids:
                continue
            if targets:
                targets.append(SPACE)
                owner.append(-1)
            targets.extend(ids)
            owner.extend([wi] * len(ids))
        if not targets or len(targets) > lp.shape[0]:
            return 0
        path = ctc_viterbi(lp, np.array(targets))
        if path is None:
            return 0
        spans: dict[int, list] = {}
        for ti, (f0, f1, score) in enumerate(path):
            wi = owner[ti]
            if wi < 0:
                continue
            sp = spans.setdefault(wi, [f0, f1, []])
            sp[0], sp[1] = min(sp[0], f0), max(sp[1], f1)
            sp[2].append(score)
        new = {}
        for wi, (f0, f1, scores) in spans.items():
            start, end = offset + f0 * FRAME, offset + (f1 + 1) * FRAME
            if end - start > 4.0 or float(np.mean(scores)) < -8.0:  # implausible: keep the original
                continue
            new[wi] = (round(start, 3), round(end, 3))
        for wi, (a, b) in new.items():
            words[wi].start, words[wi].end = a, b
        _interpolate(words, set(new))
        return len(new)


def _windows(t: Transcript, duration: float) -> list[tuple[float, float, list]]:
    """Group consecutive segments into ≤28 s audio windows."""
    out, cur = [], []
    for s in t.segments:
        if not s.words:
            continue
        if cur and (s.end - cur[0].start > MAX_WINDOW or s.start - cur[-1].end > 3.0):
            out.append(cur)
            cur = []
        cur.append(s)
    if cur:
        out.append(cur)
    res = []
    for group in out:
        ws = max(0.0, min(group[0].start, group[0].words[0].start) - PAD)
        we = min(duration, max(group[-1].end, group[-1].words[-1].end) + PAD)
        res.append((ws, we, group))
    return res


def ctc_viterbi(lp: np.ndarray, targets: np.ndarray):
    """Best CTC path for `targets` through frame log-probs `lp` [T, V].

    Returns, per target token, (first_frame, last_frame, mean_logprob), or None if impossible.
    """
    T = lp.shape[0]
    L = len(targets)
    S = 2 * L + 1
    ext = np.full(S, BLANK, dtype=np.int64)
    ext[1::2] = targets
    emit = lp[:, ext]                                    # [T, S]
    allow_skip = np.zeros(S, dtype=bool)                 # s-2 -> s allowed for non-blank, distinct labels
    allow_skip[3::2] = ext[3::2] != ext[1:-2:2]
    NEG = -1e30
    dp = np.full(S, NEG)
    dp[0] = emit[0, 0]
    if S > 1:
        dp[1] = emit[0, 1]
    back = np.zeros((T, S), dtype=np.int8)               # 0 stay, 1 from s-1, 2 from s-2
    for f in range(1, T):
        stay = dp
        prev1 = np.concatenate(([NEG], dp[:-1]))
        prev2 = np.concatenate(([NEG, NEG], dp[:-2]))
        prev2 = np.where(allow_skip, prev2, NEG)
        best = np.maximum(stay, np.maximum(prev1, prev2))
        choice = np.where(best == stay, 0, np.where(best == prev1, 1, 2)).astype(np.int8)
        dp = best + emit[f]
        back[f] = choice
    end_s = S - 1 if S < 2 or dp[S - 1] >= dp[S - 2] else S - 2
    if dp[end_s] < NEG / 2:
        return None
    states = np.empty(T, dtype=np.int64)
    s = end_s
    for f in range(T - 1, -1, -1):
        states[f] = s
        s -= int(back[f, s])
        if s < 0:
            return None
    spans: list = [None] * L
    for f in range(T):
        st = states[f]
        if st % 2 == 1:
            ti = st // 2
            sc = float(emit[f, st])
            if spans[ti] is None:
                spans[ti] = [f, f, [sc]]
            else:
                spans[ti][1] = f
                spans[ti][2].append(sc)
    if any(sp is None for sp in spans):
        return None
    return [(a, b, float(np.mean(c))) for a, b, c in spans]


def _interpolate(words: list[Word], fixed: set[int]):
    """Words that could not be aligned sit between their aligned neighbours."""
    n = len(words)
    i = 0
    while i < n:
        if i in fixed:
            i += 1
            continue
        j = i
        while j < n and j not in fixed:
            j += 1
        left = words[i - 1].end if i > 0 else None
        right = words[j].start if j < n else None
        if left is not None and right is not None and right > left:
            step = (right - left) / (j - i)
            for k in range(i, j):
                words[k].start = round(left + (k - i) * step, 3)
                words[k].end = round(left + (k - i + 1) * step, 3)
        i = j
