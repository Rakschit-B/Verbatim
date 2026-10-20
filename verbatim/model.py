# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Engine-neutral transcript data structures."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Word:
    text: str
    start: float
    end: float
    prob: float | None = None  # 0..1 confidence when the engine provides it
    speaker: str | None = None


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    speaker: str | None = None
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    compression_ratio: float | None = None
    flags: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> float | None:
        probs = [w.prob for w in self.words if w.prob is not None]
        if probs:
            return sum(probs) / len(probs)
        if self.avg_logprob is not None:
            import math

            return math.exp(self.avg_logprob)
        return None


@dataclass
class Transcript:
    segments: list[Segment]
    language: str = "unknown"
    engine: str = ""
    model: str = ""
    language_probability: float | None = None
    audio_events: list[dict] = field(default_factory=list)
    speaker_profiles: dict = field(default_factory=dict)  # label -> voice fingerprint (speaker library)

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())

    def words(self) -> list[Word]:
        return [w for s in self.segments for w in s.words]

    def to_dict(self) -> dict:
        d = asdict(self)
        for s, sd in zip(self.segments, d["segments"]):
            sd["confidence"] = s.confidence
        return d

    @staticmethod
    def from_dict(d: dict) -> "Transcript":
        segs = []
        for sd in d.get("segments", []):
            words = [Word(**{k: w.get(k) for k in ("text", "start", "end", "prob", "speaker")}) for w in sd.get("words", [])]
            segs.append(Segment(start=sd["start"], end=sd["end"], text=sd["text"], words=words,
                                speaker=sd.get("speaker"), avg_logprob=sd.get("avg_logprob"),
                                no_speech_prob=sd.get("no_speech_prob"), compression_ratio=sd.get("compression_ratio"),
                                flags=list(sd.get("flags", []))))
        return Transcript(segs, d.get("language", "unknown"), d.get("engine", ""), d.get("model", ""),
                          d.get("language_probability"), d.get("audio_events", []),
                          dict(d.get("speaker_profiles") or {}))
