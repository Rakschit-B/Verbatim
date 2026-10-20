# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Fast & accurate routing (the default).

Benchmarks: NVIDIA Parakeet was both the most accurate (3.8–4.0 % WER on earnings calls)
and by far the fastest local engine for English; Whisper large-v3 turbo is ~8x faster than
large-v3 at near-equal accuracy and covers Hindi and 99 languages. So:
  English            -> Parakeet TDT v2
  25 EU languages    -> Parakeet TDT v3
  everything else    -> Whisper large-v3 turbo (Apple GPU via MLX / faster-whisper on Windows)
With "Auto detect", the language is identified from one 30-second window by Whisper turbo.
"""
from __future__ import annotations

from .base import DecodeOptions, Engine, Progress, detect_language_chunk, slice_audio


class AutoEngine(Engine):
    id = "auto"
    label = "Fast & accurate (auto)"
    model = "auto"

    @classmethod
    def available(cls):
        return True, ""

    def _whisper(self):
        from . import build

        return build("whisper", "large-v3-turbo")

    def transcribe(self, audio, chunks, opts: DecodeOptions, progress: Progress | None = None):
        from .sherpa import PARAKEET_V3_LANGS, ParakeetEngine

        lang = opts.language
        whisper = None
        if not chunks:  # no speech found: nothing to route
            from ..model import Transcript

            return Transcript([], lang or "unknown", self.id, self.model)
        if not lang and chunks:
            whisper = self._whisper()
            s, e = detect_language_chunk(chunks)
            if progress:
                progress(0.0, "Detecting language…")
            probe = whisper._decode(slice_audio(audio, s, e), None,
                                    opts.vocabulary.whisper_prompt(opts.verbatim, context=opts.context), opts)
            lang = probe.get("language") or "en"
        if lang == "en":
            engine = ParakeetEngine("parakeet-v2")
        elif lang in PARAKEET_V3_LANGS:
            engine = ParakeetEngine("parakeet-v3")
        else:
            engine = whisper or self._whisper()
        sub = DecodeOptions(language=lang, vocabulary=opts.vocabulary, verbatim=opts.verbatim, diarize=opts.diarize,
                            num_speakers=opts.num_speakers, beam_size=opts.beam_size, context=opts.context, task=opts.task)
        t = engine.transcribe(audio, chunks, sub, progress)
        t.language = lang
        self.label = f"Auto → {engine.label}"
        return t
