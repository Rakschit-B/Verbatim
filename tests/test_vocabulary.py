# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
from verbatim.model import Segment, Transcript, Word
from verbatim.vocabulary import Vocabulary


def seg(text):
    words = [Word(" " + t, i, i + 1, 0.9) for i, t in enumerate(text.split())]
    return Segment(0, len(words), text, words)


def test_parse_terms_and_rules():
    v = Vocabulary.parse("Infinite Story, EXL\nexcel service => EXL Service\n# comment")
    assert v.terms == ["Infinite Story", "EXL", "EXL Service"]
    assert v.rules == [("excel service", "EXL Service")]
    assert "Infinite Story" in v.whisper_prompt()
    assert v.keyterms() == ["Infinite Story", "EXL", "EXL Service"]


def test_rule_casing_and_fuzzy_are_logged():
    t = Transcript([seg("we met excel service and exl at infinit story today.")])
    for w in t.segments[0].words[6:8]:
        w.prob = 0.4  # the engine was unsure of "infinit story"
    v = Vocabulary.parse("Infinite Story\nEXL\nexcel service => EXL Service")
    log = v.apply(t)
    assert t.segments[0].text == "we met EXL Service and EXL at Infinite Story today."
    assert {c["rule"] for c in log} == {"rule", "casing", "fuzzy"}


def test_fuzzy_does_not_touch_unrelated_words():
    t = Transcript([seg("the story was infinite in scope")])
    Vocabulary.parse("Infinite Story").apply(t)
    assert t.segments[0].text == "the story was infinite in scope"


def test_punctuation_preserved():
    t = Transcript([seg("thanks, exl.")])
    Vocabulary.parse("EXL").apply(t)
    assert t.segments[0].text == "thanks, EXL."


def test_safeguards_against_false_corrections():
    t = Transcript([seg("being at the call we will now hear from Maureen Maholland")])
    t.segments[0].words[-1].prob = 0.5
    log = Vocabulary.parse("Boeing\nA&T\nWillow\nMaureen Mulholland\nGeneral Counsel").apply(t)
    assert t.segments[0].text == "being at the call we will now hear from Maureen Mulholland"
    assert [c["corrected"] for c in log] == ["Maureen Mulholland"]


def test_confident_words_are_trusted():
    t = Transcript([seg("Monroe reported results")])  # prob 0.9 everywhere
    assert Vocabulary.parse("Monro").apply(t) == []


def test_short_brand_one_edit_when_unsure():
    t = Transcript([seg("welcome to the Zag quarterly call")])
    t.segments[0].words[3].prob = 0.6
    log = Vocabulary.parse("Zagg").apply(t)
    assert t.segments[0].text == "welcome to the Zagg quarterly call" and log[0]["rule"] == "fuzzy"


def test_possessive_kept():
    t = Transcript([seg("review Zag's results")])
    t.segments[0].words[1].prob = 0.5
    Vocabulary.parse("ZAGG").apply(t)
    assert t.segments[0].text == "review ZAGG's results"
