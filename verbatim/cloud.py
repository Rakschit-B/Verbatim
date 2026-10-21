# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Optional Cloud GPU mode: send the heavy engines (voice cloning, singing, music, lip-sync, scorers) to a
VERBATIM Cloud GPU server you run yourself (engine_host/server.py — see cloud/README.md).

Everything else (transcription, editing, mixing, the Master Log) stays on this computer. Off by default.
"""
from __future__ import annotations

import base64
import json
import threading
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .platform_info import models_dir, user_data_dir

TOKEN_KEY = "cloud_gpu_token"
ENGINES = ("voice", "music", "lipsync")  # runtimes that can run in the cloud (lip-sync: cloud only)


@dataclass
class CloudConfig:
    enabled: bool = False
    url: str = ""                         # https://gpu.example.com  (or http://127.0.0.1:8765 over an SSH tunnel)
    engines: list = field(default_factory=lambda: list(ENGINES))
    timeout: int = 3600

    @staticmethod
    def path() -> Path:
        return user_data_dir() / "cloud.json"

    @classmethod
    def load(cls) -> "CloudConfig":
        try:
            d = json.loads(cls.path().read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self):
        self.path().write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


def token(value: str | None = None) -> str:
    from .tts_cloud import _kr

    return _kr(TOKEN_KEY, value)


def active_for(engine: str) -> bool:
    c = CloudConfig.load()
    return bool(c.enabled and c.url and engine in c.engines)


def _req(url: str, tok: str, body: bytes | None = None, timeout: int = 30):
    r = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET",
                               headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                                        "User-Agent": "VERBATIM"})
    return urllib.request.urlopen(r, timeout=timeout)


def health(url: str = "", tok: str = "") -> dict:
    """Ask the server who it is. Never raises: returns {"ok": False, "error": …} on failure."""
    c = CloudConfig.load()
    url = (url or c.url).rstrip("/")
    tok = tok or token()
    if not url:
        return {"ok": False, "error": "No server address set."}
    try:
        with _req(url + "/v1/health", tok, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read())
        except Exception:
            return {"ok": False, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


class RemoteHost:
    """Same interface as runtimes.EngineHost, but the work runs on the Cloud GPU server."""

    def __init__(self, name: str, cfg: CloudConfig | None = None):
        self.name = name
        self.cfg = cfg or CloudConfig.load()
        self.url = self.cfg.url.rstrip("/")
        self.tok = token()
        self.lock = threading.Lock()

    # -------------------------------------------------------------- argument packing
    def pack(self, kw: dict) -> tuple[dict, dict, dict]:
        """Returns (args, files, outs): local paths become @file / @out / @model markers."""
        files: dict = {}
        outs: dict = {}
        mroot = models_dir().resolve()
        n = [0]

        def conv(key, v):
            if isinstance(v, list):
                return [conv(key, x) for x in v]
            if isinstance(v, dict):
                return {k: conv(k, x) for k, x in v.items()}
            if not isinstance(v, str) or not v or len(v) > 4096:
                return v
            if key in ("out", "out_dir", "save_se") or key.endswith("_out"):
                n[0] += 1
                tag = f"o{n[0]}/{Path(v).name}"
                outs[tag] = v
                return "@out:" + tag
            try:
                p = Path(v)
                if not p.is_absolute():
                    return v
                rp = p.resolve()
            except (OSError, ValueError):
                return v
            if rp == mroot or mroot in rp.parents:
                return "@model:" + rp.relative_to(mroot).as_posix()
            if rp.is_file():
                n[0] += 1
                fid = f"f{n[0]}/{rp.name}"
                files[fid] = base64.b64encode(rp.read_bytes()).decode()
                return "@file:" + fid
            return v

        args = {k: conv(k, v) for k, v in kw.items()}
        return args, files, outs

    @staticmethod
    def unpack(res: dict, data: dict, outs: dict) -> dict:
        """Write returned files where the caller expects them and map server paths back."""
        for rel, b64 in data.items():
            tag = rel.split("/")[0]
            matches = [t for t in outs if t.split("/")[0] == tag]
            if not matches:
                continue
            t = matches[0]
            local = Path(outs[t])
            sub = rel[len(t):].lstrip("/") if rel.startswith(t) else ""
            dest = local / sub if sub else local
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(base64.b64decode(b64))
        text = json.dumps(res)
        for t, local in outs.items():
            text = text.replace(json.dumps("@out/" + t)[1:-1], json.dumps(str(local))[1:-1])
        return json.loads(text)

    # -------------------------------------------------------------- EngineHost interface
    def request(self, op: str, progress=None, **kw) -> dict:
        args, files, outs = self.pack(kw)
        body = json.dumps({"op": op, "args": args, "files": files}).encode()
        with self.lock:
            try:
                resp = _req(self.url + "/v1/run", self.tok, body, timeout=self.cfg.timeout)
            except urllib.error.HTTPError as exc:
                try:
                    msg = json.loads(exc.read()).get("error")
                except Exception:
                    msg = f"HTTP {exc.code}"
                raise RuntimeError(f"Cloud GPU: {msg}") from None
            except Exception as exc:
                raise RuntimeError(f"Cloud GPU unreachable ({exc}). Check Settings › Cloud GPU, or turn it off "
                                   "to run on this computer.") from None
            with resp:
                for raw in resp:
                    if not raw.strip():
                        continue
                    msg = json.loads(raw)
                    if "progress" in msg and "ok" not in msg:
                        if progress:
                            progress(float(msg["progress"]), "☁ " + msg.get("message", ""))
                        continue
                    if not msg.get("ok"):
                        raise RuntimeError("Cloud GPU: " + str(msg.get("error", "engine error")))
                    return {"ok": True, **self.unpack(msg.get("result", {}), msg.get("files", {}), outs)}
        raise RuntimeError("Cloud GPU: the connection closed before the job finished")

    def close(self):
        pass
