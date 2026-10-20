# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Word-error-rate measurement against a human-verified reference.

Follows the Hugging Face Open ASR Leaderboard convention: normalise both texts
(case, punctuation, number formats, filler words) before scoring, so that only real
recognition errors count. Produces an itemised error list (substitutions, deletions,
insertions) that can be exported to Excel.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

FILLERS = {"um", "uh", "umm", "uhh", "hmm", "mm", "mhm", "er", "erm", "ah", "eh", "uhm", "hm", "mmm"}
UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
SCALES = {"hundred": 100, "thousand": 1000, "million": 10**6, "billion": 10**9, "trillion": 10**12}
ORDINALS = {"first": "one", "second": "two", "third": "three", "fourth": "four", "fifth": "five", "sixth": "six",
            "seventh": "seven", "eighth": "eight", "ninth": "nine", "tenth": "ten", "eleventh": "eleven",
            "twelfth": "twelve", "thirteenth": "thirteen", "fourteenth": "fourteen", "fifteenth": "fifteen",
            "sixteenth": "sixteen", "seventeenth": "seventeen", "eighteenth": "eighteen", "nineteenth": "nineteen",
            "twentieth": "twenty", "thirtieth": "thirty"}
SPELLING = {"okay": "ok", "o.k.": "ok", "alright": "all right", "percent": "%", "per cent": "%"}


def _words_to_numbers(tokens: list[str]) -> list[str]:
    """Convert spelled-out numbers to digits ("twenty five million" -> "25000000")."""
    out: list[str] = []
    i = 0
    num = re.compile(r"\d+(\.\d+)?")
    while i < len(tokens):
        t = tokens[i]
        if t in UNITS or t in TENS:
            total = current = 0
            last = None
            j = i
            while j < len(tokens):
                w = tokens[j]
                if w in UNITS:
                    if last == "unit" or (last == "tens" and UNITS[w] >= 10):
                        break
                    current += UNITS[w]
                    last = "unit"
                elif w in TENS:
                    if last in ("unit", "tens"):
                        break
                    current += TENS[w]
                    last = "tens"
                elif (w == "point" and last in ("unit", "tens") and j + 1 < len(tokens)
                      and tokens[j + 1] in UNITS and UNITS[tokens[j + 1]] < 10):
                    digits = ""
                    j += 1
                    while j < len(tokens) and tokens[j] in UNITS and UNITS[tokens[j]] < 10:
                        digits += str(UNITS[tokens[j]])
                        j += 1
                    current = float(f"{int(current)}.{digits}")
                    last = "decimal"
                    continue
                elif w == "hundred" and last in ("unit", "tens"):
                    current *= 100
                    last = "hundred"
                elif w in SCALES and w != "hundred" and last in ("unit", "tens", "hundred", "decimal"):
                    total += current * SCALES[w]
                    current = 0
                    last = "scale"
                elif (w == "and" and last in ("hundred", "scale") and j + 1 < len(tokens)
                      and (tokens[j + 1] in UNITS or tokens[j + 1] in TENS)):
                    j += 1
                    continue
                else:
                    break
                j += 1
            value = total + current
            # spoken years: "twenty twenty" -> 2020, "nineteen thirty three" -> 1933
            if (last in ("unit", "tens") and total == 0 and 10 <= value <= 99 and j < len(tokens)
                    and (tokens[j] in TENS or (tokens[j] in UNITS and UNITS[tokens[j]] >= 10))):
                second = TENS.get(tokens[j], UNITS.get(tokens[j], 0))
                j += 1
                if second in TENS.values() and j < len(tokens) and tokens[j] in UNITS and 0 < UNITS[tokens[j]] < 10:
                    second += UNITS[tokens[j]]
                    j += 1
                value = value * 100 + second
            out.append(str(int(value)) if value == int(value) else str(round(value, 6)))
            i = j
        elif t in SCALES and out and num.fullmatch(out[-1]):
            v = float(out[-1]) * SCALES[t]
            out[-1] = str(int(v)) if v == int(v) else str(v)
            i += 1
        else:
            out.append(t)
            i += 1
    # "1 point 5" -> "1.5"
    merged: list[str] = []
    k = 0
    while k < len(out):
        if out[k] == "point" and merged and merged[-1].isdigit() and k + 1 < len(out) and out[k + 1].isdigit():
            merged[-1] = merged[-1] + "." + out[k + 1]
            k += 2
            continue
        if out[k] in SCALES and merged and re.fullmatch(r"\d+\.\d+", merged[-1]):
            v = float(merged[-1]) * SCALES[out[k]]
            merged[-1] = str(int(v)) if v == int(v) else str(v)
            k += 1
            continue
        merged.append(out[k])
        k += 1
    return merged


def normalize(text: str, drop_fillers: bool = True) -> list[str]:
    t = unicodedata.normalize("NFKC", text).casefold()
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|<[^>]*>", " ", t)          # [laughter], (inaudible)
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)                     # 1,000 -> 1000
    t = re.sub(r"\$\s?(\d[\d.]*)(\s(?:thousand|million|billion|trillion)\b)?", r"\1\2 dollars", t)
    t = t.replace("%", " percent ").replace("&", " and ")
    for a, b in SPELLING.items():
        t = re.sub(rf"\b{re.escape(a)}\b", b, t)
    t = re.sub(r"(?<=\w)['’](?=\w)", "'", t)
    t = re.sub(r"(?<!\d)\.(?!\d)|[^\w\s'.%]", " ", t)               # keep decimals like 1.5
    t = t.replace("-", " ")
    for word, base in ORDINALS.items():
        t = re.sub(rf"\b{word}\b", f"{base} th", t)
    t = re.sub(r"(?<=\d)(st|nd|rd|th)\b", " th", t)
    t = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", t)     # q2 -> q 2, 10k -> 10 k
    toks = [w.strip("'.") for w in t.split()]
    toks = [w for w in toks if w]
    toks = _words_to_numbers(toks)
    toks = ["percent" if w == "%" else w for w in toks]
    if drop_fillers:
        toks = [w for w in toks if w not in FILLERS]
    return toks


@dataclass
class WERResult:
    wer: float
    substitutions: int
    deletions: int
    insertions: int
    ref_words: int
    hyp_words: int
    errors: list[dict] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return max(0.0, 1.0 - self.wer)


def align(ref: list[str], hyp: list[str], ref_prefix: bool = False) -> WERResult:
    """Levenshtein alignment with backtrace. ref_prefix=True scores hyp against the best
    matching *prefix* of ref (for clipped excerpts of long recordings)."""
    n, m = len(ref), len(hyp)
    if ref_prefix:
        n = min(n, int(m * 1.6) + 60)
        ref = ref[:n]
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        d[i][0] = i
        ri = ref[i - 1]
        row, prev = d[i], d[i - 1]
        for j in range(1, m + 1):
            sub = prev[j - 1] + (ri != hyp[j - 1])
            dele = prev[j] + 1
            ins = row[j - 1] + 1
            row[j] = sub if sub <= dele and sub <= ins else (dele if dele <= ins else ins)
    end = min(range(n + 1), key=lambda i: (d[i][m], -i)) if ref_prefix else n
    i, j = end, m
    S = D = I = 0
    errors = []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            if ref[i - 1] != hyp[j - 1]:
                S += 1
                errors.append({"type": "substitution", "reference": ref[i - 1], "transcript": hyp[j - 1], "ref_index": i - 1,
                               "hyp_index": j - 1})
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            D += 1
            errors.append({"type": "deletion", "reference": ref[i - 1], "transcript": "", "ref_index": i - 1,
                           "hyp_index": j})
            i -= 1
        else:
            I += 1
            errors.append({"type": "insertion", "reference": "", "transcript": hyp[j - 1], "ref_index": i,
                           "hyp_index": j - 1})
            j -= 1
    errors.reverse()
    for e in errors:
        k = e["ref_index"]
        e["context"] = " ".join(ref[max(0, k - 5):k + 6])
    return WERResult((S + D + I) / max(1, end), S, D, I, end, m, errors)


def wer(reference: str, hypothesis: str, ref_prefix: bool = False, drop_fillers: bool = True) -> WERResult:
    return align(normalize(reference, drop_fillers), normalize(hypothesis, drop_fillers), ref_prefix)
