# Copyright © 2026 Infinite Story LLP. All rights reserved.
"""3.6 — Score design language, Cloud GPU round trip, Video Localise helpers, OmniVoice step-down."""
import base64
import json
import os
import sys
import threading
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_studio_themes():
    from verbatim import ui_theme as th

    for base in (th.LIGHT, th.DARK):
        t = th.tokens(base, 0)
        for k in ("accent", "accent_ink", "soft", "side", "card", "player"):
            assert t[k].startswith("#")
    css = th.stylesheet(th.tokens(th.DARK, 0), {k: "x" for k in ("arrow", "up", "check_on", "check_off",
                                                                  "radio_on", "radio_off")})
    assert th.GRAD[0] in css and th.UI in css and "QWidget#playerBar" in css and "QPushButton#navItem" in css


def test_icons_and_fonts_ship():
    from verbatim import ui_theme as th
    from verbatim.icons_phosphor import GLYPHS

    for w in ("light", "regular", "fill", "duotone"):
        assert {"home", "music", "video", "translate", "record", "vinyl"} <= set(GLYPHS[w])
    assert b"<path" in th.svg("vinyl", "#000")
    fonts = {p.name for p in (ROOT / "assets" / "fonts").glob("*.ttf")}
    assert {"Manrope-400.ttf", "Manrope-600.ttf", "Manrope-800.ttf", "JetBrainsMono-400.ttf",
            "Mukta-Regular.ttf"} <= fonts
    assert (ROOT / "assets" / "fonts" / "OFL-Manrope.txt").exists()


def test_envelope_is_deterministic():
    from verbatim.gui_score import envelope

    a, b = envelope(120, 3), envelope(120, 3)
    assert a == b and all(0 < x <= 1 for x in a) and min(a) < 0.2 < max(a)


@pytest.fixture()
def cloud_server(tmp_path, monkeypatch):
    """A real VERBATIM Cloud server on localhost with a fake 'echo' engine (no GPU needed)."""
    sys.path.insert(0, str(ROOT / "engine_host"))
    import host
    import server

    def op_echo(req, rid):
        host.send({"id": rid, "progress": 0.5, "message": "echoing"})
        data = Path(req["src_wav"]).read_bytes()
        Path(req["out"]).write_bytes(data[::-1])
        od = Path(req["out_dir"])
        od.mkdir(parents=True, exist_ok=True)
        (od / "take1.wav").write_bytes(b"one")
        (od / "take2.wav").write_bytes(b"two")
        return {"model": req["model_dir"], "tracks": [{"path": str(od / "take1.wav")}, {"path": str(od / "take2.wav")}]}

    monkeypatch.setitem(host.OPS, "echo", op_echo)
    models = tmp_path / "server-models"
    (models / "acme").mkdir(parents=True)
    from http.server import ThreadingHTTPServer

    tok = "t" * 32
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(tok, models))
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tok, models
    srv.shutdown()


def test_cloud_round_trip(cloud_server, tmp_path, monkeypatch):
    url, tok, models = cloud_server
    from verbatim import cloud

    monkeypatch.setattr(cloud, "models_dir", lambda: tmp_path / "local-models")
    (tmp_path / "local-models" / "acme").mkdir(parents=True)
    monkeypatch.setattr(cloud, "token", lambda value=None: tok)
    h = cloud.health(url, tok)
    assert h["ok"] and "echo" in h["ops"]
    assert not cloud.health(url, "wrong" * 6)["ok"]
    src = tmp_path / "in.wav"
    src.write_bytes(b"abcdef")
    rh = cloud.RemoteHost("music", cloud.CloudConfig(enabled=True, url=url))
    seen = []
    res = rh.request("echo", progress=lambda f, m: seen.append(m), src_wav=str(src), out=str(tmp_path / "o" / "x.wav"),
                     out_dir=str(tmp_path / "raw"), model_dir=str(tmp_path / "local-models" / "acme"))
    assert (tmp_path / "o" / "x.wav").read_bytes() == b"fedcba"
    assert (tmp_path / "raw" / "take2.wav").read_bytes() == b"two"
    assert res["tracks"][0]["path"] == str(tmp_path / "raw" / "take1.wav")
    assert res["model"] == str(models / "acme")
    assert any("echoing" in m for m in seen)


def test_cloud_routing(tmp_path, monkeypatch):
    from verbatim import cloud, runtimes

    monkeypatch.setattr(cloud.CloudConfig, "path", staticmethod(lambda: tmp_path / "cloud.json"))
    assert not cloud.active_for("music")
    cloud.CloudConfig(enabled=True, url="http://127.0.0.1:9", engines=["music"]).save()
    assert cloud.active_for("music") and not cloud.active_for("voice")
    assert isinstance(runtimes.EngineHost.get("music"), cloud.RemoteHost)


def test_omnivoice_is_legacy(monkeypatch):
    from verbatim import tts

    monkeypatch.setattr(tts, "omni_installed", lambda: True)
    monkeypatch.setattr(tts, "omni_enabled", lambda: False)
    assert not any(v.id.startswith("ov:") for v in tts.voices_for("hi"))
    monkeypatch.setattr(tts, "omni_enabled", lambda: True)
    assert any(v.id.startswith("ov:") for v in tts.voices_for("hi"))
    assert all("OmniVoice" not in v.name for v in tts.omni_voices("hi"))


def test_sing_as_needs_consent(monkeypatch):
    from verbatim import music_studio, voicelab

    cv = voicelab.CustomVoice("my:x", "X")
    monkeypatch.setattr(voicelab, "get", lambda vid: cv)
    with pytest.raises(RuntimeError, match="consent"):
        music_studio.sing_as("song.wav", "my:x")


def test_localise_subtitle_mux(tmp_path):
    from verbatim.localise import mux_subtitles
    from verbatim.platform_info import ffmpeg_path
    import subprocess

    vid = tmp_path / "v.mp4"
    r = subprocess.run([ffmpeg_path(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=2",
                        "-f", "lavfi", "-i", "sine=f=440:d=2", "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(vid)],
                       capture_output=True)
    if r.returncode != 0:
        pytest.skip("ffmpeg cannot synthesise test video here")
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,500\nनमस्ते दुनिया\n", encoding="utf-8")
    out, note = mux_subtitles(vid, srt, "hi", tmp_path / "out.mp4")
    assert out == tmp_path / "out.mp4" and out.exists() and not note
    probe = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", str(out)], capture_output=True, text=True).stderr
    assert "Subtitle" in probe and "hin" in probe


def test_localise_request_defaults():
    from verbatim.localise import ISO3, LocaliseRequest

    r = LocaliseRequest(video="x.mp4")
    assert r.voice_mode == "own" and r.keep_background and r.subtitles_soft and not r.lipsync
    assert ISO3["hi"] == "hin"
