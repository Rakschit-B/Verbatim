"""Two-engine cross-check (inspired by ROVER system combination).

Two independent models rarely make the *same* mistake. Aligning the primary transcript
with a second engine's output gives:
  * an agreement rate per file (a practical accuracy proxy with no reference needed),
  * the exact places they disagree, which go to the Review Queue with both readings,
  * optional fusion: a word the primary engine itself was unsure of is replaced by
    the secondary reading only when the secondary engine is highly confident.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from .accuracy import normalize
from .model import Transcript, Word


def _norm_tokens(words: list[Word]) -> list[tuple[str, int]]:
    """Normalised tokens with a back-pointer to the source word index."""
    out = []
    for idx, w in enumerate(words):
        for tok in normalize(w.text, drop_fillers=True):
            out.append((tok, idx))
    return out


def cross_check(primary: Transcript, secondary: Transcript, fuse: bool = False,
                primary_max_prob: float = 0.45, secondary_min_prob: float = 0.90) -> dict:
    pw = primary.words()
    sw = secondary.words()
    pt, st = _norm_tokens(pw), _norm_tokens(sw)
    a, b = [t for t, _ in pt], [t for t, _ in st]
    sm = SequenceMatcher(None, a, b, autojunk=False)
    matched = sum(bl.size for bl in sm.get_matching_blocks())
    agreement = matched / max(1, len(a))
    disagreements = []
    fused = 0
    seg_of = {}
    for seg in primary.segments:
        for w in seg.words:
            seg_of[id(w)] = seg
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        p_words = sorted({pt[k][1] for k in range(i1, i2)})
        s_words = sorted({st[k][1] for k in range(j1, j2)})
        p_text = " ".join(pw[k].text.strip() for k in p_words)
        s_text = " ".join(sw[k].text.strip() for k in s_words)
        if p_words:
            t0, t1 = pw[p_words[0]].start, pw[p_words[-1]].end
        elif i1 < len(pt):
            t0 = t1 = pw[pt[i1][1]].start
        elif pw:
            t0 = t1 = pw[-1].end
        else:
            continue
        item = {"start": round(t0, 2), "end": round(t1, 2), "primary": p_text, "secondary": s_text, "fused": False}
        # Fusion: 1-to-1 substitution, primary unsure, secondary sure.
        if (fuse and op == "replace" and len(p_words) == 1 and len(s_words) == 1):
            pw_, sw_ = pw[p_words[0]], sw[s_words[0]]
            if (pw_.prob is not None and sw_.prob is not None and pw_.prob <= primary_max_prob
                    and sw_.prob >= secondary_min_prob):
                lead = " " if pw_.text.startswith(" ") else ""
                pw_.text = lead + sw_.text.strip()
                pw_.prob = sw_.prob
                item["fused"] = True
                fused += 1
        seg = seg_of.get(id(pw[p_words[0]])) if p_words else None
        if seg is not None and "engine-disagreement" not in seg.flags and not item["fused"]:
            seg.flags.append("engine-disagreement")
        disagreements.append(item)
    if fused:
        from .vocabulary import words_to_text

        for seg in primary.segments:
            seg.text = words_to_text(seg.words)
    return {"agreement": round(agreement, 4), "disagreements": disagreements, "fused_words": fused,
            "secondary_engine": f"{secondary.engine}:{secondary.model}"}
