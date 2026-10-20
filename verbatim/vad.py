"""Voice activity detection with Silero VAD v5 (ONNX, MIT licence).

Why: Whisper invents text ("Thank you for watching", repeated lines) when fed silence or
music. WhisperX and faster-whisper both gate decoding with Silero VAD; VERBATIM does the
same, and also uses the speech map to flag any transcript text that falls outside speech.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .platform_info import asset

SR = 16000
WINDOW = 512
CONTEXT = 64


@dataclass
class VadParams:
    threshold: float = 0.45
    min_speech_ms: int = 200
    min_silence_ms: int = 400
    speech_pad_ms: int = 250
    max_chunk_s: float = 28.0  # Whisper's receptive field is 30 s


class SileroVAD:
    def __init__(self, model_path: str | Path | None = None):
        import onnxruntime as ort

        path = Path(model_path) if model_path else asset("silero_vad.onnx")
        if not path.exists():
            raise FileNotFoundError(f"Silero VAD model missing: {path}")
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])

    def probabilities(self, audio: np.ndarray) -> np.ndarray:
        state = np.zeros((2, 1, 128), dtype=np.float32)
        context = np.zeros((1, CONTEXT), dtype=np.float32)
        sr = np.array(SR, dtype=np.int64)
        n = int(np.ceil(len(audio) / WINDOW))
        padded = np.zeros(n * WINDOW, dtype=np.float32)
        padded[: len(audio)] = audio
        probs = np.empty(n, dtype=np.float32)
        for i in range(n):
            chunk = padded[i * WINDOW:(i + 1) * WINDOW][None, :]
            x = np.concatenate([context, chunk], axis=1)
            out, state = self.session.run(None, {"input": x, "state": state, "sr": sr})
            probs[i] = out[0, 0]
            context = chunk[:, -CONTEXT:]
        return probs

    def speech_regions(self, audio: np.ndarray, p: VadParams | None = None) -> list[tuple[float, float]]:
        """Return [(start_s, end_s)] of speech, following Silero's reference hysteresis."""
        p = p or VadParams()
        probs = self.probabilities(audio)
        self.last_probs = probs
        neg = max(p.threshold - 0.15, 0.01)
        min_sil = p.min_silence_ms * SR / 1000
        min_speech = p.min_speech_ms * SR / 1000
        pad = p.speech_pad_ms * SR / 1000
        regions: list[list[float]] = []
        triggered = False
        start = 0
        temp_end = 0
        for i, prob in enumerate(probs):
            pos = i * WINDOW
            if prob >= p.threshold and temp_end:
                temp_end = 0
            if prob >= p.threshold and not triggered:
                triggered, start = True, pos
                continue
            if prob < neg and triggered:
                if not temp_end:
                    temp_end = pos
                if pos - temp_end < min_sil:
                    continue
                if temp_end - start > min_speech:
                    regions.append([start, temp_end])
                triggered, temp_end = False, 0
        if triggered and len(audio) - start > min_speech:
            regions.append([start, len(audio)])
        total = len(audio)
        out: list[tuple[float, float]] = []
        for s, e in regions:
            s = max(0, s - pad)
            e = min(total, e + pad)
            if out and s <= out[-1][1] * SR:
                out[-1] = (out[-1][0], e / SR)
            else:
                out.append((s / SR, e / SR))
        return out


def _split_long(s: float, e: float, max_chunk_s: float, probs: np.ndarray | None) -> list[tuple[float, float]]:
    """Split a long speech region at its quietest moment (lowest speech probability),
    searched in the second half of each window, so cuts land between words."""
    out = []
    while e - s > max_chunk_s:
        lo, hi = s + max_chunk_s * 0.5, s + max_chunk_s
        if probs is not None and len(probs):
            a, b = int(lo * SR / WINDOW), min(int(hi * SR / WINDOW), len(probs) - 1)
            cut = (a + int(np.argmin(probs[a:b + 1]))) * WINDOW / SR if b > a else hi
        else:
            cut = hi
        out.append((s, cut))
        s = cut
    out.append((s, e))
    return out


def merge_chunks(regions: list[tuple[float, float]], max_chunk_s: float = 28.0,
                 max_gap_s: float = 2.0, probs: np.ndarray | None = None) -> list[tuple[float, float]]:
    """WhisperX-style cut & merge: join neighbouring speech into windows <= max_chunk_s.

    Long single regions are split at pauses so no window exceeds the model's 30 s context.
    """
    pieces: list[tuple[float, float]] = []
    for s, e in regions:
        pieces.extend(_split_long(s, e, max_chunk_s, probs))
    chunks: list[tuple[float, float]] = []
    for s, e in pieces:
        if chunks and e - chunks[-1][0] <= max_chunk_s and s - chunks[-1][1] <= max_gap_s:
            chunks[-1] = (chunks[-1][0], e)
        else:
            chunks.append((s, e))
    return chunks


def speech_coverage(regions: list[tuple[float, float]], start: float, end: float) -> float:
    """Fraction of [start, end] that overlaps detected speech."""
    if end <= start:
        return 0.0
    overlap = sum(max(0.0, min(e, end) - max(s, start)) for s, e in regions)
    return min(1.0, overlap / (end - start))
