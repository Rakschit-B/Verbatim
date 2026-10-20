# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Phase 2: alignment core, speaker library, projects, transcript editing."""
import json

import numpy as np

from verbatim.align import _interpolate, ctc_viterbi
from verbatim.editing import EditSession, retime
from verbatim.model import Segment, Transcript, Word
from verbatim.projects import Projects
from verbatim.speakers import SpeakerLibrary, rename_in_transcript


def test_ctc_viterbi_finds_tokens_where_they_are_loudest():
    T, V = 40, 8
    lp = np.full((T, V), -10.0)
    lp[:, 0] = -0.1                       # blank everywhere …
    for f in range(5, 8):
        lp[f, 5] = -0.05                  # … token 5 at frames 5-7
    for f in range(20, 22):
        lp[f, 6] = -0.05                  # token 6 at frames 20-21
    path = ctc_viterbi(lp, np.array([5, 6]))
    assert path[0][0] == 5 and path[0][1] == 7
    assert path[1][0] == 20 and path[1][1] == 21


def test_ctc_viterbi_repeated_label_needs_blank():
    lp = np.full((10, 4), -10.0)
    lp[:, 0] = -0.5
    lp[2, 3] = lp[6, 3] = -0.01
    path = ctc_viterbi(lp, np.array([3, 3]))
    assert path[0][0] == 2 and path[1][0] == 6


def test_interpolate_fills_unaligned_words():
    ws = [Word("a", 1.0, 1.2), Word("2025", 0, 0), Word("b", 2.0, 2.2)]
    _interpolate(ws, {0, 2})
    assert 1.2 <= ws[1].start < ws[1].end <= 2.0


def test_retime_keeps_unchanged_word_times():
    old = [Word(" the", 0.0, 0.2, 0.9), Word(" excel", 0.2, 0.6, 0.3), Word(" team", 0.6, 1.0, 0.95)]
    new = retime(old, ["the", "EXL", "Service", "team"], 0.0, 1.0, "Speaker 1")
    assert [w.text for w in new] == ["the", "EXL", "Service", "team"]
    assert new[0].start == 0.0 and new[-1].end == 1.0
    assert 0.2 <= new[1].start < new[2].end <= 0.6
    assert all(w.prob == 1.0 for w in new)


def _write_job(tmp_path):
    t = Transcript([Segment(0.0, 2.0, " hello excel team", [Word(" hello", 0, .5, .9, "Speaker 1"),
                                                            Word(" excel", .5, 1.2, .2, "Speaker 1"),
                                                            Word(" team", 1.2, 2.0, .9, "Speaker 1")], "Speaker 1"),
                    Segment(2.5, 3.5, " thanks", [Word(" thanks", 2.5, 3.5, .9, "Speaker 2")], "Speaker 2")],
                   "en", "parakeet", "m", speaker_profiles={"Speaker 1": [1.0, 0.0], "Speaker 2": [0.0, 1.0]})
    src = tmp_path / "town hall.mp4"
    src.write_bytes(b"x")
    dest = tmp_path / "out" / "town hall.mp4"
    dest.mkdir(parents=True)
    jp = dest / "town hall.json"
    jp.write_text(json.dumps({"source_file": src.name, "source_path": str(src), "info": {"duration": 3.5},
                              "quality": {}, "transcript": t.to_dict(), "review": [
                                  {"start": .5, "end": 1.2, "speaker": "Speaker 1", "text": "excel", "confidence": .2,
                                   "context": "", "reason": "low confidence"}],
                              "corrections": [], "removals": [], "crosscheck": {}}), encoding="utf-8")
    return jp


def test_edit_session_saves_and_reexports(tmp_path):
    jp = _write_job(tmp_path)
    ed = EditSession(jp)
    assert ed.set_text(0, "hello EXL team")
    assert ed.rename_speaker("Speaker 2", "Rahul") == 1
    out = ed.save()
    data = json.loads(jp.read_text(encoding="utf-8"))
    segs = data["transcript"]["segments"]
    assert segs[0]["text"].strip() == "hello EXL team" and "edited" in segs[0]["flags"]
    assert segs[1]["speaker"] == "Rahul" and "Rahul" in data["transcript"]["speaker_profiles"]
    assert data["review"][0]["status"] == "Corrected"
    assert any(c["rule"] == "manual edit (editor)" for c in data["corrections"])
    txt = (jp.parent / "town hall.txt").read_text(encoding="utf-8")
    assert "EXL" in txt and "Rahul" in txt
    assert out["folder"] == str(jp.parent)


def test_speaker_library_match_is_one_to_one(tmp_path):
    lib = SpeakerLibrary(tmp_path / "s.json")
    lib.enroll("Rahul", [1, 0, 0])
    lib.enroll("Asha", [0, 1, 0])
    m = SpeakerLibrary(tmp_path / "s.json").match({"Speaker 1": [0.1, 0.99, 0], "Speaker 2": [0.98, 0.1, 0],
                                                  "Speaker 3": [0, 0, 1]})
    assert m["Speaker 1"][0] == "Asha" and m["Speaker 2"][0] == "Rahul" and "Speaker 3" not in m
    assert lib.rename("Asha", "Asha Rao") and lib.find("asha rao")
    assert lib.rename("Asha Rao", "Rahul") and len(lib.entries) == 1  # merge


def test_rename_in_transcript():
    t = Transcript([Segment(0, 1, "hi", [Word("hi", 0, 1, None, "Speaker 1")], "Speaker 1")],
                   speaker_profiles={"Speaker 1": [1]})
    rename_in_transcript(t, {"Speaker 1": "Rahul"})
    assert t.segments[0].speaker == "Rahul" and t.segments[0].words[0].speaker == "Rahul"
    assert "Rahul" in t.speaker_profiles


def test_projects(tmp_path):
    ps = Projects(tmp_path / "p.json")
    p = ps.create("EXL / Town hall", str(tmp_path), "EXL Service")
    assert p["output_dir"].endswith("EXL - Town hall")
    ps.update(p["id"], vocabulary="EXL Service\nRohit Kapoor")
    assert Projects(tmp_path / "p.json").get(p["id"])["vocabulary"].endswith("Kapoor")
    assert Projects.stats(p)["files"] == 0
    assert ps.remove(p["id"]) and not ps.items
