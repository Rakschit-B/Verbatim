# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Speech-model catalogue: bundled models, one-click downloads and model updates.

* NVIDIA Parakeet v2 (English) ships INSIDE the app — works offline from the first launch.
* Other models download once, on request or on first use (Hugging Face mirror first).
* Model updates are announced through the same release channel as app updates
  (`latest.json` → "models"). VERBATIM never downloads an update silently: it shows what
  is new and how big it is, and asks first.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .platform_info import IS_APPLE_SILICON, models_dir, resource_root

# version strings are compared as text (YYYY.MM[.N])
CATALOG: dict[str, dict] = {
    "parakeet-v2": {"kind": "sherpa", "name": "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8", "version": "2025.05",
                    "size_mb": 630, "label": "NVIDIA Parakeet v2 — English (bundled)"},
    "parakeet-v3": {"kind": "sherpa", "name": "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8", "version": "2025.08",
                    "size_mb": 640, "label": "NVIDIA Parakeet v3 — 25 European languages"},
    "whisper-turbo": {"kind": "whisper", "repo": "mlx-community/whisper-large-v3-turbo" if IS_APPLE_SILICON
                      else "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "version": "2024.10",
                      "size_mb": 1600, "label": "Whisper large-v3 turbo — Hindi & 99 languages"},
    "whisper-large-v3": {"kind": "whisper", "repo": "mlx-community/whisper-large-v3-mlx" if IS_APPLE_SILICON
                         else "Systran/faster-whisper-large-v3", "version": "2023.11", "size_mb": 3100,
                         "label": "Whisper large-v3 — most accurate multilingual"},
}


def bundled_root() -> Path:
    return resource_root() / "models"


def find_sherpa(name: str) -> Path | None:
    for root in (bundled_root() / "sherpa", models_dir() / "sherpa"):
        d = root / name
        if d.exists() and any(d.glob("*.onnx")) and any(d.glob("*tokens.txt")):
            return d
    return None


def _registry_path() -> Path:
    return models_dir() / "installed.json"


def installed_versions() -> dict:
    try:
        reg = json.loads(_registry_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        reg = {}
    for key, m in CATALOG.items():
        if key not in reg and m["kind"] == "sherpa" and find_sherpa(m["name"]):
            reg[key] = m["version"]
    return reg


def mark_installed(key: str, version: str) -> None:
    reg = installed_versions()
    reg[key] = version
    _registry_path().write_text(json.dumps(reg, indent=1), encoding="utf-8")


def is_installed(key: str) -> bool:
    m = CATALOG[key]
    if m["kind"] == "sherpa":
        return find_sherpa(m["name"]) is not None
    try:
        from huggingface_hub import try_to_load_from_cache

        return try_to_load_from_cache(m["repo"], "config.json") not in (None,)
    except Exception:
        return False


def download(key: str, progress=None, entry: dict | None = None) -> None:
    """Install or update one model (entry = an update record from the release manifest)."""
    m = dict(CATALOG[key], **(entry or {}))
    if m["kind"] == "sherpa":
        import shutil

        from .engines.sherpa import ensure_model

        target = models_dir() / "sherpa" / m["name"]
        if entry and target.exists():
            shutil.rmtree(target)  # replace with the newer files
        ensure_model(m["name"], models_dir() / "sherpa", progress)
    else:
        from huggingface_hub import snapshot_download

        if progress:
            progress(0.0, f"Downloading {m['label']} (one-time)…")
        snapshot_download(repo_id=m["repo"], etag_timeout=20)
    mark_installed(key, m["version"])


@dataclass
class ModelUpdate:
    key: str
    label: str
    version: str
    size_mb: int
    notes: str
    entry: dict


def updates_from_manifest(manifest: dict) -> list[ModelUpdate]:
    """Models whose manifest version is newer than what this computer has."""
    have = installed_versions()
    out = []
    for key, entry in (manifest.get("models") or {}).items():
        if key not in CATALOG or not isinstance(entry, dict) or "version" not in entry:
            continue
        current = have.get(key)
        if current is None and not entry.get("recommended"):
            continue  # not installed and not pushed to everyone
        if current is None or str(entry["version"]) > str(current):
            out.append(ModelUpdate(key, entry.get("label", CATALOG[key]["label"]), str(entry["version"]),
                                   int(entry.get("size_mb", CATALOG[key]["size_mb"])), entry.get("notes", ""), entry))
    return out
