# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
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

# Pinned, tested llama.cpp build. 3.4: the app ships llama-server inside (fully offline); this download is
# only the fallback for source installs. (3.3 looked for ".zip" assets — llama.cpp switched its Mac and
# Linux builds to ".tar.gz", which caused "Could not find the llama.cpp build for this computer".)
LLAMA_TAG = "b11750"
LLAMA_URL = "https://github.com/ggml-org/llama.cpp/releases/download/{tag}/llama-{tag}-bin-{suffix}"

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
    arm = platform.machine().lower() in ("arm64", "aarch64")
    if IS_MAC:
        return "macos-arm64.tar.gz" if arm else "macos-x64.tar.gz"
    if IS_WINDOWS:
        return "win-cpu-arm64.zip" if arm else "win-cpu-x64.zip"
    return "ubuntu-arm64.tar.gz" if arm else "ubuntu-x64.tar.gz"


def _exe() -> str:
    return "llama-server.exe" if IS_WINDOWS else "llama-server"


def bundled_server() -> Path | None:
    """llama-server shipped inside the VERBATIM app (resources/llama.cpp)."""
    from .platform_info import resource_root

    d = resource_root() / "llama.cpp"
    hits = sorted(d.rglob(_exe())) if d.exists() else []
    return hits[0] if hits else None


def server_path() -> Path | None:
    b = bundled_server()
    if b:
        return b
    hits = sorted((root() / "llama.cpp").rglob(_exe())) if (root() / "llama.cpp").exists() else []
    return hits[0] if hits else None


def _extract(archive: Path, dest: Path):
    import tarfile

    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                if name.startswith("/") or ".." in Path(name).parts:
                    raise RuntimeError("Unsafe path in llama.cpp archive")
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            for m in t.getmembers():
                if m.name.startswith("/") or ".." in Path(m.name).parts:
                    raise RuntimeError("Unsafe path in llama.cpp archive")
            try:
                t.extractall(dest, filter="data")
            except TypeError:
                t.extractall(dest)


def ensure_server(progress=None) -> Path:
    p = server_path()
    if p:
        return p
    from .download import fetch

    url = LLAMA_URL.format(tag=LLAMA_TAG, suffix=_asset_suffix())
    dest = root() / "llama.cpp"
    dest.mkdir(parents=True, exist_ok=True)
    tmp = root() / url.rsplit("/", 1)[-1]
    fetch(url, tmp, progress, "translation engine (llama.cpp)")
    _extract(tmp, dest)
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
        env = dict(os.environ)
        libdir = str(self.server.parent)
        for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            env[var] = libdir + (os.pathsep + env[var] if env.get(var) else "")
        if IS_WINDOWS:
            env["PATH"] = libdir + os.pathsep + env.get("PATH", "")
        self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=libdir, env=env,
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
