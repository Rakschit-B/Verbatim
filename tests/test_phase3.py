# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Phase 3: translation engines (mocked network), voice jobs, subtitles, consent register."""
import json

from verbatim import dub
from verbatim.consent import ConsentRegister
from verbatim.model import Segment, Transcript, Word
from verbatim.translate import ClaudeTranslator, glossary_from_vocabulary, offline_route


def test_glossary():
    keep, rules = glossary_from_vocabulary("Infinite Story\n# comment\nexcel service => EXL Service\n\nTata Power-DDL")
    assert keep == ["Infinite Story", "Tata Power-DDL"] and rules == {"excel service": "EXL Service"}


def test_claude_translator_numbering_and_retry(monkeypatch):
    calls = []

    def fake_call(self, system, user):
        calls.append((system, user))
        if user.startswith("Translate this line"):
            return '[{"n": 2, "t": "दूसरी पंक्ति"}]'
        return 'Here you go: [{"n": 1, "t": "पहली पंक्ति"}, {"n": 3, "t": "तीसरी"}]'

    monkeypatch.setattr(ClaudeTranslator, "_call", fake_call)
    tr = ClaudeTranslator(api_key="test")
    out = tr.translate(["first", "second", "third"], "en", "hi", vocabulary="Infinite Story\nAI => एआई")
    assert out == ["पहली पंक्ति", "दूसरी पंक्ति", "तीसरी"]
    assert "Infinite Story" in calls[0][0] and "AI → एआई" in calls[0][0]  # glossary reaches the prompt


def test_offline_route_pivots_via_english():
    idx = [{"from_code": "hi", "to_code": "en"}, {"from_code": "en", "to_code": "es"}, {"from_code": "en", "to_code": "hi"}]
    assert offline_route("en", "hi", idx) == [("en", "hi")]
    assert offline_route("hi", "es", idx) == [("hi", "en"), ("en", "es")]
    assert offline_route("es", "hi", idx) == []


def _transcript_json(tmp_path):
    words = [Word(w, i * 0.7, i * 0.7 + 0.6, 0.9, "Speaker 1") for i, w in enumerate(
        "Hello everyone. This is a long opening line that keeps going on. And here is another sentence.".split())]
    t = Transcript([Segment(0.0, words[-1].end, " ".join(w.text for w in words), words, "Speaker 1"),
                    Segment(20.0, 22.0, "Thanks.", [Word("Thanks.", 20.0, 22.0, 0.9, "Speaker 2")], "Speaker 2")], "en")
    jp = tmp_path / "talk" / "talk.json"
    jp.parent.mkdir()
    jp.write_text(json.dumps({"source_path": str(tmp_path / "talk.mp4"), "info": {"duration": 23.0},
                              "transcript": t.to_dict()}), encoding="utf-8")
    return jp


def test_voice_job_split_translate_save_reload(tmp_path):
    jp = _transcript_json(tmp_path)
    job = dub.new_job(jp, "hi")
    assert len(job.lines) >= 3 and job.lines[-1].speaker == "Speaker 2"
    assert all(a.end <= b.start + 1e-6 for a, b in zip(job.lines, job.lines[1:]))

    class Fake:
        name, model = "fake", ""

        def translate(self, lines, *a, **k):
            return [f"[{x}]" for x in lines]

    job.lines[0].text, job.lines[0].edited = "मेरा अनुवाद", True
    dub.translate_job(job, Fake())
    assert job.lines[0].text == "मेरा अनुवाद"            # edited lines are kept
    assert job.lines[1].text.startswith("[")
    again = dub.new_job(jp, "hi")                       # reopening returns saved work
    assert again.lines[0].text == "मेरा अनुवाद" and again.engine == "fake"
    assert job.path.name == "talk — Hindi.voice.json"


def test_render_timing_fit_and_outputs(tmp_path):
    import numpy as np

    jp = _transcript_json(tmp_path)
    job = dub.new_job(jp, "en")
    for ln in job.lines:
        ln.text = ln.source

    class FakeSynth:  # speech whose length depends on text length and speed
        def speak(self, text, lang, sid, speed, direction=None):
            n = int(dub.SR * 0.2 * len(text) / speed)
            return (0.2 * np.sin(np.arange(n) / 20)).astype(np.float32)

    out = dub.render(job, FakeSynth(), mix=False, video=False)
    assert set(["voice", "srt", "vtt", "txt", "report"]) <= set(out)
    fits = [ln.fit for ln in job.lines]
    assert all(f for f in fits) and any(f.startswith(("faster", "too long")) for f in fits)
    srt = open(out["srt"], encoding="utf-8").read()
    assert "-->" in srt and "Thanks." in srt


def test_subtitle_cues_wrap():
    ln = dub.Line(0, 0.0, 6.0, "S", "x", "word " * 30)
    cues = dub.subtitle_cues([ln])
    assert len(cues) >= 2 and all(len(c[2].split("\n")) <= 2 for c in cues)
    assert abs(cues[-1][1] - 6.0) < 0.01


def test_consent_register(tmp_path):
    form = tmp_path / "signed.pdf"
    form.write_bytes(b"%PDF-1.4 test")
    reg = ConsentRegister(tmp_path / "c")
    e = reg.add("Rohit Kapoor", form, "Voice cloning for this project only", "2026-10-20", "2027-10-20", "EXL")
    assert ConsentRegister(tmp_path / "c").valid_for("rohit kapoor")["id"] == e["id"]
    assert reg.status({**e, "expires": "2020-01-01"}) == "Expired"
    reg.revoke(e["id"], "withdrawn")
    assert ConsentRegister(tmp_path / "c").valid_for("Rohit Kapoor") is None
    dub_only = reg.add("Asha", form, "Voiceover in other languages (dubbing)", "2026-10-20")
    assert reg.valid_for("Asha") is None and reg.valid_for("Asha", cloning=False)["id"] == dub_only["id"]


def test_offline_translator_protects_names_and_pivots(monkeypatch):
    from verbatim import translate as tr

    class SP:
        def encode(self, s, out_type=str):
            return s.split()

        def decode(self, toks):
            return " ".join(toks)

    class Res:
        def __init__(self, toks):
            self.hypotheses = [toks]

    class TR:  # "translates" by upper-casing every token except placeholders
        def __init__(self, tag):
            self.tag = tag

        def translate_batch(self, batch, **k):
            return [Res([t if t.startswith("ZX") else t.upper() + self.tag for t in toks]) for toks in batch]

    monkeypatch.setattr(tr, "offline_route", lambda s, t, index=None: [(s, "en"), ("en", t)])
    monkeypatch.setattr(tr.OfflineTranslator, "_pair", lambda self, a, b: (SP(), TR("")))
    out = tr.OfflineTranslator().translate(["welcome to infinite story. bye!", ""], "hi", "es",
                                           vocabulary="Infinite Story")
    assert out[0] == "WELCOME TO Infinite Story. BYE!" and out[1] == ""
