"""Local text-to-speech for Voice Studio — two engines, one voice library.

- Supertonic 3 (Supertone; code MIT, model OpenRAIL-M): natural studio-style voices, 5 female + 5 male,
  each speaking 31 languages incl. Hindi, English, Russian, Japanese, Spanish, French, Arabic, German,
  Italian, Portuguese, Korean, Turkish, Ukrainian, Vietnamese, Indonesian, Polish, Dutch.
- Kokoro v1.0 (Apache-2.0): extra English voices plus Chinese (Supertonic has no Chinese).

Both run offline through sherpa-onnx; models download once from the sherpa-onnx GitHub releases.
A voice id is "<engine>:<speaker>", e.g. "st:6" (Supertonic male, deep) or "ko:47" (Kokoro Xiaoxiao).
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
}
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


def voices_for(lang: str) -> list[Voice]:
    """Best voices first: Supertonic, then Kokoro; female/male alternate in the default order."""
    vs = [v for v in VOICES.values() if lang in v.langs]
    return sorted(vs, key=lambda v: (v.engine != "st", v.gender != "female", v.id))


def supported_languages() -> list[str]:
    return sorted({lang for v in VOICES.values() for lang in v.langs})


def default_voices(lang: str, n: int) -> list[str]:
    """n distinct voices alternating female/male (Supertonic first)."""
    vs = voices_for(lang)
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
    from .platform_info import models_dir

    return (Path(root) if root else models_dir() / "tts") / ENGINES[engine]["name"]


def is_installed(engine: str = "st", root: Path | None = None) -> bool:
    d = model_dir(engine, root)
    return (d / ("voice.bin" if engine == "st" else "voices.bin")).exists()


def ensure(engine: str, progress=None, root: Path | None = None) -> Path:
    d = model_dir(engine, root)
    if is_installed(engine, root):
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
    return d


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
                 engines: tuple = ("st", "ko")):
        self.root, self.progress, self.quality = root, progress, quality
        self.wanted = engines

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

    def speak(self, text: str, lang: str, voice: str | int, speed: float = 1.0) -> np.ndarray:
        """Audio at SAMPLE_RATE. `voice` is a library id ("st:6") — a bare int means Kokoro (older jobs)."""
        text = " ".join(text.split())
        if not text:
            return np.zeros(0, dtype=np.float32)
        vid = f"ko:{voice}" if isinstance(voice, int) or str(voice).isdigit() else str(voice)
        v = VOICES.get(vid)
        if v is None or lang not in v.langs:  # fall back to the first voice for this language
            options = voices_for(lang)
            if not options:
                raise ValueError(f"No voice for language '{lang}'")
            v = options[0]
        sid = int(v.id.split(":")[1])
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
