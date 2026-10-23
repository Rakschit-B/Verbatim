# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Singer casting: make every section of a generated song sung by who the song sheet says —
male, female, a male+female duet, or a chorus of 3, 6 or 12+ voices.

  song → vocals + instrumental (UVR) → find each section in the vocal (lyrics alignment, else energy) →
  tone-colour the vocal into the cast voices (OpenVoice V2, via the voice engine or the Cloud GPU) →
  layer duets and choruses (each singer its own timbre, timing, tuning and place in the stereo field) →
  remix, master, WAV + MP3."""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from .lyrics import SINGERS, Sheet

SR = 44100
REF_VOICES = {"male": ["st:6", "st:7", "st:8"], "female": ["st:1", "st:2", "st:3"]}
REF_TEXT = ("Morning light across the river, every window opening wide, we sing together for the people "
            "who carried us this far, and the night will hold our song.")


def _spans_from_alignment(vocals: np.ndarray, sheet: Sheet) -> list[tuple[float, float]] | None:
    from .align import word_spans
    from .tts import resample

    words, owner = [], []
    for i, p in enumerate(sheet.parts):
        for ln in p.lines:
            for w in ln.split():
                words.append(w)
                owner.append(i)
    if len(words) < 4:
        return None
    try:
        spans = word_spans(resample(vocals, SR, 16000), " ".join(words), sheet.language)
    except Exception:
        return None
    out: list[list[float]] = [[1e9, -1.0] for _ in sheet.parts]
    for (w, s, e), i in zip(spans, owner):
        out[i][0] = min(out[i][0], s)
        out[i][1] = max(out[i][1], e)
    res = []
    for s, e in out:
        res.append((s, e) if e > s else (0.0, 0.0))
    return res


def _spans_from_energy(vocals: np.ndarray, sheet: Sheet) -> list[tuple[float, float]]:
    """Fallback: split the voiced time in proportion to each section's syllables."""
    hop = int(0.05 * SR)
    n = len(vocals) // hop
    e = np.sqrt((vocals[:n * hop].reshape(n, hop) ** 2).mean(1))
    on = e > max(1e-4, np.percentile(e, 40) * 1.5)
    voiced_idx = np.flatnonzero(on)
    if not len(voiced_idx):
        return [(0.0, 0.0)] * len(sheet.parts)
    weight = [sum(len(ln) for ln in p.lines) for p in sheet.parts]
    total = sum(weight) or 1
    res, k = [], 0
    for w in weight:
        cnt = int(round(len(voiced_idx) * w / total))
        seg = voiced_idx[k:k + cnt]
        k += cnt
        res.append((seg[0] * 0.05, (seg[-1] + 1) * 0.05) if len(seg) and w else (0.0, 0.0))
    return res


def sections(vocals: np.ndarray, sheet: Sheet) -> tuple[list[tuple[float, float]], str]:
    a = _spans_from_alignment(vocals, sheet)
    if a and sum(1 for s, e in a if e > s) >= max(1, len(a) // 2):
        return a, "lyrics alignment"
    return _spans_from_energy(vocals, sheet), "vocal energy"


def references(progress=None) -> dict[str, list[str]]:
    """Reference recordings for each cast voice (studio voices reading a neutral line, made once)."""
    from .platform_info import user_data_dir
    from .tts import SAMPLE_RATE, Synth
    from .voicelab import write_wav

    d = user_data_dir() / "casting"
    d.mkdir(parents=True, exist_ok=True)
    out: dict[str, list[str]] = {"male": [], "female": []}
    synth = None
    for g, ids in REF_VOICES.items():
        for vid in ids:
            p = d / f"{vid.replace(':', '_')}.wav"
            if not p.exists():
                synth = synth or Synth(progress=progress)
                try:
                    a = synth.speak(REF_TEXT, "en", vid, 1.0)
                    write_wav(p, a, SAMPLE_RATE)
                except Exception:
                    continue
            out[g].append(str(p))
    return out


def _tone(vocals: np.ndarray, targets: list[str], tau: float, progress=None) -> np.ndarray | None:
    """Vocal in another singer's tone colour (OpenVoice V2). None when the engine is unavailable."""
    from .music_studio import ensure_tone_engine
    from .runtimes import EngineHost
    from .tts import resample
    from .voicelab import read_wav, write_wav

    try:
        md = ensure_tone_engine(progress)
        tmp = Path(tempfile.mkdtemp())
        write_wav(tmp / "v.wav", vocals, SR)
        EngineHost.get("voice", progress).request("openvoice_convert", ckpt_dir=str(md), src_wav=str(tmp / "v.wav"),
                                                  tgt_wavs=targets, out=str(tmp / "o.wav"), tau=float(tau))
        b, sr = read_wav(tmp / "o.wav")
        b = resample(b, sr, SR)
        b = np.pad(b[:len(vocals)], (0, max(0, len(vocals) - len(b))))
        return b * (np.sqrt(np.mean(vocals ** 2)) / (np.sqrt(np.mean(b ** 2)) + 1e-9))
    except Exception:
        return None


def _layer(x: np.ndarray, cents: float, delay_ms: float) -> np.ndarray:
    from . import fx

    y = fx.pitch_shift(x, cents / 100.0, SR) if abs(cents) >= 1 else x
    d = int(delay_ms * SR / 1000)
    y = np.concatenate([np.zeros(d, np.float32), y])[:len(x)]
    return np.pad(y, (0, max(0, len(x) - len(y))))


def _pan(x: np.ndarray, p: float) -> np.ndarray:
    """p in −1 (left) … +1 (right), equal power."""
    a = (p + 1) * np.pi / 4
    return np.stack([x * np.cos(a), x * np.sin(a)], 1)


def cast(song: str | Path, sheet: Sheet, out_stem: Path, progress=None, tau: float = 0.3) -> dict:
    from . import fx
    from .dub import _ffmpeg
    from .music import SR as OUT_SR
    from .music import loudness_normalise, write_stereo_wav
    from .tts import resample
    from .voicelab import decode, separate

    say = progress or (lambda f, m: None)
    say(0.02, "Separating the vocals from the band…")
    mix = decode(song, SR, 2)
    voc, band = separate(mix, SR, lambda f, m: say(0.02 + 0.3 * f, m))
    vm = voc.mean(1).astype(np.float32)
    say(0.33, "Finding every section in the vocal…")
    spans, how = sections(vm, sheet)
    needed = {p.singer for p in sheet.parts if p.lines}
    from .tts import openvoice_ready

    can_tone = openvoice_ready()           # never installs anything by itself
    refs = references(lambda f, m: None) if can_tone else {"male": [], "female": []}
    timbres: dict[str, np.ndarray | None] = {}
    plan = []
    if needed & {"male", "duet", "chorus3", "chorus6", "choir"}:
        plan += [("male0", refs["male"][:1])]
    if needed & {"female", "duet", "chorus3", "chorus6", "choir"}:
        plan += [("female0", refs["female"][:1])]
    if needed & {"chorus3", "chorus6", "choir"}:
        plan += [("male1", refs["male"][1:2]), ("female1", refs["female"][1:2])]
    if needed & {"chorus6", "choir"}:
        plan += [("male2", refs["male"][2:3]), ("female2", refs["female"][2:3])]
    for k, (name, tg) in enumerate(plan):
        say(0.36 + 0.4 * k / max(1, len(plan)), f"Casting singer {k + 1} of {len(plan)}…")
        timbres[name] = _tone(vm, tg, tau) if tg else None
    engine_ok = any(v is not None for v in timbres.values())

    def voice(name: str) -> np.ndarray:
        t = timbres.get(name)
        return t if t is not None else vm

    out = np.zeros((len(vm), 2), np.float32)
    covered = np.zeros(len(vm), bool)
    fade = int(0.04 * SR)
    for p, (s, e) in zip(sheet.parts, spans):
        if e <= s or not p.lines:
            continue
        a, b = max(0, int((s - 0.25) * SR)), min(len(vm), int((e + 0.6) * SR))
        g = p.singer
        if g == "male":
            layers = [("male0", 0, 0, 0.0)]
        elif g == "female":
            layers = [("female0", 0, 0, 0.0)]
        elif g == "duet":
            layers = [("male0", -4, 0, -0.35), ("female0", 4, 12, 0.35)]
        elif g == "none":
            layers = []
        else:
            n = SINGERS[g][2]
            names = ["male0", "female0", "male1", "female1", "male2", "female2"]
            layers = []
            for i in range(n):
                layers.append((names[i % len(names)], (-1) ** i * (6 + 4 * (i // 2)), 8 + 11 * i,
                               (-0.9 + 1.8 * i / max(1, n - 1)) if n > 1 else 0.0))
        seg = np.zeros((b - a, 2), np.float32)
        for name, cents, dms, pan in layers:
            x = voice(name)[a:b]
            if cents or dms:
                x = _layer(x, cents, dms)
            seg += _pan(x, pan) * (1.0 / np.sqrt(max(1, len(layers))))
        if g in ("chorus6", "choir"):
            seg = np.stack([fx.reverb(seg[:, c], room=0.75 if g == "choir" else 0.55, wet=0.22, sr=SR)[:len(seg)]
                            for c in range(2)], 1)
        ramp = np.ones(b - a, np.float32)
        ramp[:fade] = np.linspace(0, 1, min(fade, b - a))
        ramp[-fade:] = np.linspace(1, 0, min(fade, b - a))
        out[a:b] = out[a:b] * (1 - ramp[:, None]) + seg * ramp[:, None]
        covered[a:b] = True
    out[~covered] += voc[~covered]
    say(0.85, "Mixing the cast with the band…")
    full = band + out
    full = np.stack([resample(full[:, c], SR, OUT_SR) for c in range(2)], 1)
    full = loudness_normalise(full, -14.0)
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    wav = out_stem.with_suffix(".wav")
    write_stereo_wav(wav, full)
    mp3 = out_stem.with_suffix(".mp3")
    _ffmpeg(["-i", str(wav), "-codec:a", "libmp3lame", "-b:a", "320k", "-metadata", f"title={out_stem.name}",
             "-metadata", "artist=VERBATIM Music", "-metadata", "copyright=© Infinite Story LLP", str(mp3)])
    say(1.0, "Cast.")
    note = (f"Sections found by {how}. " + ("Each part re-voiced to its cast singer." if engine_ok else
            "Voice engine not installed — duets and choruses layered, solo genders left as generated."))
    return {"wav": str(wav), "mp3": str(mp3) if mp3.exists() else "", "note": note, "engine": engine_ok}
