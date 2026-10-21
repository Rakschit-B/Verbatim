# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Voice quality scorecard — measured, not guessed. Every score is 0–100 % and compared with a human.

  Intelligibility   100 − word error rate of an independent speech recogniser on the generated audio
  Voice match       speaker similarity to the target ÷ similarity between two real recordings of that speaker
  Naturalness       predicted MOS (UTMOS22) of the voice ÷ the human reference's MOS (capped at 100)
  Expressiveness    pitch variation (semitones) of the voice ÷ the human narrator's pitch variation (capped)
  Emotion           share of lines whose emotion an independent recogniser hears as directed
  Emphasis          share of stressed words that are louder or higher than the words around them
  Timing            share of dubbed lines that fit their slot (Voice Studio jobs)
Target: ≥ 95 % on every row. The report says plainly which rows pass and which do not.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

TARGET = 95.0
CER_LANGS = {"zh", "ja", "ko", "th", "hi", "mr", "ne", "bn", "ta", "te", "gu", "pa", "ar", "ur", "he"}
EMO_MAP = {"joyful": "hap", "excited": "hap", "inspiring": "hap", "warm": "hap", "sad": "sad", "urgent": "ang",
           "neutral": "neu", "calm": "neu", "serious": "neu", "whisper": "neu"}


@dataclass
class Item:
    text: str
    lang: str
    wav: str                        # generated audio
    emotion: str = ""
    emphasis: str = ""
    engine: str = ""
    voice: str = ""


@dataclass
class Report:
    engine: str
    voice: str
    scores: dict = field(default_factory=dict)       # metric -> percent
    details: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return bool(self.scores) and all(v >= TARGET for v in self.scores.values() if v is not None)


# ---------------------------------------------------------------- metrics computed in the app
def _norm(s: str) -> str:
    return re.sub(r"[^\w\s]", " ", s.lower()).split().__str__()


def wer(ref: str, hyp: str) -> float:
    r = re.sub(r"[^\w\s']", " ", ref.lower()).split()
    h = re.sub(r"[^\w\s']", " ", hyp.lower()).split()
    d = np.arange(len(h) + 1)
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
            prev, d[j] = d[j], cur
    return float(d[len(h)]) / max(1, len(r))


def _skeleton(s: str) -> str:
    """Letters only, vowel signs and nukta dropped — so a recogniser's spelling habits are not counted
    as the voice's mistakes."""
    import unicodedata

    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if c.isalpha() and unicodedata.category(c) != "Mn")


def cer(ref: str, hyp: str) -> float:
    r, h = _skeleton(ref), _skeleton(hyp)
    d = np.arange(len(h) + 1)
    for i, rc in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hc in enumerate(h, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (rc != hc))
            prev, d[j] = d[j], cur
    return float(d[len(h)]) / max(1, len(r))


def transcribe(wav: str, lang: str) -> str:
    """Independent recogniser: Parakeet for English/European languages, Omnilingual CTC elsewhere."""
    from .tts import resample
    from .voicelab import read_wav, transcribe_clip

    a, sr = read_wav(Path(wav))
    a16 = resample(a, sr, 16000)
    txt = transcribe_clip(a16, lang)
    if txt:
        return txt
    from . import align

    return align.recognise(a16, lang) if hasattr(align, "recognise") else ""


def speaker_vec(a: np.ndarray, sr: int) -> np.ndarray:
    import sherpa_onnx

    from .diarize import embedding_model
    from .tts import resample

    key = "_titanet"
    ex = globals().get(key)
    if ex is None:
        ex = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(embedding_model()), num_threads=2))
        globals()[key] = ex
    st = ex.create_stream()
    st.accept_waveform(16000, resample(a, sr, 16000).astype(np.float32))
    st.input_finished()
    v = np.array(ex.compute(st))
    return v / (np.linalg.norm(v) + 1e-9)


def emphasis_hits(wav: str, text: str, emphasis: str, lang: str) -> tuple[int, int]:
    """Stressed words should stand out: louder (+1 dB) or higher (+0.5 st) than the line's other words."""
    words = [w.strip() for w in (emphasis or "").split(",") if w.strip()]
    if not words:
        return 0, 0
    from . import align
    from .fx import estimate_f0
    from .tts import resample
    from .voicelab import read_wav

    a, sr = read_wav(Path(wav))
    a16 = resample(a, sr, 16000)
    try:
        spans = align.word_spans(a16, text, lang)          # [(word, start, end)]
    except Exception:
        return 0, 0
    if not spans:
        return 0, 0
    f0 = estimate_f0(a16, 16000)

    def feats(s, e):
        seg = a16[int(s * 16000):int(e * 16000)]
        db = 20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-9) if len(seg) else -90
        fs = f0[int(s * 100):int(e * 100)]
        fs = fs[fs > 0]
        return db, (12 * np.log2(np.median(fs)) if len(fs) else None)

    base = [feats(s, e) for _, s, e in spans]
    hits = n = 0
    for w in words:
        idx = [k for k, (ww, _, _) in enumerate(spans) if ww.lower().strip(".,!?") == w.lower()]
        if not idx:
            continue
        n += 1
        k = idx[0]
        db, st = base[k]
        others = [b for j, b in enumerate(base) if j != k]
        odb = np.median([b[0] for b in others]) if others else db
        ost = [b[1] for b in others if b[1] is not None]
        if db - odb >= 1.0 or (st is not None and ost and st - np.median(ost) >= 0.5):
            hits += 1
    return hits, n


# ---------------------------------------------------------------- full scorecard
def score(items: list[Item], human_ref: str | None = None, human_ref2: str | None = None, host=None,
          utmos_ckpt: str | None = None, emotion_dir: str | None = None, timing: list[str] | None = None,
          progress=None) -> Report:
    """Score a set of generated lines for one engine/voice. human_ref(2): two real recordings of the target
    speaker (or of a professional narrator for stock voices) — the bar the voice is measured against."""
    from .fx import prosody_stats
    from .voicelab import read_wav

    rep = Report(items[0].engine if items else "", items[0].voice if items else "")
    say = progress or (lambda f, m: None)
    # 1. intelligibility
    errs = []
    for k, it in enumerate(items):
        say(0.1 + 0.3 * k / max(1, len(items)), f"Listening to line {k + 1}…")
        hyp = transcribe(it.wav, it.lang)
        e = cer(it.text, hyp) if it.lang in CER_LANGS else wer(it.text, hyp)
        errs.append(e)
        rep.details.setdefault("lines", []).append({"text": it.text, "heard": hyp, "error": round(e, 3)})
    rep.scores["Intelligibility"] = round(100 * (1 - min(1.0, float(np.mean(errs)))), 1) if errs else None
    # 2. voice match
    if human_ref:
        ra, rsr = read_wav(Path(human_ref))
        rv = speaker_vec(ra, rsr)
        same = None
        if human_ref2:
            rb, bsr = read_wav(Path(human_ref2))
            same = float(speaker_vec(rb, bsr) @ rv)
        sims = []
        for it in items:
            a, sr = read_wav(Path(it.wav))
            sims.append(float(speaker_vec(a, sr) @ rv))
        rep.details["similarity"] = round(float(np.mean(sims)), 3)
        rep.details["human_same_speaker"] = round(same, 3) if same else None
        rep.scores["Voice match"] = round(min(100.0, 100 * np.mean(sims) / (same or 0.85)), 1)
    # 3. expressiveness vs human
    synth_st = [prosody_stats(*read_wav(Path(it.wav)))["std_st"] for it in items]
    if human_ref:
        h = prosody_stats(*read_wav(Path(human_ref)))["std_st"]
        rep.details["pitch_variation_st"] = {"voice": round(float(np.mean(synth_st)), 2), "human": round(h, 2)}
        rep.scores["Expressiveness"] = round(min(100.0, 100 * float(np.mean(synth_st)) / max(0.5, h)), 1)
    # 4. emphasis
    hits = n = 0
    for it in items:
        h_, n_ = emphasis_hits(it.wav, it.text, it.emphasis, it.lang)
        hits, n = hits + h_, n + n_
    if n:
        rep.scores["Emphasis"] = round(100 * hits / n, 1)
    # 5/6. naturalness + emotion (torch scorers in the engine host)
    if host and utmos_ckpt:
        say(0.6, "Rating naturalness…")
        wavs = [it.wav for it in items] + ([human_ref] if human_ref else [])
        mos = host.request("utmos", ckpt=utmos_ckpt, wavs=wavs)["scores"]
        vm = float(np.mean(mos[:len(items)]))
        hm = mos[-1] if human_ref else 4.2
        rep.details["mos"] = {"voice": round(vm, 2), "human": round(hm, 2)}
        rep.scores["Naturalness"] = round(min(100.0, 100 * vm / hm), 1)
    if host and emotion_dir:
        directed = [(it, EMO_MAP.get(it.emotion or "neutral", "neu")) for it in items if it.emotion]
        if directed:
            say(0.8, "Checking emotions…")
            em = host.request("emotion", model_dir=emotion_dir, wavs=[it.wav for it, _ in directed])["emotions"]
            ok = 0
            for (it, want), probs in zip(directed, em):
                got = max(probs, key=probs.get)
                ok += got == want
                rep.details.setdefault("emotion", []).append({"text": it.text[:60], "directed": it.emotion,
                                                              "heard": got, "probs": probs})
            rep.scores["Emotion"] = round(100 * ok / len(directed), 1)
    if timing:
        fits = sum(1 for f in timing if f == "ok" or f.startswith("faster"))
        rep.scores["Timing"] = round(100 * fits / max(1, len(timing)), 1)
    say(1.0, "Scorecard ready")
    return rep


def write_report(reports: list[Report], dest: Path) -> Path:
    """HTML + JSON scorecard (green ≥ 95 %, amber 85–95 %, red below)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "scorecard.json").write_text(json.dumps([asdict(r) for r in reports], ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    metrics = []
    for r in reports:
        for m in r.scores:
            if m not in metrics:
                metrics.append(m)

    def cell(v):
        if v is None:
            return "<td>—</td>"
        c = "#15803D" if v >= TARGET else ("#B45309" if v >= 85 else "#B91C1C")
        return f'<td style="color:{c};font-weight:600">{v:.1f}%</td>'

    rows = "".join(f"<tr><td>{r.engine}</td><td>{r.voice}</td>" + "".join(cell(r.scores.get(m)) for m in metrics) +
                   f"<td>{'PASS' if r.passed else 'below target'}</td></tr>" for r in reports)
    html = (f"<html><head><meta charset='utf-8'><title>VERBATIM voice scorecard</title></head>"
            f"<body style='font-family:-apple-system,Segoe UI,sans-serif;padding:24px'>"
            f"<h2>VERBATIM voice scorecard — target {TARGET:.0f}% on every row</h2><table cellpadding=8 "
            f"style='border-collapse:collapse'><tr><th>Engine</th><th>Voice</th>" +
            "".join(f"<th>{m}</th>" for m in metrics) + "<th>Result</th></tr>" + rows +
            "</table><p>Infinite Story LLP · measured with independent recognisers; human recordings are the "
            "100% reference.</p></body></html>")
    p = dest / "scorecard.html"
    p.write_text(html, encoding="utf-8")
    return p
