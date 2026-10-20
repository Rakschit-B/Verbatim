# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Command-line interface (headless batches, accuracy tests, log rebuilds).

  VERBATIM --cli transcribe <files/folders…> [--out DIR] [--engine whisper|parakeet|elevenlabs] …
  VERBATIM --cli accuracy <reference.txt> <transcript.txt|.json> [--prefix] [--xlsx report.xlsx]
  VERBATIM --cli rebuild-log [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .settings import LANGUAGES, Settings


def _transcript_text(path: Path) -> str:
    if path.suffix == ".json":
        d = json.loads(path.read_text(encoding="utf-8"))
        segs = d.get("transcript", d).get("segments", [])
        return " ".join(s["text"] for s in segs)
    text = path.read_text(encoding="utf-8")
    if "\nTRANSCRIPT\n" in text:  # VERBATIM .txt: drop header and timestamps
        import re

        body = text.split("\nTRANSCRIPT\n", 1)[1]
        return " ".join(l for l in body.splitlines() if l.strip() and not re.match(r"^\[\d\d:\d\d:\d\d", l))
    return text


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="VERBATIM --cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("transcribe")
    t.add_argument("paths", nargs="+")
    t.add_argument("--out")
    t.add_argument("--engine", choices=["whisper", "parakeet", "elevenlabs", "whisper-onnx"])
    t.add_argument("--variant")
    t.add_argument("--language", help="ISO code (en, hi, …) or 'auto'")
    t.add_argument("--vocab", help="text file of names/terms, one per line ('wrong => right' rules allowed)")
    t.add_argument("--diarize", action="store_true")
    t.add_argument("--speakers", type=int)
    t.add_argument("--no-crosscheck", action="store_true")
    t.add_argument("--fuse", action="store_true")
    t.add_argument("--clean-verbatim", action="store_true", help="drop um/uh/false starts")
    t.add_argument("--enhance", choices=["off", "normalize", "clean"])
    a_ = sub.add_parser("accuracy")
    a_.add_argument("reference")
    a_.add_argument("transcript")
    a_.add_argument("--prefix", action="store_true", help="transcript covers only the start of the reference")
    a_.add_argument("--keep-fillers", action="store_true")
    a_.add_argument("--xlsx")
    r = sub.add_parser("rebuild-log")
    r.add_argument("--out")
    a = ap.parse_args(argv)

    if a.cmd == "accuracy":
        from .accuracy import wer

        res = wer(Path(a.reference).read_text(encoding="utf-8"), _transcript_text(Path(a.transcript)),
                  ref_prefix=a.prefix, drop_fillers=not a.keep_fillers)
        print(f"Words in reference: {res.ref_words}")
        print(f"Substitutions {res.substitutions} · Deletions {res.deletions} · Insertions {res.insertions}")
        print(f"WORD ERROR RATE: {res.wer:.2%}   →   WORD ACCURACY: {res.accuracy:.2%}")
        print("Target: ≥ 99.00% accuracy (WER ≤ 1%)  —", "MET ✓" if res.wer <= 0.01 else "not met")
        if a.xlsx:
            from openpyxl import Workbook

            wb = Workbook()
            ws = wb.active
            ws.title = "Errors"
            ws.append(["Type", "Reference said", "Transcript has", "Context (reference)"])
            for e in res.errors:
                ws.append([e["type"], e["reference"], e["transcript"], e["context"]])
            s = wb.create_sheet("Summary")
            for row in [("WER", res.wer), ("Accuracy", res.accuracy), ("Reference words", res.ref_words),
                        ("Substitutions", res.substitutions), ("Deletions", res.deletions), ("Insertions", res.insertions)]:
                s.append(row)
            wb.save(a.xlsx)
            print("Error report:", a.xlsx)
        return 0

    s = Settings.load()
    if getattr(a, "out", None):
        s.output_dir = a.out
    if a.cmd == "rebuild-log":
        from .master_log import MasterLog

        print(MasterLog(s.output_dir).export_excel())
        return 0

    if a.engine:
        s.engine = a.engine
        s.variant = a.variant or {"parakeet": "parakeet-v2", "elevenlabs": "scribe_v2"}.get(a.engine, "large-v3")
    elif a.variant:
        s.variant = a.variant
    if a.language:
        s.language = None if a.language == "auto" else LANGUAGES.get(a.language.title(), a.language)
    if a.vocab:
        s.vocabulary = Path(a.vocab).read_text(encoding="utf-8")
    s.diarize = a.diarize or s.diarize
    s.num_speakers = a.speakers or s.num_speakers
    if a.no_crosscheck:
        s.cross_check = False
    s.fuse = a.fuse or s.fuse
    if a.clean_verbatim:
        s.verbatim = False
    if a.enhance:
        s.enhancement = a.enhance

    from .pipeline import BatchRunner, collect_media

    files = collect_media(a.paths)
    if not files:
        print("No media files found.")
        return 1
    print(f"{len(files)} file(s) → {s.output_dir}  [{s.engine} {s.variant}]")
    last = {}

    def status(name, frac, msg):
        if last.get(name) != msg:
            last[name] = msg
            print(f"  {Path(name).name}: {msg}", flush=True)

    out = BatchRunner(files, s, status).run()
    print(f"\nCompleted {out['completed']} · failed {out['failed']} · skipped {out['skipped']}")
    print("Master log:", out["excel"])
    return 0 if out["failed"] == 0 else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
