# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Module 03 — Music Studio: original music, songs and beds, generated on this computer (ACE-Step 1.5).

Everything Suno offers, plus what a production house needs:
  • Simple mode (describe it) and Custom mode (style, lyrics with [Verse]/[Chorus] tags, BPM, key, time
    signature, length, vocal language, instrumental)
  • Suno-style dials: Style influence, Weirdness (creativity), Variety (let the planner rewrite your style),
    Exclude styles, Max mode (base model + more steps)
  • Takes: several versions per prompt with their seeds, re-roll any take, keep favourites
  • Cover (restyle a track), Repaint (redo a section), Extend, Stems (vocals / music separated)
  • Score to voiceover: music written to the length of a Voice Studio voiceover, following its emotion arc,
    with intro, swells in the pauses and an ending on the last word — then mixed under the voice
  • Prompt library: 299 tested style prompts (CC0) + Infinite Story brand presets
  • Mastering to −14/−16 LUFS, WAV/MP3/FLAC, ownership metadata
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

LANGS = {"instrumental": "Instrumental", "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French",
         "ja": "Japanese", "zh": "Chinese", "ko": "Korean", "pt": "Portuguese", "de": "German", "it": "Italian",
         "ru": "Russian", "ar": "Arabic", "bn": "Bengali", "ta": "Tamil", "te": "Telugu", "pa": "Punjabi",
         "unknown": "Auto"}
KEYS = [""] + [f"{n} {m}" for m in ("Major", "Minor") for n in ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab",
                                                                   "A", "Bb", "B")]
TIME_SIGS = {"": "Auto", "4": "4/4", "3": "3/4", "6": "6/8", "2": "2/4"}
STRUCTURE_TAGS = ["[Intro]", "[Verse]", "[Pre-Chorus]", "[Chorus]", "[Post-Chorus]", "[Bridge]", "[Breakdown]",
                  "[Drop]", "[Instrumental]", "[Solo]", "[Build]", "[Hook]", "[Outro]", "[Fade Out]", "[End]"]
MODELS = {"turbo": ("acestep-v15-turbo", "Fast — 8 steps (recommended)"),
          "sft": ("acestep-v15-sft", "Max mode — richer detail, slower"),
          "base": ("acestep-v15-base", "Studio tasks — stems, extend, add a part")}


@dataclass
class MusicRequest:
    title: str = "Untitled"
    mode: str = "custom"              # simple | custom | cover | repaint | extend | score
    description: str = ""             # simple mode
    style: str = ""                   # caption (genre, mood, instruments)
    lyrics: str = ""
    language: str = "instrumental"
    bpm: int | None = None
    key: str = ""
    time_signature: str = ""
    duration: float = 60.0
    takes: int = 2
    seed: int = -1
    # Suno-style dials (0–100)
    style_influence: int = 70
    weirdness: int = 35
    variety: int = 0
    exclude: str = ""
    max_mode: bool = False
    # audio-to-audio
    source_audio: str = ""
    reference_audio: str = ""
    cover_strength: float = 0.6
    repaint_start: float = 0.0
    repaint_end: float = -1.0
    # finishing
    master_lufs: float = -14.0
    formats: list = field(default_factory=lambda: ["wav", "mp3"])
    voice_job: str = ""               # score-to-voiceover: path of a .voice.json


def to_engine(r: MusicRequest, project_root: str, out_dir: str) -> dict:
    """Map the studio controls onto ACE-Step parameters."""
    model = MODELS["sft" if r.max_mode else "turbo"][0]
    if r.mode in ("extend",):
        model = MODELS["base"][0]
    instrumental = r.language == "instrumental" or not r.lyrics.strip()
    caption = r.style.strip() or r.description.strip()
    if r.exclude.strip():
        caption += f". Avoid: {r.exclude.strip()}"
    req = {
        "project_root": project_root, "dit_model": model, "out_dir": out_dir,
        "lm_model": "acestep-5Hz-lm-0.6B" if (r.mode == "simple" or r.variety > 0 or not r.bpm) else "",
        "task_type": {"cover": "cover", "repaint": "repaint", "extend": "complete"}.get(r.mode, "text2music"),
        "caption": caption[:512], "lyrics": "[Instrumental]" if instrumental else r.lyrics[:4096],
        "instrumental": instrumental, "vocal_language": "unknown" if instrumental else r.language,
        "bpm": r.bpm, "keyscale": r.key, "timesignature": r.time_signature,
        "duration": float(r.duration) if r.duration else -1.0,
        "inference_steps": 32 if r.max_mode else 8, "shift": 3.0 if not r.max_mode else 1.0,
        "guidance_scale": 3.0 + 9.0 * r.style_influence / 100,
        "lm_temperature": 0.4 + 0.9 * r.weirdness / 100, "lm_cfg_scale": 1.0 + 2.5 * r.style_influence / 100,
        "use_cot_caption": r.variety > 0, "use_cot_metas": not (r.bpm and r.key),
        "lm_negative_prompt": r.exclude.strip() or "NO USER INPUT",
        "batch_size": max(1, min(4, int(r.takes))), "audio_format": "wav",
        "seeds": [int(r.seed) + k for k in range(max(1, int(r.takes)))] if int(r.seed) >= 0 else None,
    }
    if r.mode == "cover":
        req.update(src_audio=r.source_audio, audio_cover_strength=float(r.cover_strength))
    if r.mode == "repaint":
        req.update(src_audio=r.source_audio, repainting_start=float(r.repaint_start),
                   repainting_end=float(r.repaint_end))
    if r.mode == "extend":
        req.update(src_audio=r.source_audio)
    if r.reference_audio:
        req["reference_audio"] = r.reference_audio
    return req


# ---------------------------------------------------------------- score to voiceover
def score_for_voiceover(job_path: str, style: str = "") -> MusicRequest:
    """Write a music brief from a Voice Studio job: length, tempo feel and mood arc from its performance."""
    from .direction import info
    from .dub import VoiceJob

    job = VoiceJob.load(job_path)
    lines = [ln for ln in job.lines if ln.text.strip()]
    total = max((ln.start + (ln.spoken or ln.end - ln.start) for ln in lines), default=30.0) + 6.0
    emos = [ln.emotion or "neutral" for ln in lines]
    counts = {e: emos.count(e) for e in set(emos)}
    main = max(counts, key=counts.get) if counts else "neutral"
    arc = " → ".join(dict.fromkeys(info(e)["label"].lower() for e in
                                   (emos[:1] + emos[len(emos) // 2: len(emos) // 2 + 1] + emos[-1:])))
    mood = {"inspiring": "hopeful, uplifting, building", "warm": "warm, heartfelt", "calm": "calm, spacious",
            "joyful": "bright, joyful", "excited": "energetic, driving", "serious": "serious, focused",
            "sad": "bittersweet, reflective", "urgent": "urgent, pulsing", "whisper": "intimate, minimal",
            "neutral": "modern, understated"}.get(main, "modern, understated")
    tempo = {"excited": 124, "joyful": 116, "urgent": 128, "inspiring": 96, "warm": 88, "calm": 72, "sad": 70,
             "serious": 84, "whisper": 66}.get(main, 92)
    caption = (style.strip() + ", " if style.strip() else "") + \
        f"underscore for a voiceover, {mood}, emotional arc {arc}, leaves space for narration in the midrange, " \
        f"instrumental, clear intro, gentle swells, satisfying ending"
    return MusicRequest(title=f"{Path(job.source_json).stem} — score", mode="score", style=caption,
                        language="instrumental", bpm=tempo, duration=round(min(600.0, total), 1), takes=2,
                        voice_job=job_path)


# ---------------------------------------------------------------- library
def library_dir(output_dir: str | Path) -> Path:
    d = Path(output_dir) / "Music Studio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def history_path(output_dir) -> Path:
    return library_dir(output_dir) / "library.json"


def load_history(output_dir) -> list[dict]:
    try:
        return json.loads(history_path(output_dir).read_text(encoding="utf-8")).get("items", [])
    except (OSError, ValueError):
        return []


def save_history(output_dir, items: list[dict]):
    p = history_path(output_dir)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def prompt_library() -> dict:
    from .platform_info import asset

    try:
        return json.loads(asset("music_prompts.json").read_text(encoding="utf-8"))["prompts"]
    except (OSError, ValueError, KeyError):
        return {}


# ---------------------------------------------------------------- run
def checkpoints_root() -> Path:
    from .platform_info import models_dir

    return models_dir() / "acestep"


MODEL_FILES_HINT = ("ACE-Step/Ace-Step1.5", "ACE-Step/acestep-5Hz-lm-0.6B")


def ensure_models(progress=None, max_mode: bool = False) -> Path:
    """Download the music model once (≈ 8 GB; Max mode adds the SFT model)."""
    from .download import hf_files

    root = checkpoints_root()
    ck = root / "checkpoints"
    need = [("ACE-Step/Ace-Step1.5", ck, r"^acestep-5Hz-lm-1\.7B/")]
    if not (ck / "acestep-5Hz-lm-0.6B" / "config.json").exists():
        need.append(("ACE-Step/acestep-5Hz-lm-0.6B", ck / "acestep-5Hz-lm-0.6B", ""))
    if max_mode:
        need.append(("ACE-Step/acestep-v15-sft", ck / "acestep-v15-sft", ""))
    for repo, dest, exclude in need:
        hf_files(repo, dest, progress, exclude=exclude)
    return root


def generate(r: MusicRequest, output_dir: str, progress=None) -> list[dict]:
    """Generate takes, master them, add metadata, record them in the library. Returns the new items."""
    from .runtimes import EngineHost

    say = progress or (lambda f, m: None)
    root = ensure_models(say, r.max_mode)
    host = EngineHost.get("music", say)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = library_dir(output_dir) / f"{stamp} {safe(r.title)}"
    res = host.request("music", progress=say, **to_engine(r, str(root), str(out / "raw")))
    items = []
    for k, t in enumerate(res.get("tracks", []), 1):
        final = master(Path(t["path"]), out / f"{safe(r.title)} — take {k}", r)
        if r.voice_job:
            final.update(mix_under_voice(r.voice_job, final["wav"]))
        items.append({"id": f"{stamp}-{k}", "title": r.title, "take": k, "seed": t.get("seed"), "bpm": t.get("bpm"),
                      "key": t.get("key"), "caption": t.get("caption"), "files": final, "favourite": False,
                      "request": asdict(r), "created": datetime.now().isoformat(timespec="seconds")})
    hist = load_history(output_dir)
    save_history(output_dir, items + hist)
    _log(output_dir, items)
    return items


def master(src: Path, stem: Path, r: MusicRequest) -> dict:
    """Loudness-master a take and write the requested formats with Infinite Story ownership metadata."""
    import numpy as np

    from .dub import _ffmpeg
    from .music import SR, loudness_normalise, write_stereo_wav
    from .voicelab import decode

    a = decode(src, SR, 2)
    a = loudness_normalise(a, float(r.master_lufs))
    stem.parent.mkdir(parents=True, exist_ok=True)
    wav = stem.with_suffix(".wav")
    write_stereo_wav(wav, a)
    files = {"wav": str(wav)}
    meta = ["-metadata", f"title={r.title}", "-metadata", "artist=Infinite Story LLP", "-metadata",
            "copyright=© Infinite Story LLP", "-metadata", "comment=Composed with VERBATIM Music Studio"]
    for fmt, codec in (("mp3", ["-c:a", "libmp3lame", "-b:a", "320k"]), ("flac", ["-c:a", "flac"])):
        if fmt in r.formats:
            dst = stem.with_suffix("." + fmt)
            if _ffmpeg(["-i", str(wav), *codec, *meta, str(dst)])[0] == 0:
                files[fmt] = str(dst)
    files["seconds"] = round(len(a) / SR, 2)
    files["peak_db"] = round(float(20 * np.log10(np.abs(a).max() + 1e-9)), 2)
    return files


def mix_under_voice(job_path: str, music_wav: str) -> dict:
    """Score-to-voiceover: put the new music under the job's voice with the follow-the-voice fader."""
    from .dub import VoiceJob
    from .music import BedSettings, mix_with_music, write_stereo_wav
    from .voicelab import read_wav

    job = VoiceJob.load(job_path)
    vpath = job.outputs.get("voice")
    if not vpath or not Path(vpath).exists():
        return {}
    v, sr = read_wav(Path(vpath))
    from .tts import resample

    v = resample(v, sr, 48000)
    lines = [(ln.start, ln.start + ln.spoken, ln.emotion, ln.intensity) for ln in job.lines if ln.spoken]
    mix = mix_with_music(v, BedSettings(file=music_wav, mode="follow"), lines, extra_tail=True)
    dst = Path(music_wav).with_name(Path(music_wav).stem + " + voiceover.wav")
    write_stereo_wav(dst, mix)
    return {"with_voice": str(dst)}


def separate_stems(path: str, progress=None) -> dict:
    """Vocals / music stems for any track (UVR MDX-Net)."""
    from .music import write_stereo_wav
    from .voicelab import decode, separate

    a = decode(path, 44100, 2)
    v, m = separate(a, 44100, progress)
    base = Path(path)
    vp, mp = base.with_name(base.stem + " — vocals.wav"), base.with_name(base.stem + " — instrumental.wav")
    import numpy as np

    from .tts import resample

    write_stereo_wav(vp, np.stack([resample(v[:, c], 44100, 48000) for c in range(2)], 1))
    write_stereo_wav(mp, np.stack([resample(m[:, c], 44100, 48000) for c in range(2)], 1))
    return {"vocals": str(vp), "instrumental": str(mp)}


def safe(name: str) -> str:
    import re

    return re.sub(r'[\\/:*?"<>|]+', " ", name).strip()[:80] or "Untitled"


def random_seed() -> int:
    return random.randint(0, 2 ** 31 - 1)


def _log(output_dir, items):
    try:
        from .master_log import MasterLog

        MasterLog(Path(output_dir)).record_music(items)
    except Exception:
        pass
