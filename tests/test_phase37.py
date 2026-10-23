# Copyright © 2026 Infinite Story LLP. All rights reserved.
"""3.7 — Studio UI shell, player, library, Voiceover Creator, song sheets + casting, taste, local lip-sync."""
import json
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_song_sheet_round_trip():
    from verbatim.lyrics import Part, Sheet, parse

    parts = parse("[Verse 1 | Male]\nline a\nline b\n[Chorus | Duet]\nwe rise\n[Bridge - female]\nhold on\n"
                  "## Chorus (choir)\nwe rise again\n[Outro]\nbye")
    assert [(p.section, p.singer) for p in parts] == [("Verse", "male"), ("Chorus", "duet"), ("Bridge", "female"),
                                                      ("Chorus", "choir"), ("Outro", "male")]
    sh = Sheet("t", "hi", parts)
    ace = sh.to_ace()
    assert "[Verse 1 - male]" in ace and "[Chorus - duet" in ace and "line b" in ace
    assert "duet" in sh.casting_caption() and "choir" in sh.casting_caption()
    again = Sheet.from_dict(json.loads(json.dumps(sh.as_dict())))
    assert again.to_ace() == ace


def test_casting_energy_sections():
    from verbatim import casting
    from verbatim.lyrics import Part, Sheet

    sr = casting.SR
    v = np.zeros(sr * 10, np.float32)
    v[sr * 1:sr * 4] = 0.3 * np.sin(np.arange(sr * 3) * 0.05)
    v[sr * 6:sr * 9] = 0.3 * np.sin(np.arange(sr * 3) * 0.05)
    sh = Sheet("t", "en", [Part("Verse", "male", ["aaaa"]), Part("Chorus", "duet", ["bbbb"])])
    spans = casting._spans_from_energy(v, sh)
    assert spans[0][0] >= 0.9 and spans[0][1] <= 6.5 and spans[1][0] >= 3.5 and spans[1][1] <= 9.2


def test_taste_learns(tmp_path):
    from verbatim import taste

    for _ in range(2):
        taste.record(tmp_path, "like", "bollywood romantic, soft piano, live tabla")
    taste.record(tmp_path, "favourite", "bollywood, live tabla, warm strings")
    taste.record(tmp_path, "dislike", "edm, heavy autotune")
    taste.record(tmp_path, "dislike", "trap, heavy autotune")
    style, add, bad = taste.enhance(tmp_path, "bollywood wedding")
    assert "live tabla" in add and "heavy autotune" in bad and style.startswith("bollywood wedding")


def test_bed_and_style_learning():
    from verbatim import beds, voiceover

    a = beds.generate("Corporate uplifting", 6.0)
    assert a.shape[1] == 2 and abs(len(a) - 6 * beds.SR) < beds.SR and 0.5 < np.abs(a).max() <= 0.71
    sr = 24000
    t = np.arange(sr * 6) / sr
    syll = (np.sin(2 * np.pi * 5 * t) > 0).astype(np.float32)
    x = (0.3 * np.sin(2 * np.pi * (150 + 30 * np.sin(2 * np.pi * 0.5 * t)) * t) * syll).astype(np.float32)
    st = voiceover.analyse(x, sr)
    assert st["syll_per_s"] > 1 and st["median_hz"] > 100
    s = voiceover.style_from_stats("Ref", st, "ref.wav")
    assert s.name == "Ref" and 0.82 <= s.speed <= 1.2 and s.fx and s.mood
    names = [x.name for x in voiceover.styles()]
    assert "Warm narrator" in names and "Energetic advert" in names


def test_lipsync_mel_and_limits():
    from verbatim import lipsync

    mel = lipsync.mel_spectrogram(np.random.default_rng(0).standard_normal(16000).astype(np.float32) * 0.1)
    assert mel.shape[0] == 80 and 78 <= mel.shape[1] <= 82 and mel.min() >= -4 and mel.max() <= 4
    assert lipsync.allowed_minutes({"gpu_cores": 10}) == 25
    assert lipsync.allowed_minutes({"gpu_cores": 40}) > 25
    assert lipsync.allowed_minutes({"nvidia": True}) > 25
    assert lipsync.allowed_minutes({"gpu_cores": 10}, cloud=True) > 25


def test_library_collects(tmp_path):
    from verbatim import library

    vo = tmp_path / "Voiceovers"
    vo.mkdir()
    f = vo / "a.mp3"
    f.write_bytes(b"x")
    (vo / "library.json").write_text(json.dumps({"items": [{"id": "1", "title": "Hello", "voice_name": "Aria",
                                                            "created": "2026-10-23T10:00:00", "duration": 12,
                                                            "files": {"Voice only (MP3)": str(f)}}]}))
    ms = tmp_path / "Music Studio"
    ms.mkdir()
    s = ms / "s.mp3"
    s.write_bytes(b"x")
    (ms / "library.json").write_text(json.dumps({"items": [{"id": "m1", "title": "Song", "take": 1, "created":
                                                            "2026-10-23T11:00:00", "files": {"mp3": str(s)}}]}))
    items = library.everything(tmp_path)
    kinds = [i.kind for i in items]
    assert kinds == ["music", "voiceover"] and items[0].play == str(s) and items[1].files


def test_files_from():
    from verbatim.gui_shell import files_from

    here = str(Path(__file__))
    got = files_from({"wav": here, "nested": [{"mp3": here}], "n": 3, "missing": "/no/such/file.wav"})
    assert here in got.values() and len(got) == 2


def test_window_pages_and_player(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from verbatim import gui
    from verbatim.gui_player import Media

    app = gui._app()
    w = gui.Window()
    for key in ("home", "transcribe", "voiceover", "voice", "music", "video", "film", "library", "activity",
                "settings"):
        w.go(key)
        app.processEvents()
        assert w.side.buttons[key].isChecked()
    w.toggle_theme()
    w.toggle_theme()
    wav = tmp_path / "t.wav"
    import wave

    with wave.open(str(wav), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes((np.sin(np.arange(16000) * 0.1) * 8000).astype("<i2").tobytes())
    Media.get().load(wav, "Clip", "Voiceover", autoplay=False)
    app.processEvents()
    assert w.player.now.text() == "Clip" and w.player.dl.isEnabled()
    j = w.jobs.add("Test job")
    j.progress(0.5, "half")
    j.done({"file": str(wav)})
    assert j.state == "done" and j.files
    w.close()
