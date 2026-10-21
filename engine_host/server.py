# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""VERBATIM Cloud GPU server — runs the same engines as engine_host/host.py on a GPU machine and serves
them to VERBATIM apps over HTTP(S).

    python server.py --models /data/verbatim-models --port 8765 --token <long random secret>

Put it behind HTTPS (Caddy / nginx / Cloudflare Tunnel) or reach it through an SSH tunnel. Every request
must carry `Authorization: Bearer <token>`. Nothing is kept after a request except the models.

Protocol
  GET  /v1/health                         → {"ok": true, "device": "cuda:0", "ops": [...], "version": ...}
  POST /v1/run   {"op": ..., "args": {...}, "files": {"f1": "<base64>", ...}}
       args may contain "@file:f1" (an uploaded input), "@out:o1/name.wav" (an output file or folder to
       return) and "@model:omnivoice" (a model folder on this server, fetched on first use).
       The response is a stream of JSON lines: {"progress": 0.4, "message": "…"} … then
       {"ok": true, "result": {...}, "files": {"o1/name.wav": "<base64>"}}  or  {"ok": false, "error": "…"}.
"""
from __future__ import annotations

import argparse
import base64
import hmac
import json
import os
import shutil
import sys
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

VERSION = "3.6"
MAX_BODY = 1024 * 1024 * 1024          # 1 GB of uploads per request

# model folder name → (Hugging Face repository, sub-folder, files to skip) fetched on first use;
# the layout matches the VERBATIM app's own models folder.
MODEL_REPOS = {
    "openvoice": [("myshell-ai/OpenVoiceV2", "", None)],
    "acestep": [("ACE-Step/Ace-Step1.5", "checkpoints", ["acestep-5Hz-lm-1.7B/*"]),
                ("ACE-Step/acestep-5Hz-lm-0.6B", "checkpoints/acestep-5Hz-lm-0.6B", None),
                ("ACE-Step/acestep-v15-sft", "checkpoints/acestep-v15-sft", None)],
    "emotion": [("superb/wav2vec2-base-superb-er", "", None)],
}

_RUN_LOCK = threading.Lock()           # one GPU job at a time; others queue


def resolve_model(models: Path, rel: str) -> str:
    rel = rel.strip("/\\").replace("\\", "/")
    if ".." in rel.split("/"):
        raise ValueError("bad model path")
    p = models / rel
    top = rel.split("/")[0]
    if top in MODEL_REPOS and not (models / top / ".complete").exists():
        from huggingface_hub import snapshot_download

        for repo, sub, skip in MODEL_REPOS[top]:
            snapshot_download(repo, local_dir=str(models / top / sub), ignore_patterns=skip)
        (models / top / ".complete").write_text("ok")
    return str(p)


def materialise(args, work: Path, files: dict, models: Path, outs: dict):
    """Replace @file / @out / @model markers with real paths on this server."""
    if isinstance(args, dict):
        return {k: materialise(v, work, files, models, outs) for k, v in args.items()}
    if isinstance(args, list):
        return [materialise(v, work, files, models, outs) for v in args]
    if isinstance(args, str):
        if args.startswith("@file:"):
            key = args[6:]
            name = Path(key).name or "input"
            p = work / "in" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(base64.b64decode(files[key]))
            return str(p)
        if args.startswith("@out:"):
            rel = args[5:].strip("/\\")
            if ".." in Path(rel).parts:
                raise ValueError("bad output path")
            p = work / "out" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            outs[rel] = p
            return str(p)
        if args.startswith("@model:"):
            return resolve_model(models, args[7:])
    return args


def collect(outs: dict, work: Path) -> dict:
    data = {}
    for rel, p in outs.items():
        if p.is_dir():
            for f in p.rglob("*"):
                if f.is_file():
                    data[f.relative_to(work / "out").as_posix()] = base64.b64encode(f.read_bytes()).decode()
        elif p.exists():
            data[rel] = base64.b64encode(p.read_bytes()).decode()
    return data


def make_handler(token: str, models: Path):
    import host

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"
        server_version = "VERBATIM-Cloud/" + VERSION

        def log_message(self, fmt, *a):
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % a))

        def _auth(self) -> bool:
            got = self.headers.get("Authorization", "")
            ok = got.startswith("Bearer ") and hmac.compare_digest(got[7:].strip(), token)
            if not ok:
                self._json(401, {"ok": False, "error": "Unauthorised — check the access token in VERBATIM Settings."})
            return ok

        def _json(self, code: int, obj: dict):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.rstrip("/") != "/v1/health":
                return self._json(404, {"ok": False, "error": "not found"})
            if not self._auth():
                return
            info = host.op_ping({}, 0)
            self._json(200, {"ok": True, "version": VERSION, "ops": sorted(host.OPS), "busy": _RUN_LOCK.locked(),
                             **info})

        def do_POST(self):
            if self.path.rstrip("/") != "/v1/run":
                return self._json(404, {"ok": False, "error": "not found"})
            if not self._auth():
                return
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BODY:
                return self._json(413, {"ok": False, "error": "request too large"})
            try:
                req = json.loads(self.rfile.read(n))
                op = req["op"]
                if op not in host.OPS or op in ("quit",):
                    raise KeyError(f"unknown op {op}")
            except Exception as exc:
                return self._json(400, {"ok": False, "error": f"bad request: {exc}"})
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()

            def line(obj):
                self.wfile.write((json.dumps(obj) + "\n").encode())
                self.wfile.flush()

            work = Path(tempfile.mkdtemp(prefix="verbatim-"))
            try:
                outs: dict = {}
                if _RUN_LOCK.locked():
                    line({"progress": 0.0, "message": "Waiting for the GPU (another job is running)…"})
                with _RUN_LOCK:
                    line({"progress": 0.01, "message": "Preparing on the cloud GPU…"})
                    args = materialise(req.get("args", {}), work, req.get("files", {}), models, outs)
                    old = host.send
                    host.send = lambda obj: line({k: v for k, v in obj.items() if k in ("progress", "message")}) \
                        if "progress" in obj else None
                    try:
                        res = host.OPS[op](args, 1)
                    finally:
                        host.send = old
                res = json.loads(json.dumps(res).replace(json.dumps(str(work / "out"))[1:-1], "@out"))
                line({"ok": True, "result": res, "files": collect(outs, work)})
            except Exception as exc:
                line({"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1500:]})
            finally:
                shutil.rmtree(work, ignore_errors=True)

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description="VERBATIM Cloud GPU server")
    ap.add_argument("--host", default=os.environ.get("VERBATIM_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("VERBATIM_PORT", "8765")))
    ap.add_argument("--models", default=os.environ.get("VERBATIM_MODELS", str(Path.home() / "verbatim-models")))
    ap.add_argument("--token", default=os.environ.get("VERBATIM_TOKEN", ""))
    a = ap.parse_args(argv)
    if len(a.token) < 24:
        sys.exit("Set a long access token (24+ characters): --token or VERBATIM_TOKEN")
    models = Path(a.models)
    models.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(a.token, models))
    sys.stderr.write(f"VERBATIM Cloud GPU {VERSION} listening on {a.host}:{a.port} · models in {models}\n")
    srv.serve_forever()


if __name__ == "__main__":
    main()
