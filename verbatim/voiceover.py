# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Voiceover Creator: a script becomes two finished files — the voice alone, and the voice with music
(a bed that dips under every word and swells in the pauses).

Delivery styles come built in, and new ones are learned from reference recordings: VERBATIM measures the
reference's pace, pitch movement, loudness and tone colour and turns them into a reusable style."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from .platform_info import user_data_dir

BUILTIN = {
    "Warm narrator": {"fx": "Warm & intimate", "speed": 0.97, "emotion": "warm", "intensity": 0.5,
                      "mood": "Warm & hopeful", "about": "Close, friendly, trustworthy — brand stories."},
    "Corporate film": {"fx": "Broadcast narrator", "speed": 1.0, "emotion": "inspiring", "intensity": 0.5,
                       "mood": "Corporate uplifting", "about": "Confident and clear — company films, CSR, AV."},
    "Energetic advert": {"fx": "Bright advert", "speed": 1.08, "emotion": "excited", "intensity": 0.7,
                         "mood": "Energetic advert", "about": "Punchy, bright, upbeat — 15–30 s spots."},
    "Documentary": {"fx": "Broadcast narrator", "speed": 0.94, "emotion": "calm", "intensity": 0.4,
                    "mood": "Calm documentary", "about": "Measured and calm — explainers and films."},
    "Cinematic trailer": {"fx": "Cinematic trailer", "speed": 0.9, "emotion": "serious", "intensity": 0.75,
                          "mood": "Cinematic", "about": "Deep, slow, dramatic — launches and trailers."},
    "Storyteller": {"fx": "Warm & intimate", "speed": 0.95, "emotion": "warm", "intensity": 0.65,
                    "mood": "Indian warmth", "about": "Expressive and personal — heritage and founder stories."},
    "News & radio": {"fx": "Broadcast narrator", "speed": 1.05, "emotion": "neutral", "intensity": 0.45,
                     "mood": "Corporate uplifting", "about": "Crisp and neutral — updates, announcements."},
}


@dataclass
class Style:
    name: str
    fx: str = "Broadcast narrator"
    speed: float = 1.0
    emotion: str = "neutral"
    intensity: float = 0.5
    mood: str = "Warm & hopeful"
    about: str = ""
    reference: str = ""                  # learned from this recording
    stats: dict = field(default_factory=dict)


def styles_dir() -> Path:
    d = user_data_dir() / "voice_styles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def styles() -> list[Style]:
    out = [Style(k, **v) for k, v in BUILTIN.items()]
    for p in sorted(styles_dir().glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append(Style(**{k: v for k, v in d.items() if k in Style.__dataclass_fields__}))
        except (OSError, ValueError, TypeError):
            continue
    return out


def get_style(name: str) -> Style:
    for s in styles():
        if s.name == name:
            return s
    return Style("Warm narrator", **BUILTIN["Warm narrator"])


# ---------------------------------------------------------------------- learning a style from audio
def analyse(a: np.ndarray, sr: int) -> dict:
    """Delivery fingerprint of a recording: speaking rate, pitch movement, loudness, brightness, pauses."""
    from . import fx

    a = a.astype(np.float32)
    hop = int(0.01 * sr)
    n = len(a) // hop
    rms = np.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(1) + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    thr = np.percentile(db, 90) - 25
    voiced = db > thr
    # syllable nuclei ≈ peaks of the smoothed energy envelope while voiced
    env = np.convolve(rms, np.ones(7) / 7, mode="same")
    peaks = (env[1:-1] > env[:-2]) & (env[1:-1] >= env[2:]) & voiced[1:-1] & (env[1:-1] > np.percentile(env, 60))
    speech_s = max(1.0, voiced.sum() * 0.01)
    rate = float(peaks.sum() / speech_s)                         # syllables per second while speaking
    gaps, run = [], 0
    for v in voiced:
        if not v:
            run += 1
        else:
            if run >= 25:
                gaps.append(run * 0.01)
            run = 0
    pros = fx.prosody_stats(a, sr)
    spec = np.abs(np.fft.rfft(a[: min(len(a), sr * 30)]))
    freqs = np.fft.rfftfreq(min(len(a), sr * 30), 1 / sr)
    centroid = float((spec * freqs).sum() / (spec.sum() + 1e-9))
    return {"syll_per_s": round(rate, 2), "pitch_std_st": round(pros.get("std_st", 0.0), 2),
            "median_hz": round(pros.get("median_hz", 0.0), 1), "loudness_db": round(float(np.median(db[voiced]))
                                                                                      if voiced.any() else -40.0, 1),
            "brightness_hz": round(centroid, 0), "pause_s": round(float(np.mean(gaps)) if gaps else 0.0, 2),
            "speech_ratio": round(float(voiced.mean()), 2)}


def style_from_stats(name: str, st: dict, reference: str = "") -> Style:
    rate = st.get("syll_per_s", 4.5)
    speed = float(np.clip(rate / 7.0, 0.82, 1.2))                 # this detector reads ~7 nuclei/s at natural pace
    move = st.get("pitch_std_st", 2.2)
    emotion = "excited" if rate > 8.0 and move > 3 else "inspiring" if move > 2.8 else "calm" if rate < 5.6 else \
        "warm" if move > 1.8 else "serious"
    intensity = float(np.clip(0.3 + (move - 1.2) / 4.0, 0.3, 0.9))
    bright = st.get("brightness_hz", 1800)
    low = st.get("median_hz", 160) and st.get("median_hz", 160) < 120
    fx = "Cinematic trailer" if low and rate < 6 else "Bright advert" if bright > 2600 else \
        "Warm & intimate" if bright < 1500 else "Broadcast narrator"
    mood = {"excited": "Energetic advert", "inspiring": "Corporate uplifting", "calm": "Calm documentary",
            "warm": "Warm & hopeful", "serious": "Cinematic"}[emotion]
    about = (f"Learned from {Path(reference).name}: {rate:.1f} syllables/s, ±{move:.1f} semitones of melody, "
             f"pauses ~{st.get('pause_s', 0):.1f} s.") if reference else ""
    return Style(name, fx, round(speed, 2), emotion, round(intensity, 2), mood, about, reference, st)


def learn_style(path: str | Path, name: str = "") -> Style:
    from .voicelab import decode

    a = decode(path, 24000, 1)
    a = a.mean(1) if a.ndim > 1 else a
    st = analyse(a, 24000)
    s = style_from_stats(name or Path(path).stem, st, str(path))
    safe = re.sub(r"[^\w\- ]+", "", s.name).strip() or "style"
    (styles_dir() / f"{safe}.json").write_text(json.dumps(asdict(s), ensure_ascii=False, indent=1), encoding="utf-8")
    return s


# ---------------------------------------------------------------------- making the voiceover
@dataclass
class Request:
    script: str
    title: str = "Voiceover"
    lang: str = "en"
    voice: str = ""                      # tts voice id (st:1, cb:st:6, my:…)
    voice_name: str = ""
    style: str = "Warm narrator"
    pace: float = 1.0                    # multiplies the style's pace
    music: str = "generate"              # generate | file | none
    music_file: str = ""
    mood: str = ""                       # bed mood when generating ("" = the style's)
    music_level: float = -20.0           # music under speech (dB)
    quality: str = "studio"


def library_path(output_dir) -> Path:
    d = Path(output_dir) / "Voiceovers"
    d.mkdir(parents=True, exist_ok=True)
    return d / "library.json"


def record(output_dir, item: dict):
    p = library_path(output_dir)
    try:
        items = json.loads(p.read_text(encoding="utf-8")).get("items", [])
    except (OSError, ValueError):
        items = []
    items.insert(0, item)
    p.write_text(json.dumps({"items": items[:2000]}, ensure_ascii=False, indent=1), encoding="utf-8")


def _mp3(wav: Path, title: str) -> str:
    from .dub import _ffmpeg

    mp3 = wav.with_suffix(".mp3")
    code, _ = _ffmpeg(["-i", str(wav), "-codec:a", "libmp3lame", "-b:a", "256k", "-metadata", f"title={title}",
                       "-metadata", "artist=VERBATIM Voiceover", "-metadata", "copyright=© Infinite Story LLP",
                       str(mp3)])
    return str(mp3) if code == 0 and mp3.exists() else ""


def create(req: Request, output_dir, progress=None, synth=None) -> dict:
    """Script → {"voice_wav", "voice_mp3", "music_wav", "music_mp3", "duration", …}."""
    from . import dub
    from .music import BedSettings, mix_with_music, write_stereo_wav
    from .tts import Synth

    say = progress or (lambda f, m: None)
    if not req.script.strip():
        raise ValueError("Write or paste a script first.")
    st = get_style(req.style)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r'[\\/:*?"<>|]+', " ", req.title).strip() or "Voiceover"
    folder = Path(output_dir) / "Voiceovers" / f"{stamp} {safe}"
    folder.mkdir(parents=True, exist_ok=True)
    job = dub.new_script_job(req.script, req.lang, safe, folder, req.lang)
    job.voices = {"Narrator": req.voice} if req.voice else {}
    job.speed = float(np.clip(st.speed * req.pace, 0.75, 1.3))
    job.fx_preset = st.fx
    job.quality = req.quality
    for ln in job.lines:                          # the style is the baseline; the text adds the colour
        ln.emotion, ln.intensity = st.emotion, st.intensity
    try:
        dub.direct_job(job, None, only_empty=False)
        for ln in job.lines:                      # keep the style's character, let the text vary strength
            if ln.emotion in ("neutral", ""):
                ln.emotion = st.emotion
            ln.intensity = round(0.5 * ln.intensity + 0.5 * st.intensity, 2)
    except Exception:
        pass
    say(0.03, f"Voicing in “{st.name}” style…")
    out = dub.render(job, synth or Synth(progress=lambda f, m: say(0.05 + 0.6 * f, m), quality=req.quality),
                     lambda f, m: say(0.05 + 0.65 * f, m), mix=False, video=False)
    voice = Path(out["voice"])
    res = {"folder": str(folder), "voice_wav": str(voice), "style": st.name, "duration": job.duration}
    res["voice_mp3"] = _mp3(voice, f"{req.title} (voice)")
    if req.music != "none":
        say(0.75, "Scoring the music bed…")
        bed_file = req.music_file if req.music == "file" and req.music_file else ""
        if not bed_file:
            from . import beds
            from .voicelab import read_wav

            v, sr = read_wav(voice)
            secs = len(v) / sr + 7.0
            bed = beds.generate(req.mood or st.mood, secs, seed=len(req.script))
            bed_file = str(folder / "music bed.wav")
            write_stereo_wav(Path(bed_file), bed)
        from .voicelab import read_wav

        v, sr = read_wav(voice)
        from .tts import resample

        v = resample(v, sr, 48000)
        lines = [(ln.start, ln.start + ln.spoken, ln.emotion, ln.intensity) for ln in job.lines if ln.spoken]
        mm = mix_with_music(v, BedSettings(file=bed_file, duck_db=req.music_level), lines, extra_tail=True)
        mw = folder / f"{safe} — voice + music.wav"
        write_stereo_wav(mw, mm)
        res["music_wav"] = str(mw)
        res["music_mp3"] = _mp3(mw, f"{req.title} (voice + music)")
        res["bed"] = bed_file
    say(0.98, "Saving…")
    files = {"Voice only (MP3)": res.get("voice_mp3", ""), "Voice only (WAV)": res["voice_wav"],
             "Voice + music (MP3)": res.get("music_mp3", ""), "Voice + music (WAV)": res.get("music_wav", "")}
    record(output_dir, {"id": uuid.uuid4().hex[:12], "title": req.title, "voice_name": req.voice_name,
                        "style": st.name, "created": datetime.now().isoformat(timespec="seconds"),
                        "duration": job.duration, "files": {k: v for k, v in files.items() if v},
                        "script": req.script[:4000], "lang": req.lang})
    res["files"] = {k: v for k, v in files.items() if v}
    say(1.0, "Voiceover ready.")
    return res
