"""Voice consent register — required before any voice can be cloned (Voice Studio, Phase 4).

Each entry records who gave consent, the signed form (copied into the VERBATIM data folder so it
cannot be lost), what it covers, and when it expires. The register appears in every Master Excel
Log as the "Voice Consent" sheet. VERBATIM will refuse to clone a voice that has no valid entry.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path

SCOPES = ["Voiceover in other languages (dubbing)", "Voice cloning for this project only",
          "Voice cloning for all Infinite Story work", "Internal tests only"]


def folder() -> Path:
    from .platform_info import user_data_dir

    d = user_data_dir() / "consent"
    d.mkdir(parents=True, exist_ok=True)
    return d


class ConsentRegister:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else folder()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "register.json"
        try:
            self.entries: list[dict] = json.loads(self.path.read_text(encoding="utf-8")).get("entries", [])
        except (OSError, ValueError):
            self.entries = []

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "entries": self.entries}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, person: str, form_file: str | Path, scope: str, signed: str, expires: str = "",
            project: str = "", notes: str = "", recorded_by: str = "") -> dict:
        person = person.strip()
        if not person:
            raise ValueError("Name of the person is required")
        src = Path(form_file)
        if not src.exists():
            raise ValueError("Attach the signed consent form (PDF or photo)")
        eid = uuid.uuid4().hex[:10]
        dest = self.root / "forms" / f"{eid}{src.suffix.lower()}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        e = {"id": eid, "person": person, "scope": scope, "signed": signed, "expires": expires, "project": project,
             "notes": notes, "form": str(dest), "form_name": src.name,
             "form_sha256": hashlib.sha256(dest.read_bytes()).hexdigest(), "recorded": datetime.now().isoformat(timespec="seconds"),
             "recorded_by": recorded_by, "revoked": ""}
        self.entries.append(e)
        self.save()
        return e

    def revoke(self, eid: str, reason: str = ""):
        for e in self.entries:
            if e["id"] == eid:
                e["revoked"] = datetime.now().isoformat(timespec="seconds") + (f" — {reason}" if reason else "")
        self.save()

    @staticmethod
    def status(e: dict, today: date | None = None) -> str:
        today = today or date.today()
        if e.get("revoked"):
            return "Revoked"
        if e.get("expires"):
            try:
                if date.fromisoformat(e["expires"][:10]) < today:
                    return "Expired"
            except ValueError:
                pass
        return "Valid"

    def valid_for(self, person: str, cloning: bool = True) -> dict | None:
        key = person.strip().lower()
        for e in reversed(self.entries):
            if e["person"].strip().lower() == key and self.status(e) == "Valid":
                if cloning and "cloning" not in e["scope"].lower():
                    continue
                return e
        return None
