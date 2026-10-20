# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Local speaker labels ("who spoke when") — no cloud, no Hugging Face token.

pyannote segmentation-3.0 (MIT) + NVIDIA TitaNet speaker embeddings, run through
sherpa-onnx. Each word gets the speaker whose turn overlaps it most; segments are then
re-split at speaker changes. ElevenLabs Scribe provides its own diarisation instead.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .model import Transcript

SEG_MODEL = ("speaker-segmentation-models", "sherpa-onnx-pyannote-segmentation-3-0", True)
EMB_MODEL = ("speaker-recongition-models", "nemo_en_titanet_small.onnx", False)  # sic: upstream tag spelling
BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/"


def _ensure(tag: str, name: str, archive: bool, root: Path) -> Path:
    import tarfile

    from .download import fetch

    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    if target.exists():
        return target
    if archive:
        tmp = root / f"{name}.tar.bz2"
        fetch(f"{BASE}{tag}/{name}.tar.bz2", tmp, label="speaker model")
        with tarfile.open(tmp) as t:
            try:
                t.extractall(root, filter="data")
            except TypeError:
                t.extractall(root)
        tmp.unlink(missing_ok=True)
    else:
        fetch(f"{BASE}{tag}/{name}", target, label="speaker model")
    return target


def embedding_model(model_root: Path | None = None) -> Path:
    from .platform_info import models_dir

    return _ensure(*EMB_MODEL, Path(model_root) if model_root else models_dir() / "diarization")


def label_order(turns: list[tuple[float, float, int]]) -> dict[int, int]:
    """Cluster id -> speaker number, in order of first appearance (matches assign_speakers)."""
    order: dict[int, int] = {}
    for _, _, spk in turns:
        order.setdefault(spk, len(order) + 1)
    return order


def speaker_turns(audio: np.ndarray, num_speakers: int | None = None, threshold: float = 0.9,
                  model_root: Path | None = None) -> list[tuple[float, float, int]]:
    import os

    import sherpa_onnx

    from .platform_info import models_dir

    root = Path(model_root) if model_root else models_dir() / "diarization"
    seg_dir = _ensure(*SEG_MODEL, root)
    emb = _ensure(*EMB_MODEL, root)
    seg_file = seg_dir / "model.int8.onnx" if (seg_dir / "model.int8.onnx").exists() else seg_dir / "model.onnx"
    threads = max(1, min(8, os.cpu_count() or 2))
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(seg_file)),
            num_threads=threads),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(emb), num_threads=threads),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=num_speakers or -1, threshold=threshold),
        min_duration_on=0.3, min_duration_off=0.5)
    sd = sherpa_onnx.OfflineSpeakerDiarization(config)
    result = sd.process(audio.astype(np.float32)).sort_by_start_time()
    return [(r.start, r.end, r.speaker) for r in result]


def assign_speakers(t: Transcript, turns: list[tuple[float, float, int]]) -> int:
    """Label words by maximum overlap, then split segments at speaker changes."""
    if not turns:
        return 0
    from .engines.base import words_to_segments

    order = label_order(turns)
    words = t.words()
    k = 0
    for w in words:
        best, best_ov = None, 0.0
        while k < len(turns) and turns[k][1] < w.start - 5:
            k += 1
        for s, e, spk in turns[k:k + 12]:
            ov = min(e, w.end) - max(s, w.start)
            if ov > best_ov:
                best, best_ov = spk, ov
        if best is None:  # nearest turn
            best = min(turns, key=lambda x: min(abs(x[0] - w.end), abs(x[1] - w.start)))[2]
        w.speaker = f"Speaker {order[best]}"
    old_flags = [(s.start, s.end, s.flags) for s in t.segments]
    t.segments = words_to_segments(words)
    for seg in t.segments:  # carry review flags over to the re-split segments
        for s, e, flags in old_flags:
            if flags and min(e, seg.end) - max(s, seg.start) > 0:
                seg.flags.extend(f for f in flags if f not in seg.flags)
    return len(order)
