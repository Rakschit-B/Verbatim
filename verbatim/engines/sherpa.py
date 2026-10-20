# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""ONNX engines via sherpa-onnx (k2-fsa, Apache-2.0) — identical on Mac, Windows and Linux.

* NVIDIA Parakeet TDT 0.6B (v2 English / v3 25 European languages): top-10 on the
  Hugging Face Open ASR Leaderboard (mean WER ~6.0% vs ~7.4% for Whisper large-v3),
  with word timings and per-token log-probabilities. Used as the second, independent
  engine for cross-checking, or as the primary engine for English.
* Whisper ONNX: portable fallback (no prompts, no word timings).

Models download once from the sherpa-onnx GitHub releases into the VERBATIM models folder.
"""
from __future__ import annotations

import tarfile
from pathlib import Path

import numpy as np

from ..model import Segment, Transcript, Word
from .base import SR, DecodeOptions, Engine, Progress, logprob_to_prob, slice_audio

RELEASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
PARAKEET = {
    "parakeet-v2": "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",   # English
    "parakeet-v3": "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",   # 25 European languages
}
PARAKEET_V3_LANGS = {"bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de", "el", "hu", "it", "lv", "lt",
                     "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv", "ru", "uk"}
WHISPER_ONNX = {"turbo": "sherpa-onnx-whisper-turbo", "small": "sherpa-onnx-whisper-small",
                "small.en": "sherpa-onnx-whisper-small.en", "large-v3": "sherpa-onnx-whisper-large-v3"}


def ensure_model(name: str, root: Path | None = None, progress: Progress | None = None) -> Path:
    """Fetch a sherpa-onnx model once: Hugging Face mirror first (fast CDN), then the GitHub
    release archive with timeouts, retries and resume. Never blocks forever."""
    from ..download import fetch, hf_snapshot
    from ..platform_info import models_dir

    if root is None:
        from ..models import find_sherpa

        found = find_sherpa(name)  # bundled inside the app, or downloaded earlier
        if found:
            return found
    root = Path(root) if root else models_dir() / "sherpa"
    target = root / name
    if target.exists() and any(target.glob("*.onnx")) and any(target.glob("*tokens.txt")):
        return target
    root.mkdir(parents=True, exist_ok=True)
    got = hf_snapshot(f"csukuangfj/{name}", target, progress, name)
    if got and any(target.glob("*.onnx")) and any(target.glob("*tokens.txt")):
        return target
    archive = fetch(RELEASE + f"{name}.tar.bz2", root / f"{name}.tar.bz2", progress, name)
    if progress:
        progress(1.0, f"Unpacking {name}…")
    with tarfile.open(archive) as tar:
        try:
            tar.extractall(root, filter="data")
        except TypeError:  # Python < 3.12
            tar.extractall(root)
    archive.unlink(missing_ok=True)
    return target


def _pick(folder: Path, pattern: str) -> str:
    files = sorted(folder.glob(pattern))
    int8 = [f for f in files if ".int8." in f.name]
    if not (int8 or files):
        raise FileNotFoundError(f"{pattern} not found in {folder}")
    return str((int8 or files)[0])


def _threads() -> int:
    import os

    return max(1, min(8, (os.cpu_count() or 2)))


class ParakeetEngine(Engine):
    id = "parakeet"
    label = "NVIDIA Parakeet TDT (ONNX)"
    _cache: dict = {}

    def __init__(self, variant: str = "parakeet-v2", model_root: Path | None = None):
        self.variant = variant
        self.model = PARAKEET[variant]
        self.model_root = model_root

    @classmethod
    def available(cls):
        try:
            import sherpa_onnx  # noqa: F401
            return True, ""
        except Exception as exc:
            return False, f"sherpa-onnx not installed ({exc})"

    @staticmethod
    def supports(language: str | None) -> bool:
        return language is None or language in PARAKEET_V3_LANGS

    def _recognizer(self, progress=None):
        if self.model not in self._cache:
            import sherpa_onnx

            d = ensure_model(self.model, self.model_root, progress)
            self._cache[self.model] = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=_pick(d, "encoder*.onnx"), decoder=_pick(d, "decoder*.onnx"),
                joiner=_pick(d, "joiner*.onnx"), tokens=str(d / "tokens.txt"),
                model_type="nemo_transducer", num_threads=_threads())
        return self._cache[self.model]

    def transcribe(self, audio, chunks, opts: DecodeOptions, progress: Progress | None = None) -> Transcript:
        rec = self._recognizer(progress)
        segments: list[Segment] = []
        total = sum(e - s for s, e in chunks) or 1.0
        done = 0.0
        for s, e in chunks:
            stream = rec.create_stream()
            stream.accept_waveform(SR, slice_audio(audio, s, e))
            rec.decode_stream(stream)
            r = stream.result
            words = _tokens_to_words(r.tokens, r.timestamps, list(getattr(r, "durations", []) or []),
                                     list(getattr(r, "ys_log_probs", []) or []), s)
            if words:
                from ..vocabulary import words_to_text

                segments.append(Segment(words[0].start, max(words[-1].end, words[0].start + 0.01),
                                        words_to_text(words), words))
            done += e - s
            if progress:
                progress(done / total, f"{self.label}: {done/60:.1f} of {total/60:.1f} speech-minutes")
        lang = opts.language or ("en" if self.variant == "parakeet-v2" else "auto")
        return Transcript(segments, lang, self.id, self.model)


def _tokens_to_words(tokens, stamps, durations, logprobs, offset: float) -> list[Word]:
    words: list[Word] = []
    cur_text, cur_start, cur_end, cur_lp = "", None, None, []
    for k, tok in enumerate(tokens):
        ts = offset + float(stamps[k]) if k < len(stamps) else offset
        dur = float(durations[k]) if k < len(durations) else 0.08
        lp = logprobs[k] if k < len(logprobs) else None
        starts_word = tok.startswith(" ") or tok.startswith("▁") or not cur_text
        is_punct = tok.strip() and all(not c.isalnum() for c in tok.strip())
        if starts_word and not is_punct and cur_text:
            words.append(Word(cur_text, cur_start, max(cur_end, cur_start + 0.02),
                              logprob_to_prob(min(cur_lp)) if cur_lp else None))
            cur_text, cur_lp = "", []
        if not cur_text:
            cur_start = ts
            tok = " " + tok.lstrip(" ▁")
        else:
            tok = tok.replace("▁", " ")
        cur_text += tok
        cur_end = ts + max(dur, 0.04)
        if lp is not None and not is_punct:
            cur_lp.append(lp)
    if cur_text.strip():
        words.append(Word(cur_text, cur_start, max(cur_end, cur_start + 0.02),
                          logprob_to_prob(min(cur_lp)) if cur_lp else None))
    return [w for w in words if w.text.strip()]


class WhisperOnnxEngine(Engine):
    id = "whisper-onnx"
    label = "Whisper (ONNX, portable)"
    _cache: dict = {}

    def __init__(self, size: str = "turbo", model_root: Path | None = None):
        self.size = size
        self.model = WHISPER_ONNX.get(size, size)
        self.model_root = model_root

    @classmethod
    def available(cls):
        return ParakeetEngine.available()

    def _recognizer(self, language: str, progress=None):
        key = (self.model, language)
        if key not in self._cache:
            import sherpa_onnx

            d = ensure_model(self.model, self.model_root, progress)
            self._cache[key] = sherpa_onnx.OfflineRecognizer.from_whisper(
                encoder=_pick(d, "*encoder*.onnx"), decoder=_pick(d, "*decoder*.onnx"),
                tokens=_pick(d, "*tokens.txt"), language="" if self.size.endswith(".en") else language,
                task="transcribe", num_threads=_threads(), tail_paddings=-1)
        return self._cache[key]

    def transcribe(self, audio, chunks, opts: DecodeOptions, progress: Progress | None = None) -> Transcript:
        lang = opts.language or "en"
        rec = self._recognizer(lang, progress)
        segments = []
        total = sum(e - s for s, e in chunks) or 1.0
        done = 0.0
        for s, e in chunks:
            stream = rec.create_stream()
            stream.accept_waveform(SR, slice_audio(audio, s, e).astype(np.float32))
            rec.decode_stream(stream)
            text = stream.result.text.strip()
            if text:
                segments.append(Segment(s, e, text))
            done += e - s
            if progress:
                progress(done / total, f"{self.label}: {done/60:.1f} of {total/60:.1f} speech-minutes")
        return Transcript(segments, lang, self.id, self.model)
