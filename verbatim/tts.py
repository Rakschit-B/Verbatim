# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Text-to-speech for Voice Studio — one voice library, several engines.

- Supertonic 3 (Supertone; code MIT, model OpenRAIL-M): natural studio-style voices, 5 female + 5 male,
  each speaking 31 languages incl. Hindi, English, Russian, Japanese, Spanish, French, Arabic, German,
  Italian, Portuguese, Korean, Turkish, Ukrainian, Vietnamese, Indonesian, Polish, Dutch.
- Kokoro v1.0 (Apache-2.0): extra English voices plus Chinese (Supertonic has no Chinese).

Both run offline through sherpa-onnx; models download once from the sherpa-onnx GitHub releases.
A voice id is "<engine>:<speaker>", e.g. "st:6" (Supertonic male, deep) or "ko:47" (Kokoro Xiaoxiao).
3.4 adds expressive and custom voices:
- "cb:st:6"  Expressive (Chatterbox) version of a studio voice — emotional delivery in 23 languages
- "my:<slug>" a custom voice from Voice Lab (your narration), spoken by Chatterbox (23 languages),
              ZipVoice (English/Chinese, local) or ElevenLabs (cloud clone) — whichever is available
- "el:<id>"  an ElevenLabs voice, "az:<name>" an Azure Neural voice (optional cloud engines)
Every engine receives the line's performance direction (emotion, intensity, emphasis — direction.py).
All audio is returned at SAMPLE_RATE (48 kHz) so engines can be mixed in one voiceover.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 48000

ENGINES = {
    "st": {"name": "sherpa-onnx-supertonic-3-tts-int8-2026-05-11", "size_mb": 140, "label": "Supertonic 3"},
    "ko": {"name": "kokoro-multi-lang-v1_0", "size_mb": 330, "label": "Kokoro"},
    "zv": {"name": "sherpa-onnx-zipvoice-distill-int8-zh-en-emilia", "size_mb": 160, "label": "ZipVoice (voice cloning)"},
}
ZV_EXTRA = [("vocoder-models", "vocos_24khz.onnx")]   # English goes through espeak-ng (bundled data)
CLONE_SAMPLE = ("Every story begins with a single moment. We listen closely, we feel deeply, and then, "
                "together, we tell it beautifully.")
BASE_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
SIZE_MB = ENGINES["st"]["size_mb"] + ENGINES["ko"]["size_mb"]

SUPERTONIC_LANGS = ["en", "ko", "ja", "ar", "bg", "cs", "da", "de", "el", "es", "et", "fi", "fr", "hi", "hr", "hu",
                    "id", "it", "lt", "lv", "nl", "pl", "pt", "ro", "ru", "sk", "sl", "sv", "tr", "uk", "vi"]
KOKORO_LANGS = {"en": "en", "hi": "hi", "es": "es", "fr": "fr", "it": "it", "pt": "pt-br", "ja": "ja", "zh": "zh"}


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    gender: str          # "female" | "male"
    character: str       # short description
    engine: str          # "st" | "ko"
    langs: tuple

    @property
    def label(self) -> str:
        return f"{self.name} — {self.gender}, {self.character}"


# Supertonic speakers 0–4 are female (F1–F5), 5–9 male (M1–M5). Character from measured pitch and timbre.
_ST = [(0, "Aria", "female", "bright, clear"), (1, "Maya", "female", "friendly, warm"),
       (2, "Leela", "female", "warm, mid-tone"), (3, "Nina", "female", "bright, energetic"),
       (4, "Sara", "female", "calm, low"), (5, "Kabir", "male", "light, young"),
       (6, "Dev", "male", "deep, authoritative"), (7, "Arjun", "male", "smooth, mid-tone"),
       (8, "Rohan", "male", "friendly, mid-tone"), (9, "Vikram", "male", "deep, documentary")]
_KO = [(3, "Heart", "female", "warm, US", ("en",)), (2, "Bella", "female", "soft, US", ("en",)),
       (21, "Emma", "female", "British", ("en",)), (16, "Michael", "male", "US", ("en",)),
       (26, "George", "male", "British", ("en",)),
       (31, "Alpha", "female", "Kokoro Hindi", ("hi",)), (33, "Omega", "male", "Kokoro Hindi", ("hi",)),
       (47, "Xiaoxiao", "female", "Mandarin", ("zh",)), (45, "Xiaobei", "female", "Mandarin", ("zh",)),
       (50, "Yunxi", "male", "Mandarin", ("zh",)), (52, "Yunyang", "male", "Mandarin, newsreader", ("zh",)),
       (37, "Alpha", "female", "Kokoro Japanese", ("ja",)), (41, "Kumo", "male", "Kokoro Japanese", ("ja",)),
       (28, "Dora", "female", "Kokoro Spanish", ("es",)), (29, "Alex", "male", "Kokoro Spanish", ("es",)),
       (30, "Siwis", "female", "Kokoro French", ("fr",)), (35, "Sara", "female", "Kokoro Italian", ("it",)),
       (36, "Nicola", "male", "Kokoro Italian", ("it",)), (42, "Dora", "female", "Kokoro Portuguese", ("pt",)),
       (43, "Alex", "male", "Kokoro Portuguese", ("pt",))]

VOICES: dict[str, Voice] = {}
for sid, name, g, ch in _ST:
    VOICES[f"st:{sid}"] = Voice(f"st:{sid}", name, g, ch, "st", tuple(SUPERTONIC_LANGS))
for sid, name, g, ch, langs in _KO:
    VOICES[f"ko:{sid}"] = Voice(f"ko:{sid}", name, g, ch, "ko", langs)


def voices_for(lang: str, extended: bool = True) -> list[Voice]:
    """Voices that can speak `lang`, best first: your custom voices, Expressive (Chatterbox) studio voices,
    studio voices (Supertonic), Kokoro, then cloud voices whose key is set."""
    vs = [v for v in VOICES.values() if lang in v.langs]
    vs = sorted(vs, key=lambda v: (v.engine != "st", v.gender != "female", v.id))
    if not extended:
        return vs
    return custom_voices(lang) + expressive_voices(lang) + vs + cloud_voices(lang)


def custom_voices(lang: str) -> list[Voice]:
    from . import tts_chatterbox, voicelab

    langs = tuple(sorted(tts_chatterbox.LANGS | {"en", "zh"}))
    out = []
    for cv in voicelab.library():
        if lang in langs:
            out.append(Voice(cv.id, f"★ {cv.name}", cv.gender, cv.character, "my", langs))
    return out


def expressive_voices(lang: str) -> list[Voice]:
    """Studio voices performed by Chatterbox — real emotion, 23 languages (when the voice pack is installed)."""
    from . import tts_chatterbox

    if lang not in tts_chatterbox.LANGS or not tts_chatterbox.is_installed():
        return []
    out = []
    for sid, name, g, ch in _ST:
        out.append(Voice(f"cb:st:{sid}", f"{name} · Expressive", g, ch, "cb", tuple(sorted(tts_chatterbox.LANGS))))
    return sorted(out, key=lambda v: (v.gender != "female", v.id))


def cloud_voices(lang: str) -> list[Voice]:
    out = []
    try:
        from . import tts_cloud

        if tts_cloud.azure_key()[0]:
            for name, label, g in tts_cloud.AZURE_VOICES.get(lang, []):
                out.append(Voice(f"az:{name}", f"{label} · Azure", g, "Azure Neural", "az", (lang,)))
    except Exception:
        pass
    return out


def find_voice(vid: str, lang: str = "") -> Voice | None:
    if vid in VOICES:
        return VOICES[vid]
    for v in voices_for(lang) if lang else []:
        if v.id == vid:
            return v
    return None


def supported_languages() -> list[str]:
    return sorted({lang for v in VOICES.values() for lang in v.langs})


def default_voices(lang: str, n: int) -> list[str]:
    """n distinct voices alternating female/male — Expressive voices when installed, then studio voices."""
    vs = expressive_voices(lang) + voices_for(lang, extended=False)
    fem = [v.id for v in vs if v.gender == "female"]
    mal = [v.id for v in vs if v.gender == "male"]
    out = []
    for k in range(n):
        pool = fem if k % 2 == 0 else mal
        pool = pool or fem or mal
        out.append(pool[(k // 2) % len(pool)] if pool else "")
    return out


# ---------------------------------------------------------------- models
def model_dir(engine: str, root: Path | None = None) -> Path:
    """Bundled inside the app (resources/models/tts — 3.4 ships the voices for offline use), else downloaded."""
    from .platform_info import models_dir, resource_root

    if root:
        return Path(root) / ENGINES[engine]["name"]
    bundled = resource_root() / "models" / "tts" / ENGINES[engine]["name"]
    if bundled.exists():
        return bundled
    return models_dir() / "tts" / ENGINES[engine]["name"]


def is_installed(engine: str = "st", root: Path | None = None) -> bool:
    if engine == "cb":
        from . import tts_chatterbox

        return tts_chatterbox.is_installed()
    d = model_dir(engine, root)
    if engine == "zv":
        return (d / "encoder.int8.onnx").exists() and all((d / f).exists() for _, f in ZV_EXTRA)
    return (d / ("voice.bin" if engine == "st" else "voices.bin")).exists()


def ensure(engine: str, progress=None, root: Path | None = None) -> Path:
    if engine == "cb":
        from . import tts_chatterbox

        return tts_chatterbox.ensure(progress)
    d = model_dir(engine, root)
    if is_installed(engine, root):
        return d
    if engine == "zv" and (d / "encoder.int8.onnx").exists():
        _zv_extras(d, progress)
        return d
    import tarfile

    from .download import fetch

    d.parent.mkdir(parents=True, exist_ok=True)
    name = ENGINES[engine]["name"]
    tmp = d.parent / f"{name}.tar.bz2"
    fetch(BASE_URL + name + ".tar.bz2", tmp, progress, f"{ENGINES[engine]['label']} voices")
    with tarfile.open(tmp) as t:
        members = [m for m in t.getmembers() if "test_wavs" not in m.name]
        try:
            t.extractall(d.parent, members=members, filter="data")
        except TypeError:
            t.extractall(d.parent, members=members)
    tmp.unlink(missing_ok=True)
    if engine == "zv":
        _zv_extras(d, progress)
    return d


def _zv_extras(d: Path, progress=None):
    from .download import fetch

    for tag, f in ZV_EXTRA:
        if not (d / f).exists():
            fetch(f"https://github.com/k2-fsa/sherpa-onnx/releases/download/{tag}/{f}", d / f, progress, f)
            if f.startswith("lexicon"):
                fix_lexicon(d / f)


def fix_lexicon(p: Path):
    """The current sherpa-onnx English lexicon is "word || phones" with a comment header; ZipVoice reads the
    classic "word phones" form. Convert in place (multi-word entries are left to espeak)."""
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if " || " in line:
            word, phones = line.split(" || ", 1)
            if " " in word.strip():
                continue
            line = f"{word.strip()} {phones.strip()}"
        out.append(line)
    p.write_text("\n".join(out) + "\n", encoding="utf-8")


def resample(a: np.ndarray, sr: int, target: int = SAMPLE_RATE) -> np.ndarray:
    if sr == target or len(a) == 0:
        return a.astype(np.float32)
    try:
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(sr, target)
        return resample_poly(a, target // g, sr // g).astype(np.float32)
    except Exception:
        n = int(round(len(a) * target / sr))
        return np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)


class Synth:
    """Speaks text with any library voice. quality: 'standard' (fast) or 'studio' (more refinement steps)."""
    _engines: dict = {}
    _lock = threading.Lock()

    def __init__(self, root: Path | None = None, progress=None, quality: str = "standard",
                 engines: tuple = ("st", "ko"), clone_engine: str = "auto", eleven_model: str = "eleven_v3",
                 seed: int | None = 7):
        self.root, self.progress, self.quality = root, progress, quality
        self.wanted = engines
        self.clone_engine = clone_engine      # auto | chatterbox | zipvoice | elevenlabs
        self.eleven_model = eleven_model
        self.seed = seed

    def _threads(self):
        return max(1, min(8, os.cpu_count() or 2))

    def _supertonic(self):
        import sherpa_onnx

        d = ensure("st", self.progress, self.root)
        key = ("st", str(d))
        with self._lock:
            if key not in self._engines:
                cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
                    supertonic=sherpa_onnx.OfflineTtsSupertonicModelConfig(
                        duration_predictor=str(d / "duration_predictor.int8.onnx"),
                        text_encoder=str(d / "text_encoder.int8.onnx"),
                        vector_estimator=str(d / "vector_estimator.int8.onnx"),
                        vocoder=str(d / "vocoder.int8.onnx"), tts_json=str(d / "tts.json"),
                        unicode_indexer=str(d / "unicode_indexer.bin"), voice_style=str(d / "voice.bin")),
                    num_threads=self._threads()))
                self._engines[key] = sherpa_onnx.OfflineTts(cfg)
            return self._engines[key]

    def _kokoro(self, lang: str):
        import sherpa_onnx

        d = ensure("ko", self.progress, self.root)
        code = KOKORO_LANGS[lang]
        key = ("ko", str(d), code)
        with self._lock:
            if key not in self._engines:
                lex = [d / "lexicon-us-en.txt", d / "lexicon-zh.txt"]
                if lang == "zh":
                    lex.reverse()
                k = sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(d / "model.onnx"), voices=str(d / "voices.bin"), tokens=str(d / "tokens.txt"),
                    data_dir=str(d / "espeak-ng-data"), dict_dir=str(d / "dict"),
                    lexicon=",".join(str(p) for p in lex), lang=code)
                cfg = sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(kokoro=k, num_threads=self._threads()), max_num_sentences=1)
                self._engines[key] = sherpa_onnx.OfflineTts(cfg)
            return self._engines[key]

    # ------------------------------------------------------------ expressive / custom engines
    def _zipvoice(self):
        import sherpa_onnx

        d = ensure("zv", self.progress, self.root)
        key = ("zv", str(d))
        with self._lock:
            if key not in self._engines:
                cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
                    zipvoice=sherpa_onnx.OfflineTtsZipvoiceModelConfig(
                        tokens=str(d / "tokens.txt"), encoder=str(d / "encoder.int8.onnx"),
                        decoder=str(d / "decoder.int8.onnx"), data_dir=str(d / "espeak-ng-data"),
                        lexicon=str(d / "lexicon.txt"), vocoder=str(d / "vocos_24khz.onnx")),
                    num_threads=self._threads()))
                self._engines[key] = sherpa_onnx.OfflineTts(cfg)
            return self._engines[key]

    def studio_reference(self, sid: int) -> tuple[np.ndarray, int]:
        """A studio voice's own reading of a fixed passage — used to give it Chatterbox expressiveness."""
        from .platform_info import models_dir

        p = models_dir() / "tts" / "expressive-refs" / f"st{sid}.wav"
        if not p.exists():
            a = self.speak(CLONE_SAMPLE, "en", f"st:{sid}", 1.0)
            p.parent.mkdir(parents=True, exist_ok=True)
            from .voicelab import write_wav

            write_wav(p, a, SAMPLE_RATE)
        from .voicelab import read_wav

        return read_wav(p)

    def _custom(self, text, lang, cv, speed, direction):
        from . import direction as dr
        from . import tts_chatterbox, voicelab

        d = direction or {}
        emo, inten = d.get("emotion", "neutral"), float(d.get("intensity", 0.5) or 0.5)
        pref = self.clone_engine
        ref, sr = voicelab.reference(cv)
        if pref in ("auto", "chatterbox") and lang in tts_chatterbox.LANGS and \
                (pref == "chatterbox" or tts_chatterbox.is_installed()):
            return self._chatterbox(text, lang, ref, sr, cv.id, d, speed)
        if pref in ("auto", "zipvoice") and lang in ("en", "zh") and cv.ref_text:
            import sherpa_onnx

            g = sherpa_onnx.GenerationConfig()
            g.reference_audio = ref.astype(np.float32)
            g.reference_sample_rate = sr
            g.reference_text = cv.ref_text
            g.num_steps = 16 if self.quality == "studio" else 8
            g.speed = float(speed)
            g.extra["min_char_in_sentence"] = "30"
            audio = self._zipvoice().generate(dr.shape_text(text, emo), g)
            return resample(np.asarray(audio.samples, dtype=np.float32), audio.sample_rate)
        if cv.eleven_id:
            from . import tts_cloud

            el = tts_cloud.ElevenLabs(model=self.eleven_model)
            a, r = el.speak(dr.eleven_text(text, emo, inten, d.get("emphasis", "")), cv.eleven_id, lang, speed,
                            dr.eleven_settings(emo, inten))
            return resample(a, r)
        raise RuntimeError(f"To speak {lang} in “{cv.name}”, download the Expressive voice pack (Chatterbox) "
                           "in Settings › Voice engines, or clone it to ElevenLabs.")

    def _chatterbox(self, text, lang, ref, sr, key, d, speed):
        from . import direction as dr
        from . import tts_chatterbox

        emo, inten = d.get("emotion", "neutral"), float(d.get("intensity", 0.5) or 0.5)
        base = dr.info(emo)["ex"]
        ex = max(0.25, min(1.2, base + (inten - 0.5) * 0.5))
        cb = tts_chatterbox.Chatterbox.get(self.progress)
        a = cb.generate(dr.shape_text(text, emo), lang, ref, sr, voice_key=key, exaggeration=ex,
                        temperature=0.7 if self.quality == "studio" else 0.8, seed=self.seed)
        a = resample(a, tts_chatterbox.SR)
        if abs(speed - 1.0) > 0.02:
            a = time_stretch(a, speed)
        return a

    def speak(self, text: str, lang: str, voice: str | int, speed: float = 1.0, direction: dict | None = None
              ) -> np.ndarray:
        """Audio at SAMPLE_RATE. `voice` is a library id ("st:6", "cb:st:6", "my:rakschit", "az:…", "el:…");
        a bare int means Kokoro (older jobs). `direction` = {emotion, intensity, emphasis} for this line."""
        text = " ".join(text.split())
        if not text:
            return np.zeros(0, dtype=np.float32)
        d = direction or {}
        vid = f"ko:{voice}" if isinstance(voice, int) or str(voice).isdigit() else str(voice)
        if vid.startswith("my:"):
            from . import voicelab

            cv = voicelab.get(vid)
            if cv:
                return self._custom(text, lang, cv, speed, d)
            vid = ""
        if vid.startswith("cb:st:"):
            from . import tts_chatterbox

            if lang in tts_chatterbox.LANGS:
                sid = int(vid.split(":")[2])
                ref, sr = self.studio_reference(sid)
                return self._chatterbox(text, lang, ref, sr, vid, d, speed)
            vid = vid[3:]
        if vid.startswith("az:"):
            from . import direction as dr
            from . import tts_cloud

            loc = tts_cloud.AZ_LOCALE.get(lang, "en-US")
            ssml = dr.azure_ssml(text, vid[3:], loc, d.get("emotion", "neutral"), float(d.get("intensity", 0.5) or 0.5),
                                 d.get("emphasis", ""), speed)
            a, r = tts_cloud.Azure().speak_ssml(ssml)
            return resample(a, r)
        if vid.startswith("el:"):
            from . import direction as dr
            from . import tts_cloud

            emo, inten = d.get("emotion", "neutral"), float(d.get("intensity", 0.5) or 0.5)
            a, r = tts_cloud.ElevenLabs(model=self.eleven_model).speak(
                dr.eleven_text(text, emo, inten, d.get("emphasis", "")), vid[3:], lang, speed,
                dr.eleven_settings(emo, inten))
            return resample(a, r)
        v = VOICES.get(vid)
        if v is None or lang not in v.langs:  # fall back to the first voice for this language
            options = voices_for(lang, extended=False)
            if not options:
                raise ValueError(f"No voice for language '{lang}'")
            v = options[0]
        sid = int(v.id.split(":")[1])
        if d.get("emotion"):
            from . import direction as dr

            text = dr.shape_text(text, d["emotion"])
        if v.engine == "st":
            import sherpa_onnx

            tts = self._supertonic()
            g = sherpa_onnx.GenerationConfig()
            g.sid = sid
            g.num_steps = 16 if self.quality == "studio" else 8
            g.speed = float(speed)
            g.extra["lang"] = lang
            audio = tts.generate(text, g)
        else:
            audio = self._kokoro(lang).generate(text, sid=sid, speed=float(speed))
        return resample(np.asarray(audio.samples, dtype=np.float32), audio.sample_rate)


def time_stretch(a: np.ndarray, rate: float) -> np.ndarray:
    """Change tempo without changing pitch (WSOLA-style overlap-add). rate > 1 = faster."""
    if len(a) < 2048 or abs(rate - 1) < 0.01:
        return a
    win, hop_out = 1024, 256
    hop_in = hop_out * rate
    w = np.hanning(win).astype(np.float32)
    n_out = int(len(a) / rate) + win
    out = np.zeros(n_out, dtype=np.float32)
    norm = np.zeros(n_out, dtype=np.float32)
    pos_in, pos_out, prev = 0.0, 0, None
    tol = 128
    while int(pos_in) + win + tol < len(a) and pos_out + win < n_out:
        c = int(pos_in)
        if prev is not None:   # pick the offset that best continues the previous grain
            seg = a[max(0, c - tol): c + tol + win]
            best, score = c, -1e9
            for k in range(0, len(seg) - win, 16):
                sc = float(np.dot(seg[k:k + hop_out], prev))
                if sc > score:
                    best, score = max(0, c - tol) + k, sc
            c = best
        g = a[c:c + win]
        out[pos_out:pos_out + win] += g * w
        norm[pos_out:pos_out + win] += w
        prev = a[c + hop_out:c + 2 * hop_out] if c + 2 * hop_out <= len(a) else None
        pos_in += hop_in
        pos_out += hop_out
    norm[norm < 1e-3] = 1.0
    return (out / norm)[:int(len(a) / rate)]
