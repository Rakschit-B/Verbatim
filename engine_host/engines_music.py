# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Music Studio engine — ACE-Step 1.5 (DiT + VAE + Qwen3 text encoder, optional 5 Hz planner LM).

Tasks: text2music (song from a description + lyrics), cover (restyle an existing track), repaint (regenerate
a time range), complete/extend, extract (stems), lego (add a part) — the last three need the base model.
Requests come from VERBATIM's Music Studio (verbatim/music_studio.py)."""
from __future__ import annotations

import os
import time
from pathlib import Path


def _handlers(req, cache, progress):
    import torch

    root = req["project_root"]                         # contains checkpoints/
    model = req.get("dit_model", "acestep-v15-turbo")
    lm = req.get("lm_model", "")
    key = ("acestep", root, model, lm)
    if key in cache:
        return cache[key]
    from acestep.handler import AceStepHandler
    from acestep.llm_inference import LLMHandler

    if torch.cuda.is_available():
        dev = "cuda"
    elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        dev = "mps"
    else:
        dev = "cpu"
    progress(0.05, "Loading the music model (first time takes a minute)…")
    dit = AceStepHandler()
    msg, ok = dit.initialize_service(project_root=root, config_path=model, device=dev,
                                     offload_to_cpu=bool(req.get("offload", dev == "cpu")))
    if not ok:
        raise RuntimeError(f"Music model failed to load: {msg}")
    llm = LLMHandler()
    if lm:
        backend = "mlx" if dev == "mps" and _has_mlx() else ("vllm" if dev == "cuda" and _has_vllm() else "pt")
        progress(0.12, "Loading the song planner…")
        msg, ok = llm.initialize(checkpoint_dir=os.path.join(root, "checkpoints"), lm_model_path=lm, backend=backend,
                                 device=dev)
        if not ok:
            llm = LLMHandler()   # carry on without the planner
    cache.clear()                # one music model in memory at a time
    cache[key] = (dit, llm)
    return cache[key]


def _has_mlx():
    try:
        import mlx.core  # noqa: F401

        return True
    except Exception:
        return False


def _has_vllm():
    try:
        import vllm  # noqa: F401

        return True
    except Exception:
        return False


FIELDS = ("task_type", "caption", "lyrics", "instrumental", "vocal_language", "bpm", "keyscale", "timesignature",
          "duration", "inference_steps", "seed", "guidance_scale", "use_adg", "shift", "infer_method",
          "reference_audio", "src_audio", "repainting_start", "repainting_end", "audio_cover_strength",
          "thinking", "lm_temperature", "lm_cfg_scale", "lm_top_p", "lm_negative_prompt", "use_cot_caption",
          "use_cot_metas", "use_cot_language", "instruction")


def generate(req: dict, progress, cache: dict) -> dict:
    from acestep.inference import GenerationConfig, GenerationParams, generate_music

    dit, llm = _handlers(req, cache, progress)
    p = {k: req[k] for k in FIELDS if k in req and req[k] is not None}
    if not getattr(llm, "llm_initialized", False) and not getattr(llm, "initialized", False):
        p["thinking"] = False
        p.setdefault("use_cot_caption", False)
        p.setdefault("use_cot_metas", False)
        p.setdefault("use_cot_language", False)
    params = GenerationParams(**p)
    seeds = req.get("seeds")
    config = GenerationConfig(batch_size=int(req.get("batch_size", 1)), use_random_seed=not seeds,
                              seeds=seeds, audio_format=req.get("audio_format", "wav32"))
    out_dir = Path(req["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    progress(0.2, "Composing…")
    res = generate_music(dit, llm, params, config, save_dir=str(out_dir))
    if not res.success:
        raise RuntimeError(res.error or "music generation failed")
    tracks = []
    for a in res.audios:
        pr = a.get("params", {}) or {}
        tracks.append({"path": a.get("path"), "seed": pr.get("seed"), "bpm": pr.get("bpm") or pr.get("cot_bpm"),
                       "key": a.get("key") or pr.get("keyscale") or pr.get("cot_keyscale"),
                       "caption": pr.get("cot_caption") or pr.get("caption"), "duration": pr.get("duration")})
    return {"tracks": tracks, "elapsed": time.time() - t0}
