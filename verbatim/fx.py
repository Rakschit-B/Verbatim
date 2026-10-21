# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Voice finishing — Infinite Story's own effects chain (numpy/scipy only, no third-party DSP licences).

Modulation & tone:  pitch shift (semitones, formant-aware option), pitch range (expressiveness ×),
                    warmth (low-shelf), presence (2–5 kHz bell), air (high-shelf), de-esser
Dynamics:           compressor, limiter, gain, loudness normalise (LUFS-style)
Space:              room / hall reverb (FDN), delay, stereo width
Each effect is a dict {"type": ..., params}; a chain is a list. Presets ship for common deliveries.
"""
from __future__ import annotations

import numpy as np

SR = 48000

PRESETS = {
    "Broadcast narrator": [{"type": "highpass", "hz": 70}, {"type": "warmth", "db": 2.0},
                           {"type": "presence", "db": 2.5}, {"type": "deess", "amount": 0.5},
                           {"type": "compressor", "threshold_db": -20, "ratio": 3.0},
                           {"type": "loudness", "lufs": -16}],
    "Warm & intimate": [{"type": "highpass", "hz": 60}, {"type": "warmth", "db": 3.5}, {"type": "air", "db": -1.5},
                        {"type": "compressor", "threshold_db": -24, "ratio": 2.5}, {"type": "loudness", "lufs": -18}],
    "Bright advert": [{"type": "highpass", "hz": 90}, {"type": "presence", "db": 3.5}, {"type": "air", "db": 2.5},
                      {"type": "compressor", "threshold_db": -18, "ratio": 4.0}, {"type": "loudness", "lufs": -14}],
    "Cinematic trailer": [{"type": "pitch", "semitones": -1.5}, {"type": "warmth", "db": 4.0},
                          {"type": "reverb", "room": 0.7, "wet": 0.18}, {"type": "compressor", "threshold_db": -20,
                                                                           "ratio": 4.0}, {"type": "loudness", "lufs": -14}],
    "Phone call": [{"type": "highpass", "hz": 300}, {"type": "lowpass", "hz": 3400}, {"type": "compressor",
                                                                                       "threshold_db": -20, "ratio": 6.0}],
    "Radio": [{"type": "highpass", "hz": 200}, {"type": "lowpass", "hz": 5000}, {"type": "presence", "db": 4.0},
              {"type": "compressor", "threshold_db": -22, "ratio": 5.0}],
    "Big hall": [{"type": "reverb", "room": 0.9, "wet": 0.3}],
    "Deep voice": [{"type": "pitch", "semitones": -3.0}, {"type": "warmth", "db": 2.0}],
}


# ---------------------------------------------------------------- filters (RBJ biquads)
def _biquad(a: np.ndarray, b0, b1, b2, a0, a1, a2) -> np.ndarray:
    from scipy.signal import lfilter

    return lfilter([b0 / a0, b1 / a0, b2 / a0], [1.0, a1 / a0, a2 / a0], a).astype(np.float32)


def _shelf(a, hz, db, high: bool, sr=SR):
    A = 10 ** (db / 40)
    w = 2 * np.pi * hz / sr
    cs, sn = np.cos(w), np.sin(w)
    al = sn / 2 * np.sqrt(2)
    s = 1 if high else -1
    b0 = A * ((A + 1) + s * (A - 1) * cs + 2 * np.sqrt(A) * al)
    b1 = -2 * s * A * ((A - 1) + s * (A + 1) * cs)
    b2 = A * ((A + 1) + s * (A - 1) * cs - 2 * np.sqrt(A) * al)
    a0 = (A + 1) - s * (A - 1) * cs + 2 * np.sqrt(A) * al
    a1 = 2 * s * ((A - 1) - s * (A + 1) * cs)
    a2 = (A + 1) - s * (A - 1) * cs - 2 * np.sqrt(A) * al
    return _biquad(a, b0, b1, b2, a0, a1, a2)


def _bell(a, hz, db, q=1.0, sr=SR):
    A = 10 ** (db / 40)
    w = 2 * np.pi * hz / sr
    al = np.sin(w) / (2 * q)
    return _biquad(a, 1 + al * A, -2 * np.cos(w), 1 - al * A, 1 + al / A, -2 * np.cos(w), 1 - al / A)


def _pass(a, hz, high: bool, sr=SR):
    from scipy.signal import butter, sosfilt

    sos = butter(2, min(hz, sr * 0.45) / (sr / 2), "highpass" if high else "lowpass", output="sos")
    return sosfilt(sos, a).astype(np.float32)


# ---------------------------------------------------------------- pitch
def pitch_shift(a: np.ndarray, semitones: float, sr: int = SR) -> np.ndarray:
    """Shift pitch, keep duration: time-stretch by r then resample by 1/r."""
    if abs(semitones) < 0.01:
        return a
    from .tts import resample, time_stretch

    r = 2 ** (semitones / 12)
    st = time_stretch(a, 1 / r)                      # longer by r
    out = resample(st, int(round(sr * r)), sr)       # play back faster → higher pitch, original length
    n = len(a)
    return np.pad(out, (0, max(0, n - len(out))))[:n].astype(np.float32)


def pitch_range(a: np.ndarray, factor: float, sr: int = SR) -> np.ndarray:
    """Expressiveness: widen (factor > 1) or flatten (< 1) the intonation around the speaker's median pitch.
    Works phrase by phrase: each 200 ms window is shifted toward/away from the median."""
    if abs(factor - 1) < 0.02 or len(a) < sr // 2:
        return a
    f0 = estimate_f0(a, sr)
    voiced = f0[f0 > 0]
    if len(voiced) < 10:
        return a
    med = np.median(voiced)
    hop = int(0.2 * sr)
    out = np.zeros_like(a)
    norm = np.zeros_like(a)
    win = np.hanning(hop * 2).astype(np.float32)
    fpw = len(f0) / max(1, len(a))
    for s in range(0, len(a) - hop, hop):
        seg = a[s:s + hop * 2]
        fs = f0[int(s * fpw):int((s + hop * 2) * fpw)]
        fs = fs[fs > 0]
        shift = 0.0
        if len(fs):
            st = 12 * np.log2(np.median(fs) / med)
            shift = float(np.clip(st * (factor - 1), -4, 4))
        y = pitch_shift(seg, shift, sr) if abs(shift) > 0.05 else seg
        w = win[:len(y)]
        out[s:s + len(y)] += y * w
        norm[s:s + len(y)] += w
    norm[norm < 1e-3] = 1
    return (out / norm).astype(np.float32)


def estimate_f0(a: np.ndarray, sr: int = SR, hop_s: float = 0.01, fmin: float = 65.0, fmax: float = 450.0
                ) -> np.ndarray:
    """YIN pitch track (Hz per 10 ms, 0 = unvoiced) with octave-jump repair — robust prosody statistics."""
    x = a if sr <= 16000 else _decimate(a, sr, 16000)
    s2 = min(sr, 16000)
    fr, hop = int(0.04 * s2), int(hop_s * s2)
    tmin, tmax = int(s2 / fmax), int(s2 / fmin)
    if len(x) < fr + tmax:
        return np.zeros(0, dtype=np.float32)
    rms_all = np.sqrt((x ** 2).mean()) + 1e-9
    out = []
    for i in range(0, len(x) - fr - tmax, hop):
        f = x[i:i + fr + tmax].astype(np.float64)
        if np.sqrt((f[:fr] ** 2).mean()) < rms_all * 0.25:
            out.append(0.0)
            continue
        # difference function d(tau) for tau in [1, tmax]
        e = np.cumsum(f ** 2)
        frame = f[:fr]
        corr = np.correlate(f[:fr + tmax], frame, "valid")[:tmax + 1]
        energy = e[fr - 1:fr + tmax] - np.concatenate([[0.0], e[:tmax]])
        d = e[fr - 1] + energy - 2 * corr
        d[0] = 0
        cmnd = d[1:] * np.arange(1, len(d)) / (np.cumsum(d[1:]) + 1e-12)
        seg = cmnd[tmin - 1:]
        cand = np.where(seg < 0.2)[0]
        if not len(cand) and seg.min() < 0.4:
            cand = np.array([int(np.argmin(seg))])
        if len(cand):
            t = cand[0] + tmin
            while t + 1 < len(cmnd) + 1 and cmnd[t] < cmnd[t - 1]:
                t += 1
            out.append(s2 / t)
        else:
            out.append(0.0)
    f0 = np.array(out, dtype=np.float32)
    v = f0 > 0
    if v.sum() > 5:   # octave repair against a running median
        med = np.median(f0[v])
        for k in np.where(v)[0]:
            r = f0[k] / med
            if r > 1.8:
                f0[k] /= 2
            elif r < 0.55:
                f0[k] *= 2
    return f0


def _decimate(a, sr, target):
    from .tts import resample

    return resample(a, sr, target)


def prosody_stats(a: np.ndarray, sr: int = SR) -> dict:
    """Pitch statistics used by the quality scorecard: median Hz, range and variation in semitones."""
    f0 = estimate_f0(a, sr)
    v = f0[f0 > 0]
    if len(v) < 5:
        return {"median_hz": 0.0, "std_st": 0.0, "range_st": 0.0, "voiced": 0.0}
    st = 12 * np.log2(v / np.median(v))
    return {"median_hz": float(np.median(v)), "std_st": float(np.std(st)),
            "range_st": float(np.percentile(st, 95) - np.percentile(st, 5)), "voiced": float(len(v) / len(f0))}


# ---------------------------------------------------------------- dynamics
def compressor(a, threshold_db=-20.0, ratio=3.0, attack_ms=8.0, release_ms=120.0, makeup_db=None, sr=SR):
    env = np.abs(a)
    at, rl = np.exp(-1 / (attack_ms * sr / 1000)), np.exp(-1 / (release_ms * sr / 1000))
    # vectorised-ish envelope at 1 ms control rate
    step = max(1, sr // 1000)
    blocks = env[:len(env) // step * step].reshape(-1, step).max(1) if len(env) >= step else env
    e, out = 0.0, np.empty(len(blocks), dtype=np.float32)
    a_c, r_c = at ** step, rl ** step
    for i, v in enumerate(blocks):
        e = a_c * e + (1 - a_c) * v if v > e else r_c * e + (1 - r_c) * v
        out[i] = e
    lvl = 20 * np.log10(out + 1e-9)
    gr = np.where(lvl > threshold_db, (threshold_db - lvl) * (1 - 1 / ratio), 0.0)
    if makeup_db is None:
        makeup_db = -threshold_db * (1 - 1 / ratio) * 0.35
    g = 10 ** ((gr + makeup_db) / 20)
    g = np.repeat(g, step)
    g = np.pad(g, (0, len(a) - len(g)), mode="edge") if len(g) < len(a) else g[:len(a)]
    return (a * g).astype(np.float32)


def deess(a, amount=0.5, sr=SR):
    """Tame harsh 's' sounds: compress only the 5–9 kHz band."""
    band = _pass(_pass(a, 5000, True, sr), 9000, False, sr)
    squashed = compressor(band, threshold_db=-30, ratio=2 + 6 * amount, attack_ms=1, release_ms=40, makeup_db=0, sr=sr)
    return (a - band + squashed).astype(np.float32)


def limiter(a, ceiling_db=-1.0):
    c = 10 ** (ceiling_db / 20)
    k = c * 0.85
    over = np.abs(a) > k
    if over.any():
        x = a[over]
        a = a.copy()
        a[over] = np.sign(x) * (k + (c - k) * np.tanh((np.abs(x) - k) / (c - k)))
    return a.astype(np.float32)


def loudness(a, lufs=-16.0, sr=SR):
    from .music import loudness_normalise

    return loudness_normalise(a, lufs)


# ---------------------------------------------------------------- space
def reverb(a, room=0.5, wet=0.2, damping=0.4, sr=SR):
    """Convolution reverb with a synthetic room response (decaying, darkening noise + early reflections)."""
    from scipy.signal import fftconvolve

    rt = 0.3 + 2.2 * room                                   # decay time (s)
    n = int(rt * sr)
    t = np.arange(n) / sr
    rng = np.random.default_rng(11)
    ir = rng.standard_normal(n).astype(np.float32) * np.exp(-6.9 * t / rt)
    ir = _pass(ir, 9000 - 6000 * damping, False, sr)       # high frequencies die faster
    for d, g in ((0.011, 0.6), (0.019, 0.45), (0.027, 0.35), (0.041, 0.25)):
        k = int(d * sr * (0.6 + room))
        if k < n:
            ir[k] += g
    ir /= np.sqrt((ir ** 2).sum()) + 1e-9
    tail = fftconvolve(a, ir)[: len(a) + n].astype(np.float32)
    dry = np.pad(a, (0, len(tail) - len(a)))
    return ((1 - wet) * dry + wet * tail * 0.5).astype(np.float32)


def delay(a, seconds=0.25, feedback=0.3, mix=0.2, sr=SR):
    d = int(seconds * sr)
    out = np.pad(a, (0, d * 4)).astype(np.float32)
    y = out.copy()
    for k in range(1, 5):
        y[d * k:] += out[:len(out) - d * k] * (feedback ** k)
    return ((1 - mix) * out + mix * y).astype(np.float32)


# ---------------------------------------------------------------- chain
def apply(a: np.ndarray, chain: list[dict], sr: int = SR) -> np.ndarray:
    for fx in chain or []:
        t = fx.get("type")
        if fx.get("enabled") is False:
            continue
        if t == "pitch":
            a = pitch_shift(a, float(fx.get("semitones", 0)), sr)
        elif t == "pitch_range":
            a = pitch_range(a, float(fx.get("factor", 1.0)), sr)
        elif t == "highpass":
            a = _pass(a, float(fx.get("hz", 80)), True, sr)
        elif t == "lowpass":
            a = _pass(a, float(fx.get("hz", 12000)), False, sr)
        elif t == "warmth":
            a = _shelf(a, 220, float(fx.get("db", 2)), False, sr)
        elif t == "presence":
            a = _bell(a, 3200, float(fx.get("db", 2)), 0.9, sr)
        elif t == "air":
            a = _shelf(a, 9000, float(fx.get("db", 2)), True, sr)
        elif t == "deess":
            a = deess(a, float(fx.get("amount", 0.5)), sr)
        elif t == "compressor":
            a = compressor(a, float(fx.get("threshold_db", -20)), float(fx.get("ratio", 3)), sr=sr)
        elif t == "gain":
            a = a * 10 ** (float(fx.get("db", 0)) / 20)
        elif t == "reverb":
            a = reverb(a, float(fx.get("room", 0.5)), float(fx.get("wet", 0.2)), sr=sr)
        elif t == "delay":
            a = delay(a, float(fx.get("seconds", 0.25)), float(fx.get("feedback", 0.3)), float(fx.get("mix", 0.2)), sr)
        elif t == "loudness":
            a = loudness(a, float(fx.get("lufs", -16)), sr)
    return limiter(np.asarray(a, dtype=np.float32))
