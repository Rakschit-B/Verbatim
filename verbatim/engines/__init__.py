"""Engine registry. Each preset maps to a concrete engine on the current platform."""
from __future__ import annotations

from ..platform_info import IS_APPLE_SILICON
from .base import DecodeOptions, Engine  # noqa: F401

# Modes follow TurboScribe's simple speed/accuracy ladder (Cheetah / Dolphin / Whale).
ENGINE_CHOICES = {
    # label shown in the UI -> (engine id, model size/variant)
    "Fast & accurate (recommended) — Parakeet for English, Whisper turbo for Hindi & others": ("auto", "auto"),
    "Most accurate — Whisper large-v3 (99 languages)": ("whisper", "large-v3"),
    "Most accurate, classic — Whisper large-v2 (TurboScribe 'Whale' model)": ("whisper", "large-v2"),
    "Balanced — Whisper large-v3 turbo (5× faster)": ("whisper", "large-v3-turbo"),
    "Fast — Whisper small (quick drafts)": ("whisper", "small"),
    "Best English — NVIDIA Parakeet v2": ("parakeet", "parakeet-v2"),
    "European languages — NVIDIA Parakeet v3": ("parakeet", "parakeet-v3"),
    "Cloud, highest accuracy — ElevenLabs Scribe v2": ("elevenlabs", "scribe_v2"),
}


def build(engine: str, variant: str) -> Engine:
    if engine == "whisper":
        if IS_APPLE_SILICON:
            from .whisper_local import MLXWhisperEngine

            ok, why = MLXWhisperEngine.available()
            if ok:
                return MLXWhisperEngine(variant)
            # Never fall back silently to a 20x slower CPU engine on a Mac: say what is wrong.
            raise RuntimeError(f"The Mac GPU Whisper engine could not load ({why}). "
                               "Reinstall VERBATIM, or choose a Parakeet engine.")
        from .whisper_local import FasterWhisperEngine

        ok, _ = FasterWhisperEngine.available()
        if ok:
            return FasterWhisperEngine(variant)
        from .sherpa import WhisperOnnxEngine

        return WhisperOnnxEngine("turbo" if "turbo" in variant else variant)
    if engine == "auto":
        from .auto import AutoEngine

        return AutoEngine()
    if engine == "whisper-onnx":
        from .sherpa import WhisperOnnxEngine

        return WhisperOnnxEngine(variant)
    if engine == "parakeet":
        from .sherpa import ParakeetEngine

        return ParakeetEngine(variant)
    if engine == "elevenlabs":
        from .elevenlabs import ElevenLabsScribeEngine

        return ElevenLabsScribeEngine(variant)
    raise ValueError(f"Unknown engine {engine}")


def secondary_for(primary_engine: str, language: str | None) -> tuple[str, str] | None:
    """Choose an *independent* engine for cross-checking."""
    from .sherpa import ParakeetEngine

    if primary_engine == "auto":
        return ("whisper", "large-v3-turbo") if language in (None, "en") or ParakeetEngine.supports(language) else None
    if primary_engine in ("whisper", "elevenlabs"):
        if language in (None, "en"):
            return ("parakeet", "parakeet-v2")
        if ParakeetEngine.supports(language):
            return ("parakeet", "parakeet-v3")
        return ("whisper", "large-v3-turbo") if primary_engine == "elevenlabs" else None
    if primary_engine == "parakeet":
        return ("whisper", "large-v3-turbo")
    return None
