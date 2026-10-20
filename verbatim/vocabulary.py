"""Custom vocabulary: biasing before decoding and audited correction after it.

Before decoding the terms become a Whisper prompt / faster-whisper hotwords /
ElevenLabs `keyterms`. After decoding, three conservative passes run, each logged so
the Master Log shows exactly what was changed and why:
  1. explicit rules        ("tata power ddl => Tata Power-DDL")
  2. canonical casing      ("exl" -> "EXL")
  3. fuzzy name repair     ("Afimed" -> "Affimed"; high threshold, names >= 5 letters)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import Segment, Transcript, Word

RULE_SPLIT = re.compile(r"\s*(?:=>|->|→)\s*")
CORE = re.compile(r"^(\W*)(.*?)(\W*)$", re.S)

# Prompt style matters: Whisper imitates the prompt. A disfluent prompt keeps fillers
# (OpenAI prompting guide); a clean one encourages tidy punctuation.
VERBATIM_STYLE = "Um, so, uh, I- I think we should, you know, start. Hmm. Okay."
CLEAN_STYLE = "Hello, welcome. Let's begin with today's discussion."


@dataclass
class Vocabulary:
    terms: list[str] = field(default_factory=list)
    rules: list[tuple[str, str]] = field(default_factory=list)

    @staticmethod
    def parse(text: str) -> "Vocabulary":
        terms: list[str] = []
        rules: list[tuple[str, str]] = []
        for raw in re.split(r"[\n,;]", text or ""):
            item = raw.strip()
            if not item or item.startswith("#"):
                continue
            parts = RULE_SPLIT.split(item)
            if len(parts) == 2 and parts[0] and parts[1]:
                rules.append((parts[0].strip(), parts[1].strip()))
                if parts[1].strip() not in terms:
                    terms.append(parts[1].strip())
            elif item not in terms:
                terms.append(item)
        return Vocabulary(terms, rules)

    def __bool__(self) -> bool:
        return bool(self.terms or self.rules)

    # ---------- biasing ----------
    def whisper_prompt(self, verbatim: bool = True, max_chars: int = 600, context: str = "") -> str:
        style = VERBATIM_STYLE if verbatim else CLEAN_STYLE
        if context:
            style = f"{context}. {style}"
        if not self.terms:
            return style
        glossary = ""
        for t in self.terms:
            nxt = (glossary + ", " + t) if glossary else t
            if len(nxt) > max_chars:
                break
            glossary = nxt
        return f"{style} Names and terms: {glossary}."

    def hotwords(self, max_chars: int = 600) -> str:
        return ", ".join(self.terms)[:max_chars]

    def keyterms(self) -> list[str]:
        """ElevenLabs keyterms: <50 chars, <=5 words, no <>{}[]\\ characters."""
        out = []
        for t in self.terms:
            t = re.sub(r"[<>{}\[\]\\]", "", t).strip()
            if t and len(t) < 50 and len(t.split()) <= 5:
                out.append(t)
        return out[:1000]

    # ---------- correction ----------
    def apply(self, transcript: Transcript, fuzzy_threshold: float = 90.0, confident: float = 0.85) -> list[dict]:
        """Audited post-correction. Safeguards (each one added after a benchmark exposed a
        false correction): exact rules first; casing only for terms whose casing is
        distinctive (EXL, iPhone, multi-word names); fuzzy repair only of spans the engine
        itself was unsure of, never of common words, never across a different word count,
        and never of something that already is another vocabulary term."""
        log: list[dict] = []
        if not self:
            return log
        known = {_norm(t) for t in self.terms}
        casing_terms = [t for t in self.terms if _distinctive_case(t)]
        fuzzy_terms: dict[int, list[str]] = {}
        if fuzzy_threshold <= 100:
            for t in self.terms:
                if len(re.sub(r"\W", "", t)) >= 4:
                    fuzzy_terms.setdefault(len(t.split()), []).append(t)
        for seg in transcript.segments:
            if not seg.words:
                continue
            for wrong, right in self.rules:
                log += _replace_exact(seg, wrong, right, "rule")
            for term in casing_terms:
                log += _replace_exact(seg, term, term, "casing")
            if fuzzy_terms:
                log += _fuzzy_pass(seg, fuzzy_terms, known, fuzzy_threshold, confident)
            seg.text = words_to_text(seg.words)
        return log


COMMON = set("""a about above after again against all also am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have having he her
here hers him his how i if in into is it its just me more most my no nor not now of off on once only or other our
out over own same she should so some such than that the their them then there these they this those through to too
under until up very was we were what when where which while who whom why will with would you your yours yes okay
well going go get got make made say said see think know mean right like just really thank thanks good morning
afternoon evening call today quarter year years new one two three first second last next time people company
business results also call question questions operator please now let us call""".split())


def terms_from_filename(stem: str) -> tuple[str, list[str]]:
    """TurboScribe found that metadata such as the file name improves names and terms.
    Returns a readable context phrase and the name-like tokens (ZAGG, Tata, EXL…)."""
    phrase = re.sub(r"[_\-.]+", " ", stem)
    phrase = re.sub(r"\b(final|v\d+|copy|export|edit|draft|mp4|mov|\d{3,4}p|img|vid|dsc)\b", " ", phrase, flags=re.I)
    phrase = re.sub(r"\s+", " ", phrase).strip()
    if sum(c.isalpha() for c in phrase) < 4:
        return "", []
    terms = []
    for tok in re.findall(r"[A-Za-z][A-Za-z&'-]{2,}", phrase):
        if (tok.isupper() or tok[0].isupper()) and tok.casefold() not in common_words() and tok not in terms:
            terms.append(tok)
    return phrase, terms


_COMMON_EN: set[str] | None = None


def common_words() -> set[str]:
    """20k most frequent English words (wordfreq, CC-BY-SA 4.0) — a single *common* word is
    never 'corrected' into a vocabulary term ("sell" must not become "Shell")."""
    global _COMMON_EN
    if _COMMON_EN is None:
        try:
            from .platform_info import asset

            _COMMON_EN = set(asset("common_words_en.txt").read_text(encoding="utf-8").split()) | COMMON
        except OSError:
            _COMMON_EN = set(COMMON)
    return _COMMON_EN


def _distinctive_case(term: str) -> bool:
    words = term.split()
    return len(words) > 1 or any(c.isupper() for c in term[1:]) or not term[:1].isalpha()


def _fuzzy_pass(seg: Segment, terms_by_len: dict[int, list[str]], known: set[str], threshold: float,
                confident: float) -> list[dict]:
    from rapidfuzz import fuzz, process

    log = []
    words = seg.words
    i = 0
    while i < len(words):
        done = False
        for n in sorted(terms_by_len, reverse=True):
            if i + n > len(words):
                continue
            span = words[i:i + n]
            cores = [_core(w.text.strip())[1] for w in span]
            poss = ""
            m = re.search(r"['’]s$", cores[-1])
            if m:  # keep possessives: "Zag's" -> "Zagg's"
                poss = m.group(0)
                cores[-1] = cores[-1][: -len(poss)]
            cand = " ".join(cores)
            cn = _norm(cand)
            if not cn or cn in known:
                continue
            if all(c.casefold() in COMMON for c in cores) or (n == 1 and cores[0].casefold() in common_words()):
                continue  # never turn ordinary words into names ("being" -> "Boeing", "sell" -> "Shell")
            probs = [w.prob for w in span]
            if all(p is not None for p in probs):
                if min(probs) >= confident:
                    continue  # engine was sure; trust it
            elif not all(c[:1].isupper() for c in cores if c):
                continue  # no confidence info: only touch capitalised (name-like) words
            choices = {t: _norm(t) for t in terms_by_len[n]}
            best = process.extractOne(cn, choices, scorer=fuzz.ratio, score_cutoff=threshold)
            term = best[2] if best else None
            if term is None or len(choices[term]) < 6:
                # short names (Zagg, Tata): ratio is too coarse — allow exactly one edit instead
                from rapidfuzz.distance import Levenshtein

                short = [t for t, tn in choices.items() if 4 <= len(tn) <= 6 and len(cn) >= 3
                         and Levenshtein.distance(cn, tn) == 1]
                term = short[0] if len(short) == 1 else (term if term and len(choices[term]) >= 6 else None)
            if not term:
                continue
            tn = choices[term]
            if tn[0] != cn[0] or abs(len(tn) - len(cn)) > 3:
                continue
            log += _substitute(seg, i, n, term + poss, "fuzzy")
            i += len(term.split())
            done = True
            break
        if not done:
            i += 1
    return log


def _replace_exact(seg: Segment, phrase: str, replacement: str, kind: str) -> list[dict]:
    n = len(phrase.split())
    target = phrase.casefold().split()
    log = []
    i = 0
    while i <= len(seg.words) - n:
        cores = [_core(w.text.strip())[1] for w in seg.words[i:i + n]]
        if [c.casefold() for c in cores] == target and " ".join(cores) != replacement:
            log += _substitute(seg, i, n, replacement, kind)
            i += len(replacement.split())
        else:
            i += 1
    return log


def _substitute(seg: Segment, i: int, n: int, replacement: str, kind: str) -> list[dict]:
    words = seg.words
    span_words = words[i:i + n]
    lead_space = " " if span_words[0].text.startswith(" ") else ""
    prefix = _core(span_words[0].text.strip())[0]
    suffix = _core(span_words[-1].text.strip())[2]
    original = "".join(w.text for w in span_words).strip()
    new_tokens = replacement.split()
    start, end = span_words[0].start, span_words[-1].end
    probs = [w.prob for w in span_words if w.prob is not None]
    step = (end - start) / max(1, len(new_tokens))
    new_words = []
    for k, tok in enumerate(new_tokens):
        text = (lead_space if k == 0 else " ") + (prefix if k == 0 else "") + tok
        if k == len(new_tokens) - 1:
            text += suffix
        new_words.append(Word(text, start + k * step, start + (k + 1) * step,
                              min(probs) if probs else None, span_words[0].speaker))
    corrected = "".join(w.text for w in new_words).strip()
    if corrected == original:
        return []
    words[i:i + n] = new_words
    return [{"time": round(start, 2), "original": original, "corrected": corrected, "rule": kind}]


def _core(token: str) -> tuple[str, str, str]:
    m = CORE.match(token)
    return (m.group(1), m.group(2), m.group(3)) if m else ("", token, "")


def _norm(s: str) -> str:
    """Case/space-insensitive key that keeps symbols such as & + so 'A&T' != 'at'."""
    return re.sub(r"[\s.,;:!?'\"’-]", "", s.casefold())


def words_to_text(words: list[Word]) -> str:
    return re.sub(r"\s+", " ", "".join(w.text for w in words)).strip()
