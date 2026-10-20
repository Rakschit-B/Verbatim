"""Engine interface and helpers shared by all speech-to-text back-ends."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..model import Segment, Transcript, Word
from ..vocabulary import Vocabulary

SR = 16000
Progress = Callable[[float, str], None]

WHISPER_TEMPERATURES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "prof.", "st.", "inc.", "ltd.", "co.", "corp.", "vs.", "etc.", "e.g.",
                 "i.e.", "no.", "jr.", "sr.", "u.s.", "approx.", "dept.", "govt.", "shri.", "smt."}


@dataclass
class DecodeOptions:
    language: str | None = None          # ISO-639-1, None = auto-detect once per file
    vocabulary: Vocabulary = field(default_factory=Vocabulary)
    verbatim: bool = True                # keep fillers / false starts
    diarize: bool = False
    num_speakers: int | None = None
    beam_size: int = 5
    context: str = ""                    # e.g. the file name — helps names/terms (TurboScribe tip)
    task: str = "transcribe"             # or "translate" (Whisper: any language -> English)


class Engine:
    id = "base"
    label = "Base"
    model = ""

    @classmethod
    def available(cls) -> tuple[bool, str]:
        return False, "not implemented"

    def transcribe(self, audio: np.ndarray, chunks: list[tuple[float, float]], opts: DecodeOptions,
                   progress: Progress | None = None) -> Transcript:
        raise NotImplementedError


def detect_language_chunk(chunks: list[tuple[float, float]]) -> tuple[float, float]:
    """Pick the longest of the first few chunks for one-off language identification."""
    head = chunks[:4] or [(0.0, 30.0)]
    return max(head, key=lambda c: c[1] - c[0])


def slice_audio(audio: np.ndarray, start: float, end: float) -> np.ndarray:
    return audio[int(start * SR):int(end * SR)]


def whisper_segments(raw_segments: list[dict], offset: float, chunk_end: float) -> list[Segment]:
    """Convert openai-whisper-style dict segments (mlx / faster-whisper) to Segments."""
    out = []
    for s in raw_segments:
        get = s.get if isinstance(s, dict) else (lambda k, d=None, _s=s: getattr(_s, k, d))
        words = []
        for w in get("words") or []:
            wg = w.get if isinstance(w, dict) else (lambda k, d=None, _w=w: getattr(_w, k, d))
            words.append(Word(wg("word", ""), offset + float(wg("start", 0)), offset + float(wg("end", 0)),
                              float(wg("probability")) if wg("probability") is not None else None))
        start = offset + float(get("start", 0))
        end = min(offset + float(get("end", 0)), chunk_end + 0.5)
        text = str(get("text", "")).strip()
        if not text:
            continue
        out.append(Segment(start, max(end, start + 0.01), text, words,
                           avg_logprob=get("avg_logprob"), no_speech_prob=get("no_speech_prob"),
                           compression_ratio=get("compression_ratio")))
    return out


def words_to_segments(words: list[Word], max_gap: float = 1.0, max_words: int = 45,
                      max_dur: float = 20.0) -> list[Segment]:
    """Group a flat word stream into readable segments (speaker turn, pause, sentence end)."""
    segs: list[Segment] = []
    cur: list[Word] = []

    def flush():
        if cur:
            from ..vocabulary import words_to_text

            text = words_to_text(cur)
            if text:
                segs.append(Segment(cur[0].start, cur[-1].end, text, list(cur), speaker=cur[0].speaker))
            cur.clear()

    for w in words:
        if cur:
            gap = w.start - cur[-1].end
            last = cur[-1].text.strip()
            sentence_end = last.endswith((".", "?", "!", "।", "。", "？", "！")) and last.lower() not in ABBREVIATIONS
            if (w.speaker != cur[-1].speaker or gap > max_gap or len(cur) >= max_words
                    or w.end - cur[0].start > max_dur or (sentence_end and len(cur) >= 12)):
                flush()
        cur.append(w)
    flush()
    return segs


def logprob_to_prob(lp) -> float | None:
    try:
        return max(0.0, min(1.0, math.exp(float(lp))))
    except (TypeError, ValueError, OverflowError):
        return None
