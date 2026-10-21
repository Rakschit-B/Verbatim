# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Performance direction — how each line should be *performed*, not just what it says.

A human voice artist reads a script with intent: an emotion, how strongly to play it, which words to
lean on, where to breathe. VERBATIM stores that per line (Line.emotion / .intensity / .emphasis) and
every voice engine turns it into its own controls:

  • Chatterbox (local)   → emotion "exaggeration" + sampling temperature, emotion-matched reference clip
  • ElevenLabs (cloud)   → inline audio tags ([warmly], [excited], [whispers]…), CAPS on emphasised
                           words, stability lowered for more expressive takes
  • Azure Neural (cloud) → SSML <mstts:express-as style=… styledegree=…>, <emphasis>, <prosody> pitch
  • all engines          → pauses from punctuation (commas, ellipses) and a pace nudge per emotion

Direction comes from the "Direct the performance" button: Claude reads the whole script and marks
each line (best), or the built-in rules mark it from punctuation and wording (offline, instant).
The director never changes the words.
"""
from __future__ import annotations

import json
import re

# emotion -> label, chatterbox exaggeration, pace ×, ElevenLabs tag, Azure style
EMOTIONS: dict[str, dict] = {
    "neutral":   {"label": "Neutral",   "ex": 0.45, "pace": 1.00, "tag": "",              "az": "", "range": 1.00},
    "warm":      {"label": "Warm",      "ex": 0.55, "pace": 0.97, "tag": "[warmly]",      "az": "friendly", "range": 1.08},
    "inspiring": {"label": "Inspiring", "ex": 0.65, "pace": 0.95, "tag": "[hopeful]",     "az": "hopeful", "range": 1.18},
    "calm":      {"label": "Calm",      "ex": 0.35, "pace": 0.93, "tag": "[calmly]",      "az": "gentle", "range": 0.9},
    "joyful":    {"label": "Joyful",    "ex": 0.75, "pace": 1.03, "tag": "[happily]",     "az": "cheerful", "range": 1.25},
    "excited":   {"label": "Excited",   "ex": 0.85, "pace": 1.06, "tag": "[excited]",     "az": "excited", "range": 1.35},
    "serious":   {"label": "Serious",   "ex": 0.40, "pace": 0.97, "tag": "[seriously]",   "az": "serious", "range": 0.92},
    "sad":       {"label": "Sad",       "ex": 0.55, "pace": 0.92, "tag": "[sorrowful]",   "az": "sad", "range": 0.85},
    "urgent":    {"label": "Urgent",    "ex": 0.80, "pace": 1.08, "tag": "[urgently]",    "az": "excited", "range": 1.2},
    "whisper":   {"label": "Whisper",   "ex": 0.30, "pace": 0.92, "tag": "[whispers]",    "az": "whispering", "range": 0.8},
}
ORDER = list(EMOTIONS)

_LEX = {
    "inspiring": r"\b(dream|believe|future|together|story|journey|possible|inspire|courage|hope|begin|freedom|rise|"
                 r"legacy|meaningful|belong|change|grow|purpose|सपन|विश्वास|भविष्य|साथ|कहानी|उम्मीद|हिम्मत)",
    "joyful": r"\b(celebrat|happy|joy|smile|laugh|fun|delight|wonderful|love|खुश|जश्न|मुस्कान|प्यार)",
    "sad": r"\b(loss|lost|miss|alone|goodbye|grief|sorry|tears|pain|never again|अकेल|दुख|आंसू|याद)",
    "serious": r"\b(risk|safety|warning|important|must|responsib|compliance|security|danger|ज़रूरी|सुरक्षा|खतरा)",
    "urgent": r"\b(now|today only|hurry|limited|don't miss|last chance|अभी|जल्दी)",
    "calm": r"\b(quiet|still|calm|peace|gentle|slow|breathe|rest|restore|शांत|सुकून)",
    "warm": r"\b(home|family|friend|care|welcome|thank|familiar|warm|घर|परिवार|दोस्त|धन्यवाद)",
}
_STRESS = r"^(best|first|only|never|always|every|most|biggest|all|nothing|everything|more|real|true|own)$"


def info(emotion: str) -> dict:
    return EMOTIONS.get(emotion or "neutral", EMOTIONS["neutral"])


# ---------------------------------------------------------------- built-in rules (offline)
def auto_direct(texts: list[str]) -> list[dict]:
    """Rule-based direction from punctuation and wording. Returns [{emotion, intensity, emphasis}]."""
    out = []
    n = len(texts)
    for k, t in enumerate(texts):
        s = " ".join((t or "").split())
        low = s.lower()
        emo, inten = "neutral", 0.5
        scores = {e: len(re.findall(p, low)) for e, p in _LEX.items()}
        best = max(scores, key=scores.get) if scores else "neutral"
        if scores.get(best):
            emo, inten = best, min(0.9, 0.45 + 0.15 * scores[best])
        if s.endswith("!"):
            emo = "excited" if emo in ("neutral", "urgent") else ("joyful" if emo == "warm" else emo)
            inten = max(inten, 0.7)
        if len(s.split()) <= 3 and s.endswith((".", "…")) and emo == "neutral":
            emo, inten = "calm", 0.5          # short fragment: give it room
        if k == n - 1 and n > 2 and emo in ("neutral", "warm"):
            emo, inten = "inspiring", max(inten, 0.6)   # closing line lands
        out.append({"emotion": emo, "intensity": round(inten, 2), "emphasis": ", ".join(stress_words(s))})
    return out


def stress_words(s: str) -> list[str]:
    words = re.findall(r"[\w'’-]+", s)
    out = []
    for i, w in enumerate(words):
        if (len(w) > 1 and w.isupper() and w.isalpha()) or re.match(_STRESS, w.lower()) or \
                (i > 0 and w[:1].isupper() and w.lower() not in ("i", "i'm")) or re.match(r"^\d[\d,.%]*$", w):
            if w not in out:
                out.append(w)
    return out[:3]


# ---------------------------------------------------------------- Claude as the director
DIRECTOR_SYSTEM = """You are an award-winning voice director preparing a script for a voice artist.
For every numbered line decide how it should be PERFORMED. Do not change any words.
Return JSON only: {"lines": [{"n": 1, "emotion": "...", "intensity": 0.0-1.0, "emphasis": ["word", ...]}]}
emotion is one of: neutral, warm, inspiring, calm, joyful, excited, serious, sad, urgent, whisper.
intensity: 0.3 subtle · 0.5 natural · 0.8 strong. Read the whole script first and build an arc —
a brand film usually opens calm or warm, builds, and lands its final line with conviction.
emphasis: the 0–2 words (exactly as written in the line, any language) a skilled narrator would stress."""


def claude_direct(texts: list[str], lang: str, translator) -> list[dict]:
    """Ask Claude (translate.ClaudeTranslator) to direct the whole script at once."""
    from .translate import LANG_NAMES

    user = (f"Language: {LANG_NAMES.get(lang, lang)}\nScript:\n" +
            "\n".join(f"{i}. {t}" for i, t in enumerate(texts, 1)))
    raw = translator._call(DIRECTOR_SYSTEM, user)
    return parse_direction(raw, texts)


def parse_direction(raw: str, texts: list[str]) -> list[dict]:
    fallback = auto_direct(texts)
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        items = json.loads(m.group(0))["lines"] if m else []
    except (ValueError, KeyError, TypeError):
        items = []
    for it in items:
        try:
            k = int(it.get("n", 0)) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= k < len(texts):
            continue
        emo = str(it.get("emotion", "neutral")).lower().strip()
        emp = it.get("emphasis") or []
        if isinstance(emp, str):
            emp = [x.strip() for x in emp.split(",")]
        emp = [w for w in emp if w and w.lower() in texts[k].lower()][:3]
        try:
            inten = float(it.get("intensity", 0.5))
        except (TypeError, ValueError):
            inten = 0.5
        fallback[k] = {"emotion": emo if emo in EMOTIONS else "neutral",
                       "intensity": round(max(0.0, min(1.0, inten)), 2), "emphasis": ", ".join(emp)}
    return fallback


# ---------------------------------------------------------------- engine renderings
def emphasis_list(emphasis: str) -> list[str]:
    return [w.strip() for w in (emphasis or "").split(",") if w.strip()]


def eleven_text(text: str, emotion: str, intensity: float, emphasis: str) -> str:
    """ElevenLabs v3/v4: an audio tag up front, CAPS on stressed words (their documented emphasis cue)."""
    t = text
    for w in emphasis_list(emphasis):
        if w.isascii():   # capitals only mean something in Latin script
            t = re.sub(rf"(?<!\w){re.escape(w)}(?!\w)", w.upper(), t, count=1)
    tag = info(emotion)["tag"]
    if tag and intensity >= 0.75 and emotion not in ("whisper",):
        tag = tag[:-1] + ", strongly]" if emotion in ("serious", "urgent") else tag
    return f"{tag} {t}".strip() if tag else t


def eleven_settings(emotion: str, intensity: float, base_stability: float = 0.5) -> dict:
    """Lower stability = more expressive (ElevenLabs guidance); v3 accepts 0.0 / 0.5 / 1.0 only."""
    expressive = emotion not in ("neutral", "serious", "calm")
    stab = 0.0 if expressive and intensity >= 0.7 else (0.5 if expressive or intensity >= 0.4 else 1.0)
    return {"stability": stab, "similarity_boost": 0.8, "style": round(min(1.0, intensity * 0.6), 2),
            "use_speaker_boost": True}


def azure_ssml(text: str, voice: str, lang_tag: str, emotion: str, intensity: float, emphasis: str,
               rate: float = 1.0) -> str:
    """Azure Neural TTS SSML: speaking style + degree, emphasised words, pace, gentle pitch lift."""
    from xml.sax.saxutils import escape

    body = escape(text)
    for w in emphasis_list(emphasis):
        ew = escape(w)
        body = re.sub(rf"(?<![\w>]){re.escape(ew)}(?!\w)", f'<emphasis level="moderate">{ew}</emphasis>', body, count=1)
    pitch = {"excited": "+6%", "joyful": "+5%", "inspiring": "+3%", "urgent": "+4%", "sad": "-4%",
             "calm": "-2%", "whisper": "-2%"}.get(emotion, "+0%")
    pct = f"{(rate - 1) * 100:+.0f}%"
    inner = f'<prosody rate="{pct}" pitch="{pitch}">{body}</prosody>'
    style = info(emotion)["az"]
    if style:
        deg = f"{max(0.5, min(2.0, 0.6 + intensity * 1.4)):.2f}"
        inner = f'<mstts:express-as style="{style}" styledegree="{deg}">{inner}</mstts:express-as>'
    return (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            f'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{lang_tag}">'
            f'<voice name="{voice}">{inner}</voice></speak>')


OMNI_TAGS = {"joyful": "[laughter]", "sad": "[sigh]"}


def omni_text(text: str, emotion: str, intensity: float) -> str:
    """OmniVoice: delivery comes from the voice reference; strong joy/sadness get a natural non-verbal cue."""
    t = shape_text(text, emotion)
    tag = OMNI_TAGS.get(emotion or "")
    if tag and intensity >= 0.8:
        t = f"{tag} {t}"
    return t


def shape_text(text: str, emotion: str) -> str:
    """Engine-neutral delivery cues: breathing room for calm/sad/inspiring lines."""
    t = " ".join((text or "").split())
    if emotion in ("calm", "sad", "inspiring", "whisper") and t and t[-1] not in ".!?…।。？！":
        t += "."
    return t
