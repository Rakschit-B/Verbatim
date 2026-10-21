# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""VERBATIM engine host — runs the PyTorch engines (OpenVoice V2 tone colour, ACE-Step 1.5 music, LatentSync
lip-sync on a Cloud GPU, quality scorers and the legacy designer) in their own Python runtime, so their heavy and conflicting dependencies never touch the app.

Protocol: one JSON object per line on stdin → one JSON object per line on stdout
  {"id": 1, "op": "omnivoice", ...}   →   {"id": 1, "ok": true, ...}  or  {"id": 1, "ok": false, "error": "..."}
Progress lines: {"id": 1, "progress": 0.4, "message": "..."}.  Models stay loaded between requests.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

_CACHE: dict = {}
_OUT = sys.stdout
sys.stdout = sys.stderr          # libraries that print() must not corrupt the protocol


def send(obj: dict):
    _OUT.write(json.dumps(obj, ensure_ascii=False) + "\n")
    _OUT.flush()


def device_and_dtype():
    import torch

    if torch.cuda.is_available():
        return "cuda:0", torch.float16
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps", torch.float32
    return "cpu", torch.float32


def load_wav(path: str, sr: int):
    import librosa

    a, _ = librosa.load(path, sr=sr, mono=True)
    return a


def write_wav(path: str, audio, sr: int):
    import numpy as np
    import soundfile as sf

    a = np.asarray(audio, dtype=np.float32).reshape(-1)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, a, sr, subtype="PCM_16")
    return len(a) / sr


def seed_all(seed):
    if seed is None or int(seed) < 0:
        return
    import random

    import numpy as np
    import torch

    random.seed(int(seed))
    np.random.seed(int(seed))
    torch.manual_seed(int(seed))


# ---------------------------------------------------------------- OmniVoice
def op_omnivoice(req: dict, rid):
    import torch
    from omnivoice import OmniVoice

    key = ("omnivoice", req["model_dir"])
    if key not in _CACHE:
        send({"id": rid, "progress": 0.05, "message": "Loading OmniVoice…"})
        dev, dt = device_and_dtype()
        _CACHE[key] = OmniVoice.from_pretrained(req["model_dir"], device_map=dev, dtype=dt)
    model = _CACHE[key]
    seed_all(req.get("seed"))
    kw = {k: req[k] for k in ("num_step", "guidance_scale", "t_shift", "position_temperature", "class_temperature",
                              "speed", "duration", "denoise", "language") if req.get(k) is not None}
    if req.get("ref_wav"):
        pkey = ("prompt", req["ref_wav"], req.get("ref_text", ""))
        if pkey not in _CACHE:
            _CACHE[pkey] = model.create_voice_clone_prompt(ref_audio=req["ref_wav"], ref_text=req.get("ref_text") or None)
        kw["voice_clone_prompt"] = _CACHE[pkey]
    if req.get("instruct"):
        kw["instruct"] = req["instruct"]
    t0 = time.time()
    with torch.inference_mode():
        audio = model.generate(text=req["text"], **kw)
    secs = write_wav(req["out"], audio[0], 24000)
    return {"out": req["out"], "sr": 24000, "seconds": secs, "elapsed": time.time() - t0}


# ---------------------------------------------------------------- OpenVoice V2
def _converter(ckpt_dir: str):
    key = ("openvoice", ckpt_dir)
    if key not in _CACHE:
        from openvoice.converter import ToneColorConverter

        dev, _ = device_and_dtype()
        dev = "cpu" if dev == "mps" else dev      # a few ops in the flow model are not on MPS
        d = Path(ckpt_dir) / "converter"
        _CACHE[key] = ToneColorConverter(str(d / "config.json"), str(d / "checkpoint.pth"), dev)
    return _CACHE[key]


def op_openvoice_convert(req: dict, rid):
    """Re-voice `src_wav` with the tone colour of `tgt_wavs` (list). tau: 0.1 strict … 0.5 loose."""
    import torch

    cv = _converter(req["ckpt_dir"])
    src = load_wav(req["src_wav"], cv.sr)
    tkey = ("se", tuple(req["tgt_wavs"]))
    if tkey not in _CACHE:
        _CACHE[tkey] = cv.embedding([load_wav(p, cv.sr) for p in req["tgt_wavs"]])
    src_se = cv.embedding([src])
    t0 = time.time()
    out = cv.convert(src, src_se, _CACHE[tkey], tau=float(req.get("tau", 0.3)))
    secs = write_wav(req["out"], out, cv.sr)
    if req.get("save_se"):
        torch.save(_CACHE[tkey].cpu(), req["save_se"])
    return {"out": req["out"], "sr": cv.sr, "seconds": secs, "elapsed": time.time() - t0}


# ---------------------------------------------------------------- quality scorers
def op_utmos(req: dict, rid):
    """Predicted naturalness MOS (1–5) for each wav (UTMOS22 strong, SpeechMOS implementation)."""
    import torch

    from scorers.utmos import UTMOS22Strong

    key = ("utmos", req["ckpt"])
    if key not in _CACHE:
        m = UTMOS22Strong()
        m.load_state_dict(torch.load(req["ckpt"], map_location="cpu"))
        _CACHE[key] = m.eval()
    m = _CACHE[key]
    scores = []
    for p in req["wavs"]:
        a = torch.tensor(load_wav(p, 16000)).unsqueeze(0)
        with torch.inference_mode():
            scores.append(float(m(a, 16000).item()))
    return {"scores": scores}


def op_emotion(req: dict, rid):
    """Speech emotion probabilities (neutral / happy / angry / sad) — wav2vec2 SUPERB ER."""
    import torch
    from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

    key = ("emotion", req["model_dir"])
    if key not in _CACHE:
        _CACHE[key] = (AutoFeatureExtractor.from_pretrained(req["model_dir"]),
                       AutoModelForAudioClassification.from_pretrained(req["model_dir"]).eval())
    fe, m = _CACHE[key]
    out = []
    for p in req["wavs"]:
        a = load_wav(p, 16000)
        x = fe(a, sampling_rate=16000, return_tensors="pt")
        with torch.inference_mode():
            pr = torch.softmax(m(**x).logits, -1)[0].tolist()
        out.append({m.config.id2label[i]: round(v, 4) for i, v in enumerate(pr)})
    return {"emotions": out}


# ---------------------------------------------------------------- ACE-Step 1.5 (music)
def op_music(req: dict, rid):
    from engines_music import generate

    return generate(req, lambda f, m: send({"id": rid, "progress": f, "message": m}), _CACHE)


# ---------------------------------------------------------------- lip-sync (Cloud GPU)
def op_lipsync(req: dict, rid):
    """Re-time the mouths in `video` to `audio` with LatentSync 1.6 (Apache-2.0, ByteDance). NVIDIA GPU only.
    The server install (cloud/install.sh) puts the LatentSync source + checkpoints in $VERBATIM_LATENTSYNC."""
    import subprocess

    root = Path(os.environ.get("VERBATIM_LATENTSYNC", str(Path.home() / "LatentSync")))
    if not (root / "scripts" / "inference.py").exists():
        raise RuntimeError("LatentSync is not installed on this server — run cloud/install.sh --with-lipsync")
    cfg = root / "configs" / "unet" / ("stage2_512.yaml" if (root / "configs/unet/stage2_512.yaml").exists() else "stage2.yaml")
    send({"id": rid, "progress": 0.1, "message": "Lip-syncing every face (LatentSync)…"})
    t0 = time.time()
    cmd = [sys.executable, "-m", "scripts.inference", "--unet_config_path", str(cfg),
           "--inference_ckpt_path", str(root / "checkpoints" / "latentsync_unet.pt"),
           "--inference_steps", str(int(req.get("steps", 20))), "--guidance_scale", str(float(req.get("guidance", 1.5))),
           "--video_path", req["video"], "--audio_path", req["audio"], "--video_out_path", req["out"]]
    if req.get("deepcache", True):
        cmd.append("--enable_deepcache")
    r = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
    if r.returncode != 0 or not Path(req["out"]).exists():
        raise RuntimeError("LatentSync failed: " + (r.stderr or r.stdout)[-600:])
    return {"out": req["out"], "elapsed": time.time() - t0}


def op_ping(req: dict, rid):
    info = {"python": sys.version.split()[0], "pid": os.getpid()}
    try:
        import torch

        info.update(torch=torch.__version__, device=device_and_dtype()[0])
    except Exception as exc:
        info["torch_error"] = str(exc)
    return info


OPS = {"ping": op_ping, "omnivoice": op_omnivoice, "openvoice_convert": op_openvoice_convert,
       "utmos": op_utmos, "emotion": op_emotion, "music": op_music, "lipsync": op_lipsync}


def main():
    send({"ready": True, "pid": os.getpid()})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            send({"ok": False, "error": "bad json"})
            continue
        rid = req.get("id")
        if req.get("op") == "quit":
            send({"id": rid, "ok": True})
            break
        try:
            res = OPS[req["op"]](req, rid)
            send({"id": rid, "ok": True, **res})
        except Exception as exc:
            send({"id": rid, "ok": False, "error": f"{type(exc).__name__}: {exc}",
                  "trace": traceback.format_exc()[-1500:]})


if __name__ == "__main__":
    main()
