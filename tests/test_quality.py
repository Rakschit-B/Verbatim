# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
from verbatim.crosscheck import cross_check
from verbatim.model import Segment, Transcript, Word
from verbatim.quality import missed_speech, remove_hallucinations, review_items


def mk(text, start=0.0, prob=0.95, step=0.4):
    words = [Word(" " + t, start + i * step, start + (i + 1) * step, prob) for i, t in enumerate(text.split())]
    return Segment(words[0].start, words[-1].end, text, words)


def test_hallucination_on_silence_removed_but_real_speech_kept():
    t = Transcript([mk("Hello and welcome to the call.", 0), mk("Thank you for watching.", 30, prob=0.4)])
    log = remove_hallucinations(t, speech=[(0, 10)])
    assert [s.text for s in t.segments] == ["Hello and welcome to the call."]
    assert log and log[0]["action"].startswith("removed")


def test_repetition_loop_collapsed():
    s = mk(" ".join(["thank you"] * 8) + " bye", 0)
    t = Transcript([s])
    log = remove_hallucinations(t, speech=[(0, 100)])
    assert t.segments[0].text.count("thank you") == 2 and log


def test_missed_speech_detected():
    t = Transcript([mk("only the start", 0)])
    assert missed_speech(t, [(0, 2), (20, 25)]) == [(20, 25)]


def test_low_confidence_review_items():
    s = mk("the client is excel", 0)
    s.words[3].prob = 0.2
    items = review_items(Transcript([s]), 0.5)
    assert items[0]["text"] == "excel" and "[excel]" in items[0]["context"]


def test_crosscheck_agreement_and_fusion():
    a = Transcript([mk("revenue grew by twelve percent", 0)])
    a.segments[0].words[1].prob = 0.3
    a.segments[0].words[1].text = " grue"
    b = Transcript([mk("revenue grew by twelve percent", 0, prob=0.97)])
    r = cross_check(a, b, fuse=True)
    assert r["fused_words"] == 1 and "grew" in a.segments[0].text
    r2 = cross_check(Transcript([mk("a b c d", 0)]), Transcript([mk("a x c d", 0)]))
    assert r2["agreement"] == 0.75 and r2["disagreements"][0]["secondary"] == "x"
