# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Chatterbox Multilingual (Resemble AI, MIT licence) on ONNX Runtime — expressive, emotional speech in
23 languages (incl. Hindi, Hebrew, Arabic, Japanese, Chinese, Russian, Spanish, French) that clones any
voice from a short reference clip. Runs fully offline once the voice pack is downloaded (~1.6 GB).

Pipeline (four ONNX graphs): speech_encoder(reference audio) → conditioning + speaker features;
embed_tokens(text tokens, emotion exaggeration) → embeddings; language_model (autoregressive, KV cache)
→ speech tokens; conditional_decoder(speech tokens, speaker) → 24 kHz waveform.

"exaggeration" is the emotion-intensity control (0.25 flat … 0.5 natural … 1.0 very animated); VERBATIM
sets it from each line's performance direction (direction.py).
"""
from __future__ import annotations

import os
import threading
import unicodedata
from pathlib import Path

import numpy as np

REPO = "onnx-community/chatterbox-multilingual-ONNX"
SR = 24000
START, STOP = 6561, 6562
LAYERS, KV_HEADS, HEAD_DIM = 30, 16, 64
LANGS = {"ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it", "ja", "ko", "ms", "nl", "no", "pl", "pt",
         "ru", "sv", "sw", "tr", "zh"}
FILES = ["onnx/speech_encoder.onnx", "onnx/speech_encoder.onnx_data", "onnx/embed_tokens.onnx",
         "onnx/embed_tokens.onnx_data", "onnx/conditional_decoder.onnx", "onnx/conditional_decoder.onnx_data",
         "tokenizer.json", "default_voice.wav", "Cangjie5_TC.json"]
LM_VARIANTS = {"q4": ("onnx/language_model_q4.onnx", "onnx/language_model_q4.onnx_data", 354),
               "fp16": ("onnx/language_model_fp16.onnx", "onnx/language_model_fp16.onnx_data", 1040)}
SIZE_MB = 1210 + 354


def model_dir() -> Path:
    from .platform_info import models_dir

    return models_dir() / "tts" / "chatterbox-multilingual"


def _lm_files(d: Path) -> tuple[Path, Path] | None:
    for key in ("fp16", "q4"):
        a, b, _ = LM_VARIANTS[key]
        if (d / a).exists() and (d / b).exists():
            return d / a, d / b
    return None


def is_installed(d: Path | None = None) -> bool:
    d = d or model_dir()
    return all((d / f).exists() for f in FILES if not f.endswith(".json") or f == "tokenizer.json") \
        and _lm_files(d) is not None


def ensure(progress=None, variant: str = "q4") -> Path:
    d = model_dir()
    if is_installed(d):
        return d
    from .download import fetch

    wanted = FILES + list(LM_VARIANTS[variant][:2])
    for k, f in enumerate(wanted):
        dest = d / f
        if dest.exists():
            continue
        cb = None
        if progress:
            def cb(frac, msg, k=k):
                progress((k + frac) / len(wanted), f"Chatterbox voice pack ({k + 1}/{len(wanted)}): {msg}")
        fetch(f"https://huggingface.co/{REPO}/resolve/main/{f}", dest, cb, f.split("/")[-1])
    return d


# ---------------------------------------------------------------- text preparation
def _jamo(text: str) -> str:
    out = []
    for ch in text:
        c = ord(ch)
        if 0xAC00 <= c <= 0xD7A3:
            c -= 0xAC00
            out += [chr(0x1100 + c // 588), chr(0x1161 + (c % 588) // 28)]
            if c % 28:
                out.append(chr(0x11A7 + c % 28))
        else:
            out.append(ch)
    return "".join(out)


def _japanese(text: str) -> str:
    try:
        import pykakasi

        kks = pykakasi.kakasi()
        return "".join(item["hira"] for item in kks.convert(text))
    except Exception:
        return text


class _Cangjie:
    def __init__(self, path: Path):
        import json

        self.map = {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for code, ch in (data.items() if isinstance(data, dict) else []):
                self.map.setdefault(ch, code) if len(ch) == 1 else self.map.setdefault(code, ch)
        except (OSError, ValueError):
            pass

    def __call__(self, text: str) -> str:
        out = []
        for ch in text:
            code = self.map.get(ch)
            out.append(f"[cj_{code}]" if code and "一" <= ch <= "鿿" else ch)
        return "".join(out)


def punc_norm(text: str) -> str:
    """Same clean-up the Chatterbox authors apply before tokenising."""
    t = " ".join((text or "").split())
    if not t:
        return "You need to add some text for me to talk."
    t = t[0].upper() + t[1:]
    for a, b in (("…", ", "), (":", ","), (" - ", ", "), (";", ", "), ("—", "-"), ("–", "-"), (" ,", ","),
                 ("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'")):
        t = t.replace(a, b)
    t = t.rstrip(" ")
    if not t.endswith((".", "!", "?", "-", ",", "।", "。", "？", "！", "؟")):
        t += "."
    return t


def prepare(text: str, lang: str, cangjie=None) -> str:
    t = punc_norm(text)
    if lang == "zh" and cangjie:
        t = cangjie(t)
    elif lang == "ja":
        t = _japanese(t)
    elif lang == "ko":
        t = _jamo(t)
    t = unicodedata.normalize("NFKD", t.lower())
    return f"[{lang}]{t}"


# ---------------------------------------------------------------- engine
class Chatterbox:
    _lock = threading.Lock()
    _inst: "Chatterbox | None" = None

    @classmethod
    def get(cls, progress=None) -> "Chatterbox":
        with cls._lock:
            if cls._inst is None:
                cls._inst = Chatterbox(ensure(progress))
            return cls._inst

    def __init__(self, d: Path):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, min(8, os.cpu_count() or 2))
        prov = ["CPUExecutionProvider"]

        def sess(p):
            return ort.InferenceSession(str(p), sess_options=so, providers=prov)

        self.enc = sess(d / "onnx/speech_encoder.onnx")
        self.emb = sess(d / "onnx/embed_tokens.onnx")
        lm, _ = _lm_files(d)
        self.lm = sess(lm)
        self.dec = sess(d / "onnx/conditional_decoder.onnx")
        self.tok = Tokenizer.from_file(str(d / "tokenizer.json"))
        self.cangjie = _Cangjie(d / "Cangjie5_TC.json")
        self.default_voice = d / "default_voice.wav"
        self.lm_inputs = [i.name for i in self.lm.get_inputs()]
        kv = next((i for i in self.lm.get_inputs() if i.name.startswith("past_key_values")), None)
        self.kv_dtype = np.float16 if kv is not None and "float16" in kv.type else np.float32
        self._cond_cache: dict = {}
        self.run_lock = threading.Lock()

    def conditioning(self, ref: np.ndarray, sr: int, key: str = ""):
        """Speaker conditioning from a reference clip (cached per voice)."""
        if key and key in self._cond_cache:
            return self._cond_cache[key]
        from .tts import resample

        a = resample(np.asarray(ref, dtype=np.float32), sr, SR)[: SR * 10]   # ≤10 s, like the reference code
        out = self.enc.run(None, {"audio_values": a[None, :].astype(np.float32)})
        if key:
            self._cond_cache[key] = out
        return out

    def generate(self, text: str, lang: str, ref: np.ndarray, ref_sr: int, voice_key: str = "",
                 exaggeration: float = 0.5, temperature: float = 0.8, min_p: float = 0.05,
                 rep_penalty: float = 1.2, seed: int | None = 7) -> np.ndarray:
        if lang not in LANGS:
            raise ValueError(f"Chatterbox does not speak '{lang}'")
        with self.run_lock:
            return self._generate(text, lang, ref, ref_sr, voice_key, exaggeration, temperature, min_p,
                                  rep_penalty, seed)

    def _generate(self, text, lang, ref, ref_sr, voice_key, exaggeration, temperature, min_p, rep_penalty, seed):
        rng = np.random.default_rng(seed)
        cond_emb, prompt_tok, ref_xvec, prompt_feat = self.conditioning(ref, ref_sr, voice_key)
        ids = np.array([self.tok.encode(prepare(text, lang, self.cangjie)).ids], dtype=np.int64)
        if not (ids[0] >= START).any():   # the exported tokenizer normally appends the speech-start tokens itself
            ids = np.concatenate([ids, np.array([[START, START]], dtype=np.int64)], axis=1)
        pos = np.where(ids >= START, 0, np.arange(ids.shape[1])[None, :] - 1).astype(np.int64)
        feed = {"input_ids": ids, "position_ids": pos, "exaggeration": np.array([exaggeration], dtype=np.float32)}
        max_new = int(min(1000, 80 + len(text) * 3))
        generated = np.array([[START]], dtype=np.int64)
        cache, attn = None, None
        for step in range(max_new):
            embeds = self.emb.run(None, feed)[0]
            if step == 0:
                embeds = np.concatenate([cond_emb, embeds], axis=1)
                b, L = embeds.shape[0], embeds.shape[1]
                cache = {f"past_key_values.{l}.{kv}": np.zeros((b, KV_HEADS, 0, HEAD_DIM), dtype=self.kv_dtype)
                         for l in range(LAYERS) for kv in ("key", "value")}
                attn = np.ones((b, L), dtype=np.int64)
            lm_feed = {"inputs_embeds": embeds.astype(np.float32 if self.kv_dtype == np.float32 else embeds.dtype),
                       "attention_mask": attn, **cache}
            lm_feed = {k: v for k, v in lm_feed.items() if k in self.lm_inputs}
            outs = self.lm.run(None, lm_feed)
            logits = outs[0][:, -1, :].astype(np.float64)
            # repetition penalty on tokens already spoken
            seen = np.unique(generated)
            vals = logits[0, seen]
            logits[0, seen] = np.where(vals < 0, vals * rep_penalty, vals / rep_penalty)
            nxt = self._sample(logits[0], temperature, min_p, rng)
            generated = np.concatenate([generated, [[nxt]]], axis=1)
            if nxt == STOP:
                break
            for j, key in enumerate(cache):
                cache[key] = outs[1 + j]
            attn = np.concatenate([attn, np.ones((attn.shape[0], 1), dtype=np.int64)], axis=1)
            feed["input_ids"] = np.array([[nxt]], dtype=np.int64)
            feed["position_ids"] = np.array([[step + 1]], dtype=np.int64)
        speech = generated[:, 1:]
        if speech.shape[1] and speech[0, -1] == STOP:
            speech = speech[:, :-1]
        speech = speech[speech < START][None, :] if speech.size else speech
        speech = np.concatenate([prompt_tok, speech.astype(prompt_tok.dtype)], axis=1)
        wav = self.dec.run(None, {"speech_tokens": speech, "speaker_embeddings": ref_xvec,
                                  "speaker_features": prompt_feat})[0]
        return np.squeeze(wav).astype(np.float32)

    @staticmethod
    def _sample(logits: np.ndarray, temperature: float, min_p: float, rng) -> int:
        if temperature <= 0.01:
            return int(np.argmax(logits))
        z = logits / temperature
        z -= z.max()
        p = np.exp(z)
        p /= p.sum()
        if min_p > 0:
            p[p < p.max() * min_p] = 0.0
            p /= p.sum()
        return int(rng.choice(len(p), p=p))


# ---------------------------------------------------------------- voice changer (speech-to-speech)
def voice_convert(src: np.ndarray, src_sr: int, target_ref: np.ndarray, target_sr: int, target_key: str = "",
                  chunk_s: float = 8.0, progress=None) -> np.ndarray:
    """Re-speak a recorded performance in another voice — keeps the words, timing, pitch movement and emotion of
    the performance (Chatterbox S3 speech tokens → target speaker decoder). Returns 24 kHz audio."""
    from .tts import resample

    cb = Chatterbox.get(progress)
    _, _, x_vec, feat = cb.conditioning(target_ref, target_sr, target_key)
    t_tok = cb.conditioning(target_ref, target_sr, target_key)[1]
    a = resample(np.asarray(src, dtype=np.float32), src_sr, SR)
    C, O = int(chunk_s * SR), int(0.25 * SR)
    out, pos = [], 0
    n = len(a)
    with cb.run_lock:
        while pos < n:
            piece = a[pos:pos + C]
            _, s_tok, _, _ = cb.enc.run(None, {"audio_values": piece[None, :].astype(np.float32)})
            toks = np.concatenate([t_tok, s_tok.astype(t_tok.dtype)], axis=1)
            w = np.squeeze(cb.dec.run(None, {"speech_tokens": toks, "speaker_embeddings": x_vec,
                                             "speaker_features": feat})[0]).astype(np.float32)
            out.append(w)
            if progress:
                progress(min(1.0, (pos + C) / n), "Re-voicing your performance…")
            pos += C
    if not out:
        return np.zeros(0, dtype=np.float32)
    y = out[0]
    for w in out[1:]:
        k = min(O, len(y), len(w))
        ramp = np.linspace(0, 1, k, dtype=np.float32)
        y = np.concatenate([y[:-k], y[-k:] * (1 - ramp) + w[:k] * ramp, w[k:]]) if k else np.concatenate([y, w])
    return y
