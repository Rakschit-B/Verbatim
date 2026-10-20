"""Transcript editing (used by the editor window): change words or speakers, then re-export.

Edits keep word timings wherever the words did not change (difflib alignment of old vs new
words); new or changed words share the time of what they replaced. Edited words are marked as
human-verified (confidence 1.0), every change is logged to the Master Excel Log as a correction,
and open review items inside edited lines are marked "Corrected".
"""
from __future__ import annotations

import difflib
import json
import re
from datetime import datetime
from pathlib import Path

from .model import Segment, Transcript, Word

_TOKEN = re.compile(r"\S+")


class EditSession:
    def __init__(self, json_path: str | Path):
        self.path = Path(json_path)
        self.payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.t = Transcript.from_dict(self.payload["transcript"])
        self.edits: list[dict] = []
        self.ranges: list[tuple[float, float]] = []

    # ------------------------------------------------------------ info
    @property
    def source(self) -> Path:
        return Path(self.payload.get("source_path") or self.payload.get("source_file", ""))

    @property
    def threshold(self) -> float:
        return float(self.payload.get("info", {}).get("review_threshold", 0.8))

    def speakers(self) -> list[str]:
        seen = []
        for s in self.t.segments:
            if s.speaker and s.speaker not in seen:
                seen.append(s.speaker)
        return seen

    # ------------------------------------------------------------ edits
    def set_text(self, i: int, new_text: str) -> bool:
        seg = self.t.segments[i]
        new_text = " ".join(new_text.split())
        if new_text == " ".join(seg.text.split()):
            return False
        old_words = seg.words or [Word(tok, seg.start, seg.end, None, seg.speaker) for tok in _TOKEN.findall(seg.text)]
        seg.words = retime(old_words, _TOKEN.findall(new_text), seg.start, seg.end, seg.speaker)
        self.edits.append({"time": seg.start, "original": seg.text.strip(), "corrected": new_text,
                           "rule": "manual edit (editor)"})
        seg.text = " " + new_text if seg.text.startswith(" ") else new_text
        if "edited" not in seg.flags:
            seg.flags.append("edited")
        self.ranges.append((seg.start, seg.end))
        return True

    def set_speaker(self, i: int, name: str):
        seg = self.t.segments[i]
        name = name.strip()
        if not name or name == seg.speaker:
            return
        self.edits.append({"time": seg.start, "original": f"[{seg.speaker or 'no speaker'}]", "corrected": f"[{name}]",
                           "rule": "speaker changed (editor)"})
        seg.speaker = name
        for w in seg.words:
            w.speaker = name

    def rename_speaker(self, old: str, new: str) -> int:
        new = new.strip()
        if not new or new == old:
            return 0
        from .speakers import rename_in_transcript

        n = rename_in_transcript(self.t, {old: new})
        if n:
            self.edits.append({"time": 0.0, "original": f"[{old}]", "corrected": f"[{new}]",
                               "rule": "speaker renamed (editor)"})
        return n

    def profile(self, label: str):
        return (self.t.speaker_profiles or {}).get(label)

    # ------------------------------------------------------------ save
    def save(self, settings=None) -> dict:
        """Write the JSON, re-export every format, update the Master Log. Returns output paths."""
        from .exporters import export_all
        from .pipeline import FileResult

        p = self.payload
        res = FileResult(self.source, transcript=self.t, info=p.get("info", {}), quality=p.get("quality", {}),
                         review=p.get("review", []), corrections=p.get("corrections", []) + self.edits,
                         removals=p.get("removals", []), crosscheck=p.get("crosscheck", {}),
                         started=p.get("started", ""), finished=p.get("finished", ""), status="Completed")
        res.info = dict(res.info)
        res.info["edited"] = datetime.now().isoformat(timespec="seconds")
        if self.ranges:  # review items inside edited lines are resolved
            for r in res.review:
                if any(r["start"] < b and r["end"] > a for a, b in self.ranges):
                    r["status"] = "Corrected"
        formats = list(getattr(settings, "formats", None) or ["txt", "srt", "vtt", "csv", "json", "docx", "md"])
        dest = self.path.parent
        res.outputs = export_all(res, dest.parent, formats, settings, dest=dest)
        try:
            from .master_log import MasterLog

            ml = MasterLog(dest.parent)
            if ml.record_manual_edit(str(self.path), self.t, self.edits, self.ranges):
                ml.export_excel()
        except Exception:
            pass
        self.payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.edits, self.ranges = [], []
        return res.outputs


def retime(old: list[Word], new_tokens: list[str], seg_start: float, seg_end: float,
           speaker: str | None) -> list[Word]:
    """New word list that keeps the timings of unchanged words."""
    def key(s):
        return re.sub(r"[^\w']", "", s.lower())

    sm = difflib.SequenceMatcher(a=[key(w.text) for w in old], b=[key(t) for t in new_tokens], autojunk=False)
    out: list[Word] = []
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op == "equal":
            for k in range(b1 - b0):
                w = old[a0 + k]
                out.append(Word(new_tokens[b0 + k], w.start, w.end, w.prob, w.speaker or speaker))
            continue
        if b1 == b0:  # deletion
            continue
        if a1 > a0:
            start, end = old[a0].start, old[a1 - 1].end
        else:  # insertion between neighbours
            start = old[a0 - 1].end if a0 > 0 else seg_start
            end = old[a0].start if a0 < len(old) else seg_end
            if end <= start:
                end = start + 0.2 * (b1 - b0)
        step = (end - start) / (b1 - b0)
        for k in range(b1 - b0):
            out.append(Word(new_tokens[b0 + k], round(start + k * step, 3), round(start + (k + 1) * step, 3),
                            1.0, speaker))
    for w in out:  # editor text is human-verified
        w.prob = 1.0 if w.prob is None or w.prob < 1.0 else w.prob
    return out


def segment_html(seg: Segment, threshold: float, colors: tuple[str, str]) -> str:
    """Line text with uncertain words highlighted (for the editor's list)."""
    import html

    if not seg.words:
        return html.escape(seg.text.strip())
    bg, ink = colors
    parts = []
    for w in seg.words:
        t = html.escape(w.text.strip())
        if w.prob is not None and w.prob < threshold:
            parts.append(f"<span style='background:{bg}; color:{ink}'>{t}</span>")
        else:
            parts.append(t)
    return " ".join(parts)
