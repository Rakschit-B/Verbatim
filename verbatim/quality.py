# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Accuracy safeguards: hallucination removal, missed-speech detection, confidence review.

Nothing here rewrites what was said. Text is only *removed* when it is a known
hallucination pattern sitting on non-speech audio, or a runaway repetition loop; every
removal is logged. Everything else is *flagged* for human review.
"""
from __future__ import annotations

import re
import zlib

from .model import Segment, Transcript, Word
from .vad import speech_coverage
from .vocabulary import words_to_text

# Phrases Whisper is known to produce on silence/music (from WhisperX, faster-whisper
# and whisper GitHub issue threads). Matched on normalised text.
HALLUCINATION_PATTERNS = [
    r"thank(s| you) (so much )?for watching", r"please subscribe", r"like and subscribe",
    r"subtitles? (by|created by|provided by)", r"amara\.org", r"transcribed by", r"captions? by",
    r"see you (in the )?next (video|time)", r"don'?t forget to subscribe", r"www\.\w+\.(com|org)",
    r"^(you|thank you\.?|bye\.?|okay\.?|\.+|music|\[music\]|♪+)$",
    r"字幕", r"ご視聴ありがとうございました", r"продолжение следует", r"sous-titres",
]
_HALL = re.compile("|".join(HALLUCINATION_PATTERNS), re.I)


def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", s.casefold()).strip()


def compression_ratio(text: str) -> float:
    b = text.encode("utf-8")
    return len(b) / max(1, len(zlib.compress(b)))


def collapse_repetition_loops(seg: Segment, min_repeats_phrase: int = 4, min_repeats_word: int = 6) -> dict | None:
    """Collapse decoder loops like 'and then and then and then and then ...'.

    Real speech repeats too ("no, no, no"), so the limits are generous; at most two
    copies of the looping n-gram are kept and the change is logged.
    """
    words = seg.words
    if len(words) < 8:
        return None
    toks = [re.sub(r"\W", "", w.text.casefold()) for w in words]
    for n in range(1, 9):
        limit = min_repeats_word if n == 1 else min_repeats_phrase
        i = 0
        while i + n * limit <= len(toks):
            gram = toks[i:i + n]
            if not any(gram):
                i += 1
                continue
            reps = 1
            while toks[i + reps * n:i + (reps + 1) * n] == gram:
                reps += 1
            if reps >= limit:
                cut_from, cut_to = i + 2 * n, i + reps * n
                removed = words_to_text(words[cut_from:cut_to])
                del words[cut_from:cut_to]
                seg.text = words_to_text(words)
                seg.flags.append("repetition-loop-collapsed")
                return {"time": round(seg.start, 2), "action": "collapsed repetition loop", "text": removed[:300]}
            i += 1
    return None


def remove_hallucinations(t: Transcript, speech: list[tuple[float, float]] | None) -> list[dict]:
    log: list[dict] = []
    kept: list[Segment] = []
    prev_norm = None
    dup_run = 0
    for seg in t.segments:
        text_n = norm_text(seg.text)
        cov = speech_coverage(speech, seg.start, seg.end) if speech else 1.0
        conf = seg.confidence
        is_pattern = bool(_HALL.search(text_n))
        if speech is not None and cov < 0.15 and (is_pattern or (conf is not None and conf < 0.6) or len(text_n) < 4):
            log.append({"time": round(seg.start, 2), "action": "removed text on non-speech audio", "text": seg.text})
            continue
        if is_pattern and (conf is None or conf < 0.75):
            seg.flags.append("possible-hallucination")
        if speech is not None and cov < 0.5:
            seg.flags.append("low-speech-coverage")
        dup_run = dup_run + 1 if text_n and text_n == prev_norm else 0
        prev_norm = text_n
        if dup_run >= 2:  # third identical line in a row
            log.append({"time": round(seg.start, 2), "action": "removed repeated duplicate line", "text": seg.text})
            continue
        loop = collapse_repetition_loops(seg)
        if loop:
            log.append(loop)
        cr = compression_ratio(seg.text)
        seg.compression_ratio = round(cr, 2)
        if cr > 2.4 and len(seg.text) > 40:
            seg.flags.append("high-compression-ratio")
        kept.append(seg)
    t.segments = kept
    return log


def missed_speech(t: Transcript, speech: list[tuple[float, float]], min_len: float = 1.5) -> list[tuple[float, float]]:
    """Speech regions (per VAD) where the transcript has no words — likely omissions."""
    covered = [(w.start, w.end) for w in t.words()] or [(s.start, s.end) for s in t.segments]
    gaps = []
    for s, e in speech:
        if e - s < min_len:
            continue
        if speech_coverage(covered, s, e) < 0.1:
            gaps.append((round(s, 2), round(e, 2)))
    return gaps


def review_items(t: Transcript, word_threshold: float = 0.5, context: int = 6) -> list[dict]:
    """Low-confidence words grouped into runs, each with surrounding context."""
    items: list[dict] = []
    for seg in t.segments:
        words = seg.words
        i = 0
        while i < len(words):
            w = words[i]
            if w.prob is not None and w.prob < word_threshold:
                j = i
                while j + 1 < len(words) and words[j + 1].prob is not None and words[j + 1].prob < word_threshold:
                    j += 1
                run = words[i:j + 1]
                ctx = words_to_text(words[max(0, i - context):i]) + " [" + words_to_text(run) + "] " + \
                    words_to_text(words[j + 1:j + 1 + context])
                items.append({
                    "start": run[0].start, "end": run[-1].end, "speaker": seg.speaker or "",
                    "text": words_to_text(run), "confidence": round(min(x.prob for x in run if x.prob is not None), 3),
                    "context": ctx.strip(), "reason": "low confidence",
                })
                i = j + 1
            else:
                i += 1
        for f in seg.flags:
            if f in ("possible-hallucination", "low-speech-coverage", "high-compression-ratio"):
                items.append({"start": seg.start, "end": seg.end, "speaker": seg.speaker or "", "text": seg.text[:200],
                              "confidence": round(seg.confidence, 3) if seg.confidence is not None else "",
                              "context": seg.text[:300], "reason": f.replace("-", " ")})
    items.sort(key=lambda x: x["start"])
    return items


def summary(t: Transcript, review: list[dict], gaps: list, threshold: float = 0.5) -> dict:
    words = t.words()
    probs = [w.prob for w in words if w.prob is not None]
    low = sum(1 for p in probs if p < threshold)
    mean = sum(probs) / len(probs) if probs else None
    return {
        "word_count": len(words) or len(t.text.split()),
        "mean_confidence": round(mean, 4) if mean is not None else None,
        "low_confidence_words": low,
        "low_confidence_pct": round(100 * low / len(probs), 2) if probs else None,
        "review_items": len(review),
        "missed_speech_regions": len(gaps),
        "segments_flagged": sum(1 for s in t.segments if s.flags),
    }


def ensure_words(t: Transcript) -> None:
    """Engines without word timings get words spread evenly over the segment."""
    for seg in t.segments:
        if seg.words:
            continue
        toks = seg.text.split()
        if not toks:
            continue
        step = (seg.end - seg.start) / len(toks)
        seg.words = [Word(" " + tok, seg.start + k * step, seg.start + (k + 1) * step, None, seg.speaker)
                     for k, tok in enumerate(toks)]
