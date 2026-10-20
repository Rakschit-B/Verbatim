"""Local Whisper engines.

* MLX Whisper  — Apple Silicon GPU (Metal) via ml-explore/mlx-examples.
* faster-whisper — CTranslate2; Windows, Intel Macs and Linux; supports beam search.

Both decode VAD chunk by chunk (WhisperX "cut & merge"), which matters for accuracy:
with condition_on_previous_text=False, openai-whisper style decoders only apply the
initial prompt to the FIRST 30-second window, so custom vocabulary silently stopped
working after 30 s in VERBATIM 1.x. Per-chunk decoding re-applies the prompt to every
window and gives each window clean context (no error propagation or repetition carry-over).
"""
from __future__ import annotations

import numpy as np

from ..model import Transcript
from .base import (WHISPER_TEMPERATURES, DecodeOptions, Engine, Progress, detect_language_chunk,
                   slice_audio, whisper_segments)

MLX_MODELS = {
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v2": "mlx-community/whisper-large-v2-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
}
FW_MODELS = {
    "large-v3": "large-v3",
    "large-v2": "large-v2",
    "large-v3-turbo": "large-v3-turbo",
    "medium": "medium",
    "small": "small",
}

COMMON = dict(
    temperature=WHISPER_TEMPERATURES,   # fallback when output looks like a loop / low logprob
    compression_ratio_threshold=2.4,
    logprob_threshold=-1.0,
    no_speech_threshold=0.6,
    condition_on_previous_text=False,
    word_timestamps=True,
)


class _ChunkedWhisper(Engine):
    def __init__(self, size: str = "large-v3"):
        self.size = size

    def _decode(self, audio: np.ndarray, language: str | None, prompt: str, opts: DecodeOptions) -> dict:
        raise NotImplementedError

    def transcribe(self, audio, chunks, opts: DecodeOptions, progress: Progress | None = None) -> Transcript:
        prompt = opts.vocabulary.whisper_prompt(verbatim=opts.verbatim, context=opts.context)
        language = opts.language
        lang_prob = None
        if not chunks:
            return Transcript([], language or "unknown", self.id, self.model)
        reuse = {}
        if not language:
            s, e = detect_language_chunk(chunks)
            probe = self._decode(slice_audio(audio, s, e), None, prompt, opts)
            language = probe.get("language") or "en"
            lang_prob = probe.get("language_probability")
            reuse[(s, e)] = probe  # already decoded in the detected language
        segments = []
        total = sum(e - s for s, e in chunks) or 1.0
        done = 0.0
        for s, e in chunks:
            res = reuse.get((s, e)) or self._decode(slice_audio(audio, s, e), language, prompt, opts)
            segments += whisper_segments(res.get("segments", []), s, e)
            done += e - s
            if progress:
                progress(done / total, f"{self.label}: {done/60:.1f} of {total/60:.1f} speech-minutes")
        return Transcript(segments, language, self.id, self.model, lang_prob)


class MLXWhisperEngine(_ChunkedWhisper):
    id = "mlx-whisper"
    label = "Whisper (Apple Silicon, MLX)"

    def __init__(self, size: str = "large-v3"):
        super().__init__(size)
        self.model = MLX_MODELS.get(size, size)

    @classmethod
    def available(cls):
        from ..platform_info import IS_APPLE_SILICON

        if not IS_APPLE_SILICON:
            return False, "requires an Apple Silicon Mac"
        try:
            import mlx_whisper  # noqa: F401
            return True, ""
        except Exception as exc:
            return False, f"mlx-whisper not installed ({exc})"

    def _decode(self, audio, language, prompt, opts):
        import mlx_whisper

        kw = dict(COMMON, path_or_hf_repo=self.model, verbose=None, initial_prompt=prompt,
                  hallucination_silence_threshold=2.0, task=opts.task)
        if language:
            kw["language"] = language
        try:
            return mlx_whisper.transcribe(audio.astype(np.float32), **kw)
        except TypeError:  # older mlx-whisper without hallucination_silence_threshold
            kw.pop("hallucination_silence_threshold", None)
            return mlx_whisper.transcribe(audio.astype(np.float32), **kw)


class FasterWhisperEngine(_ChunkedWhisper):
    id = "faster-whisper"
    label = "Whisper (faster-whisper, CPU/NVIDIA)"
    _cache: dict = {}

    def __init__(self, size: str = "large-v3"):
        super().__init__(size)
        self.model = FW_MODELS.get(size, size)

    @classmethod
    def available(cls):
        try:
            import faster_whisper  # noqa: F401
            return True, ""
        except Exception as exc:
            return False, f"faster-whisper not installed ({exc})"

    def _model(self):
        if self.model not in self._cache:
            from faster_whisper import WhisperModel

            from ..platform_info import models_dir

            try:
                import ctranslate2

                cuda = ctranslate2.get_cuda_device_count() > 0
            except Exception:
                cuda = False
            self._cache[self.model] = WhisperModel(
                self.model, device="cuda" if cuda else "cpu", compute_type="float16" if cuda else "int8",
                download_root=str(models_dir() / "faster-whisper"))
        return self._cache[self.model]

    def _decode(self, audio, language, prompt, opts):
        model = self._model()
        segs, info = model.transcribe(
            audio.astype(np.float32), language=language, task=opts.task, beam_size=opts.beam_size, best_of=5,
            initial_prompt=prompt, hotwords=opts.vocabulary.hotwords() or None,
            vad_filter=False, hallucination_silence_threshold=2.0,
            temperature=list(WHISPER_TEMPERATURES), compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0, no_speech_threshold=0.6,  # faster-whisper spells it log_prob_
            condition_on_previous_text=False, word_timestamps=True)
        segs = list(segs)
        return {"segments": segs, "language": info.language, "language_probability": info.language_probability}
