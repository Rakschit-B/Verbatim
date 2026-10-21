# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Engine runtimes — self-contained Python environments for the PyTorch engines.

The voice engines (OmniVoice, OpenVoice V2) and the music engine (ACE-Step 1.5) need PyTorch and library
versions that conflict with each other and would bloat the app, so each lives in its own runtime folder:
  <models>/runtimes/<name>/python   — a standalone CPython 3.12 (astral-sh/python-build-standalone)
  …/site-packages                    — that runtime's pinned packages
Setup is one click (Voice Lab / Music Studio › Engines), runs once, then everything is offline.
The engine code itself (engine_host/) ships inside VERBATIM; the runtime just provides the libraries.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tarfile
import threading
from pathlib import Path

from .platform_info import IS_MAC, IS_WINDOWS

PBS_TAG, PBS_PY = "20261013", "3.12.15"
RUNTIME_REV = 2      # bump to rebuild every runtime (3.5.1: clean environment for pip, see _clean_env)
PBS_URL = ("https://github.com/astral-sh/python-build-standalone/releases/download/"
           "{tag}/cpython-{py}+{tag}-{arch}-install_only.tar.gz")

_TORCH = ["torch==2.9.0", "torchaudio==2.9.0"]
RUNTIMES = {
    "voice": {"label": "Voice engines — OmniVoice, OpenVoice V2, quality scoring",
              "size_mb": 1400,
              "packages": _TORCH + ["transformers>=5.3,<6", "accelerate>=1.10", "safetensors", "librosa>=0.10",
                                    "soundfile", "numpy<2.4", "omnivoice==0.2.1", "pydub"],
              "no_deps": ["omnivoice==0.2.1"],
              "check": ["torch", "torchaudio", "transformers", "librosa", "soundfile", "omnivoice"]},
    "music": {"label": "Music engine — ACE-Step 1.5",
              "size_mb": 2200,
              "packages": _TORCH + ["transformers>=4.51,<4.58", "diffusers", "accelerate>=1.10", "einops",
                                    "safetensors", "soundfile", "scipy", "loguru", "numba", "toml", "tqdm",
                                    "pyyaml", "peft>=0.18", "vector-quantize-pytorch>=1.27", "librosa",
                                    "huggingface_hub", "xxhash"]
                                   + (["mlx>=0.25.2", "mlx-lm>=0.20"] if IS_MAC and platform.machine() == "arm64" else []),
              "check": ["torch", "torchaudio", "transformers", "diffusers", "loguru", "tqdm", "yaml", "soundfile",
                        "einops", "vector_quantize_pytorch"],
              "source": ("https://github.com/ace-step/ACE-Step-1.5/archive/{commit}.zip",
                         "ca1e85fe9430179831e6bc6be790c332190a3866")},
}


def root() -> Path:
    from .platform_info import models_dir

    return models_dir() / "runtimes"


def _arch() -> str:
    m = platform.machine().lower()
    if IS_MAC:
        return "aarch64-apple-darwin" if m == "arm64" else "x86_64-apple-darwin"
    if IS_WINDOWS:
        return "x86_64-pc-windows-msvc"
    return "aarch64-unknown-linux-gnu" if m in ("aarch64", "arm64") else "x86_64-unknown-linux-gnu"


def python_exe(name: str) -> Path:
    base = root() / name / "python"
    return base / ("python.exe" if IS_WINDOWS else "bin/python3")


def host_script() -> Path:
    from .platform_info import resource_root

    for p in (resource_root() / "engine_host" / "host.py", resource_root() / "app" / "engine_host" / "host.py",
              Path(__file__).resolve().parents[1] / "engine_host" / "host.py"):
        if p.exists():
            return p
    raise FileNotFoundError("engine_host/host.py is missing from this VERBATIM installation")


def marker(name: str) -> Path:
    return root() / name / "ready.json"


def wanted_signature(name: str) -> str:
    spec = RUNTIMES[name]
    return json.dumps([RUNTIME_REV, PBS_PY, spec["packages"], spec.get("source", "")], sort_keys=True)


def _clean_env(extra: dict | None = None) -> dict:
    """Environment for a runtime's own Python. VERBATIM's launcher sets PYTHONHOME/PYTHONPATH for the app's
    bundled Python; if those leak into the runtime, pip installs packages somewhere the engine never looks
    (3.5.0: "No module named 'loguru'"). Strip them and keep user site-packages out."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE", "VIRTUAL_ENV",
                        "PYTHONEXECUTABLE", "__PYVENV_LAUNCHER__", "PIP_TARGET", "PIP_PREFIX", "PIP_USER")}
    env.update(PYTHONNOUSERSITE="1", PYTHONUNBUFFERED="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    env.update(extra or {})
    return env


def is_ready(name: str) -> bool:
    override = os.environ.get(f"VERBATIM_RUNTIME_{name.upper()}")   # developer machines: an existing python
    if override:
        return True
    try:
        return json.loads(marker(name).read_text())["sig"] == wanted_signature(name) and python_exe(name).exists()
    except (OSError, ValueError, KeyError):
        return False


def interpreter(name: str) -> str:
    return os.environ.get(f"VERBATIM_RUNTIME_{name.upper()}") or str(python_exe(name))


def ensure(name: str, progress=None) -> str:
    """Create (once) the runtime `name`. Returns the interpreter path."""
    if is_ready(name):
        return interpreter(name)
    from .download import fetch

    spec = RUNTIMES[name]
    d = root() / name
    d.mkdir(parents=True, exist_ok=True)
    say = progress or (lambda f, m: None)
    if not python_exe(name).exists():
        url = PBS_URL.format(tag=PBS_TAG, py=PBS_PY, arch=_arch())
        tgz = d / "python.tar.gz"
        fetch(url, tgz, (lambda f, m: say(0.1 * f, m)), "Python runtime")
        with tarfile.open(tgz) as t:
            for m in t.getmembers():
                if m.name.startswith("/") or ".." in Path(m.name).parts:
                    raise RuntimeError("Unsafe path in the Python runtime archive")
            try:
                t.extractall(d, filter="tar")
            except TypeError:
                t.extractall(d)
        tgz.unlink(missing_ok=True)
    py = str(python_exe(name))
    flags = 0x08000000 if IS_WINDOWS else 0
    no_deps = set(spec.get("no_deps", []))
    groups = [[p for p in spec["packages"] if p not in no_deps]] + ([sorted(no_deps)] if no_deps else [])
    for gi, pkgs in enumerate(groups):
        cmd = [py, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
               "--progress-bar", "off", *(["--no-deps"] if gi == 1 else []), *pkgs]
        say(0.12 + 0.75 * gi / len(groups), f"Installing {spec['label']} libraries (one time)…")
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                             creationflags=flags, env=_clean_env())
        tail = []
        for line in p.stdout:
            line = line.strip()
            tail = (tail + [line])[-12:]
            if line.startswith(("Collecting", "Downloading", "Installing")):
                say(0.12 + 0.75 * gi / len(groups), line[:110])
        if p.wait() != 0:
            raise RuntimeError("Could not install the engine libraries:\n" + "\n".join(tail))
    if spec.get("source"):
        _fetch_source(name, spec["source"], say)
    check = spec.get("check") or []
    if check:   # prove the engine's libraries import from the runtime itself before declaring it ready
        r = subprocess.run([py, "-c", "import " + ", ".join(check)], capture_output=True, text=True,
                           env=_clean_env(), creationflags=flags)
        if r.returncode != 0:
            raise RuntimeError("Engine libraries installed but cannot be imported:\n" + r.stderr[-800:])
    marker(name).write_text(json.dumps({"sig": wanted_signature(name)}))
    say(1.0, f"{spec['label']} ready")
    return py


def _fetch_source(name: str, source, say):
    import zipfile

    from .download import fetch

    url_t, commit = source
    d = root() / name / "src"
    if (d / commit / ".ok").exists():
        return
    z = root() / name / "src.zip"
    fetch(url_t.format(commit=commit), z, (lambda f, m: say(0.88 + 0.1 * f, m)), "engine source")
    with zipfile.ZipFile(z) as zf:
        for m in zf.namelist():
            if m.startswith("/") or ".." in Path(m).parts:
                raise RuntimeError("Unsafe path in engine source")
        zf.extractall(d / commit)
    z.unlink(missing_ok=True)
    (d / commit / ".ok").write_text("ok")


def source_dir(name: str) -> Path | None:
    spec = RUNTIMES[name]
    if not spec.get("source"):
        return None
    env = os.environ.get(f"VERBATIM_SOURCE_{name.upper()}")
    if env:
        return Path(env)
    base = root() / name / "src" / spec["source"][1]
    subs = [p for p in base.iterdir() if p.is_dir()] if base.exists() else []
    return subs[0] if len(subs) == 1 else base


# ====================================================================== client
class EngineHost:
    """Talks to engine_host/host.py running inside a runtime. Thread-safe; one request at a time."""
    _hosts: dict = {}

    @classmethod
    def get(cls, name: str, progress=None) -> "EngineHost":
        h = cls._hosts.get(name)
        if h is None or h.proc.poll() is not None:
            py = ensure(name, progress)
            h = cls._hosts[name] = EngineHost(py, name)
        return h

    def __init__(self, python: str, name: str = ""):
        flags = 0x08000000 if IS_WINDOWS else 0
        env = _clean_env({"TOKENIZERS_PARALLELISM": "false", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                          "PYTORCH_ENABLE_MPS_FALLBACK": "1"})
        src = source_dir(name) if name in RUNTIMES else None
        if src:
            env["PYTHONPATH"] = str(src)
        self.log = open(root().parent / f"engine-{name or 'host'}.log", "a", encoding="utf-8", errors="replace") \
            if root().parent.exists() else subprocess.DEVNULL
        self.proc = subprocess.Popen([python, "-u", str(host_script())], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self.log, text=True, encoding="utf-8",
                                     bufsize=1, creationflags=flags, env=env)
        self.lock = threading.Lock()
        self.n = 0
        first = json.loads(self.proc.stdout.readline() or "{}")
        if not first.get("ready"):
            raise RuntimeError(f"The {name or 'engine'} runtime did not start — see engine-{name}.log")

    def request(self, op: str, progress=None, **kw) -> dict:
        with self.lock:
            self.n += 1
            rid = self.n
            self.proc.stdin.write(json.dumps({"id": rid, "op": op, **kw}) + "\n")
            self.proc.stdin.flush()
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    raise RuntimeError("The engine stopped unexpectedly — see the engine log in the data folder")
                msg = json.loads(line)
                if msg.get("id") != rid:
                    continue
                if "progress" in msg:
                    if progress:
                        progress(float(msg["progress"]), msg.get("message", ""))
                    continue
                if not msg.get("ok"):
                    raise RuntimeError(msg.get("error", "engine error"))
                return msg

    def close(self):
        try:
            self.request("quit")
        except Exception:
            pass
        if self.proc.poll() is None:
            self.proc.terminate()

    @classmethod
    def shutdown(cls):
        for h in list(cls._hosts.values()):
            h.close()
        cls._hosts.clear()


def dev_runtime_from_current_python() -> bool:
    """Tests/dev: use the interpreter running VERBATIM when it already has torch."""
    try:
        import importlib.util

        return importlib.util.find_spec("torch") is not None and sys.executable is not None
    except Exception:
        return False
