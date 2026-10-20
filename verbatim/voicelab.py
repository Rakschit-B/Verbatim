# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Voice Lab — custom voices made from a recording (your own narration, a consented speaker).

Pipeline for "Create voice from a recording":
  1. decode the file (MP3/WAV/MP4…) and, if it has music under the voice, separate the voice with the
     UVR MDX-Net vocal model (sherpa-onnx);
  2. find the cleanest 6–12 s of continuous speech to use as the voice reference;
  3. transcribe that reference (local Parakeet) — the cloning engines need to know what was said;
  4. store reference.wav + voice.json in the VERBATIM data folder, linked to a consent-register entry.

A custom voice id is "my:<slug>". Which engine speaks it depends on the language (see tts.Synth):
ZipVoice (local, English/Chinese), Chatterbox Multilingual (local, 23 languages, when installed) or
ElevenLabs (cloud, your account) — all clone from the same reference.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

REF_SR = 24000
UVR_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/source-separation-models/UVR-MDX-NET-Voc_FT.onnx"
UVR_MB = 64


@dataclass
class CustomVoice:
    id: str                     # "my:<slug>"
    name: str
    gender: str = "female"
    character: str = "your voice"
    lang: str = "en"            # language of the reference recording
    ref_text: str = ""
    source: str = ""            # original file name
    owner: str = ""             # whose voice it is
    rights: str = ""            # how the rights were confirmed
    consent_id: str = ""
    created: str = ""
    eleven_id: str = ""         # ElevenLabs instant-clone id, once uploaded
    extra_refs: list = field(default_factory=list)   # more reference clips (file names) for emotion range

    @property
    def slug(self) -> str:
        return self.id.split(":", 1)[1]

    @property
    def folder(self) -> Path:
        return voices_dir() / self.slug

    @property
    def ref_wav(self) -> Path:
        return self.folder / "reference.wav"

    @property
    def label(self) -> str:
        return f"{self.name} — {self.gender}, {self.character}"


def voices_dir() -> Path:
    from .platform_info import user_data_dir

    d = user_data_dir() / "voices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "voice"


def library() -> list[CustomVoice]:
    out = []
    for p in sorted(voices_dir().glob("*/voice.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append(CustomVoice(**{k: v for k, v in d.items() if k in CustomVoice.__dataclass_fields__}))
        except (OSError, ValueError, TypeError):
            continue
    return out


def get(voice_id: str) -> CustomVoice | None:
    slug = voice_id.split(":", 1)[-1]
    p = voices_dir() / slug / "voice.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return CustomVoice(**{k: v for k, v in d.items() if k in CustomVoice.__dataclass_fields__})


def save(cv: CustomVoice, ref: np.ndarray | None = None, sr: int = REF_SR) -> CustomVoice:
    cv.folder.mkdir(parents=True, exist_ok=True)
    if ref is not None:
        write_wav(cv.ref_wav, ref, sr)
    tmp = cv.folder / "voice.json.tmp"
    tmp.write_text(json.dumps(asdict(cv), ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(cv.folder / "voice.json")
    return cv


def delete(voice_id: str) -> bool:
    cv = get(voice_id)
    if not cv:
        return False
    shutil.rmtree(cv.folder, ignore_errors=True)
    return True


def reference(cv: CustomVoice) -> tuple[np.ndarray, int]:
    return read_wav(cv.ref_wav)


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """16-bit PCM WAV → mono float32 (no extra dependencies)."""
    import wave

    with wave.open(str(path), "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        a = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(1)
    return a, sr


def write_wav(path: Path, a: np.ndarray, sr: int):
    import wave

    pcm = (np.clip(a, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


# ---------------------------------------------------------------- audio helpers
def decode(path: str | Path, sr: int = 44100, channels: int = 2) -> np.ndarray:
    """Any audio/video file → float32 array (frames, channels) via the bundled ffmpeg."""
    import subprocess

    from .platform_info import IS_WINDOWS, ffmpeg_path

    r = subprocess.run([ffmpeg_path(), "-nostdin", "-loglevel", "error", "-i", str(path), "-vn", "-ac", str(channels),
                        "-ar", str(sr), "-f", "f32le", "-"], capture_output=True,
                       creationflags=0x08000000 if IS_WINDOWS else 0)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(f"Could not read {Path(path).name}: {r.stderr.decode(errors='replace')[-200:]}")
    return np.frombuffer(r.stdout, dtype=np.float32).reshape(-1, channels).copy()


def resample(a: np.ndarray, sr: int, target: int) -> np.ndarray:
    from .tts import resample as _rs

    return _rs(a, sr, target)


def uvr_model(progress=None) -> Path:
    from .download import fetch
    from .platform_info import models_dir, resource_root

    b = resource_root() / "models" / "separation" / "UVR-MDX-NET-Voc_FT.onnx"
    if b.exists():
        return b
    p = models_dir() / "separation" / "UVR-MDX-NET-Voc_FT.onnx"
    if not p.exists():
        fetch(UVR_URL, p, progress, "voice separation model")
    return p


_SEP = {}


def separate(stereo: np.ndarray, sr: int = 44100, progress=None, chunk_s: float = 4.0,
             overlap_s: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    """Split a mix into (voice, music) — both (frames, 2) at `sr`. Processed in overlapping chunks
    with a cross-fade so memory stays low (~2 GB) on long files."""
    import os

    import sherpa_onnx

    key = str(uvr_model(progress))
    if key not in _SEP:
        _SEP[key] = sherpa_onnx.OfflineSourceSeparation(sherpa_onnx.OfflineSourceSeparationConfig(
            model=sherpa_onnx.OfflineSourceSeparationModelConfig(
                uvr=sherpa_onnx.OfflineSourceSeparationUvrModelConfig(model=key),
                num_threads=max(1, min(8, os.cpu_count() or 2)))))
    sp = _SEP[key]
    if stereo.ndim == 1:
        stereo = np.stack([stereo, stereo], 1)
    n = len(stereo)
    C, O = int(chunk_s * sr), int(overlap_s * sr)
    voice = np.zeros((n, 2), dtype=np.float32)
    weight = np.zeros(n, dtype=np.float32)
    s = 0
    while s < n:
        e = min(n, s + C)
        piece = np.ascontiguousarray(stereo[s:e].T)
        o = sp.process(sample_rate=sr, samples=piece)
        v = np.asarray(o.stems[0].data, dtype=np.float32).T
        if o.sample_rate != sr:
            v = np.stack([resample(v[:, c], o.sample_rate, sr) for c in range(v.shape[1])], 1)
        v = v[:e - s]
        w = np.ones(len(v), dtype=np.float32)
        if s > 0:
            w[:min(O, len(w))] = np.linspace(0, 1, min(O, len(w)), dtype=np.float32)
        if e < n:
            w[-min(O, len(w)):] = np.minimum(w[-min(O, len(w)):], np.linspace(1, 0, min(O, len(w)), dtype=np.float32))
        voice[s:s + len(v)] += v * w[:, None]
        weight[s:s + len(v)] += w
        if progress:
            progress(e / n, f"Separating voice from music: {e / sr:.0f} of {n / sr:.0f} s")
        if e >= n:
            break
        s = e - O
    voice /= np.maximum(weight, 1e-6)[:, None]
    return voice, stereo - voice


def speech_spans(mono: np.ndarray, sr: int, frame: float = 0.05, floor_db: float = -38.0,
                 min_gap: float = 0.35) -> list[tuple[float, float]]:
    """Continuous voiced spans (seconds) from frame energy; short gaps are bridged."""
    fr = int(sr * frame)
    if len(mono) < fr:
        return []
    frames = mono[:len(mono) // fr * fr].reshape(-1, fr)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(1)) + 1e-9)
    peak = np.percentile(db, 95)
    on = db > max(floor_db, peak - 30)
    spans, start, last_on = [], None, None
    for i, v in enumerate(on):
        t = i * frame
        if v:
            if start is None:
                start = t
            last_on = t + frame
        elif start is not None and t - last_on > min_gap:
            spans.append((start, last_on))
            start = None
    if start is not None:
        spans.append((start, last_on))
    return spans


def pick_reference(mono: np.ndarray, sr: int, lo: float = 6.0, hi: float = 12.0) -> tuple[float, float]:
    """Choose the best reference window: mostly speech, few long pauses, steady loudness, ~6–12 s."""
    spans = speech_spans(mono, sr)
    if not spans:
        return 0.0, min(len(mono) / sr, hi)
    best, best_score = None, -1e9
    for i in range(len(spans)):
        s = spans[i][0]
        for j in range(i, len(spans)):
            e = spans[j][1]
            dur = e - s
            if dur > hi:
                break
            if dur < lo:
                continue
            voiced = sum(b - a for a, b in spans[i:j + 1])
            seg = mono[int(s * sr):int(e * sr)]
            fr = int(0.1 * sr)
            rms = np.sqrt((seg[:len(seg) // fr * fr].reshape(-1, fr) ** 2).mean(1)) + 1e-9
            steady = -np.std(20 * np.log10(rms[rms > np.percentile(rms, 30)]))
            score = voiced / dur * 10 + steady * 0.3 + min(dur, 10) * 0.2
            if score > best_score:
                best, best_score = (s, e), score
    if best is None:  # no window long enough: take the longest span (padded)
        s, e = max(spans, key=lambda x: x[1] - x[0])
        return max(0.0, s - 0.1), min(len(mono) / sr, e + 0.1)
    return max(0.0, best[0] - 0.08), min(len(mono) / sr, best[1] + 0.12)


def transcribe_clip(mono16k: np.ndarray, lang: str = "en") -> str:
    """What is said in the reference clip (local Parakeet; multilingual v3 for European languages)."""
    from .engines.base import DecodeOptions
    from .engines.sherpa import PARAKEET_V3_LANGS, ParakeetEngine

    variant = "parakeet-v2" if lang == "en" else ("parakeet-v3" if lang in PARAKEET_V3_LANGS else "")
    if not variant:
        return ""
    t = ParakeetEngine(variant).transcribe(mono16k.astype(np.float32), [(0.0, len(mono16k) / 16000)],
                                            DecodeOptions(language=lang))
    return " ".join(s.text.strip() for s in t.segments).strip()


def create_from_recording(path: str | Path, name: str, gender: str = "female", character: str = "custom voice",
                          lang: str = "en", owner: str = "", rights: str = "", consent_id: str = "",
                          remove_music: bool | None = None, ref_text: str = "", progress=None) -> CustomVoice:
    """Build a custom voice from any recording. remove_music=None decides automatically."""
    if not consent_id:
        raise ValueError("A consent-register entry is required before a voice can be created")
    sr = 44100
    stereo = decode(path, sr, 2)
    if progress:
        progress(0.05, "Reading the recording…")
    mono = stereo.mean(1)
    voice = mono
    if remove_music is None:
        remove_music = music_likely(mono, sr)
    if remove_music:
        v, _ = separate(stereo, sr, (lambda f, m: progress(0.05 + 0.6 * f, m)) if progress else None)
        voice = v.mean(1)
    s, e = pick_reference(voice, sr)
    clip = voice[int(s * sr):int(e * sr)]
    clip = clip / max(1e-6, float(np.abs(clip).max())) * 0.9
    ref = resample(clip, sr, REF_SR)
    if progress:
        progress(0.8, "Listening to the reference clip…")
    if not ref_text:
        try:
            ref_text = transcribe_clip(resample(clip, sr, 16000), lang)
        except Exception:
            ref_text = ""
    cv = CustomVoice(f"my:{unique_slug(name)}", name.strip(), gender, character, lang, ref_text, Path(path).name,
                     owner, rights, consent_id, datetime.now().isoformat(timespec="seconds"))
    save(cv, ref)
    # keep the cleaned full voice too: more reference material for emotion range and cloud cloning
    write_wav(cv.folder / "full_voice.wav", resample(voice, sr, REF_SR), REF_SR)
    if progress:
        progress(1.0, f"Voice “{cv.name}” is ready")
    return cv


def unique_slug(name: str) -> str:
    base = slugify(name)
    slug, k = base, 2
    while (voices_dir() / slug).exists():
        slug, k = f"{base}-{k}", k + 1
    return slug


def music_likely(mono: np.ndarray, sr: int) -> bool:
    """Music under the voice keeps the 'silence' between phrases loud; clean voice drops to the floor."""
    fr = int(0.05 * sr)
    if len(mono) < fr * 20:
        return False
    frames = mono[:len(mono) // fr * fr].reshape(-1, fr)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(1)) + 1e-9)
    return float(np.percentile(db, 95) - np.percentile(db, 10)) < 35.0


PACK_EXT = ".verbatimvoices"


def export_pack(voice_ids: list[str], dest: str | Path) -> Path:
    """Share voices privately (e.g. with a colleague): a zip of voice.json + reference audio."""
    import zipfile

    dest = Path(dest)
    if dest.suffix != PACK_EXT:
        dest = dest.with_suffix(PACK_EXT)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for vid in voice_ids:
            cv = get(vid)
            if not cv:
                continue
            for f in cv.folder.iterdir():
                if f.is_file() and f.suffix in (".json", ".wav"):
                    z.write(f, f"{cv.slug}/{f.name}")
    return dest


def import_pack(path: str | Path, owner_declared: bool = True, recorded_by: str = "") -> list[CustomVoice]:
    """Import a .verbatimvoices pack. Each voice gets a consent-register entry for its stated owner."""
    import tempfile
    import zipfile

    from .consent import ConsentRegister

    out = []
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(path) as z:
        for m in z.namelist():
            if m.startswith("/") or ".." in Path(m).parts:
                raise RuntimeError("Unsafe path in voice pack")
        z.extractall(tmp)
        reg = ConsentRegister()
        for vj in sorted(Path(tmp).glob("*/voice.json")):
            d = json.loads(vj.read_text(encoding="utf-8"))
            cv = CustomVoice(**{k: v for k, v in d.items() if k in CustomVoice.__dataclass_fields__})
            if get(cv.id):
                continue
            if owner_declared:
                e = reg.valid_for(cv.owner) or reg.add_declaration(
                    cv.owner, f"Voice “{cv.name}” imported from a VERBATIM voice pack. Rights: {cv.rights}",
                    recorded_by=recorded_by)
                cv.consent_id = e["id"]
            cv.eleven_id = ""          # clones belong to the original ElevenLabs account
            shutil.copytree(vj.parent, cv.folder, dirs_exist_ok=True)
            save(cv)
            out.append(cv)
    return out


def import_bundled(progress=None) -> int:
    """First run: copy the voices shipped with VERBATIM (assets/voices) into the library."""
    from .platform_info import asset

    src = asset("voices")
    if not src.exists():
        return 0
    n = 0
    for vj in sorted(src.glob("*/voice.json")):
        dest = voices_dir() / vj.parent.name
        if (dest / "voice.json").exists():
            continue
        shutil.copytree(vj.parent, dest, dirs_exist_ok=True)
        n += 1
    return n


# ---------------------------------------------------------------- diagnostics
DIAG_LINES = {"en": "Every story begins with a single moment of belief — and today, that moment is yours.",
              "hi": "हर कहानी विश्वास के एक पल से शुरू होती है — और आज, वह पल आपका है।"}


def run_diagnostics(out_dir: str | Path, progress=None) -> Path:
    """Speak a test line with every installed engine (and each custom voice) → WAVs + report.txt.
    Used to verify a new installation; nothing leaves the computer."""
    import platform
    import time
    import traceback

    from . import __version__, tts, tts_chatterbox

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = [f"VERBATIM {__version__} voice diagnostics — {datetime.now().isoformat(timespec='seconds')}",
            f"{platform.platform()} · {platform.machine()}", ""]
    tests = []
    if tts.is_installed("st"):
        tests += [("studio-en", "en", "st:6", None), ("studio-hi", "hi", "st:1", None)]
    if tts_chatterbox.is_installed():
        tests += [("expressive-en-inspiring", "en", "cb:st:6", {"emotion": "inspiring", "intensity": 0.7}),
                  ("expressive-hi-warm", "hi", "cb:st:1", {"emotion": "warm", "intensity": 0.6})]
    for cv in library()[:3]:
        tests.append((f"custom-{cv.slug}-en", "en", cv.id, {"emotion": "inspiring", "intensity": 0.6}))
        if tts_chatterbox.is_installed():
            tests.append((f"custom-{cv.slug}-hi", "hi", cv.id, {"emotion": "warm", "intensity": 0.6}))
    for k, (name, lang, vid, d) in enumerate(tests):
        if progress:
            progress(k / max(1, len(tests)), f"Testing {name}…")
        t0 = time.time()
        try:
            engines = ("auto",)
            if vid.startswith("my:") and lang == "en":
                engines = ("zipvoice", "chatterbox") if tts_chatterbox.is_installed() else ("zipvoice",)
            for engine in engines:
                a = tts.Synth(clone_engine=engine).speak(DIAG_LINES[lang], lang, vid, 1.0, d)
                tag = name if engine == "auto" else f"{name}-{engine}"
                write_wav(out / f"{tag}.wav", a, tts.SAMPLE_RATE)
                rows.append(f"OK    {tag:44s} {len(a) / tts.SAMPLE_RATE:5.1f} s audio in {time.time() - t0:5.1f} s")
                t0 = time.time()
        except Exception as exc:
            rows.append(f"FAIL  {name:44s} {type(exc).__name__}: {exc}")
            rows.append("      " + traceback.format_exc().strip().splitlines()[-3].strip())
    rep = out / "report.txt"
    rep.write_text("\n".join(rows) + "\n", encoding="utf-8")
    if progress:
        progress(1.0, "Diagnostics finished")
    return rep
