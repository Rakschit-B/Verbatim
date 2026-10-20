# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""VERBATIM 3.4 — performance direction, music bed, voice lab, cloud voices, GitHub updates, llama.cpp fix."""
import io
import json
import tarfile
import urllib.error
import zipfile

import numpy as np
import pytest

from verbatim import direction, dub, llm, music, tts, tts_cloud, updater, voicelab


# ---------------------------------------------------------------- direction
def test_auto_direct_marks_emotion_and_stress():
    d = direction.auto_direct(["Life isn't measured only by the milestones we celebrate.",
                               "This is amazing!", "To live.", "Together, they become our story."])
    assert d[0]["emotion"] in ("joyful", "inspiring")
    assert d[1]["emotion"] == "excited" and d[1]["intensity"] >= 0.7
    assert d[2]["emotion"] == "calm"
    assert d[3]["emotion"] == "inspiring"           # closing line lands
    assert "only" in d[0]["emphasis"]


def test_parse_direction_validates_and_falls_back():
    texts = ["We begin again.", "Never give up."]
    raw = 'ok {"lines":[{"n":1,"emotion":"INSPIRING","intensity":1.4,"emphasis":["begin","notthere"]},' \
          '{"n":9,"emotion":"sad"}]}'
    d = direction.parse_direction(raw, texts)
    assert d[0] == {"emotion": "inspiring", "intensity": 1.0, "emphasis": "begin"}
    assert d[1]["emotion"] in direction.EMOTIONS        # line 2 kept from the rule-based fallback
    assert direction.parse_direction("garbage", texts)[0]["emotion"] in direction.EMOTIONS


def test_engine_renderings():
    t = direction.eleven_text("This is the only way", "excited", 0.8, "only")
    assert t.startswith("[excited]") and "ONLY" in t
    s = direction.eleven_settings("excited", 0.8)
    assert s["stability"] == 0.0
    ssml = direction.azure_ssml("Hello & welcome home", "hi-IN-SwaraNeural", "hi-IN", "warm", 0.6, "home", 1.1)
    assert 'style="friendly"' in ssml and "<emphasis" in ssml and "&amp;" in ssml and 'rate="+10%"' in ssml


# ---------------------------------------------------------------- music bed
def _voice(sr=music.SR):
    v = np.zeros(sr * 12, dtype=np.float32)
    t = np.arange(sr * 2) / sr
    v[sr * 2:sr * 4] = 0.3 * np.sin(2 * np.pi * 200 * t)      # speech 2–4 s
    v[sr * 4 + sr // 2:sr * 6] = 0.3 * np.sin(2 * np.pi * 200 * t[:sr + sr // 2])  # 4.5–6 s (short gap)
    v[sr * 9:sr * 10] = 0.3 * np.sin(2 * np.pi * 200 * t[:sr])  # 9–10 s (long gap before)
    return v


def test_gain_curve_ducks_swells_and_follows_tone():
    sr = music.SR
    s = music.BedSettings(file="x", outro_s=1.5, fade_out_s=1.0)
    g = music.gain_curve(_voice(), s)
    db = lambda t: 20 * np.log10(g[int(t * sr)] + 1e-9)
    assert db(1.0) > -2            # intro full
    assert db(3.0) < -15           # ducked under speech
    assert db(4.25) < -12          # short gap stays down
    assert db(7.5) > -9            # long pause swells back up
    assert db(8.95) < db(7.5) - 3  # look-ahead dip before the next line
    assert g[int(11.9 * sr)] < 0.01  # faded out after the outro
    g2 = music.gain_curve(_voice(), s, [(2.0, 4.0, "excited", 0.9)])
    assert g2[int(3 * sr)] > g[int(3 * sr)] * 1.5      # excited line lifts the bed


def test_mix_with_music_end_to_end(tmp_path):
    sr = music.SR
    m = 0.2 * np.sin(2 * np.pi * 330 * np.arange(sr * 3) / sr).astype(np.float32)
    f = tmp_path / "bed.wav"
    music.write_stereo_wav(f, np.stack([m, m], 1))
    out = music.mix_with_music(_voice(), music.BedSettings(file=str(f), outro_s=2.0))
    assert out.shape[1] == 2 and len(out) == sr * 14          # looped to cover voice + outro
    assert np.abs(out).max() <= 10 ** (-1 / 20) + 1e-3          # peak ceiling


# ---------------------------------------------------------------- voice lab
def test_reference_picker_prefers_clean_continuous_speech():
    sr = 16000
    a = np.zeros(sr * 30, dtype=np.float32)
    rng = np.random.default_rng(0)
    a[sr * 2:sr * 4] = 0.2 * rng.standard_normal(sr * 2)           # short burst
    for k in range(10, 20):                                          # 10–20 s: phrases with tiny gaps
        a[sr * k:sr * k + int(sr * 0.85)] = 0.2 * rng.standard_normal(int(sr * 0.85))
    s, e = voicelab.pick_reference(a, sr)
    assert 9.5 <= s <= 12 and 15 <= e <= 20.5 and 6 <= e - s <= 12.5
    assert not voicelab.music_likely(a, sr)
    noisy = a + 0.05 * rng.standard_normal(len(a)).astype(np.float32)
    assert voicelab.music_likely(noisy, sr)


def test_custom_voice_store_and_wav_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(voicelab, "voices_dir", lambda: tmp_path)
    cv = voicelab.CustomVoice("my:test", "Test", consent_id="c1")
    voicelab.save(cv, 0.5 * np.ones(2400, dtype=np.float32))
    assert [v.id for v in voicelab.library()] == ["my:test"]
    a, sr = voicelab.reference(voicelab.get("my:test"))
    assert sr == voicelab.REF_SR and abs(a.mean() - 0.5) < 1e-3
    assert voicelab.unique_slug("Test") == "test-2"
    assert voicelab.delete("my:test") and voicelab.library() == []


def test_create_voice_requires_consent():
    with pytest.raises(ValueError):
        voicelab.create_from_recording("x.mp3", "Name")


def test_consent_declaration(tmp_path):
    from verbatim.consent import ConsentRegister

    reg = ConsentRegister(tmp_path)
    e = reg.add_declaration("Rakschit", "I own this recording.", recorded_by="me")
    assert reg.valid_for("rakschit") and "cloning" in e["scope"].lower()


# ---------------------------------------------------------------- tts routing
def test_custom_voice_needs_an_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(voicelab, "voices_dir", lambda: tmp_path)
    voicelab.save(voicelab.CustomVoice("my:me", "Me", consent_id="c"), np.zeros(2400, dtype=np.float32))
    from verbatim import tts_chatterbox

    monkeypatch.setattr(tts_chatterbox, "is_installed", lambda d=None: False)
    s = tts.Synth()
    with pytest.raises(RuntimeError, match="Expressive voice pack"):
        s.speak("Namaste", "hi", "my:me")
    ids = [v.id for v in tts.voices_for("hi")]
    assert ids[0] == "my:me" and "st:0" in ids
    assert all(not v.startswith("my:") for v in tts.default_voices("hi", 4))


def test_time_stretch_keeps_pitch():
    sr = 48000
    a = np.sin(2 * np.pi * 220 * np.arange(sr) / sr).astype(np.float32)
    b = tts.time_stretch(a, 1.25)
    assert abs(len(b) / sr - 0.8) < 0.01
    spec = np.abs(np.fft.rfft(b[2000:-2000]))
    assert abs(np.argmax(spec) * sr / (len(b) - 4000) - 220) < 5


def test_chatterbox_text_prep():
    from verbatim import tts_chatterbox as cb

    assert cb.prepare("hello world", "en") == "[en]hello world."
    assert cb.prepare("नमस्ते दुनिया", "hi").startswith("[hi]")
    assert cb._jamo("한") == "한"
    assert cb.punc_norm("Wait… what") == "Wait,  what."


# ---------------------------------------------------------------- cloud voices (no network)
def test_elevenlabs_request_and_clone():
    calls = []

    def post(url, body, headers, timeout=120):
        calls.append((url, body, headers))
        if url.endswith("/voices/add"):
            return json.dumps({"voice_id": "abc"}).encode()
        return (np.ones(441, dtype="<i2") * 1000).tobytes()

    el = tts_cloud.ElevenLabs(key="k", post=post)
    a, sr = el.speak("[excited] Hi", "v1", "hi", 1.4, {"stability": 0.0})
    body = json.loads(calls[0][1])
    assert sr == 44100 and len(a) == 441 and body["voice_settings"]["speed"] == 1.2
    assert body["model_id"] == "eleven_v3" and body["language_code"] == "hi" and "pcm_44100" in calls[0][0]
    import tempfile
    from pathlib import Path

    f = Path(tempfile.mkdtemp()) / "r.wav"
    f.write_bytes(b"RIFF0000")
    assert el.clone("Me", [f]) == "abc" and b'name="files"' in calls[1][1]


def test_azure_request():
    seen = {}

    def post(url, body, headers, timeout=120):
        seen.update(url=url, body=body, headers=headers)
        return np.zeros(480, dtype="<i2").tobytes()

    a, sr = tts_cloud.Azure(key="k", region="centralindia", post=post).speak_ssml("<speak/>")
    assert sr == 48000 and "centralindia.tts.speech.microsoft.com" in seen["url"]
    assert seen["headers"]["X-Microsoft-OutputFormat"] == "raw-48khz-16bit-mono-pcm"


# ---------------------------------------------------------------- script voiceover + direction in render
class FakeSynth:
    def __init__(self):
        self.calls = []

    def speak(self, text, lang, voice, speed=1.0, direction=None):
        self.calls.append((text, voice, speed, direction))
        return 0.3 * np.ones(int(48000 * 0.8 / speed), dtype=np.float32)


def test_script_job_sequential_render(tmp_path):
    job = dub.new_script_job("First line here. Second line!\n\nNew paragraph now.", "en", "Brand film", tmp_path)
    assert [ln.source for ln in job.lines] == ["First line here.", "Second line!", "New paragraph now."]
    assert job.sequential and job.paragraph_ends == [1, 2] and all(ln.text for ln in job.lines)
    dub.direct_job(job)
    assert all(ln.emotion for ln in job.lines)
    fs = FakeSynth()
    out = dub.render(job, fs, mix=False, video=False)
    assert fs.calls[0][3]["emotion"] == job.lines[0].emotion        # direction reaches the engine
    l0, l1, l2 = job.lines
    assert abs(l0.start - 0.3) < 1e-6
    assert l1.start - l0.end >= 0.45 - 1e-6
    assert l2.start - l1.end >= 0.8 - 1e-6                          # paragraph pause is longer
    assert all(ln.fit == "ok" or ln.fit.startswith("faster") for ln in job.lines)
    assert (tmp_path / "Voice Studio").exists() and out["voice"]
    again = dub.VoiceJob.load(job.path)                              # new fields persist
    assert again.sequential and again.lines[0].emotion == job.lines[0].emotion


def test_script_job_with_music(tmp_path):
    sr = music.SR
    m = 0.2 * np.sin(2 * np.pi * 330 * np.arange(sr * 2) / sr).astype(np.float32)
    f = tmp_path / "bed.wav"
    music.write_stereo_wav(f, np.stack([m, m], 1))
    job = dub.new_script_job("One. Two.", "en", "With music", tmp_path)
    job.music = {"file": str(f), "mode": "follow", "outro_s": 1.0}
    out = dub.render(job, FakeSynth(), mix=False, video=False)
    assert out.get("music_mix") and not out.get("music_error")
    assert job.lines[0].start >= 2.4                                  # music intro before the first word


# ---------------------------------------------------------------- GitHub updates
def test_check_github_channels(monkeypatch):
    monkeypatch.setattr(updater, "__version__", "3.4.0")

    def get_404(url, timeout=30):
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)

    st = updater.check_github(get=get_404)
    assert st.reachable and not st.latest and "no release published" in st.summary()

    def get_ok(url, timeout=30):
        if "verbatim-releases" in url:
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        return json.dumps({"version": "3.5.0", "notes": "n", "assets": {
            "source": {"url": "https://x/s.zip", "sha256": "AB"}}}).encode()

    st = updater.check_github(get=get_ok)
    assert st.latest == "3.5.0" and st.update and st.update.sha256 == "ab" and st.repo == "Rakschit-B/Verbatim"
    assert "3.5.0 is available" in st.summary()

    def get_down(url, timeout=30):
        raise OSError("no network")

    st = updater.check_github(get=get_down)
    assert not st.reachable and "Can't reach GitHub" in st.summary()


# ---------------------------------------------------------------- llama.cpp download fix
def test_llama_asset_names_and_extract(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "IS_MAC", True)
    monkeypatch.setattr(llm, "IS_WINDOWS", False)
    monkeypatch.setattr(llm.platform, "machine", lambda: "arm64")
    assert llm._asset_suffix() == "macos-arm64.tar.gz"
    url = llm.LLAMA_URL.format(tag=llm.LLAMA_TAG, suffix=llm._asset_suffix())
    assert url.endswith(f"/{llm.LLAMA_TAG}/llama-{llm.LLAMA_TAG}-bin-macos-arm64.tar.gz")
    monkeypatch.setattr(llm, "IS_MAC", False)
    monkeypatch.setattr(llm, "IS_WINDOWS", True)
    monkeypatch.setattr(llm.platform, "machine", lambda: "AMD64")
    assert llm._asset_suffix() == "win-cpu-x64.zip"
    # tar.gz and zip both extract; unsafe paths refused
    tg = tmp_path / "a.tar.gz"
    with tarfile.open(tg, "w:gz") as t:
        data = b"#!/bin/sh\n"
        ti = tarfile.TarInfo("llama-b1/llama-server")
        ti.size = len(data)
        t.addfile(ti, io.BytesIO(data))
    llm._extract(tg, tmp_path / "out")
    assert (tmp_path / "out/llama-b1/llama-server").exists()
    bad = tmp_path / "b.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../evil", "x")
    with pytest.raises(RuntimeError):
        llm._extract(bad, tmp_path / "out2")
