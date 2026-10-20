"""Local text-to-speech for Voice Studio: Kokoro v1.0 (Apache-2.0) through sherpa-onnx.

Stock voices only (no cloning — that is Phase 4, behind the consent register). Runs offline on
Mac and Windows; the 330 MB model downloads once from the sherpa-onnx GitHub releases.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

MODEL_NAME = "kokoro-multi-lang-v1_0"
MODEL_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/{MODEL_NAME}.tar.bz2"
SIZE_MB = 330
SAMPLE_RATE = 24000

# language -> (espeak/kokoro language code, [(speaker id, label)])
VOICES: dict[str, tuple[str, list[tuple[int, str]]]] = {
    "en": ("en", [(3, "Heart — female, US"), (2, "Bella — female, US"), (9, "Sarah — female, US"),
                  (16, "Michael — male, US"), (14, "Fenrir — male, US"), (11, "Adam — male, US"),
                  (21, "Emma — female, UK"), (26, "George — male, UK"), (24, "Daniel — male, UK")]),
    "hi": ("hi", [(31, "Alpha — female"), (32, "Beta — female"), (33, "Omega — male"), (34, "Psi — male")]),
    "es": ("es", [(28, "Dora — female"), (29, "Alex — male")]),
    "fr": ("fr", [(30, "Siwis — female")]),
    "it": ("it", [(35, "Sara — female"), (36, "Nicola — male")]),
    "pt": ("pt-br", [(42, "Dora — female, BR"), (43, "Alex — male, BR")]),
    "ja": ("ja", [(37, "Alpha — female"), (41, "Kumo — male")]),
    "zh": ("zh", [(47, "Xiaoxiao — female"), (45, "Xiaobei — female"), (50, "Yunxi — male"), (52, "Yunyang — male")]),
}


def supported_languages() -> list[str]:
    return list(VOICES)


def voices_for(lang: str) -> list[tuple[int, str]]:
    return VOICES.get(lang, (None, []))[1]


def model_dir(root: Path | None = None) -> Path:
    from .platform_info import models_dir

    return (Path(root) if root else models_dir() / "tts") / MODEL_NAME


def is_installed(root: Path | None = None) -> bool:
    d = model_dir(root)
    return (d / "model.onnx").exists() and (d / "voices.bin").exists()


def ensure(progress=None, root: Path | None = None) -> Path:
    d = model_dir(root)
    if is_installed(root):
        return d
    import tarfile

    from .download import fetch

    d.parent.mkdir(parents=True, exist_ok=True)
    tmp = d.parent / f"{MODEL_NAME}.tar.bz2"
    fetch(MODEL_URL, tmp, progress, "voice model")
    with tarfile.open(tmp) as t:
        try:
            t.extractall(d.parent, filter="data")
        except TypeError:
            t.extractall(d.parent)
    tmp.unlink(missing_ok=True)
    return d


class Synth:
    """One Kokoro engine per language (the phonemiser language is fixed per engine)."""
    _engines: dict = {}
    _lock = threading.Lock()

    def __init__(self, root: Path | None = None, progress=None):
        self.dir = ensure(progress, root)

    def _engine(self, lang: str):
        import sherpa_onnx

        code = VOICES[lang][0]
        key = (str(self.dir), code)
        with self._lock:
            if key not in self._engines:
                d = self.dir
                lex = [d / "lexicon-us-en.txt", d / "lexicon-zh.txt"]
                if lang == "zh":
                    lex.reverse()
                k = sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(d / "model.onnx"), voices=str(d / "voices.bin"), tokens=str(d / "tokens.txt"),
                    data_dir=str(d / "espeak-ng-data"), dict_dir=str(d / "dict"),
                    lexicon=",".join(str(p) for p in lex), lang=code)
                cfg = sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(kokoro=k, num_threads=max(1, min(8, os.cpu_count() or 2))),
                    max_num_sentences=1)
                self._engines[key] = sherpa_onnx.OfflineTts(cfg)
            return self._engines[key]

    def speak(self, text: str, lang: str, sid: int, speed: float = 1.0) -> np.ndarray:
        text = " ".join(text.split())
        if not text:
            return np.zeros(0, dtype=np.float32)
        audio = self._engine(lang).generate(text, sid=int(sid), speed=float(speed))
        return np.asarray(audio.samples, dtype=np.float32)
