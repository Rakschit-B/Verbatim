# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Music taste memory: VERBATIM learns from what you keep. Every 👍, ♥, download or "use as voiceover bed"
strengthens the style words of that take; every 👎 weakens them. New prompts are then completed with the
words you reliably like (for the same kind of song) and steered away from what you reject."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

WEIGHTS = {"like": 1.0, "favourite": 2.0, "download": 1.5, "bed": 1.5, "dislike": -2.0, "reroll": -0.3}
HALF_LIFE_DAYS = 120
GENRES = {"pop", "rock", "hip hop", "rap", "edm", "house", "techno", "jazz", "blues", "classical", "cinematic",
          "orchestral", "folk", "country", "r&b", "soul", "funk", "lofi", "lo-fi", "ambient", "bollywood", "sufi",
          "ghazal", "qawwali", "bhangra", "indie", "acoustic", "devotional", "bhajan", "trap", "reggaeton", "afrobeats",
          "k-pop", "metal", "punk", "disco", "synthwave", "corporate", "advert", "jingle", "carnatic", "hindustani"}


def tags(text: str) -> list[str]:
    out = []
    for t in re.split(r"[,;/\n]+", (text or "").lower()):
        t = re.sub(r"\s+", " ", t).strip(" .-")
        if 2 <= len(t) <= 40 and t not in out:
            out.append(t)
    return out


def path(output_dir) -> Path:
    d = Path(output_dir) / "Music Studio"
    d.mkdir(parents=True, exist_ok=True)
    return d / "taste.json"


def load(output_dir) -> dict:
    try:
        return json.loads(path(output_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"events": []}


def record(output_dir, event: str, style: str, extra: dict | None = None):
    d = load(output_dir)
    d["events"].append({"t": time.time(), "e": event, "tags": tags(style), **(extra or {})})
    d["events"] = d["events"][-3000:]
    path(output_dir).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def profile(output_dir, context: str = "") -> dict[str, float]:
    """tag → weight, decayed by age; with `context`, events sharing a genre word count double."""
    now = time.time()
    ctx = {g for g in GENRES if g in (context or "").lower()}
    w: dict[str, float] = {}
    for ev in load(output_dir).get("events", []):
        k = WEIGHTS.get(ev.get("e"), 0.0)
        if not k:
            continue
        age = (now - ev.get("t", now)) / 86400
        k *= 0.5 ** (age / HALF_LIFE_DAYS)
        evg = {g for g in GENRES if any(g in t for t in ev.get("tags", []))}
        if ctx and evg & ctx:
            k *= 2.0
        for t in ev.get("tags", []):
            w[t] = w.get(t, 0.0) + k
    return w


def enhance(output_dir, style: str, n_add: int = 3) -> tuple[str, list[str], list[str]]:
    """(style with learned words added, the added words, words to avoid)."""
    have = tags(style)
    w = profile(output_dir, style)
    good = [t for t, v in sorted(w.items(), key=lambda x: -x[1]) if v >= 1.4 and t not in have
            and not any(t in h or h in t for h in have)]
    bad = [t for t, v in sorted(w.items(), key=lambda x: x[1]) if v <= -1.5 and t not in have][:6]
    add = good[:n_add]
    out = ", ".join(have + add) if have else ", ".join(add)
    return out, add, bad
