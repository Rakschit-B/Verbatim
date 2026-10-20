"""Self-updater.

Release channel = a `latest.json` manifest published with each GitHub Release:

    {"version": "2.1.0", "date": "2026-11-01", "notes": "…",
     "assets": {"mac-arm64":   {"url": ".../VERBATIM-2.1.0-mac-arm64.dmg", "sha256": "…"},
                "windows-x64": {"url": ".../VERBATIM-2.1.0-Setup.exe",   "sha256": "…"},
                "source":      {"url": ".../VERBATIM-2.1.0-source.zip",   "sha256": "…"}},
     "signature": "<base64 Ed25519 signature of the canonical manifest without this field>"}

Safety rules: HTTPS only; every download's SHA-256 must match; when a public key is
bundled (assets/update_public_key.txt) the manifest signature must verify, so a
tampered manifest or file is rejected. The previous version is kept for rollback.
Run modes:  VERBATIM --update [--check-only] [--auto] [--yes]
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import __version__
from .platform_info import FROZEN, IS_MAC, IS_WINDOWS, asset, user_data_dir


def parse_version(v: str) -> tuple:
    parts = []
    for p in v.strip().lstrip("v").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(num or 0))
    return tuple(parts + [0] * (3 - len(parts)))


def platform_key() -> str:
    if IS_MAC:
        return "mac-arm64" if platform.machine() == "arm64" else "mac-x64"
    if IS_WINDOWS:
        return "windows-x64"
    return "source"


@dataclass
class UpdateInfo:
    version: str
    notes: str
    url: str
    sha256: str
    manifest: dict


def canonical(manifest: dict) -> bytes:
    body = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def verify_signature(manifest: dict) -> bool:
    key_file = asset("update_public_key.txt")
    if not key_file.exists():
        return True  # signing not configured: SHA-256 + HTTPS still enforced
    pub = key_file.read_text().strip()
    if not pub:
        return True
    sig = manifest.get("signature")
    if not sig:
        return False
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub)).verify(base64.b64decode(sig), canonical(manifest))
        return True
    except Exception:
        return False


def _get(url: str, timeout: int = 30) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("Updates are only fetched over HTTPS")
    req = urllib.request.Request(url, headers={"User-Agent": f"VERBATIM/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_manifest(manifest_url: str) -> dict:
    manifest = json.loads(_get(manifest_url))
    if not verify_signature(manifest):
        raise RuntimeError("Update manifest signature is invalid — update refused.")
    return manifest


def check(manifest_url: str) -> UpdateInfo | None:
    manifest = json.loads(_get(manifest_url))
    if not verify_signature(manifest):
        raise RuntimeError("Update manifest signature is invalid — update refused.")
    if parse_version(manifest["version"]) <= parse_version(__version__):
        return None
    key = platform_key() if FROZEN else "source"
    a = manifest["assets"].get(key) or manifest["assets"].get("source")
    if not a:
        return None
    return UpdateInfo(manifest["version"], manifest.get("notes", ""), a["url"], a["sha256"].lower(), manifest)


def download(info: UpdateInfo, progress=None) -> Path:
    dest = user_data_dir() / "updates"
    dest.mkdir(parents=True, exist_ok=True)
    name = info.url.rsplit("/", 1)[-1]
    target = dest / name
    tmp = target.with_suffix(target.suffix + ".part")
    h = hashlib.sha256()
    req = urllib.request.Request(info.url, headers={"User-Agent": f"VERBATIM/{__version__}"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if progress and total:
                progress(got / total)
    if h.hexdigest() != info.sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Downloaded update failed its SHA-256 check — discarded.")
    tmp.replace(target)
    return target


def install(package: Path, info: UpdateInfo, relaunch: bool = True) -> str:
    """Install a verified package. Returns a human-readable result."""
    log = user_data_dir() / "update.log"
    if package.suffix == ".dmg" and IS_MAC:
        return _install_dmg(package, relaunch, log)
    if package.suffix == ".exe" and IS_WINDOWS:
        # Inno Setup: silent, closes the running app, keeps user data; relaunches when done.
        subprocess.Popen([str(package), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS", f"/LOG={log}"],
                         creationflags=0x00000008)  # DETACHED_PROCESS
        return "Installer started — VERBATIM will restart when it finishes."
    if package.suffix == ".zip":
        return _install_source(package, info)
    raise RuntimeError(f"Don't know how to install {package.name} on this platform")


def _install_dmg(dmg: Path, relaunch: bool, log: Path) -> str:
    app_now = Path(sys.executable).resolve().parents[2] if FROZEN else Path("/Applications/VERBATIM.app")
    script = tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False)
    script.write(f"""#!/bin/bash
exec >> "{log}" 2>&1
echo "== $(date) installing {dmg.name}"
while kill -0 {os.getpid()} 2>/dev/null || pgrep -f "VERBATIM.app/Contents/MacOS/VERBATIM$" >/dev/null; do sleep 2; done
MNT=$(mktemp -d)
hdiutil attach -nobrowse -quiet -mountpoint "$MNT" "{dmg}" || exit 1
NEW=$(ls -d "$MNT"/*.app | head -1)
DEST="{app_now}"
if [ -d "$DEST" ]; then rm -rf "$DEST.previous"; mv "$DEST" "$DEST.previous"; fi
ditto "$NEW" "$DEST" && xattr -dr com.apple.quarantine "$DEST" 2>/dev/null
hdiutil detach -quiet "$MNT"
if [ ! -d "$DEST" ] && [ -d "$DEST.previous" ]; then mv "$DEST.previous" "$DEST"; echo "rolled back"; fi
{"open " + chr(34) + "$DEST" + chr(34) if relaunch else ""}
""")
    script.close()
    os.chmod(script.name, 0o755)
    subprocess.Popen(["/bin/bash", script.name], start_new_session=True)
    return "Update will install as soon as VERBATIM closes (previous version kept as VERBATIM.app.previous)."


def _install_source(zip_path: Path, info: UpdateInfo) -> str:
    """Source installs: unpack beside the current folder, install deps, keep old copy."""
    here = Path(__file__).resolve().parents[1]
    parent = here.parent
    new_dir = parent / f"VERBATIM-{info.version}"
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            for m in z.namelist():
                if m.startswith("/") or ".." in Path(m).parts:
                    raise RuntimeError("Unsafe path in update archive")
            z.extractall(tmp)
        roots = [p for p in Path(tmp).iterdir() if p.is_dir()]
        src = roots[0] if len(roots) == 1 else Path(tmp)
        if new_dir.exists():
            shutil.rmtree(new_dir)
        shutil.copytree(src, new_dir)
    venv = here / ".venv"
    if venv.exists() and not (new_dir / ".venv").exists():
        py = venv / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
        subprocess.run([str(py), "-m", "pip", "install", "-q", "-r", str(new_dir / "requirements.txt")], check=False)
        try:
            (new_dir / ".venv").symlink_to(venv, target_is_directory=True)
        except OSError:
            shutil.copytree(venv, new_dir / ".venv", symlinks=True)
    (parent / "VERBATIM-current.txt").write_text(str(new_dir), encoding="utf-8")
    return f"Installed {info.version} into {new_dir}. Your previous version is untouched in {here}."


def gui_running() -> bool:
    """True if the VERBATIM desktop app (not this updater process) is open."""
    try:
        if IS_MAC:
            out = subprocess.run(["pgrep", "-f", "VERBATIM.app/Contents/MacOS/VERBATIM"], capture_output=True, text=True).stdout
            return any(int(p) != os.getpid() for p in out.split())
        if IS_WINDOWS:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq VERBATIM.exe"], capture_output=True, text=True).stdout
            return "VERBATIM.exe" in out
    except Exception:
        pass
    return False


def refresh_dependencies() -> str:
    """Source installs: upgrade Python packages within the pinned ranges."""
    if FROZEN:
        return "Packaged app: dependencies update with the app itself."
    req = Path(__file__).resolve().parents[1] / "requirements.txt"
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--upgrade", "-r", str(req)],
                       capture_output=True, text=True)
    return "Dependencies up to date." if r.returncode == 0 else "Dependency update failed: " + r.stderr[-300:]


def main(argv: list[str]) -> int:
    import argparse

    from .settings import Settings

    ap = argparse.ArgumentParser(prog="VERBATIM --update")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--auto", action="store_true", help="scheduled run: install without prompting")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--manifest", default=None)
    a = ap.parse_args(argv)
    s = Settings.load()
    url = a.manifest or s.update_manifest_url
    print(f"VERBATIM {__version__} — checking {url}")
    try:
        info = check(url)
    except Exception as exc:
        print("Could not check for updates:", exc)
        return 2
    s.last_update_check = datetime.now().isoformat(timespec="seconds")
    s.save()
    if not info:
        print("You have the latest version.")
        if not FROZEN:
            print(refresh_dependencies())
        return 0
    print(f"New version {info.version} available.\n{info.notes}")
    if a.check_only:
        return 10
    if a.auto and gui_running():
        print("VERBATIM is open — the app will offer this update in its banner instead.")
        return 0
    if not (a.yes or a.auto):
        if input("Install now? [y/N] ").strip().lower() not in ("y", "yes"):
            return 0
    pkg = download(info, lambda f: print(f"\r  downloading {f:5.1%}", end=""))
    print("\n  verified SHA-256 ✓")
    print(install(pkg, info))
    return 0
