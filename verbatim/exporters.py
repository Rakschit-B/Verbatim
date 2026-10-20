"""Per-file exports. The original file name is preserved everywhere.

TXT · SRT · VTT · CSV · JSON · DOCX (uncertain words highlighted) · Markdown · audit log.
Subtitle cues follow broadcast conventions (<=42 chars/line, <=2 lines, 1–7 s).
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from . import __version__
from .model import Transcript, Word


def stamp(seconds: float, sep: str = ".") -> str:
    ms = max(0, round(float(seconds) * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02}{sep}{ms:03}"


def safe_folder_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "file"


def output_folder(root: Path, source: Path) -> Path:
    base = safe_folder_name(source.name)
    cand = root / base
    i = 2
    marker = ".verbatim_source"
    while cand.exists():
        m = cand / marker
        if m.exists() and m.read_text(encoding="utf-8") == str(source.resolve()):
            return cand  # same source re-run: overwrite its outputs
        cand = root / f"{base}__{i:02d}"
        i += 1
    cand.mkdir(parents=True)
    (cand / marker).write_text(str(source.resolve()), encoding="utf-8")
    return cand


def subtitle_cues(t: Transcript, max_chars: int = 42, max_lines: int = 2, max_dur: float = 7.0,
                  min_dur: float = 1.0) -> list[tuple[float, float, str]]:
    """Broadcast-style cues: <= max_lines lines of <= max_chars, <= max_dur seconds, split at
    pauses and sentence ends; a speaker label opens each new speaker turn."""
    from .engines.base import ABBREVIATIONS

    cues: list[tuple[float, float, str]] = []
    last_speaker = None
    for seg in t.segments:
        words = seg.words or [Word(" " + x, seg.start, seg.end) for x in seg.text.split()]
        lines: list[str] = []
        cue_words: list[Word] = []

        def flush():
            nonlocal lines, cue_words
            if cue_words:
                cues.append((cue_words[0].start, max(cue_words[-1].end, cue_words[0].start + min_dur), "\n".join(lines)))
            lines, cue_words = [], []

        for w in words:
            tok = w.text.strip()
            if not tok:
                continue
            if cue_words and ((w.end - cue_words[0].start) > max_dur or w.start - cue_words[-1].end > 0.8):
                flush()
            if not cue_words and seg.speaker and seg.speaker != last_speaker:
                tok = f"[{seg.speaker}] {tok}"
                last_speaker = seg.speaker
            if lines and len(lines[-1]) + 1 + len(tok) <= max_chars:
                lines[-1] += " " + tok
            elif len(lines) < max_lines:
                lines.append(tok)
            else:
                flush()
                lines = [tok]
            cue_words.append(w)
            ends = tok.endswith((".", "?", "!")) and tok.lower() not in ABBREVIATIONS
            if ends and sum(len(x) for x in lines) > max_chars * 0.6:
                flush()
        flush()
    fixed = []
    for i, (s, e, txt) in enumerate(cues):
        if i + 1 < len(cues):
            e = min(e, cues[i + 1][0] - 0.04)
        fixed.append((s, max(e, s + 0.3), txt))
    return fixed


def cues_has_speaker(cues, speaker) -> bool:
    return bool(cues) and cues[-1][2].startswith(f"[{speaker}]")


def _header(res) -> list[tuple[str, str]]:
    t = res.transcript
    q = res.quality
    rows = [("Source file", res.source.name), ("Source path", str(res.source.resolve())),
            ("Duration", stamp(res.info.get("duration", 0))), ("Language", t.language),
            ("Engine", f"{t.engine} · {t.model}"), ("Words", str(q.get("word_count", ""))),
            ("Mean word confidence", f"{q['mean_confidence']:.1%}" if q.get("mean_confidence") is not None else "n/a"),
            ("Items to review", str(q.get("review_items", 0)))]
    if q.get("agreement") is not None:
        rows.append(("Two-engine agreement", f"{q['agreement']:.1%}"))
    rows.append(("Transcribed", f"{res.finished} · VERBATIM {__version__}"))
    return [(k, "" if v is None else str(v)) for k, v in rows]


def paragraphs(t: Transcript, max_gap: float = 2.5, max_dur: float = 60.0, max_sentences: int = 6) -> list[dict]:
    """TurboScribe-style readable paragraphs: one speaker turn, split at long pauses or
    after a few sentences, each with its start time."""
    out: list[dict] = []
    for seg in t.segments:
        cur = out[-1] if out else None
        sentences = cur["text"].count(". ") + cur["text"].count("? ") + 1 if cur else 0
        if (cur and seg.speaker == cur["speaker"] and seg.start - cur["end"] <= max_gap
                and seg.end - cur["start"] <= max_dur and sentences < max_sentences):
            cur["text"] += " " + seg.text
            cur["end"] = seg.end
            cur["words"] += seg.words
        else:
            out.append({"start": seg.start, "end": seg.end, "speaker": seg.speaker, "text": seg.text,
                        "words": list(seg.words)})
    return out


def _para_lines(t: Transcript, opts) -> list[str]:
    ts, spk_on, para = opts.get("include_timestamps", True), opts.get("include_speakers", True), opts.get("paragraphs", True)
    blocks = paragraphs(t) if para else [{"start": s.start, "end": s.end, "speaker": s.speaker, "text": s.text}
                                         for s in t.segments]
    lines = []
    for b in blocks:
        head = []
        if ts:
            head.append(f"[{stamp(b['start']).split('.')[0]}]" if para else f"[{stamp(b['start'])} - {stamp(b['end'])}]")
        if spk_on and b["speaker"]:
            head.append(f"{b['speaker']}:")
        if head:
            lines.append(" ".join(head))
        lines += [b["text"], ""]
    return lines


def _opts(settings) -> dict:
    keys = ("paragraphs", "include_timestamps", "include_speakers")
    return {k: getattr(settings, k, True) for k in keys} if settings is not None else {}


def export_all(res, root: Path, formats: list[str], settings=None, dest: Path | None = None) -> dict:
    t: Transcript = res.transcript
    dest = Path(dest) if dest else output_folder(Path(root), res.source)
    stem = res.source.stem
    out: dict[str, str] = {"folder": str(dest)}
    fmt = set(formats) | {"json"}
    opts = _opts(settings)

    if res.translation is not None and res.translation.segments:
        tr = res.translation
        (dest / f"{stem} (English translation).txt").write_text(
            "\n".join([f"ENGLISH TRANSLATION OF: {res.source.name}", "Machine translation by Whisper — "
                        "check before publishing.", ""] + _para_lines(tr, opts)), encoding="utf-8")
        cues_tr = subtitle_cues(tr)
        (dest / f"{stem} (English).srt").write_text(
            "".join(f"{i}\n{stamp(a, ',')} --> {stamp(b, ',')}\n{x}\n\n" for i, (a, b, x) in enumerate(cues_tr, 1)),
            encoding="utf-8")
        out["translation"] = str(dest / f"{stem} (English translation).txt")

    if "txt" in fmt:
        lines = [f"{k.upper()}: {v}" for k, v in _header(res)] + ["", "TRANSCRIPT", ""] + _para_lines(t, opts)
        p = dest / f"{stem}.txt"
        p.write_text("\n".join(lines), encoding="utf-8")
        plain = dest / f"{stem} (dialogue only).txt"
        plain.write_text("\n".join((f"{s.speaker}: " if s.speaker else "") + s.text for s in t.segments), encoding="utf-8")
        out["txt"] = str(p)
    cues = subtitle_cues(t) if fmt & {"srt", "vtt"} else []
    if "srt" in fmt:
        p = dest / f"{stem}.srt"
        p.write_text("".join(f"{i}\n{stamp(s, ',')} --> {stamp(e, ',')}\n{txt}\n\n" for i, (s, e, txt) in enumerate(cues, 1)),
                     encoding="utf-8")
        out["srt"] = str(p)
    if "vtt" in fmt:
        p = dest / f"{stem}.vtt"
        p.write_text("WEBVTT\n\n" + "".join(f"{stamp(s)} --> {stamp(e)}\n{txt}\n\n" for s, e, txt in cues), encoding="utf-8")
        out["vtt"] = str(p)
    if "csv" in fmt:
        p = dest / f"{stem}.csv"
        with p.open("w", encoding="utf-8-sig", newline="") as f:  # BOM so Excel shows Hindi etc. correctly
            w = csv.writer(f)
            w.writerow(["Source File", "Start", "End", "Speaker", "Text", "Confidence", "Flags"])
            for s in t.segments:
                c = s.confidence
                w.writerow([res.source.name, stamp(s.start), stamp(s.end), s.speaker or "", s.text,
                            f"{c:.3f}" if c is not None else "", "; ".join(s.flags)])
        out["csv"] = str(p)
    if "json" in fmt:
        p = dest / f"{stem}.json"
        payload = {"source_file": res.source.name, "source_path": str(res.source.resolve()), "info": res.info,
                   "quality": res.quality, "transcript": t.to_dict(), "review": res.review,
                   "corrections": res.corrections, "removals": res.removals,
                   "crosscheck": {k: v for k, v in res.crosscheck.items()}, "version": __version__,
                   "started": res.started, "finished": res.finished}
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        out["json"] = str(p)
    if "md" in fmt:
        p = dest / f"{stem}.md"
        md = [f"# {res.source.name}", ""] + [f"- **{k}:** {v}" for k, v in _header(res)] + ["", "## Transcript", ""]
        for b in paragraphs(t):
            spk = f"**{b['speaker']}** " if b["speaker"] and opts.get("include_speakers", True) else ""
            ts = f"`{stamp(b['start']).split('.')[0]}` " if opts.get("include_timestamps", True) else ""
            md.append(f"{ts}{spk}{b['text']}\n")
        p.write_text("\n".join(md), encoding="utf-8")
        out["md"] = str(p)
    if "docx" in fmt:
        try:
            out["docx"] = str(_docx(res, dest / f"{stem}.docx", opts))
        except ImportError:
            pass
    p = dest / f"{stem} - processing log.txt"
    p.write_text(_audit(res), encoding="utf-8")
    out["log"] = str(p)
    return out


def _docx(res, path: Path, opts: dict | None = None) -> Path:
    from docx import Document
    from docx.enum.text import WD_COLOR_INDEX
    from docx.shared import Pt, RGBColor

    t = res.transcript
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)
    doc.add_heading(res.source.name, level=1)
    table = doc.add_table(rows=0, cols=2)
    table.style = "Light List Accent 1"
    for k, v in _header(res):
        cells = table.add_row().cells
        cells[0].text, cells[1].text = k, v
    note = doc.add_paragraph()
    r = note.add_run("Words highlighted in yellow were transcribed with lower confidence — check them against the audio. "
                     "Engine disagreements and possible missed speech are listed in the Master Log's Review Queue.")
    r.italic = True
    r.font.size = Pt(9)
    thr = res.info.get("review_threshold", 0.8)
    opts = opts or {}
    blocks = paragraphs(t) if opts.get("paragraphs", True) else [
        {"start": s.start, "speaker": s.speaker, "text": s.text, "words": s.words} for s in t.segments]
    for s in blocks:
        s = type("B", (), s)  # attribute access
        p = doc.add_paragraph()
        if opts.get("include_timestamps", True):
            ts = p.add_run(f"[{stamp(s.start).split('.')[0]}] ")
            ts.font.color.rgb = RGBColor(0x91, 0x3A, 0x80)
            ts.font.size = Pt(9)
        if s.speaker and opts.get("include_speakers", True):
            p.add_run(f"{s.speaker}: ").bold = True
        for k, w in enumerate(s.words or [Word(" " + s.text, s.start, 0)]):
            run = p.add_run(w.text.lstrip() if k == 0 else w.text)
            if w.prob is not None and w.prob < thr:
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    doc.save(path)
    return path


def _audit(res) -> str:
    L = [f"VERBATIM {__version__} — processing log", "=" * 60]
    L += [f"{k}: {v}" for k, v in _header(res)]
    L += ["", "AUDIO", *(f"  {k}: {v}" for k, v in res.info.items())]
    L += ["", "QUALITY", *(f"  {k}: {v}" for k, v in res.quality.items())]
    L += ["", f"VOCABULARY CORRECTIONS ({len(res.corrections)})"]
    L += [f"  {stamp(c['time'])}  {c['original']!r} -> {c['corrected']!r}  [{c['rule']}]" for c in res.corrections]
    L += ["", f"REMOVED / COLLAPSED TEXT ({len(res.removals)})"]
    L += [f"  {stamp(r['time'])}  {r['action']}: {r['text']!r}" for r in res.removals]
    if res.crosscheck:
        L += ["", "CROSS-CHECK", f"  second engine: {res.crosscheck.get('secondary_engine', '')}",
              f"  agreement: {res.crosscheck.get('agreement')}", f"  fused words: {res.crosscheck.get('fused_words', 0)}"]
        if res.crosscheck.get("error"):
            L.append(f"  error: {res.crosscheck['error']}")
    L += ["", f"REVIEW QUEUE ({len(res.review)})"]
    L += [f"  {stamp(r['start'])}  {r['reason']}: {r['context']}" for r in res.review]
    L += ["", f"Started {res.started} · finished {res.finished} · {res.seconds}s"]
    return "\n".join(L) + "\n"
