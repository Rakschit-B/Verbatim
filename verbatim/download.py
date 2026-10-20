# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Model downloads that cannot hang.

Lesson from a real run: a single urllib download from GitHub stalled for 8 hours with no
timeout, freezing the batch. Every download now has connect/read timeouts, retries with
resume (HTTP Range), progress, and a Hugging Face mirror tried first (fast CDN).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

Progress = Callable[[float, str], None]


def fetch(url: str, dest: Path, progress: Progress | None = None, label: str = "",
          retries: int = 6, timeout: tuple[int, int] = (20, 60)) -> Path:
    import requests

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    last_err: Exception | None = None
    for attempt in range(retries):
        have = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": "VERBATIM", **({"Range": f"bytes={have}-"} if have else {})}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=timeout, allow_redirects=True) as r:
                if r.status_code == 416 and part.exists():  # already complete
                    part.replace(dest)
                    return dest
                r.raise_for_status()
                if have and r.status_code != 206:  # server ignored Range: start over
                    have = 0
                    part.unlink(missing_ok=True)
                total = int(r.headers.get("Content-Length") or 0) + have
                done = have
                last_report = 0.0
                with open(part, "ab" if have else "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        done += len(chunk)
                        now = time.time()
                        if progress and total and now - last_report > 1.0:
                            last_report = now
                            progress(done / total, f"Downloading {label or dest.name} (one-time): "
                                                   f"{done / 1e6:.0f} of {total / 1e6:.0f} MB")
            if total and part.stat().st_size < total:
                raise IOError("download incomplete")
            part.replace(dest)
            return dest
        except Exception as exc:  # network hiccup: wait and resume
            last_err = exc
            time.sleep(min(30, 3 * (attempt + 1)))
    raise RuntimeError(f"Could not download {label or url}: {last_err}")


def hf_snapshot(repo_id: str, target: Path, progress: Progress | None = None, label: str = "",
                allow_patterns: list[str] | None = None) -> Path | None:
    """Try a Hugging Face mirror (usually much faster than GitHub release downloads)."""
    try:
        from huggingface_hub import snapshot_download

        if progress:
            progress(0.0, f"Downloading {label or repo_id} (one-time, fast mirror)…")
        path = snapshot_download(repo_id=repo_id, local_dir=str(target), etag_timeout=20,
                                 allow_patterns=allow_patterns or ["*.int8.onnx", "*tokens.txt"])
        return Path(path)
    except Exception:
        return None
