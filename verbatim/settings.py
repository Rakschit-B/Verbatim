# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""User settings, persisted as JSON in the VERBATIM data folder."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields

from .platform_info import default_output_dir, user_data_dir

LANGUAGES = {
    "Auto detect": None, "English": "en", "Hindi": "hi", "Bengali": "bn", "Tamil": "ta", "Telugu": "te",
    "Marathi": "mr", "Gujarati": "gu", "Kannada": "kn", "Malayalam": "ml", "Punjabi": "pa", "Urdu": "ur",
    "Arabic": "ar", "Chinese": "zh", "Dutch": "nl", "French": "fr", "German": "de", "Indonesian": "id",
    "Italian": "it", "Japanese": "ja", "Korean": "ko", "Portuguese": "pt", "Russian": "ru", "Spanish": "es",
    "Turkish": "tr",
}

FORMATS = ["txt", "srt", "vtt", "csv", "json", "docx", "md"]


@dataclass
class Settings:
    engine: str = "auto"                    # fast & accurate routing (see engines/auto.py)
    variant: str = "auto"
    language: str | None = None
    enhancement: str = "normalize"          # off | normalize | clean
    vocabulary: str = ""
    verbatim: bool = True                   # keep um/uh/false starts
    diarize: bool = False
    num_speakers: int | None = None
    cross_check: bool = False               # second independent engine (~2x slower; opt-in)
    fuse: bool = False                      # let the second engine repair low-confidence words
    fuzzy_vocab: bool = True
    review_threshold: float = 0.8           # word confidence below this goes to Review Queue
                                            # (benchmark: 0.5 light · 0.8 standard · 0.95 thorough)
    use_vad: bool = True
    filename_context: bool = True           # use the file name as a hint for names/terms
    translate_english: bool = False         # also produce an English translation (Whisper)
    paragraphs: bool = True                 # TXT/DOCX/MD as readable speaker paragraphs
    include_timestamps: bool = True
    include_speakers: bool = True
    output_dir: str = field(default_factory=lambda: str(default_output_dir()))
    formats: list[str] = field(default_factory=lambda: list(FORMATS))
    update_manifest_url: str = "https://github.com/Rakschit-B/Verbatim/releases/latest/download/latest.json"
    auto_check_updates: bool = True
    precise_timing: bool = False            # CTC forced alignment of Whisper word times (align.py)
    speaker_library: bool = True            # recognise named voices (speakers.py)
    active_project: str = ""                # projects.py; "" = no project
    base_vocabulary: str = ""               # vocabulary / output folder used when no project is active
    base_output_dir: str = ""
    theme: str = "dark"                     # dark (Studio, default) | light (Clean) | system
    legacy_omnivoice: bool = False          # 3.6: OmniVoice (non-commercial weights) is legacy, off unless chosen
    last_update_check: str = ""
    settings_version: int = 3

    @classmethod
    def path(cls):
        return user_data_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        try:
            raw = json.loads(cls.path().read_text(encoding="utf-8"))
            names = {f.name for f in fields(cls)}
            if int(raw.get("settings_version", 1)) < 2:
                # 2.1.1: switch older installs to the fast default (auto engine, cross-check off)
                for k in ("engine", "variant", "cross_check", "settings_version"):
                    raw.pop(k, None)
            if int(raw.get("settings_version", 1)) < 3:
                raw["theme"] = "dark"              # 3.7: the Studio look opens dark; light stays one click away
                raw["settings_version"] = 3
            if "infinitestory/verbatim" in str(raw.get("update_manifest_url", "")):
                raw.pop("update_manifest_url")  # 3.2.1: placeholder channel -> the real GitHub repository
            return cls(**{k: v for k, v in raw.items() if k in names})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(self.path())

    def fingerprint(self) -> str:
        """Settings that change transcript content (used to decide if a file can be resumed)."""
        import hashlib

        keys = ("engine", "variant", "language", "enhancement", "vocabulary", "verbatim", "diarize",
                "num_speakers", "cross_check", "fuse", "fuzzy_vocab", "use_vad", "filename_context",
                "translate_english")
        d = {k: getattr(self, k) for k in keys}
        if self.precise_timing:  # only when on, so older finished files still count as done
            d["precise_timing"] = True
        blob = json.dumps(d, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]
