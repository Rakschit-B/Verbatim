"""Segment-by-segment translation for Voice Studio.

Two engines, chosen per job:
- "offline": Argos Translate / OPUS-MT models (CTranslate2 + SentencePiece). Free and private,
  downloaded once per language pair (~100 MB each). Pairs without a direct model pivot via English.
- "claude": Anthropic Claude API (your API key, stored in the system keychain). Best quality for
  names, idioms and corporate tone; keeps your vocabulary spellings; asked to keep each line about
  as long as the original so the voiceover fits the same time slot.

Timestamps never change: line i of the translation belongs to line i of the transcript.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

LANG_NAMES = {
    "en": "English", "hi": "Hindi", "bn": "Bengali", "ta": "Tamil", "te": "Telugu", "mr": "Marathi",
    "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam", "pa": "Punjabi", "ur": "Urdu", "es": "Spanish",
    "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese", "ar": "Arabic", "ja": "Japanese",
    "zh": "Chinese (Simplified)", "ru": "Russian", "id": "Indonesian", "ko": "Korean", "tr": "Turkish",
    "nl": "Dutch", "he": "Hebrew",
}
ARGOS_INDEX = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
CLAUDE_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODELS = {"claude-sonnet-5-5": "Claude Sonnet 5.5 (recommended)", "claude-opus-5-5": "Claude Opus 5.5 (highest quality)",
                 "claude-haiku-5-5": "Claude Haiku 5.5 (fastest, cheapest)"}
KEYRING_SERVICE = "VERBATIM-Claude"


# ====================================================================== API key
def get_claude_key() -> str:
    import os

    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, "api_key") or ""
    except Exception:
        return ""


def set_claude_key(key: str):
    import keyring

    keyring.set_password(KEYRING_SERVICE, "api_key", key.strip())


# ====================================================================== helpers
def glossary_from_vocabulary(vocab_text: str) -> tuple[list[str], dict[str, str]]:
    """Vocabulary terms (kept as written) and 'source => target' rules."""
    keep, rules = [], {}
    for line in (vocab_text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=>" in line:
            a, b = (x.strip() for x in line.split("=>", 1))
            if a and b:
                rules[a] = b
        else:
            keep.append(line)
    return keep, rules


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield i, items[i:i + size]


STYLES = {
    "faithful": "Translate closely and precisely (corporate, legal, training content): keep every point, no embellishment.",
    "natural": "Translate the way a native speaker would naturally say it in a professional voiceover: idiomatic, warm, "
               "clear; not word-for-word.",
    "creative": "Transcreate (brand films and ads): recreate the emotional effect, rhythm and imagery for native "
                "listeners; you may change wording and images, but keep the message, the brand and the length.",
}
LANG_GUIDES = {
    "hi": "Hindi: everyday spoken Hindi as heard in good Indian advertising and corporate films; avoid heavy Sanskritised "
          "words; common English business terms may stay in English but written in Devanagari; use आप.",
    "bn": "Bengali: standard colloquial Bengali (চলিত ভাষা) in Bengali script.",
    "ta": "Tamil: modern spoken-standard Tamil in Tamil script.", "te": "Telugu: modern standard Telugu in Telugu script.",
    "mr": "Marathi: modern standard Marathi in Devanagari.", "ur": "Urdu: natural Urdu in Nastaliq/Arabic script.",
    "he": "Hebrew: modern Israeli Hebrew, without niqqud, natural gender agreement; right-to-left script.",
    "ar": "Arabic: Modern Standard Arabic suitable for voiceover, without diacritics unless needed.",
    "ja": "Japanese: natural polite form (です／ます) suited to narration; avoid stiff literal phrasing.",
    "zh": "Chinese: Simplified Chinese, natural Mainland Mandarin phrasing.",
    "ru": "Russian: natural modern Russian, formal 'вы' where addressing viewers.",
    "es": "Spanish: neutral international Spanish (no regional slang), 'usted' for formal address.",
    "fr": "French: natural modern French, 'vous' for viewers; correct French typography (space before : ; ? !).",
    "de": "German: natural modern German, 'Sie' for viewers.",
}


def claude_system(src: str, tgt: str, vocabulary: str = "", style: str = "natural") -> str:
    S, T = LANG_NAMES.get(src, src), LANG_NAMES.get(tgt, tgt)
    keep, rules = glossary_from_vocabulary(vocabulary)
    gl = ""
    if keep:
        gl += "Keep these names/terms exactly as written (do not translate or transliterate): " + "; ".join(keep[:200]) + "\n"
    if rules:
        gl += "Use these fixed translations/spellings: " + "; ".join(f"{a} → {b}" for a, b in list(rules.items())[:200]) + "\n"
    return (f"You are an award-winning {T} dubbing and subtitle writer working for a creative video agency in India. "
            f"Translate numbered lines from {S} into {T} for a voiceover. {STYLES.get(style, STYLES['natural'])} "
            f"{LANG_GUIDES.get(tgt, '')} Rules: translate every line separately and keep the numbering; never merge, split, "
            f"drop or add lines; each line must take about as long to speak as the original (same time slot); keep brand, "
            f"product and people's names unless a fixed translation is given; write numbers, dates and currencies the way "
            f"a voice artist would read them aloud; no notes or explanations. "
            f"Reply with JSON only: an array of objects {{\"n\": <line number>, \"t\": \"<translation>\"}}.\n" + gl)


# ====================================================================== Claude
class ClaudeTranslator:
    name = "claude"

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-5-5", timeout: int = 120):
        self.key = api_key or get_claude_key()
        if not self.key:
            raise RuntimeError("Add your Claude API key first (Settings › Cloud engines).")
        self.model = model
        self.timeout = timeout
        self.usage = {"input_tokens": 0, "output_tokens": 0}

    def _call(self, system: str, user: str) -> str:
        body = json.dumps({"model": self.model, "max_tokens": 8000, "temperature": 0,
                           "system": system, "messages": [{"role": "user", "content": user}]}).encode()
        req = urllib.request.Request(CLAUDE_URL, data=body, method="POST", headers={
            "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        last = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read())
                u = data.get("usage", {})
                self.usage["input_tokens"] += u.get("input_tokens", 0)
                self.usage["output_tokens"] += u.get("output_tokens", 0)
                return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")[:300]
                if e.code in (401, 403):
                    raise RuntimeError("Claude API key was rejected — check it in Settings.") from e
                if e.code in (429, 500, 502, 503, 529):
                    last = RuntimeError(f"Claude API busy ({e.code})")
                    time.sleep(min(30, 2 ** attempt * 2))
                    continue
                raise RuntimeError(f"Claude API error {e.code}: {msg}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                last = e
                time.sleep(min(30, 2 ** attempt * 2))
        raise RuntimeError(f"Could not reach the Claude API: {last}")

    def translate(self, lines: list[str], src: str, tgt: str, vocabulary: str = "", context: str = "",
                  speakers: list[str] | None = None, progress=None, style: str = "natural",
                  polish: bool = True) -> list[str]:
        system = claude_system(src, tgt, vocabulary, style)
        doc = "\n".join(x.strip() for x in lines if x.strip())
        if len(doc) > 24000:
            doc = doc[:24000] + " …"
        out = [""] * len(lines)
        total = max(1, len(lines))
        steps = 2 if polish else 1
        for start, part in _chunks(lines, 40):
            numbered = "\n".join(f"{start + k + 1}. {(speakers[start + k] + ': ') if speakers and speakers[start + k] else ''}"
                                 f"{t.strip()}" for k, t in enumerate(part))
            user = ((f"Video: {context}\n" if context else "") +
                    f"The whole script, for context and consistent terminology:\n<script>\n{doc}\n</script>\n\n"
                    f"Translate these lines (speaker labels are for context only — do not translate or include them):\n"
                    f"{numbered}")
            got = self._parse(self._call(system, user))
            missing = [start + k + 1 for k in range(len(part)) if (start + k + 1) not in got]
            for n in missing:  # one retry per dropped line
                got.update(self._parse(self._call(system, f"Translate this line:\n{n}. {lines[n - 1].strip()}")))
            for k in range(len(part)):
                out[start + k] = got.get(start + k + 1, "").strip()
            if progress:
                progress(min(1.0, (start + len(part)) / total) / steps,
                         f"Translating with Claude: {start + len(part)} of {total} lines")
        if polish and any(out):
            out = self.polish(lines, out, src, tgt, vocabulary, style, progress)
        return out

    def polish(self, src_lines, tgt_lines, src, tgt, vocabulary="", style="natural", progress=None) -> list[str]:
        """Second pass by a native-speaker 'voice director': fix anything stiff, literal or inconsistent."""
        T = LANG_NAMES.get(tgt, tgt)
        system = (claude_system(src, tgt, vocabulary, style) +
                  f"\nYou are now the native {T} voice director reviewing a draft translation before recording. "
                  f"For each numbered line, return the final line: keep it if it already sounds like a native {T} speaker "
                  f"talking naturally; otherwise rewrite it so it does — idiomatic, not literal, consistent terms across "
                  f"lines, same meaning, about the same spoken length. Same JSON format.")
        out = list(tgt_lines)
        total = max(1, len(src_lines))
        for start, part in _chunks(list(range(len(src_lines))), 40):
            body = "\n".join(f"{i + 1}. SOURCE: {src_lines[i].strip()}\n   DRAFT: {tgt_lines[i].strip()}" for i in part
                             if tgt_lines[i].strip())
            if not body:
                continue
            got = self._parse(self._call(system, "Review and return the final lines:\n" + body))
            for i in part:
                if got.get(i + 1, "").strip():
                    out[i] = got[i + 1].strip()
            if progress:
                progress(0.5 + 0.5 * min(1.0, (start + len(part)) / total),
                         f"Native-speaker polish: {start + len(part)} of {total} lines")
        return out

    def shorten(self, items: list[tuple[int, str, str, int]], src: str, tgt: str, vocabulary: str = "") -> dict[int, str]:
        """items: (line number, source, current translation, target length in characters) -> shorter lines."""
        if not items:
            return {}
        T = LANG_NAMES.get(tgt, tgt)
        system = (claude_system(src, tgt, vocabulary, "natural") +
                  f"\nThese {T} voiceover lines are too long for their time slot. Rewrite each so it is at most the "
                  f"given number of characters, keeping the essential meaning and a natural spoken tone (cut filler, use "
                  f"shorter synonyms, drop what the picture already shows). Same JSON format.")
        body = "\n".join(f"{n}. (max {limit} chars) SOURCE: {s.strip()} | CURRENT: {cur.strip()}" for n, s, cur, limit in items)
        return {n: v.strip() for n, v in self._parse(self._call(system, body)).items() if v.strip()}

    def back_translate(self, lines: list[str], src: str, tgt: str, progress=None) -> list[str]:
        """Literal translation back into the source language, so a reviewer can check the meaning."""
        system = (f"Translate each numbered {LANG_NAMES.get(tgt, tgt)} line literally into {LANG_NAMES.get(src, src)}, "
                  f"so a reviewer who does not speak {LANG_NAMES.get(tgt, tgt)} can check the meaning. Keep numbering. "
                  f"Reply with JSON only: an array of objects {{\"n\": <line number>, \"t\": \"<translation>\"}}.")
        out = [""] * len(lines)
        for start, part in _chunks(lines, 50):
            numbered = "\n".join(f"{start + k + 1}. {t.strip()}" for k, t in enumerate(part) if t.strip())
            if numbered:
                got = self._parse(self._call(system, numbered))
                for k in range(len(part)):
                    out[start + k] = got.get(start + k + 1, "").strip()
            if progress:
                progress(min(1.0, (start + len(part)) / max(1, len(lines))), "Meaning check")
        return out

    @staticmethod
    def _parse(text: str) -> dict[int, str]:
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            return {}
        try:
            arr = json.loads(m.group(0))
        except ValueError:
            return {}
        res = {}
        for o in arr:
            try:
                res[int(o["n"])] = str(o["t"])
            except (KeyError, TypeError, ValueError):
                continue
        return res


# ====================================================================== offline (Argos / OPUS-MT)
def _argos_root() -> Path:
    from .platform_info import models_dir

    return models_dir() / "translate"


def argos_index(timeout: int = 30) -> list[dict]:
    cache = _argos_root() / "index.json"
    try:
        req = urllib.request.Request(ARGOS_INDEX, headers={"User-Agent": "VERBATIM"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
    except Exception:
        if not cache.exists():
            raise
        data = cache.read_bytes()
    return json.loads(data)


def offline_route(src: str, tgt: str, index: list[dict] | None = None) -> list[tuple[str, str]]:
    """Language pairs to chain (direct, or via English). Empty if not available."""
    index = index if index is not None else argos_index()
    pairs = {(m["from_code"], m["to_code"]) for m in index}
    if (src, tgt) in pairs:
        return [(src, tgt)]
    if (src, "en") in pairs and ("en", tgt) in pairs:
        return [(src, "en"), ("en", tgt)]
    return []


def offline_targets(src: str, index: list[dict] | None = None) -> list[str]:
    index = index if index is not None else argos_index()
    return sorted({t for t in LANG_NAMES if t != src and offline_route(src, t, index)})


def ensure_pair(src: str, tgt: str, progress=None, index: list[dict] | None = None) -> Path:
    root = _argos_root() / f"{src}_{tgt}"
    if (root / "model").exists():
        return root
    index = index if index is not None else argos_index()
    m = next((m for m in index if m["from_code"] == src and m["to_code"] == tgt), None)
    if not m:
        raise RuntimeError(f"No offline model for {src}→{tgt}")
    url = next((u for u in m.get("links", []) if u.startswith("https://")), None)
    if not url:
        raise RuntimeError(f"No download link for {src}→{tgt}")
    from .download import fetch

    tmp = root.parent / f"{src}_{tgt}.argosmodel"
    root.parent.mkdir(parents=True, exist_ok=True)
    fetch(url, tmp, progress, f"translation model {src}→{tgt}")
    with zipfile.ZipFile(tmp) as z:
        for name in z.namelist():
            if name.startswith("/") or ".." in Path(name).parts:
                raise RuntimeError("Unsafe path in translation model")
        z.extractall(root.parent / f"{src}_{tgt}.tmp")
    inner = next(p for p in (root.parent / f"{src}_{tgt}.tmp").iterdir() if p.is_dir())
    inner.rename(root)
    import shutil

    shutil.rmtree(root.parent / f"{src}_{tgt}.tmp", ignore_errors=True)
    tmp.unlink(missing_ok=True)
    return root


_SENT = re.compile(r"(?<=[.!?।])\s+")


class OfflineTranslator:
    name = "offline"
    _cache: dict = {}

    def __init__(self, progress=None):
        self.progress = progress

    def _pair(self, src: str, tgt: str):
        key = (src, tgt)
        if key not in self._cache:
            import ctranslate2
            import sentencepiece as spm

            d = ensure_pair(src, tgt, self.progress)
            sp = spm.SentencePieceProcessor(model_file=str(d / "sentencepiece.model"))
            tr = ctranslate2.Translator(str(d / "model"), device="cpu", compute_type="int8")
            self._cache[key] = (sp, tr)
        return self._cache[key]

    def _translate_pair(self, lines: list[str], src: str, tgt: str) -> list[str]:
        sp, tr = self._pair(src, tgt)
        sents, owner = [], []
        for i, line in enumerate(lines):
            for s in _SENT.split(line.strip()) if line.strip() else []:
                sents.append(s)
                owner.append(i)
        out = [[] for _ in lines]
        for start, part in _chunks(sents, 32):
            toks = [sp.encode(s, out_type=str) for s in part]
            res = tr.translate_batch(toks, beam_size=4, max_decoding_length=256)
            for k, r in enumerate(res):
                out[owner[start + k]].append(sp.decode(r.hypotheses[0]).replace("▁", " ").strip())
        return [" ".join(x) for x in out]

    def translate(self, lines: list[str], src: str, tgt: str, vocabulary: str = "", context: str = "",
                  speakers: list[str] | None = None, progress=None, **_) -> list[str]:
        route = offline_route(src, tgt)
        if not route:
            raise RuntimeError(f"No offline translation for {LANG_NAMES.get(src, src)} → {LANG_NAMES.get(tgt, tgt)}. "
                               "Use the Claude engine for this language.")
        keep, rules = glossary_from_vocabulary(vocabulary)
        protected, cur = [], list(lines)
        for i, line in enumerate(cur):  # protect names: swap for placeholders the model leaves alone
            ph = {}
            for j, term in enumerate(sorted(keep, key=len, reverse=True)):
                if term and term.lower() in line.lower():
                    tok = f"ZX{j}Q"
                    line = re.sub(re.escape(term), tok, line, flags=re.I)
                    ph[tok] = term
            cur[i] = line
            protected.append(ph)
        for k, (a, b) in enumerate(route):
            if progress:
                progress(k / len(route), f"Translating offline ({a}→{b})…")
            cur = self._translate_pair(cur, a, b)
        res = []
        for line, ph in zip(cur, protected):
            for tok, term in ph.items():
                line = re.sub(re.escape(tok), term, line, flags=re.I)
            for a, b in rules.items():
                line = line.replace(a, b)
            res.append(line)
        if progress:
            progress(1.0, "Translation done")
        return res


# ====================================================================== offline LLM (TranslateGemma)
GEMMA_CODES = {"zh": "zh-CN", "pt": "pt-BR"}


def gemma_prompt(text: str, src: str, tgt: str) -> str:
    """Google's published TranslateGemma prompt (Gemma chat format)."""
    S, T = LANG_NAMES.get(src, src), LANG_NAMES.get(tgt, tgt).split(" (")[0]
    sc, tc = GEMMA_CODES.get(src, src), GEMMA_CODES.get(tgt, tgt)
    return (f"<start_of_turn>user\nYou are a professional {S} ({sc}) to {T} ({tc}) translator. Your goal is to "
            f"accurately convey the meaning and nuances of the original {S} text while adhering to {T} grammar, "
            f"vocabulary, and cultural sensitivities.\nProduce only the {T} translation, without any additional "
            f"explanations or commentary. Please translate the following {S} text into {T}:\n\n\n"
            f"{text.strip()}<end_of_turn>\n<start_of_turn>model\n")


class GemmaTranslator:
    """Offline, private, 55 languages: Google TranslateGemma run by llama.cpp on this computer."""
    name = "translategemma"

    def __init__(self, size: str = "translategemma-4b", progress=None):
        self.model = size
        self.progress = progress

    def _protect(self, lines, vocabulary):
        keep, rules = glossary_from_vocabulary(vocabulary)
        prot, maps = [], []
        for line in lines:
            ph = {}
            for j, term in enumerate(sorted(keep, key=len, reverse=True)):
                if term and term.lower() in line.lower():
                    tok = f"[{j}]"
                    line = re.sub(re.escape(term), tok, line, flags=re.I)
                    ph[tok] = term
            prot.append(line)
            maps.append(ph)
        return prot, maps, rules

    @staticmethod
    def _restore(text, ph, rules):
        for tok, term in ph.items():
            text = text.replace(tok, term)
        for a, b in rules.items():
            text = text.replace(a, b)
        return text.strip().strip('"').strip()

    def _run(self, lines, src, tgt, label, progress):
        from . import llm

        server = llm.ensure_server(self.progress)
        model = llm.ensure_model(self.model, self.progress)
        out = []
        if progress:
            progress(0.0, "Starting the offline translator…")
        with llm.LlamaServer(model, server) as srv:
            for k, line in enumerate(lines):
                out.append(srv.complete(gemma_prompt(line, src, tgt)) if line.strip() else "")
                if progress:
                    progress((k + 1) / max(1, len(lines)), f"{label}: {k + 1} of {len(lines)} lines")
        return out

    def translate(self, lines: list[str], src: str, tgt: str, vocabulary: str = "", context: str = "",
                  speakers: list[str] | None = None, progress=None, style: str = "natural", polish: bool = False):
        prot, maps, rules = self._protect(lines, vocabulary)
        raw = self._run(prot, src, tgt, "Translating offline (TranslateGemma)", progress)
        return [self._restore(t, ph, rules) for t, ph in zip(raw, maps)]

    def back_translate(self, lines: list[str], src: str, tgt: str, progress=None) -> list[str]:
        return [t.strip() for t in self._run(lines, tgt, src, "Meaning check", progress)]


def build(engine: str, model: str = "claude-sonnet-5-5", progress=None):
    if engine == "translategemma":
        return GemmaTranslator(model or "translategemma-4b", progress)
    if engine == "opus":
        return OfflineTranslator(progress)
    return ClaudeTranslator(model=model) if engine == "claude" else GemmaTranslator("translategemma-4b", progress)

