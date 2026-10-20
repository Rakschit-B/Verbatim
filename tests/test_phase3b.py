"""3.3: voice library, TranslateGemma prompt + local server lifecycle, Claude polish/shorten, meaning check."""
import json
import sys
import textwrap

import numpy as np

from verbatim import dub, llm, tts
from verbatim.translate import ClaudeTranslator, GemmaTranslator, claude_system, gemma_prompt


def test_voice_library():
    hi = tts.voices_for("hi")
    assert len([v for v in hi if v.engine == "st"]) == 10 and hi[0].engine == "st"
    assert {v.gender for v in hi} == {"female", "male"}
    assert tts.voices_for("zh") and all(v.engine == "ko" for v in tts.voices_for("zh"))
    assert tts.voices_for("he") == []                       # no local Hebrew voice yet
    d = tts.default_voices("hi", 3)
    assert tts.VOICES[d[0]].gender == "female" and tts.VOICES[d[1]].gender == "male" and d[0] != d[2]


def test_resample_lengths():
    a = np.sin(np.arange(44100) / 10).astype(np.float32)
    assert abs(len(tts.resample(a, 44100)) - 48000) <= 2
    assert len(tts.resample(a[:24000], 24000)) == 48000


def test_gemma_prompt():
    p = gemma_prompt("Hello", "en", "hi")
    assert p.startswith("<start_of_turn>user\nYou are a professional English (en) to Hindi (hi) translator")
    assert p.endswith("Hello<end_of_turn>\n<start_of_turn>model\n")
    assert "Chinese (zh-CN)" in gemma_prompt("x", "en", "zh")


def test_claude_system_style_and_language_guide():
    s = claude_system("en", "hi", "Infinite Story", "creative")
    assert "Transcreate" in s and "Devanagari" in s and "Infinite Story" in s


def test_claude_polish_and_shorten(monkeypatch):
    def fake(self, system, user):
        if "voice director" in system:
            return '[{"n": 1, "t": "बेहतर पंक्ति"}]'
        if "too long" in system:
            return '[{"n": 2, "t": "छोटी"}]'
        return '[{"n": 1, "t": "पंक्ति"}, {"n": 2, "t": "दूसरी बहुत लंबी पंक्ति"}]'

    monkeypatch.setattr(ClaudeTranslator, "_call", fake)
    tr = ClaudeTranslator(api_key="k")
    assert tr.translate(["one", "two"], "en", "hi")[0] == "बेहतर पंक्ति"      # polish pass applied
    assert tr.shorten([(2, "two", "दूसरी बहुत लंबी पंक्ति", 8)], "en", "hi") == {2: "छोटी"}


def test_gemma_translator_glossary(monkeypatch):
    seen = []

    def fake_run(self, lines, src, tgt, label, progress):
        seen.extend(lines)
        return [ln.replace("hello", "नमस्ते") for ln in lines]

    monkeypatch.setattr(GemmaTranslator, "_run", fake_run)
    out = GemmaTranslator().translate(["hello Infinite Story"], "en", "hi", vocabulary="Infinite Story\nAI => एआई")
    assert seen == ["hello [0]"] and out == ["नमस्ते Infinite Story"]


def test_llama_server_lifecycle(tmp_path, monkeypatch):
    fake = tmp_path / "llama-server"
    fake.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import json, sys
        from http.server import BaseHTTPRequestHandler, HTTPServer
        port = int(sys.argv[sys.argv.index("--port") + 1])
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def _send(self, d):
                b = json.dumps(d).encode(); self.send_response(200); self.end_headers(); self.wfile.write(b)
            def do_GET(self): self._send({{"status": "ok"}})
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self._send({{"content": "ECHO:" + body["prompt"][-12:]}})
        HTTPServer(("127.0.0.1", port), H).serve_forever()
        """))
    fake.chmod(0o755)
    monkeypatch.setattr(llm, "root", lambda: tmp_path)
    model = tmp_path / "m.gguf"
    model.write_bytes(b"GGUF")
    with llm.LlamaServer(model, fake) as srv:
        assert srv.complete("hello world!").startswith("ECHO:")
        proc = srv.proc
    assert proc.poll() is not None                          # stopped after the job


def test_shorten_long_lines_and_check(tmp_path):
    job = dub.VoiceJob(str(tmp_path / "x.json"), "", "en", "hi")
    job.lines = [dub.Line(0, 0, 2, "S", "a", "बहुत लंबी पंक्ति", fit="too long +0.8 s", spoken=3.0),
                 dub.Line(1, 3, 5, "S", "b", "ठीक", fit="ok", spoken=1.0)]

    class T:
        def shorten(self, items, *a):
            assert items[0][0] == 1 and items[0][3] < len("बहुत लंबी पंक्ति")
            return {1: "छोटी"}

        def back_translate(self, lines, *a, **k):
            return [f"back:{x}" for x in lines]

    assert dub.shorten_long_lines(job, T()) == 1 and job.lines[0].text == "छोटी" and job.lines[0].edited
    dub.check_meaning(job, T())
    assert job.lines[1].check == "back:ठीक"
    assert json.loads(job.path.read_text(encoding="utf-8"))["lines"][0]["text"] == "छोटी"
