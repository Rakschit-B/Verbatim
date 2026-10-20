# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Platform detection, user folders and bundled-tool discovery."""
from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

from . import APP_NAME

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = os.name == "nt"
IS_APPLE_SILICON = IS_MAC and platform.machine() == "arm64"
FROZEN = bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Folder containing bundled assets (PyInstaller-aware)."""
    if FROZEN and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def asset(name: str) -> Path:
    return resource_root() / "assets" / name


def user_data_dir() -> Path:
    if IS_MAC:
        base = Path.home() / "Library" / "Application Support"
    elif IS_WINDOWS:
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_dir() -> Path:
    d = user_data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_output_dir() -> Path:
    return Path.home() / "Documents" / "Infinite Story Transcripts"


def ffmpeg_path() -> str:
    """Prefer a system FFmpeg; fall back to the binary bundled with imageio-ffmpeg.

    The fallback means the packaged DMG/EXE works without Homebrew.
    """
    extra = ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"]
    found = shutil.which("ffmpeg") or next((p for p in extra if Path(p).exists()), None)
    if found:
        return found
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - depends on host
        raise RuntimeError(
            "FFmpeg not found. Install it (Mac: brew install ffmpeg) or reinstall VERBATIM."
        ) from exc
