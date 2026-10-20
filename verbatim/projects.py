# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Projects: group work by client or campaign.

A project has its own output folder (so its own Master Excel Log) and its own vocabulary.
Switching project switches both; "No project" uses the general settings.
Stored in the VERBATIM data folder as projects.json.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path


def store_path() -> Path:
    from .platform_info import user_data_dir

    return user_data_dir() / "projects.json"


def _folder_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", name).strip(" .") or "Project"


class Projects:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else store_path()
        try:
            self.items: list[dict] = json.loads(self.path.read_text(encoding="utf-8")).get("projects", [])
        except (OSError, ValueError):
            self.items = []

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "projects": self.items}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(self.path)

    def get(self, pid: str) -> dict | None:
        return next((p for p in self.items if p["id"] == pid), None)

    def create(self, name: str, base_output: str, vocabulary: str = "", client: str = "") -> dict:
        name = name.strip() or "Untitled project"
        out = Path(base_output) / _folder_name(name)
        now = datetime.now().isoformat(timespec="seconds")
        p = {"id": uuid.uuid4().hex[:10], "name": name, "client": client.strip(), "output_dir": str(out),
             "vocabulary": vocabulary, "created": now, "updated": now}
        self.items.append(p)
        self.save()
        return p

    def update(self, pid: str, **fields) -> dict | None:
        p = self.get(pid)
        if p:
            p.update({k: v for k, v in fields.items() if v is not None})
            p["updated"] = datetime.now().isoformat(timespec="seconds")
            self.save()
        return p

    def remove(self, pid: str) -> bool:
        """Removes the project from the list only — its transcripts and log stay on disk."""
        p = self.get(pid)
        if not p:
            return False
        self.items.remove(p)
        self.save()
        return True

    @staticmethod
    def stats(p: dict) -> dict:
        import sqlite3

        db = Path(p["output_dir"]) / ".verbatim" / "ledger.sqlite"
        if not db.exists():
            return {"files": 0, "hours": 0.0, "last": ""}
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            n, dur, last = con.execute("SELECT COUNT(*), COALESCE(SUM(duration),0), COALESCE(MAX(finished),'') "
                                       "FROM files WHERE status='Completed'").fetchone()
            con.close()
            return {"files": n, "hours": round(dur / 3600, 2), "last": last}
        except sqlite3.Error:
            return {"files": 0, "hours": 0.0, "last": ""}
