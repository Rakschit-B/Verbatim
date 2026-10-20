"""Engine wiring tests with the real libraries replaced by fakes (models are multi-GB)."""
import sys
import types
from types import SimpleNamespace

import numpy as np

from verbatim.engines.base import DecodeOptions
from verbatim.engines.whisper_local import FasterWhisperEngine, MLXWhisperEngine
from verbatim.vocabulary import Vocabulary


def test_mlx_engine_prompts_every_window_and_detects_language_once(monkeypatch):
    calls = []

    def fake_transcribe(audio, **kw):
        calls.append(kw)
        n = len(audio) / 16000
        return {"language": kw.get("language") or "hi",
                "segments": [{"start": 0.0, "end": n, "text": " namaste", "avg_logprob": -0.1,
                              "words": [{"word": " namaste", "start": 0.1, "end": n, "probability": 0.8}]}]}

    monkeypatch.setitem(sys.modules, "mlx_whisper", types.SimpleNamespace(transcribe=fake_transcribe))
    eng = MLXWhisperEngine("large-v3")
    audio = np.zeros(16000 * 60, np.float32)
    chunks = [(0.0, 20.0), (25.0, 50.0), (52.0, 58.0)]
    t = eng.transcribe(audio, chunks, DecodeOptions(vocabulary=Vocabulary.parse("Tata Power-DDL")))
    assert t.language == "hi"
    assert len(calls) == 3                       # probe reused for its own chunk
    assert all("Tata Power-DDL" in c["initial_prompt"] for c in calls)
    assert calls[0].get("language") is None and all(c["language"] == "hi" for c in calls[1:])
    assert all(c["word_timestamps"] and c["temperature"][0] == 0.0 and not c["condition_on_previous_text"] for c in calls)
    assert [round(s.start, 1) for s in t.segments] == [0.0, 25.0, 52.0]
    assert t.segments[1].words[0].start == 25.1


def test_faster_whisper_engine_arguments(monkeypatch):
    seen = {}

    class FakeModel:
        def __init__(self, *a, **k):
            seen["init"] = k

        def transcribe(self, audio, **kw):
            seen.update(kw)
            w = SimpleNamespace(word=" hello", start=0.0, end=0.5, probability=0.9)
            seg = SimpleNamespace(start=0.0, end=0.5, text=" hello", words=[w], avg_logprob=-0.2,
                                  no_speech_prob=0.01, compression_ratio=1.1)
            return iter([seg]), SimpleNamespace(language="en", language_probability=0.99)

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    FasterWhisperEngine._cache.clear()
    t = FasterWhisperEngine("large-v3").transcribe(np.zeros(16000 * 5, np.float32), [(1.0, 4.0)],
                                                   DecodeOptions(language="en", vocabulary=Vocabulary.parse("EXL")))
    assert seen["beam_size"] == 5 and seen["hotwords"] == "EXL" and seen["log_prob_threshold"] == -1.0
    assert t.segments[0].start == 1.0 and t.segments[0].words[0].prob == 0.9
