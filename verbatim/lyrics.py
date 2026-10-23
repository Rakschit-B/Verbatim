# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Song sheets: sections, lyrics and who sings each part (male / female / duet / chorus), plus the lyric
writer — offline (Gemma 3 on this computer, via llama.cpp) or online (Claude)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

SECTIONS = ["Intro", "Verse", "Pre-Chorus", "Chorus", "Post-Chorus", "Bridge", "Hook", "Rap", "Breakdown",
            "Instrumental", "Outro"]
SINGERS = {          # key: (label, ACE-Step caption words, voices layered when casting)
    "male": ("Male", "male lead vocal", 1),
    "female": ("Female", "female lead vocal", 1),
    "duet": ("Duet (male + female)", "male and female duet vocals in harmony", 2),
    "chorus3": ("Chorus · 3 singers", "small group of three singers in harmony", 3),
    "chorus6": ("Chorus · 6 singers", "group chorus of six singers", 6),
    "choir": ("Choir · 12+", "big choir, gang vocals", 12),
    "none": ("Instrumental", "instrumental", 0),
}
WRITER_MODEL = "gemma-3-4b"


@dataclass
class Part:
    section: str = "Verse"
    singer: str = "male"
    lines: list = field(default_factory=list)


@dataclass
class Sheet:
    title: str = ""
    language: str = "en"
    parts: list = field(default_factory=list)

    def to_ace(self) -> str:
        """Lyrics in ACE-Step's tagged format, with the singer named in each section tag."""
        out, n = [], {}
        for p in self.parts:
            n[p.section] = n.get(p.section, 0) + 1
            num = f" {n[p.section]}" if p.section in ("Verse", "Pre-Chorus", "Bridge", "Rap") else ""
            who = SINGERS.get(p.singer, SINGERS["male"])[0].split(" ·")[0].split(" (")[0].lower()
            tag = f"[{p.section}{num}]" if p.singer == "none" else f"[{p.section}{num} - {who}]"
            out.append(tag)
            out += [ln for ln in p.lines if ln.strip()]
            out.append("")
        return "\n".join(out).strip()

    def casting_caption(self) -> str:
        used = []
        for p in self.parts:
            if p.lines and p.singer not in used and p.singer != "none":
                used.append(p.singer)
        words = [SINGERS[s][1] for s in used]
        if not words:
            return "instrumental"
        if len(words) == 1:
            return words[0]
        return ", ".join(words[:-1]) + " and " + words[-1]

    def to_text(self) -> str:
        return "\n\n".join(f"[{p.section} | {SINGERS.get(p.singer, SINGERS['male'])[0]}]\n" + "\n".join(p.lines)
                           for p in self.parts)

    def as_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Sheet":
        return Sheet(d.get("title", ""), d.get("language", "en"),
                     [Part(**{k: v for k, v in x.items() if k in Part.__dataclass_fields__}) for x in d.get("parts", [])])


_SINGER_WORDS = [("choir", "choir"), ("chorus 6", "chorus6"), ("six", "chorus6"), ("chorus 3", "chorus3"),
                 ("three", "chorus3"), ("group", "chorus6"), ("chorus", "chorus3"), ("duet", "duet"),
                 ("both", "duet"), ("female", "female"), ("woman", "female"), ("girl", "female"), ("male", "male"),
                 ("man", "male"), ("boy", "male"), ("instrumental", "none")]


def _singer(text: str, default: str) -> str:
    t = text.lower()
    for w, k in _SINGER_WORDS:
        if w in t:
            return k
    return default


def parse(text: str, default_singer: str = "male") -> list[Part]:
    """'[Chorus | Duet]' / '[Verse 1 - female]' / '[Bridge]' headers + lines → parts."""
    parts: list[Part] = []
    cur = None
    for raw in text.splitlines():
        line = raw.strip().strip("*").strip()
        m = re.match(r"^\[(.+?)\]$|^#+\s*(.+)$|^\(?(intro|verse|pre-chorus|chorus|bridge|hook|outro|rap)\b.*\)?:?$",
                     line, re.I)
        if m:
            head = (m.group(1) or m.group(2) or line).strip()
            name = re.split(r"[|\-–:(]", head)[0].strip()
            name = re.sub(r"\s*\d+$", "", name).strip().title().replace("Pre-chorus", "Pre-Chorus")
            if name.lower() not in [s.lower() for s in SECTIONS]:
                name = "Chorus" if "chorus" in name.lower() else "Verse"
            rest = head[len(re.split(r"[|\-–:(]", head)[0]):]
            sing = _singer(rest, "female" if name == "Bridge" and default_singer == "male" else default_singer)
            if name == "Chorus" and not rest.strip():
                sing = "duet"
            cur = Part(name, sing, [])
            parts.append(cur)
            continue
        if not line:
            continue
        if cur is None:
            cur = Part("Verse", default_singer, [])
            parts.append(cur)
        cur.lines.append(line)
    return parts


def default_plan() -> list[tuple[str, str]]:
    return [("Intro", "none"), ("Verse", "male"), ("Pre-Chorus", "female"), ("Chorus", "duet"),
            ("Verse", "female"), ("Chorus", "chorus3"), ("Bridge", "male"), ("Chorus", "choir"), ("Outro", "duet")]


def _prompt(brief: str, language: str, plan: list[tuple[str, str]], mood: str) -> str:
    from .translate import LANG_NAMES

    lang = LANG_NAMES.get(language, language)
    plan_txt = "\n".join(f"[{s} | {SINGERS[g][0]}]" for s, g in plan)
    return (f"Write original song lyrics in {lang}.\nBrief: {brief}\nMood/genre: {mood or 'as the brief suggests'}\n\n"
            "Rules: singable lines of 6–10 syllables, natural rhyme, a memorable chorus that repeats, concrete images, "
            "no clichés like 'fire' and 'desire', no artist names. Keep this exact section order and singer in each "
            "header, write 2–4 lines per section (Intro/Outro may be 0–2), and output ONLY the lyrics with the "
            f"headers, nothing else:\n\n{plan_txt}")


def write(brief: str, language: str = "en", plan: list[tuple[str, str]] | None = None, mood: str = "",
          engine: str = "offline", progress=None, seed: int = -1) -> list[Part]:
    plan = plan or default_plan()
    prompt = _prompt(brief, language, plan, mood)
    say = progress or (lambda f, m: None)
    if engine == "claude":
        from .translate import ClaudeTranslator

        say(0.2, "Claude is writing the lyrics…")
        text = ClaudeTranslator()._call("You are an award-winning lyricist for Indian and international pop, film and "
                                        "advertising music. You write original lyrics only.", prompt, temperature=0.9)
    else:
        from . import llm

        say(0.05, "Preparing the offline lyric writer (Gemma 3, one-time download)…")
        server = llm.ensure_server(say)
        model = llm.ensure_model(WRITER_MODEL, say)
        say(0.5, "Writing lyrics on this computer…")
        with llm.LlamaServer(model, server, ctx=4096) as srv:
            text = srv.complete(f"<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\n", n_predict=900,
                                temperature=0.85, seed=seed)
    parts = parse(text)
    # keep the user's singer plan even if the model drifted
    for p, (s, g) in zip(parts, plan):
        p.singer = g
    say(1.0, "Lyrics ready.")
    return parts
