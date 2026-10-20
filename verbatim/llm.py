"""Local LLM runtime for offline translation: llama.cpp's `llama-server` + a GGUF model.

The llama.cpp binaries (MIT) are downloaded once from the official GitHub releases (Metal build on
Apple Silicon, CPU build on Windows); the model (e.g. Google TranslateGemma, Gemma terms of use) is
downloaded once from Hugging Face. The server runs only while a translation job runs, on 127.0.0.1.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path

from .platform_info import IS_MAC, IS_WINDOWS

RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"

# name -> candidate (repo, file) on Hugging Face, tried in order; size for the download prompt
MODELS = {
    "translategemma-4b": {"label": "TranslateGemma 4B (fast, 2.5 GB)", "size_mb": 2500, "ram_gb": 8, "files": [
        ("mradermacher/translategemma-4b-it-GGUF", "translategemma-4b-it.Q4_K_M.gguf"),
        ("bartowski/google_translategemma-4b-it-GGUF", "google_translategemma-4b-it-Q4_K_M.gguf"),
        ("vjchou/translategemma-4b-it-GGUF", "translategemma-4b-it-Q4_K_M.gguf")]},
    "translategemma-12b": {"label": "TranslateGemma 12B (best, 7.3 GB, 16 GB RAM)", "size_mb": 7300, "ram_gb": 16,
                           "files": [
        ("mradermacher/translategemma-12b-it-GGUF", "translategemma-12b-it.Q4_K_M.gguf"),
        ("bartowski/google_translategemma-12b-it-GGUF", "google_translategemma-12b-it-Q4_K_M.gguf")]},
}


def root() -> Path:
    from .platform_info import models_dir

    return models_dir() / "llm"


def _asset_suffix() -> str:
    if IS_MAC:
        return "bin-macos-arm64.zip" if platform.machine() == "arm64" else "bin-macos-x64.zip"
    if IS_WINDOWS:
        return "bin-win-cpu-x64.zip"
    return "bin-ubuntu-x64.zip"


def server_path() -> Path | None:
    exe = "llama-server.exe" if IS_WINDOWS else "llama-server"
    hits = sorted((root() / "llama.cpp").rglob(exe)) if (root() / "llama.cpp").exists() else []
    return hits[0] if hits else None


def ensure_server(progress=None) -> Path:
    p = server_path()
    if p:
        return p
    req = urllib.request.Request(RELEASES_API, headers={"User-Agent": "VERBATIM", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rel = json.loads(r.read())
    asset = next((a for a in rel.get("assets", []) if a["name"].endswith(_asset_suffix())), None)
    if not asset:
        raise RuntimeError("Could not find the llama.cpp build for this computer")
    from .download import fetch

    dest = root() / "llama.cpp"
    dest.mkdir(parents=True, exist_ok=True)
    tmp = root() / asset["name"]
    fetch(asset["browser_download_url"], tmp, progress, "translation engine (llama.cpp)")
    with zipfile.ZipFile(tmp) as z:
        for name in z.namelist():
            if name.startswith("/") or ".." in Path(name).parts:
                raise RuntimeError("Unsafe path in llama.cpp archive")
        z.extractall(dest)
    tmp.unlink(missing_ok=True)
    p = server_path()
    if not p:
        raise RuntimeError("llama-server missing from the llama.cpp download")
    if not IS_WINDOWS:
        for f in p.parent.iterdir():
            if f.is_file():
                f.chmod(0o755)
    return p


def model_path(name: str) -> Path | None:
    d = root() / name
    hits = sorted(d.glob("*.gguf")) if d.exists() else []
    return hits[0] if hits else None


def ensure_model(name: str, progress=None) -> Path:
    p = model_path(name)
    if p:
        return p
    from .download import fetch

    d = root() / name
    d.mkdir(parents=True, exist_ok=True)
    last = None
    for repo, fname in MODELS[name]["files"]:
        try:
            fetch(f"https://huggingface.co/{repo}/resolve/main/{fname}", d / fname, progress, MODELS[name]["label"])
            return d / fname
        except Exception as exc:  # try the next mirror
            last = exc
            (d / fname).unlink(missing_ok=True)
    raise RuntimeError(f"Could not download {MODELS[name]['label']}: {last}")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LlamaServer:
    """Context manager: starts llama-server for one model, stops it afterwards."""

    def __init__(self, model: Path, server: Path, ctx: int = 4096):
        self.model, self.server, self.ctx = model, server, ctx
        self.proc = None
        self.port = 0

    def __enter__(self):
        self.port = _free_port()
        threads = max(2, (os.cpu_count() or 4) - 1)
        cmd = [str(self.server), "-m", str(self.model), "--host", "127.0.0.1", "--port", str(self.port),
               "-c", str(self.ctx), "-t", str(threads), "--no-webui"]
        if IS_MAC:
            cmd += ["-ngl", "99"]
        flags = 0x08000000 if IS_WINDOWS else 0
        log = open(root() / "llama-server.log", "w", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(self.server.parent),
                                     creationflags=flags)
        t0 = time.time()
        while time.time() - t0 < 300:
            if self.proc.poll() is not None:
                raise RuntimeError("The translation engine stopped while starting — see llama-server.log")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2) as r:
                    if json.loads(r.read()).get("status") == "ok":
                        return self
            except Exception:
                time.sleep(0.5)
        raise RuntimeError("The translation engine did not start in time")

    def complete(self, prompt: str, n_predict: int = 512, stop=("<end_of_turn>",)) -> str:
        body = json.dumps({"prompt": prompt, "n_predict": n_predict, "temperature": 0.0, "top_k": 1,
                           "stop": list(stop), "cache_prompt": True}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/completion", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read()).get("content", "")

    def __exit__(self, *exc):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except Exception:
                self.proc.kill()
        return False
