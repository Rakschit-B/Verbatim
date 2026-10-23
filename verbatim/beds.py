# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Instant offline music beds for voiceovers — synthesised here, so "Voice + music" always works, even before
the Music Studio engine is installed. Original material, owned by Infinite Story LLP."""
from __future__ import annotations

import numpy as np

SR = 48000

MOODS = {   # chords (semitones from the key root), bpm, pulse, brightness, key root (Hz)
    "Warm & hopeful": {"prog": [[0, 4, 7, 11], [5, 9, 12, 16], [9, 12, 16, 19], [7, 11, 14, 17]], "bpm": 76,
                       "pulse": 0.0, "bright": 0.35, "root": 196.0},
    "Corporate uplifting": {"prog": [[0, 4, 7], [7, 11, 14], [9, 12, 16], [5, 9, 12]], "bpm": 104, "pulse": 0.55,
                            "bright": 0.55, "root": 220.0},
    "Energetic advert": {"prog": [[0, 4, 7], [5, 9, 12], [7, 11, 14], [5, 9, 12]], "bpm": 122, "pulse": 0.9,
                         "bright": 0.75, "root": 246.9},
    "Cinematic": {"prog": [[0, 3, 7], [8, 12, 15], [3, 7, 10], [10, 14, 17]], "bpm": 66, "pulse": 0.2,
                  "bright": 0.25, "root": 130.8},
    "Calm documentary": {"prog": [[0, 7, 12, 16], [5, 12, 16, 21], [0, 7, 14, 16], [7, 14, 19, 23]], "bpm": 70,
                         "pulse": 0.0, "bright": 0.3, "root": 174.6},
    "Indian warmth": {"prog": [[0, 7, 12], [0, 5, 12], [0, 7, 12], [0, 3, 10]], "bpm": 84, "pulse": 0.4,
                      "bright": 0.45, "root": 207.7, "drone": True},
}


def _env(n: int, a: float, r: float) -> np.ndarray:
    t = np.arange(n) / SR
    e = np.minimum(1.0, t / max(a, 1e-3)) * np.exp(-np.maximum(0, t - a) / max(r, 1e-3))
    return e.astype(np.float32)


def _pad(freqs, n, bright, rng) -> np.ndarray:
    t = np.arange(n) / SR
    out = np.zeros((n, 2), np.float32)
    att = np.minimum(1.0, t / 1.2) * np.minimum(1.0, (t[-1] - t + 1e-3) / 1.0)
    for f in freqs:
        for det, pan in ((-0.004, 0.25), (0.004, 0.75)):
            ph = rng.uniform(0, 2 * np.pi)
            ff = f * (1 + det)
            w = np.sin(2 * np.pi * ff * t + ph)
            w += bright * 0.35 * np.sin(4 * np.pi * ff * t + ph) + bright * 0.15 * np.sin(6 * np.pi * ff * t + ph)
            w *= 1 + 0.08 * np.sin(2 * np.pi * 0.2 * t + ph)
            out[:, 0] += w * (1 - pan) * att
            out[:, 1] += w * pan * att
    return out / max(1, len(freqs))


def generate(mood: str, seconds: float, seed: int = 7) -> np.ndarray:
    """A looping-free bed of `seconds` length, stereo (frames, 2) float32 at 48 kHz."""
    m = MOODS.get(mood) or MOODS["Warm & hopeful"]
    rng = np.random.default_rng(seed)
    n = int(max(4.0, seconds) * SR)
    out = np.zeros((n, 2), np.float32)
    bar = 4 * 60.0 / m["bpm"]
    nb = int(bar * SR)
    root = m["root"]
    i = 0
    k = 0
    while i < n:
        chord = m["prog"][k % len(m["prog"])]
        seg = min(nb * 2, n - i)
        freqs = [root * 2 ** (s / 12) for s in chord] + [root / 2 * 2 ** (chord[0] / 12)]
        out[i:i + seg] += 0.22 * _pad(freqs, seg, m["bright"], rng)
        i += seg
        k += 1
    if m.get("drone"):
        t = np.arange(n) / SR
        d = 0.06 * (np.sin(2 * np.pi * root / 2 * t) + 0.5 * np.sin(2 * np.pi * root * 3 / 4 * t))
        out += np.stack([d, d], 1).astype(np.float32)
    if m["pulse"] > 0:            # soft kick + shaker on the beat
        beat = int(60.0 / m["bpm"] * SR)
        kick_n = int(0.25 * SR)
        tk = np.arange(kick_n) / SR
        kick = (np.sin(2 * np.pi * (50 + 60 * np.exp(-tk * 30)) * tk) * _env(kick_n, 0.003, 0.12)).astype(np.float32)
        hat_n = int(0.06 * SR)
        hat = (rng.standard_normal(hat_n) * _env(hat_n, 0.001, 0.02)).astype(np.float32)
        hat = np.diff(hat, prepend=0)       # brighter
        for b, pos in enumerate(range(int(nb * 0.5), n - kick_n, beat)):
            out[pos:pos + kick_n] += (0.35 * m["pulse"] * kick)[:, None]
            hp = pos + beat // 2
            if hp + hat_n < n:
                out[hp:hp + hat_n] += (0.05 * m["pulse"] * hat)[:, None]
    fade = int(min(3.0, seconds / 4) * SR)
    out[:fade] *= np.linspace(0, 1, fade)[:, None]
    out[-fade:] *= np.linspace(1, 0, fade)[:, None]
    peak = float(np.abs(out).max() or 1.0)
    return (out / peak * 0.7).astype(np.float32)
