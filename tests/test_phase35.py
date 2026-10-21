# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""VERBATIM 3.5 — engine host, effects, scorecard helpers, Music Studio mapping."""
import json
import sys

import numpy as np
import pytest

from verbatim import fx, music_studio as ms, runtimes, scorecard


def test_engine_host_protocol(monkeypatch, tmp_path):
    monkeypatch.setattr(runtimes, "root", lambda: tmp_path / "runtimes")
    (tmp_path / "runtimes").mkdir()
    h = runtimes.EngineHost(sys.executable, "test")
    r = h.request("ping")
    assert r["ok"] and r["python"]
    with pytest.raises(RuntimeError):
        h.request("nope")
    h.close()


def test_pitch_shift_accuracy():
    sr = 48000
    a = (0.3 * np.sin(2 * np.pi * 150 * np.arange(sr * 2) / sr)).astype(np.float32)
    for st in (-3, 2, 5):
        f = fx.estimate_f0(fx.pitch_shift(a, st, sr), sr)
        assert abs(np.median(f[f > 0]) / 150 - 2 ** (st / 12)) < 0.02


def test_presets_run_and_limit():
    sr = 48000
    a = (0.5 * np.random.default_rng(0).standard_normal(sr)).astype(np.float32)
    for name, chain in fx.PRESETS.items():
        y = fx.apply(a, chain, sr)
        assert np.isfinite(y).all() and np.abs(y).max() <= 10 ** (-1 / 20) + 1e-3, name


def test_pitch_range_widens_intonation():
    sr = 48000
    t = np.arange(sr * 3) / sr
    f = 140 * 2 ** (2 * np.sin(2 * np.pi * 0.5 * t) / 12)            # ±2 semitone contour
    a = (0.3 * np.sin(2 * np.pi * np.cumsum(f) / sr)).astype(np.float32)
    before = fx.prosody_stats(a, sr)["std_st"]
    after = fx.prosody_stats(fx.pitch_range(a, 1.5, sr), sr)["std_st"]
    assert after > before * 1.2


def test_wer_cer():
    assert scorecard.wer("the cat sat", "the cat sat") == 0
    assert abs(scorecard.wer("the cat sat", "the bat sat") - 1 / 3) < 1e-9
    assert scorecard.cer("नमस्ते दुनिया", "नमसते दुनिया") == 0      # vowel signs are not counted against the voice


def test_report_html(tmp_path):
    r = scorecard.Report("omnivoice", "my:me", {"Intelligibility": 98.0, "Voice match": 91.0})
    p = scorecard.write_report([r], tmp_path)
    html = p.read_text()
    assert "98.0%" in html and "below target" in html and json.loads((tmp_path / "scorecard.json").read_text())


def test_music_request_mapping():
    r = ms.MusicRequest(title="T", style="corporate piano", duration=45, takes=3, seed=7, style_influence=100,
                        weirdness=0, exclude="drums", max_mode=False)
    e = ms.to_engine(r, "/root", "/out")
    assert e["dit_model"] == "acestep-v15-turbo" and e["inference_steps"] == 8 and e["instrumental"]
    assert e["lyrics"] == "[Instrumental]" and e["seeds"] == [7, 8, 9] and e["batch_size"] == 3
    assert "Avoid: drums" in e["caption"] and e["guidance_scale"] == 12.0
    r2 = ms.MusicRequest(mode="cover", source_audio="a.wav", cover_strength=0.3, lyrics="[Verse]\nhi", language="hi",
                         max_mode=True)
    e2 = ms.to_engine(r2, "/root", "/out")
    assert e2["task_type"] == "cover" and e2["src_audio"] == "a.wav" and e2["vocal_language"] == "hi"
    assert e2["dit_model"] == "acestep-v15-sft" and e2["inference_steps"] == 32


def test_prompt_library_loaded():
    lib = ms.prompt_library()
    assert len(lib) > 250
    assert any(p.get("useCase") == "Infinite Story preset" for p in lib.values())


def test_score_for_voiceover(tmp_path):
    from verbatim import dub

    job = dub.new_script_job("Hello there. We build stories!\n\nThank you.", "en", "S", tmp_path)
    dub.direct_job(job)
    for k, ln in enumerate(job.lines):
        ln.start, ln.spoken = k * 3.0, 2.5
    job.save()
    r = ms.score_for_voiceover(str(job.path), "piano")
    assert r.language == "instrumental" and 10 < r.duration < 30 and r.bpm and "piano" in r.style
