# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
from verbatim.accuracy import normalize, wer


def test_perfect_and_case_punctuation():
    assert wer("Hello, world!", "hello world").wer == 0


def test_numbers_years_currency_equivalent():
    assert normalize("Revenue was $5.2 million in Q2 twenty twenty") == normalize("revenue was five point two million dollars in q 2 2020")


def test_fillers_ignored_by_default():
    assert wer("we should start", "um we should uh start").wer == 0
    assert wer("we should start", "um we should uh start", drop_fillers=False).insertions == 2


def test_error_breakdown():
    r = wer("the cat sat on the mat", "the cat sit on mat")
    assert (r.substitutions, r.deletions, r.insertions) == (1, 1, 0)
    assert round(r.wer, 3) == round(2 / 6, 3)


def test_prefix_mode_for_excerpts():
    r = wer("one two three four five six seven eight", "one two three four", ref_prefix=True)
    assert r.wer == 0 and r.ref_words == 4
