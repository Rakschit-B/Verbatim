# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""One library of everything VERBATIM made: transcripts, voiceovers, songs, localised films and dubbed
feature films — each with something to play and every file to download."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

KINDS = {"transcript": "Transcript", "voiceover": "Voiceover", "music": "Music", "video": "Video", "film": "Feature film"}
GLYPH = {"transcript": "quotes", "voiceover": "voice", "music": "music", "video": "video", "film": "film_reel"}


@dataclass
class Item:
    kind: str
    title: str
    sub: str = ""
    when: str = ""                       # ISO time
    duration: float = 0.0
    play: str = ""                       # file the ▶ button plays
    files: dict = field(default_factory=dict)   # label -> path (each one is downloadable)
    folder: str = ""
    key: str = ""

    def exists(self) -> bool:
        return any(Path(p).exists() for p in self.files.values()) or (self.play and Path(self.play).exists())


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _keep(files: dict) -> dict:
    return {k: v for k, v in files.items() if v and isinstance(v, str) and Path(v).exists()}


def transcripts(root: Path) -> list[Item]:
    db = root / ".verbatim" / "ledger.sqlite"
    out = []
    if not db.exists():
        return out
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = con.execute("SELECT source_name, duration, language, finished, docx, txt, output_folder, json, status "
                           "FROM files ORDER BY id DESC LIMIT 3000").fetchall()
        con.close()
    except sqlite3.Error:
        return out
    seen = set()
    for name, dur, lang, fin, docx, txt, folder, js, status in rows:
        if not js or js in seen or (status or "").lower().startswith("fail"):
            continue
        seen.add(js)
        files = {"Word (DOCX)": docx or "", "Text (TXT)": txt or "", "JSON": js or ""}
        for ext, label in ((".srt", "Subtitles (SRT)"), (".vtt", "Subtitles (VTT)"), (".csv", "CSV"), (".md", "Markdown")):
            p = Path(js).with_suffix(ext)
            if p.exists():
                files[label] = str(p)
        media = ""
        try:
            media = json.loads(Path(js).read_text(encoding="utf-8")).get("source_path", "")
        except (OSError, ValueError):
            pass
        out.append(Item("transcript", Path(name or js).stem, f"Transcript · {(lang or '').upper()}", fin or "",
                        float(dur or 0), media if media and Path(media).exists() else "", _keep(files),
                        folder or str(Path(js).parent), js))
    return out


def voiceovers(root: Path) -> list[Item]:
    out = []
    for p in sorted(root.glob("**/Voice Studio/*.voice.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:500]:
        if "Voiceovers" in p.relative_to(root).parts[:1]:      # Voiceover Creator lists its own results
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        o = d.get("outputs", {}) or {}
        files = _keep({"Voiceover (WAV)": o.get("voice", ""), "Mixed with original": o.get("mix", ""),
                       "Voice + music (WAV)": o.get("music_mix", ""), "Voice + music (MP3)": o.get("music_mp3", ""),
                       "Dubbed video (MP4)": o.get("video", ""), "Subtitles (SRT)": o.get("srt", "")})
        if not files:
            continue
        play = files.get("Dubbed video (MP4)") or files.get("Voice + music (MP3)") or files.get("Mixed with original") \
            or files.get("Voiceover (WAV)")
        kind = "video" if "Dubbed video (MP4)" in files else "voiceover"
        title = p.name.replace(".voice.json", "")
        out.append(Item(kind, title, f"{KINDS[kind]} · {d.get('tgt_lang', '').upper()}", d.get("rendered") or
                        d.get("updated") or _iso(p.stat().st_mtime), float(d.get("duration") or 0), play, files,
                        str(p.parent), str(p)))
    return out


def creator(root: Path) -> list[Item]:
    """Voiceover Creator outputs (voice only / voice + music)."""
    lib = root / "Voiceovers" / "library.json"
    try:
        items = json.loads(lib.read_text(encoding="utf-8")).get("items", [])
    except (OSError, ValueError):
        return []
    out = []
    for it in items:
        files = _keep(it.get("files", {}))
        if files:
            play = files.get("Voice + music (MP3)") or files.get("Voice only (MP3)") or next(iter(files.values()))
            out.append(Item("voiceover", it.get("title", "Voiceover"), f"Voiceover · {it.get('voice_name', '')}",
                            it.get("created", ""), float(it.get("duration") or 0), play, files,
                            str(Path(play).parent), it.get("id", "")))
    return out


def music(root: Path) -> list[Item]:
    from .music_studio import load_history

    out = []
    for it in load_history(root):
        f = it.get("files", {}) or {}
        files = _keep({"Song, cast (MP3)": f.get("cast_mp3", ""), "Song, cast (WAV)": f.get("cast_wav", ""),
                       "Song (MP3)": f.get("mp3", ""), "Song (WAV)": f.get("wav", ""),
                       "With voiceover": f.get("with_voice", ""), "Vocals stem": f.get("vocals", ""),
                       "Instrumental stem": f.get("instrumental", "")})
        for v in it.get("versions", []) or []:
            if v.get("mp3") and Path(v["mp3"]).exists():
                files[f"Sung by {v.get('voice', 'you')} (MP3)"] = v["mp3"]
        if not files:
            continue
        play = files.get("Song, cast (MP3)") or files.get("Song (MP3)") or files.get("Song (WAV)") or \
            next(iter(files.values()))
        out.append(Item("music", f"{it.get('title', 'Untitled')} — take {it.get('take', 1)}",
                        f"Song · {it.get('bpm') or ''} BPM {it.get('key') or ''}".strip(), it.get("created", ""),
                        float((it.get("request") or {}).get("duration") or 0), play, files, str(Path(play).parent),
                        it.get("id", "")))
    return out


def films(root: Path) -> list[Item]:
    out = []
    for p in list(root.glob("**/* — localisation.json"))[:300] + list(root.glob("**/Feature Film/*/film.json"))[:300]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        kind = "film" if p.name == "film.json" else "video"
        for lang, o in (d.get("results") or {}).items():
            files = _keep({"Film (MP4)": o.get("film", ""), "Lip-synced (MP4)": o.get("lipsync", ""),
                           "Dialogue (WAV)": o.get("voice", ""), "Full mix (WAV)": o.get("mix", ""),
                           "Subtitles (SRT)": o.get("srt", "")})
            if files:
                title = Path(d.get("video", p.stem)).stem
                out.append(Item(kind, f"{title} — {lang.upper()}", f"{KINDS[kind]} · {lang.upper()}",
                                d.get("finished") or _iso(p.stat().st_mtime), 0.0,
                                files.get("Lip-synced (MP4)") or files.get("Film (MP4)") or next(iter(files.values())),
                                files, str(p.parent), f"{p}:{lang}"))
    return out


def everything(output_dir: str | Path) -> list[Item]:
    root = Path(output_dir)
    items: list[Item] = []
    for fn in (transcripts, voiceovers, creator, music, films):
        try:
            items += fn(root)
        except Exception:
            continue
    items.sort(key=lambda i: i.when or "", reverse=True)
    return items
