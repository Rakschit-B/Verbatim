# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""AI audio restoration ("Restore audio", as in TurboScribe) — opt-in for poor recordings.

GTCRN neural speech enhancement (k2-fsa/sherpa-onnx, ~0.5 MB ONNX model, CPU-fast).
TurboScribe itself recommends restoration only for poor-quality files; VERBATIM's
benchmark agrees (see docs/ACCURACY.md), so it is never on by default.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/gtcrn_simple.onnx"
_DENOISER = None


def _model(model_path: Path | None = None) -> Path:
    if model_path:
        return Path(model_path)
    from .platform_info import models_dir

    p = models_dir() / "restore" / "gtcrn_simple.onnx"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        from .download import fetch

        fetch(MODEL_URL, p, label="audio restoration model")
    return p


def restore(audio: np.ndarray, sr: int = 16000, model_path: Path | None = None) -> np.ndarray:
    global _DENOISER
    import os

    import sherpa_onnx

    if _DENOISER is None:
        cfg = sherpa_onnx.OfflineSpeechDenoiserConfig(
            model=sherpa_onnx.OfflineSpeechDenoiserModelConfig(
                gtcrn=sherpa_onnx.OfflineSpeechDenoiserGtcrnModelConfig(model=str(_model(model_path))),
                num_threads=max(1, min(8, os.cpu_count() or 2))))
        _DENOISER = sherpa_onnx.OfflineSpeechDenoiser(cfg)
    out = []
    step = sr * 60  # process in 1-minute blocks to bound memory on long files
    for i in range(0, len(audio), step):
        r = _DENOISER(audio[i:i + step].astype(np.float32), sr)
        block = np.asarray(r.samples, dtype=np.float32)
        if r.sample_rate != sr:
            raise RuntimeError("denoiser changed the sample rate")
        out.append(block[: len(audio[i:i + step])])
    y = np.concatenate(out) if out else audio
    peak = float(np.max(np.abs(y))) or 1.0
    return (y / peak * 0.9).astype(np.float32) if peak > 1.0 else y
