# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Create latest.json for a GitHub Release (SHA-256 of every asset + optional Ed25519 signature).

  python scripts/release/make_manifest.py --version 2.1.0 --base-url https://github.com/<owner>/<repo>/releases/download/v2.1.0 \
      --notes "What changed" --mac dist/VERBATIM-2.1.0-mac-arm64.dmg --win dist/VERBATIM-2.1.0-Setup.exe --src dist/VERBATIM-2.1.0-source.zip
Signing key: env VERBATIM_SIGNING_KEY (base64 Ed25519 private key from generate_signing_key.py).
"""
import argparse, base64, hashlib, json, os, sys
from datetime import date
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--version", required=True); ap.add_argument("--base-url", required=True)
ap.add_argument("--notes", default=""); ap.add_argument("--mac"); ap.add_argument("--win"); ap.add_argument("--src")
ap.add_argument("--out", default="dist/latest.json")
a = ap.parse_args()

def entry(p):
    p = Path(p); h = hashlib.sha256(p.read_bytes()).hexdigest()
    return {"url": f"{a.base_url.rstrip('/')}/{p.name}", "sha256": h, "size": p.stat().st_size}

assets = {}
if a.mac: assets["mac-arm64"] = entry(a.mac)
if a.win: assets["windows-x64"] = entry(a.win)
if a.src: assets["source"] = entry(a.src)
m = {"version": a.version, "date": date.today().isoformat(), "notes": a.notes, "assets": assets}
# Model channel: bump a model's "version" in packaging/models.json (and optionally add "notes",
# "recommended": true) to offer that model update to every installed copy — users are asked first.
models_file = Path(__file__).resolve().parents[2] / "packaging" / "models.json"
if models_file.exists():
    m["models"] = json.loads(models_file.read_text())
key = os.environ.get("VERBATIM_SIGNING_KEY")
if key:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    body = json.dumps(m, sort_keys=True, separators=(",", ":")).encode()
    m["signature"] = base64.b64encode(Ed25519PrivateKey.from_private_bytes(base64.b64decode(key)).sign(body)).decode()
Path(a.out).write_text(json.dumps(m, indent=2)); print(json.dumps(m, indent=2))
