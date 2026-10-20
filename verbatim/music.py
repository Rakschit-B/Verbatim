# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Music bed — music that breathes with the voice, the way a sound engineer would ride the fader.

The automatic mix ("follow the voice"):
  • intro: the music plays at full level, then dips just before the first word (look-ahead);
  • under speech: the music sits low so every word is clear (ducking);
  • pauses: in any gap longer than ~0.9 s the music swells back up, then dips again before the voice;
  • tone: lines directed as inspiring / joyful / excited lift the bed a little; calm / sad / whisper lines
    lower it — so the music rises and falls with the emotion of the script;
  • outro: after the last line the music swells to full and fades out.
The mix is loudness-normalised (≈ −16 LUFS, streaming/social) with a peak ceiling of −1 dBFS.

Also: separate the original voice from a video's soundtrack (UVR) so a dub can keep the original
music and effects instead of playing the foreign voice underneath.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

SR = 48000

MODES = {"follow": "Follow the voice (swell in pauses, dip under speech)",
         "steady": "Steady bed (constant level under the voice)",
         "intro_outro": "Intro & outro only (music around the voice)"}

TONE_DB = {"inspiring": 3.0, "joyful": 3.0, "excited": 4.0, "urgent": 2.0, "warm": 1.0, "neutral": 0.0,
           "serious": -1.0, "calm": -2.0, "sad": -3.0, "whisper": -4.0}


@dataclass
class BedSettings:
    file: str = ""
    mode: str = "follow"
    bed_db: float = -6.0         # music level in pauses / steady mode, relative to the track's own level
    duck_db: float = -20.0       # music level under speech
    intro_s: float = 2.5         # music before the first word (script voiceovers)
    outro_s: float = 4.0         # music after the last word, then fade
    fade_out_s: float = 3.0
    swell_gap_s: float = 0.9     # pauses longer than this get a swell
    target_lufs: float = -16.0

    @staticmethod
    def from_dict(d: dict | None) -> "BedSettings":
        d = d or {}
        return BedSettings(**{k: v for k, v in d.items() if k in BedSettings.__dataclass_fields__})


def load_music(path: str | Path, seconds: float) -> np.ndarray:
    """Music as (frames, 2) at SR, looped with a cross-fade if shorter than needed."""
    from .voicelab import decode

    m = decode(path, SR, 2)
    need = int(seconds * SR)
    if len(m) >= need:
        return m[:need]
    xf = min(int(1.5 * SR), len(m) // 4)
    out = m.copy()
    while len(out) < need:
        ramp = np.linspace(0, 1, xf, dtype=np.float32)[:, None]
        tail = out[-xf:] * (1 - ramp) + m[:xf] * ramp
        out = np.concatenate([out[:-xf], tail, m[xf:]])
    return out[:need]


def voice_activity(voice: np.ndarray, sr: int = SR, frame: float = 0.02) -> np.ndarray:
    """Per-sample 0/1 speech mask from the voice track (bridging tiny gaps between words)."""
    fr = int(sr * frame)
    n = len(voice) // fr
    if n == 0:
        return np.zeros(len(voice), dtype=np.float32)
    rms = np.sqrt((voice[:n * fr].reshape(n, fr) ** 2).mean(1))
    on = (rms > max(1e-4, rms.max() * 0.02)).astype(np.float32)
    # bridge gaps shorter than 0.5 s (between words / short breaths)
    gap = int(0.5 / frame)
    idx = np.where(on > 0)[0]
    for a, b in zip(idx[:-1], idx[1:]):
        if 1 < b - a <= gap:
            on[a:b] = 1
    mask = np.repeat(on, fr)
    return np.pad(mask, (0, len(voice) - len(mask)))


def gain_curve(voice: np.ndarray, s: BedSettings, lines: list[tuple[float, float, str, float]] | None = None,
               sr: int = SR) -> np.ndarray:
    """Music gain (linear) per sample — the automatic fader ride."""
    n = len(voice)
    speech = voice_activity(voice, sr)
    db = np.full(n, s.bed_db, dtype=np.float32)
    on = np.where(speech > 0)[0]
    if len(on) == 0:
        return np.full(n, 10 ** (s.bed_db / 20), dtype=np.float32)
    first, last = on[0], on[-1]
    if s.mode == "steady":
        db[:] = s.duck_db + 6
    else:
        db[speech > 0] = s.duck_db
        if s.mode == "intro_outro":
            db[first:last] = s.duck_db
        else:  # follow: pauses shorter than swell_gap stay ducked
            gap = int(s.swell_gap_s * sr)
            idx = np.where(np.diff(speech) != 0)[0]
            starts = [i + 1 for i in idx if speech[i + 1] == 0]
            ends = [i + 1 for i in idx if speech[i + 1] > 0]
            for a in starts:
                b = next((e for e in ends if e > a), None)
                if b is not None and b - a < gap:
                    db[a:b] = s.duck_db
        db[:first] = 0.0
        db[last:] = 0.0
    if lines:  # tone: lift or lower the bed under each line by its emotion
        for st, en, emo, inten in lines:
            a, b = int(st * sr), min(n, int(en * sr))
            if b > a:
                db[a:b] += TONE_DB.get(emo or "neutral", 0.0) * (0.5 + float(inten or 0.5))
    # smooth: fast dip before speech (look-ahead), slow swell after
    db = _smooth(db, sr, attack=0.25, release=0.9)
    g = (10 ** (db / 20)).astype(np.float32)
    if s.fade_out_s > 0:
        end_fade = min(n, last + int(s.outro_s * sr))
        f0 = max(0, end_fade - int(s.fade_out_s * sr))
        g[f0:end_fade] *= np.linspace(1, 0, end_fade - f0, dtype=np.float32)
        g[end_fade:] = 0
    return g


def _smooth(db: np.ndarray, sr: int, attack: float, release: float) -> np.ndarray:
    """Asymmetric smoothing at 100 Hz control rate; downward moves start `attack` s early (look-ahead)."""
    step = sr // 100
    ctl = db[::step].astype(np.float64)
    la = int(attack * 100)
    # look-ahead: take the minimum over the next `la` frames so the dip lands before the word
    look = np.array([ctl[i:i + la + 1].min() for i in range(len(ctl))])
    out = np.empty_like(look)
    cur = look[0]
    a_c = 1 - np.exp(-1 / (attack * 100 / 3))
    r_c = 1 - np.exp(-1 / (release * 100 / 3))
    for i, v in enumerate(look):
        cur += (v - cur) * (a_c if v < cur else r_c)
        out[i] = cur
    return np.interp(np.arange(len(db)), np.arange(len(out)) * step, out).astype(np.float32)


def loudness_normalise(mix: np.ndarray, target_lufs: float = -16.0, ceiling_db: float = -1.0) -> np.ndarray:
    """Approximate integrated loudness (K-weighting-free RMS of active parts) + soft peak limiter."""
    mono = mix.mean(1) if mix.ndim > 1 else mix
    fr = int(0.4 * SR)
    n = len(mono) // fr
    if n:
        blocks = (mono[:n * fr].reshape(n, fr) ** 2).mean(1)
        active = blocks[blocks > blocks.max() * 1e-3] if blocks.max() > 0 else blocks
        lufs = -0.691 + 10 * np.log10(active.mean() + 1e-12) if len(active) else -70
        mix = mix * (10 ** ((target_lufs - lufs) / 20))
    ceil = 10 ** (ceiling_db / 20)
    over = np.abs(mix) > ceil * 0.8
    if over.any():   # soft-knee limiter above 80 % of the ceiling
        x = mix[over]
        k = ceil * 0.8
        mix[over] = np.sign(x) * (k + (ceil - k) * np.tanh((np.abs(x) - k) / (ceil - k)))
    return mix.astype(np.float32)


def mix_with_music(voice: np.ndarray, s: BedSettings, lines=None, extra_tail: bool = True) -> np.ndarray:
    """Voice (mono, SR) + music bed → stereo mix (frames, 2), loudness-normalised."""
    tail = s.outro_s if extra_tail else 0.0
    total = len(voice) / SR + tail
    v = np.pad(voice, (0, int(total * SR) - len(voice))) if tail else voice
    m = load_music(s.file, total)
    # set the music to a sensible reference level (−20 dBFS RMS) before riding the fader
    rms = float(np.sqrt((m ** 2).mean()) + 1e-9)
    m = m * (0.1 / rms)
    g = gain_curve(v, s, lines)
    out = m * g[:, None] + v[:, None]
    return loudness_normalise(out, s.target_lufs)


def separate_background(media: str | Path, progress=None) -> np.ndarray:
    """Original soundtrack minus the original voice → music & effects (frames, 2) at SR."""
    from .voicelab import decode, separate

    mix = decode(media, 44100, 2)
    _, bg = separate(mix, 44100, progress)
    from .tts import resample

    return np.stack([resample(bg[:, c], 44100, SR) for c in range(2)], 1)


def write_stereo_wav(path: Path, a: np.ndarray, sr: int = SR):
    import wave

    pcm = (np.clip(a, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
