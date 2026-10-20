import base64
import json

import numpy as np
import pytest

from verbatim import updater
from verbatim.engines.elevenlabs import ElevenLabsScribeEngine
from verbatim.vad import SileroVAD, merge_chunks

SCRIBE = {"language_code": "eng", "language_probability": 0.99, "text": "Hello there. Hi!",
          "words": [{"text": "Hello", "type": "word", "start": 0.1, "end": 0.4, "logprob": -0.01, "speaker_id": "speaker_0"},
                    {"text": " ", "type": "spacing", "start": 0.4, "end": 0.5},
                    {"text": "there.", "type": "word", "start": 0.5, "end": 0.9, "logprob": -1.2, "speaker_id": "speaker_0"},
                    {"text": "(laughs)", "type": "audio_event", "start": 1.0, "end": 1.5},
                    {"text": "Hi!", "type": "word", "start": 2.0, "end": 2.3, "logprob": -0.05, "speaker_id": "speaker_1"}]}


def test_scribe_parse_speakers_confidence_events():
    t = ElevenLabsScribeEngine.parse(SCRIBE)
    assert t.language == "en" and [s.speaker for s in t.segments] == ["Speaker 1", "Speaker 2"]
    assert t.segments[0].text == "Hello there." and t.segments[0].words[1].prob < 0.4
    assert t.audio_events[0]["event"] == "(laughs)"


def test_vad_finds_speech_not_silence():
    from verbatim.audio import load_audio
    from pathlib import Path

    a = load_audio(Path(__file__).parent / "data" / "jfk.flac")
    padded = np.concatenate([np.zeros(16000 * 5, np.float32), a, np.zeros(16000 * 5, np.float32)])
    vad = SileroVAD()
    regions = vad.speech_regions(padded)
    assert regions and regions[0][0] > 4.5 and regions[-1][1] < 5 + len(a) / 16000 + 1
    assert all(e - s <= 28.0 + 1e-6 for s, e in merge_chunks(regions, probs=vad.last_probs))
    assert vad.speech_regions(np.zeros(16000 * 10, np.float32)) == []


def test_version_compare():
    assert updater.parse_version("2.10.0") > updater.parse_version("2.9.9")
    assert updater.parse_version("v2.0") == (2, 0, 0)


def test_manifest_signature(monkeypatch, tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    k = Ed25519PrivateKey.generate()
    pub = base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    keyfile = tmp_path / "update_public_key.txt"
    keyfile.write_text(pub)
    monkeypatch.setattr(updater, "asset", lambda name: keyfile)
    m = {"version": "9.0.0", "assets": {"source": {"url": "https://x/y.zip", "sha256": "ab"}}}
    m["signature"] = base64.b64encode(k.sign(updater.canonical(m))).decode()
    assert updater.verify_signature(m)
    m["assets"]["source"]["url"] = "https://evil/y.zip"
    assert not updater.verify_signature(m)


def test_rejects_plain_http():
    with pytest.raises(ValueError):
        updater._get("http://example.com/latest.json")
