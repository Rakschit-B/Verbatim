"""Speaker library: name a voice once, VERBATIM recognises it in later files.

Each diarised speaker in a file gets a voice fingerprint (NVIDIA TitaNet embedding, computed
locally from up to 30 s of that speaker's speech). When you name a speaker ("Speaker 2 = Rahul"),
the fingerprint is stored in the library. In later files, a speaker whose fingerprint is close
enough to a named voice is labelled with that name automatically; anyone else stays
"Speaker N". Matching is one-to-one per file and deliberately conservative: a wrong name is
worse than no name.

Fingerprints stay on this computer (VERBATIM data folder / speakers.json). They are not audio
and cannot be turned back into a voice.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np

MATCH_THRESHOLD = 0.60   # cosine; measured: same voice 0.85–0.96, different voices ≤ 0.42 (docs/PHASE2.md)
MAX_PRINTS = 24          # fingerprints kept per named speaker
SECONDS_PER_PRINT = 30.0


def library_path() -> Path:
    from .platform_info import user_data_dir

    return user_data_dir() / "speakers.json"


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


class SpeakerLibrary:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else library_path()
        try:
            self.entries: list[dict] = json.loads(self.path.read_text(encoding="utf-8")).get("speakers", [])
        except (OSError, ValueError):
            self.entries = []

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "speakers": self.entries}), encoding="utf-8")
        tmp.replace(self.path)

    # ------------------------------------------------------------ queries
    def names(self) -> list[str]:
        return [e["name"] for e in self.entries]

    def find(self, name: str) -> dict | None:
        key = name.strip().lower()
        return next((e for e in self.entries if e["name"].strip().lower() == key), None)

    @staticmethod
    def centroid(entry: dict) -> np.ndarray:
        return _unit(np.mean([_unit(p) for p in entry["prints"]], axis=0))

    def similarity(self, entry: dict, vec) -> float:
        v = _unit(vec)
        # best of the centroid and the closest single print: robust to different mics and rooms
        return max([float(self.centroid(entry) @ v)] + [float(_unit(p) @ v) for p in entry["prints"]])

    def match(self, prints: dict[str, list], threshold: float = MATCH_THRESHOLD) -> dict[str, tuple[str, float]]:
        """{label: fingerprint} -> {label: (name, similarity)} — one-to-one, best pairs first."""
        pairs = []
        for label, vec in prints.items():
            for e in self.entries:
                s = self.similarity(e, vec)
                if s >= threshold:
                    pairs.append((s, label, e["name"]))
        out, used_l, used_n = {}, set(), set()
        for s, label, name in sorted(pairs, reverse=True):
            if label in used_l or name in used_n:
                continue
            out[label] = (name, round(s, 3))
            used_l.add(label)
            used_n.add(name)
        return out

    # ------------------------------------------------------------ edits
    def enroll(self, name: str, vec, source: str = "") -> dict:
        name = name.strip()
        e = self.find(name)
        now = datetime.now().isoformat(timespec="seconds")
        if e is None:
            e = {"id": uuid.uuid4().hex[:12], "name": name, "prints": [], "files": [], "created": now}
            self.entries.append(e)
        e["prints"].append([round(float(x), 5) for x in _unit(vec)])
        e["prints"] = e["prints"][-MAX_PRINTS:]
        if source and source not in e["files"]:
            e["files"] = (e["files"] + [source])[-200:]
        e["updated"] = now
        self.save()
        return e

    def rename(self, old: str, new: str) -> bool:
        e = self.find(old)
        if not e or not new.strip():
            return False
        other = self.find(new)
        if other and other is not e:  # merging two names
            other["prints"] = (other["prints"] + e["prints"])[-MAX_PRINTS:]
            other["files"] = list(dict.fromkeys(other["files"] + e["files"]))[-200:]
            self.entries.remove(e)
        else:
            e["name"] = new.strip()
        self.save()
        return True

    def delete(self, name: str) -> bool:
        e = self.find(name)
        if not e:
            return False
        self.entries.remove(e)
        self.save()
        return True


# ---------------------------------------------------------------- fingerprints from audio
def fingerprints(audio: np.ndarray, turns: list[tuple[float, float, int]], order: dict[int, int],
                 model_path: Path, sr: int = 16000) -> dict[str, list]:
    """One TitaNet fingerprint per diarised speaker (label 'Speaker N') from their longest turns."""
    import os

    import sherpa_onnx

    cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(model_path),
                                                      num_threads=max(1, min(4, os.cpu_count() or 2)))
    ex = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
    by_spk: dict[int, list] = {}
    for s, e, spk in turns:
        if e - s >= 0.6:
            by_spk.setdefault(spk, []).append((s, e))
    out = {}
    for spk, spans in by_spk.items():
        spans.sort(key=lambda x: x[1] - x[0], reverse=True)
        pieces, total = [], 0.0
        for s, e in spans:
            pieces.append(audio[int(s * sr):int(e * sr)])
            total += e - s
            if total >= SECONDS_PER_PRINT:
                break
        if total < 1.5:
            continue
        stream = ex.create_stream()
        stream.accept_waveform(sr, np.concatenate(pieces).astype(np.float32))
        stream.input_finished()
        vec = _unit(ex.compute(stream))
        out[f"Speaker {order[spk]}"] = [round(float(x), 5) for x in vec]
    return out


def rename_in_transcript(t, mapping: dict[str, str]) -> int:
    """Rename speaker labels (e.g. 'Speaker 2' -> 'Rahul') in words and segments."""
    n = 0
    for seg in t.segments:
        if seg.speaker in mapping:
            seg.speaker = mapping[seg.speaker]
            n += 1
        for w in seg.words:
            if w.speaker in mapping:
                w.speaker = mapping[w.speaker]
    if getattr(t, "speaker_profiles", None):
        t.speaker_profiles = {mapping.get(k, k): v for k, v in t.speaker_profiles.items()}
    return n
