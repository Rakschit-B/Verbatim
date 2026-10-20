# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""VERBATIM desktop app (PySide6 / Qt) — Mac and Windows.

Layout: header (logo, modules, updates) · left navigation · centre (drop zone + file table, or a page)
· right panel (Settings / Speakers / Vocabulary / Output tabs + Start). Modules: 01 Transcribe and
02 Voice Studio (gui_voice.py) are live; 03 Video Localise shows a "Coming soon" label only.
"""
from __future__ import annotations

import getpass
import math
import sqlite3
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QDesktopServices, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog,
                               QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QProgressDialog, QPushButton,
                               QScrollArea, QSizePolicy, QStackedWidget, QTableWidget, QTableWidgetItem, QToolButton,
                               QVBoxLayout, QWidget)

from . import __version__
from . import ui_theme as th
from .audio import MEDIA_EXTENSIONS
from .engines import ENGINE_CHOICES
from .platform_info import IS_WINDOWS, asset, ffmpeg_path, resource_root, user_data_dir
from .settings import FORMATS, LANGUAGES, Settings

T: dict = th.LIGHT  # current theme tokens
CODE_TO_LANG = {v: k for k, v in LANGUAGES.items() if v}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv", ".mts", ".m2ts", ".3gp"}
ENH_VALUES = ["normalize", "off", "clean", "restore"]
ENH_LABELS = ["Standard – fix volume (recommended)", "Off – untouched audio", "Clean – filter hum & hiss",
              "Restore audio (AI) – only for poor recordings"]
REVIEW_LABELS = ["Light (≈1% of words flagged)", "Standard (≈3–9% flagged)", "Thorough (≈7–13% flagged)"]
REVIEW_VALUES = (0.5, 0.8, 0.95)


# ====================================================================== small helpers
def hms(sec: float | None) -> str:
    if not sec:
        return "—"
    sec = int(round(sec))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB", "MB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def when(d: datetime) -> str:
    today = datetime.now().date()
    t = d.strftime("%I:%M %p")
    if d.date() == today:
        return f"Today, {t}"
    if d.date() == today - timedelta(days=1):
        return f"Yesterday, {t}"
    return d.strftime("%d %b %Y, ") + t


def classify(frac: float, msg: str) -> str:
    if msg.startswith(("Completed", "Already")):
        return "ready"
    if msg.startswith("Failed"):
        return "failed"
    if msg.startswith("Not started"):
        return "stopped"
    if "speech-minutes" in msg or msg.startswith(("Uploading", "Scribe")):
        return "transcribing"
    return "processing"


STATUS_TEXT = {"queued": "Queued", "transcribing": "Transcribing", "processing": "Processing", "ready": "Ready",
               "failed": "Failed", "stopped": "Stopped"}


def open_path(p: str | Path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))


def hline() -> QFrame:
    f = QFrame()
    f.setObjectName("hline")
    return f


def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def card() -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    return f


class Icons:
    """Remembers which widget shows which icon so a theme switch can recolour them all."""

    def __init__(self):
        self.items: list[tuple] = []

    def set(self, w, name: str, role: str = "ink", size: int = 20):
        self.items.append((w, name, role, size))
        self._apply(w, name, role, size)

    def _apply(self, w, name, role, size):
        color = T.get(role, role)
        if isinstance(w, QLabel):
            w.setPixmap(th.pixmap(name, color, size))
        else:
            w.setIcon(th.icon(name, color, size))
            w.setIconSize(QSize(size, size))

    def refresh(self):
        alive = []
        for it in self.items:
            try:
                self._apply(*it)
                alive.append(it)
            except RuntimeError:  # widget deleted
                pass
        self.items = alive


ICONS = Icons()


# ====================================================================== custom widgets
class Toggle(QCheckBox):
    """iOS-style switch."""

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(26)

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(s.width() + 26, max(26, s.height()))

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = 20
        y = (self.height() - h) / 2
        track = QRectF(0, y, 36, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T["accent"] if self.isChecked() else T["field_border"]))
        p.drawRoundedRect(track, h / 2, h / 2)
        p.setBrush(QColor("white"))
        x = 18 if self.isChecked() else 2
        p.drawEllipse(QRectF(x, y + 2, h - 4, h - 4))
        p.setPen(QColor(T["ink"]))
        p.drawText(QRectF(48, 0, self.width() - 48, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())


class ModulePill(QFrame):
    def __init__(self, on_click):
        super().__init__()
        self.on_click = on_click

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.on_click()


class DropZone(QFrame):
    """The big 'Drop your videos…' card with painted silk waves."""
    dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.hover = False
        self.setMinimumHeight(250)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            self.hover = True
            self.update()
            e.acceptProposedAction()

    def dragLeaveEvent(self, _):
        self.hover = False
        self.update()

    def dropEvent(self, e):
        self.hover = False
        self.update()
        self.dropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        clip = QPainterPath()
        clip.addRoundedRect(r, 20, 20)
        p.setClipPath(clip)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor(T["drop_a"]))
        g.setColorAt(1, QColor(T["drop_b"]))
        p.fillRect(r, g)
        w, h = r.width(), r.height()
        k = T["wave"]
        bands = [  # (baseline, amplitude, frequency, phase, colours)
            (0.62, 0.10, 1.1, 0.4, [(0, "#7F9BFF", 70), (0.5, "#C9A7FF", 60), (1, "#FFC2D9", 70)]),
            (0.72, 0.08, 0.9, 2.1, [(0, "#A7C1FF", 80), (0.6, "#E3B8F5", 70), (1, "#FFD6C2", 90)]),
            (0.82, 0.06, 1.3, 4.0, [(0, "#C4D3FF", 90), (0.5, "#F2C6EA", 80), (1, "#FFE1CC", 100)]),
        ]
        for base, amp, freq, phase, stops in bands:
            path = QPainterPath()
            path.moveTo(r.left(), r.bottom())
            for i in range(0, 61):
                x = r.left() + w * i / 60
                y = r.top() + h * (base + amp * math.sin(2 * math.pi * freq * i / 60 + phase))
                path.lineTo(x, y)
            path.lineTo(r.right(), r.bottom())
            path.closeSubpath()
            lg = QLinearGradient(r.left(), 0, r.right(), 0)
            for pos, col, a in stops:
                c = QColor(col)
                c.setAlpha(int(a * k))
                lg.setColorAt(pos, c)
            p.fillPath(path, lg)
        pen = QPen(QColor(255, 255, 255, 150 if T['name'] == 'light' else 34), 1.2)
        p.setPen(pen)
        for j in range(7):  # silk lines
            path = QPainterPath()
            for i in range(0, 61):
                x = r.left() + w * i / 60
                y = r.top() + h * (0.55 + 0.012 * j + 0.13 * math.sin(2 * math.pi * 0.8 * i / 60 + 1.2 + 0.18 * j))
                path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
            p.drawPath(path)
        p.setClipping(False)
        p.setBrush(Qt.NoBrush)
        if self.hover:
            p.setPen(QPen(QColor(T["accent"]), 2, Qt.DashLine))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 200) if T["name"] == "light" else QColor(T["border"]), 1.5))
        p.drawRoundedRect(r, 20, 20)


class UploadBadge(QLabel):
    def __init__(self):
        super().__init__()
        self.setFixedSize(96, 96)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 110 if T["name"] == "light" else 30))
        p.drawEllipse(QRectF(0, 0, 96, 96))
        g = QLinearGradient(QPointF(12, 12), QPointF(84, 84))
        g.setColorAt(0, QColor("#F6F4FF" if T["name"] == "light" else "#2C2A55"))
        g.setColorAt(1, QColor("#E2DCFF" if T["name"] == "light" else "#3A2B5C"))
        p.setBrush(g)
        p.setPen(QPen(QColor(255, 255, 255, 220) if T["name"] == "light" else QColor(T["border"]), 1.2))
        p.drawEllipse(QRectF(12, 12, 72, 72))
        p.drawPixmap(33, 33, th.pixmap("upload", T["ink"], 30))


class Thumb(QLabel):
    def __init__(self, video: bool):
        super().__init__()
        self.setFixedSize(76, 44)
        self.video = video
        self.img: QPixmap | None = None

    def set_image(self, data: bytes):
        px = QPixmap()
        if px.loadFromData(data):
            self.img = px
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(0, 0, 76, 44)
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        p.setClipPath(path)
        if self.img:
            s = self.img.scaled(152, 88, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            s.setDevicePixelRatio(2)
            p.drawPixmap(int((76 - s.width() / 2) / 2), int((44 - s.height() / 2) / 2), s)
        else:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, QColor("#DCE4FF" if T["name"] == "light" else "#2A3160"))
            g.setColorAt(1, QColor("#F5DDF2" if T["name"] == "light" else "#45285A"))
            p.fillRect(r, g)
            p.drawPixmap(26, 10, th.pixmap("film" if self.video else "wave", T["sub"], 24))


# ====================================================================== workers
class BatchWorker(QObject):
    status = Signal(str, float, str)
    result = Signal(str, dict)
    finished = Signal(dict)

    def __init__(self, files, settings):
        super().__init__()
        from .pipeline import BatchRunner

        self.runner = BatchRunner(files, settings, lambda n, f, m: self.status.emit(n, f, m), self._result)

    def _result(self, name, res):
        t = res.transcript
        self.result.emit(name, {"language": getattr(t, "language", "") if t else "",
                                "duration": res.info.get("duration", 0), "outputs": dict(res.outputs or {})})

    def run(self):
        try:
            self.finished.emit(self.runner.run())
        except Exception as exc:
            self.finished.emit({"error": str(exc), "completed": 0, "failed": 0, "skipped": 0, "excel": ""})


class MetaLoader(QObject):
    """Reads duration and a video frame for each added file (one background thread, never blocks the UI)."""
    ready = Signal(str, float, bytes)

    def __init__(self):
        super().__init__()
        self.q: Queue = Queue()
        threading.Thread(target=self._loop, daemon=True).start()

    def add(self, path: Path):
        self.q.put(path)

    def _loop(self):
        from .audio import probe

        flags = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW
        while True:
            path = self.q.get()
            dur, png = 0.0, b""
            try:
                dur = probe(path).duration
            except Exception:
                pass
            if path.suffix.lower() in VIDEO_EXT:
                try:
                    ss = f"{min(max(dur * 0.1, 0), 30):.2f}" if dur > 2 else "0"
                    r = subprocess.run([ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", ss,
                                        "-i", str(path), "-frames:v", "1", "-vf", "scale=200:-2", "-f", "image2pipe",
                                        "-vcodec", "png", "-"], capture_output=True, timeout=40, creationflags=flags)
                    png = r.stdout if r.returncode == 0 else b""
                except Exception:
                    pass
            self.ready.emit(str(path), float(dur or 0), png)


class UpdateWorker(QObject):
    """Asks GitHub (public releases, no login) whether a newer VERBATIM exists."""
    status = Signal(object)          # updater.ChannelStatus
    models_found = Signal(list)
    finished = Signal()

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            from .updater import check_github

            st = check_github(self.url)
            self.status.emit(st)
            if st.latest:
                from .models import updates_from_manifest
                from .updater import fetch_manifest

                ups = updates_from_manifest(fetch_manifest(st.url))
                if ups:
                    self.models_found.emit(ups)
        except Exception:
            pass
        self.finished.emit()


class InstallWorker(QObject):
    """Downloads the verified installer in the background, then hands it to the installer."""
    progress = Signal(int)
    done = Signal(bool, str)

    def __init__(self, info):
        super().__init__()
        self.info = info

    def run(self):
        from .updater import download, install

        try:
            pkg = download(self.info, lambda f: self.progress.emit(int(f * 100)))
            self.done.emit(True, install(pkg, self.info))
        except Exception as exc:
            self.done.emit(False, str(exc))


class ModelWorker(QObject):
    """Downloads models in the background (never during a batch)."""
    progress = Signal(str)
    done = Signal(str)

    def __init__(self, jobs):
        super().__init__()
        self.jobs = jobs  # [(key, entry-or-None)]

    def run(self):
        from . import llm, tts
        from .models import CATALOG, download

        ok = []
        for key, entry in self.jobs:
            label = extra_model_label(key) or CATALOG[key]["label"]
            try:
                last = [0.0]

                def cb(f, m, last=last):
                    if f - last[0] >= 0.05 or f >= 1:
                        last[0] = f
                        self.progress.emit(m)
                if key == "sep-uvr":
                    from .voicelab import uvr_model

                    uvr_model(cb)
                elif key.startswith("tts-"):
                    tts.ensure(key[4:], cb)
                elif key.startswith("llm-"):
                    llm.ensure_server(cb)
                    llm.ensure_model(key[4:], cb)
                else:
                    download(key, cb, entry)
                ok.append(label)
            except Exception as exc:
                self.progress.emit(f"Could not download {label}: {exc}")
        self.done.emit(", ".join(ok))


def extra_model_label(key: str) -> str:
    from . import llm, tts

    if key == "tts-cb":
        return "Expressive voices & voice cloning — Chatterbox Multilingual"
    if key == "sep-uvr":
        return "Voice / music separation — UVR MDX-Net"
    if key.startswith("tts-"):
        return f"Voice Studio voices — {tts.ENGINES[key[4:]]['label']}"
    if key.startswith("llm-"):
        return f"Offline translation — {llm.MODELS[key[4:]]['label']}"
    return ""


# ====================================================================== queue model
@dataclass
class Row:
    path: Path
    added: datetime
    size: int = 0
    duration: float = 0.0
    language: str = ""
    state: str = "queued"
    frac: float = 0.0
    message: str = "Waiting to start"
    outputs: dict = field(default_factory=dict)
    thumb: bytes = b""
    checked: bool = False
    w: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return str(self.path)


# ====================================================================== main window
class Window(QMainWindow):
    NAV = [("Transcribe", "home"), ("Files", "file"), ("Projects", "projects"), ("Speakers", "users"),
           ("Vocabulary", "vocab"), ("Output", "output"), ("Activity Log", "clock"), ("Settings", "gear")]
    TABS = ["Settings", "Speakers", "Vocabulary", "Output"]

    def __init__(self):
        super().__init__()
        self.s = Settings.load()
        self.rows: list[Row] = []
        self.by_key: dict[str, Row] = {}
        self.thread = None
        self.running = False
        self.sort_key = "added"
        self.setWindowTitle(f"VERBATIM {__version__} — an Infinite Story LLP product")
        scr = QApplication.primaryScreen().availableGeometry() if QApplication.primaryScreen() else None
        self.resize(min(1560, int(scr.width() * 0.94)) if scr else 1480, min(980, int(scr.height() * 0.92)) if scr else 940)
        self.setMinimumSize(1180, 720)
        self.icons = ICONS
        self.apply_theme(first=True)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(26, 18, 26, 18)
        outer.setSpacing(14)
        outer.addLayout(self._header())
        self.banner = self._banner()
        outer.addWidget(self.banner)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self._nav())
        self.right = self._right_panel()  # built first: pages mirror some of its controls
        self.pages = QStackedWidget()
        self.pages.addWidget(self._transcribe_page())   # 0
        self.pages.addWidget(self._library_page())      # 1
        self.pages.addWidget(self._projects_page())     # 2
        self.pages.addWidget(self._log_page())          # 3
        self.pages.addWidget(self._app_settings_page())  # 4
        self.pages.addWidget(self._speakers_page())     # 5
        from .gui_voice import VoiceStudio

        self.voice = VoiceStudio(self)                   # 6 — module 02
        self.voice.log.connect(self.say)
        self.pages.addWidget(self.voice)
        body.addWidget(self.pages, 1)
        body.addWidget(self.right)
        outer.addLayout(body, 1)

        self.meta = MetaLoader()
        self.meta.ready.connect(self.on_meta)
        self.select_nav(0)
        self.refresh_table()
        self.update_project_ui()
        if self.s.auto_check_updates:
            QTimer.singleShot(2500, self.check_updates)

    # ------------------------------------------------------------------ theme
    def theme_tokens(self) -> dict:
        mode = self.s.theme
        if mode == "system":
            try:
                dark = QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
            except Exception:
                dark = False
            return th.DARK if dark else th.LIGHT
        return th.DARK if mode == "dark" else th.LIGHT

    def apply_theme(self, first: bool = False):
        global T
        T = self.theme_tokens()
        img = th.write_qss_images(user_data_dir() / "ui", T)
        self.setStyleSheet(th.stylesheet(T, img))
        if first:
            return
        ICONS.refresh()
        self.set_logo()
        for r in self.rows:
            self.paint_row(r)
        self.update()
        for w in self.findChildren(QWidget):
            w.update()

    def set_logo(self):
        name = "verbatim_by_story_dark.png" if T["name"] == "dark" else "verbatim_by_story.png"
        p = asset(name)
        if p.exists():
            px = QPixmap(str(p))
            dpr = 2.0
            px = px.scaledToHeight(int(50 * dpr), Qt.SmoothTransformation)
            px.setDevicePixelRatio(dpr)
            self.logo.setPixmap(px)
        else:
            self.logo.setText("VERBATIM")

    # ------------------------------------------------------------------ header
    def _header(self):
        h = QHBoxLayout()
        h.setSpacing(18)
        brand = QVBoxLayout()
        brand.setSpacing(4)
        self.logo = QLabel()
        self.set_logo()
        brand.addWidget(self.logo)
        tag = label("EVERY WORD.  EVERY MOMENT.", "tagline")
        tag.setContentsMargins(70, 0, 0, 0)
        brand.addWidget(tag)
        h.addLayout(brand)
        h.addSpacing(24)
        h.addLayout(self._modules())
        h.addStretch()
        self.subtitle = label("Accurate batch transcription with a full audit trail.", "sub")
        h.addWidget(self.subtitle)
        upd = QPushButton("  Check for updates")
        self.upd_btn = upd
        upd.setToolTip("VERBATIM checks GitHub for new versions. Nothing installs without your OK.")
        upd.setObjectName("pillBtn")
        upd.setCursor(Qt.PointingHandCursor)
        ICONS.set(upd, "download", "ink", 16)
        upd.clicked.connect(self.header_update_clicked)
        h.addWidget(upd)
        user = (getpass.getuser() or "V").strip()
        av = label(user[:1].upper(), "avatar")
        av.setFixedSize(44, 44)
        av.setAlignment(Qt.AlignCenter)
        av.setToolTip(f"{user} — VERBATIM {__version__} · © 2026 Infinite Story LLP")
        h.addWidget(av)
        return h

    def _modules(self):
        row = QHBoxLayout()
        row.setSpacing(6)
        mods = [("01", "TRANSCRIBE", True), ("02", "VOICE STUDIO", True), ("03", "VIDEO LOCALISE", False)]
        self.mod_widgets = []
        for k, (num, name, live) in enumerate(mods):
            f = ModulePill(lambda k=k: self.select_module(k)) if live else QFrame()
            f.setObjectName("module")
            lay = QHBoxLayout(f)
            lay.setContentsMargins(12, 8, 12, 8)
            lay.setSpacing(8)
            n = label(num, "modNum")
            nm = label(name, "modName")
            lay.addWidget(n)
            lay.addWidget(nm)
            if not live:
                lay.addWidget(label("Coming soon", "pill"))
                f.setToolTip(f"{name.title()} — coming soon")
            else:
                f.setCursor(Qt.PointingHandCursor)
            self.mod_widgets.append((f, n, nm))
            row.addWidget(f)
        self.module = 0
        self.paint_modules()
        return row

    def paint_modules(self):
        for k, (f, n, nm) in enumerate(self.mod_widgets):
            on = k == self.module
            f.setObjectName("moduleOn" if on else "module")
            n.setObjectName("modNumOn" if on else "modNum")
            nm.setObjectName("modNameOn" if on else "modName")
            for w in (f, n, nm):
                w.style().unpolish(w)
                w.style().polish(w)

    def select_module(self, k: int):
        if k == 0:
            self.select_nav(0)
            return
        self.module = 1
        self.paint_modules()
        self.nav_group.setExclusive(False)
        for b in self.nav_group.buttons():
            b.setChecked(False)
        self.nav_group.setExclusive(True)
        self.right.setVisible(False)
        self.voice.refresh_sources()
        self.pages.setCurrentIndex(6)

    def send_to_voice(self, json_path: str):
        if json_path:
            self.select_module(1)
            self.voice.select_source(json_path)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "subtitle"):
            self.subtitle.setVisible(self.width() >= 1680)

    def _banner(self):
        f = QFrame()
        f.setObjectName("banner")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(16, 8, 10, 8)
        self.banner_text = QLabel()
        lay.addWidget(self.banner_text, 1)
        b = QPushButton("Install update")
        b.setObjectName("link")
        b.clicked.connect(self.install_update)
        lay.addWidget(b)
        later = QPushButton("Later")
        later.setObjectName("link")
        later.clicked.connect(lambda: f.setVisible(False))
        lay.addWidget(later)
        f.setVisible(False)
        return f

    # ------------------------------------------------------------------ navigation
    def _nav(self):
        w = QWidget()
        w.setFixedWidth(206)
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for i, (name, ic) in enumerate(self.NAV):
            b = QPushButton("   " + name)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            ICONS.set(b, ic, "ink", 20)
            b.toggled.connect(lambda on, b=b, ic=ic: ICONS._apply(b, ic, "nav_ink" if on else "ink", 20))
            self.nav_group.addButton(b, i)
            v.addWidget(b)
        self.nav_group.idClicked.connect(self.select_nav)
        v.addStretch()
        v.addWidget(self._soon_card())
        return w

    def _soon_card(self):
        f = QFrame()
        f.setObjectName("soon")
        v = QVBoxLayout(f)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(6)
        g = QLabel()
        g.setFixedSize(64, 46)
        g.setPixmap(self._globe_badge())
        v.addWidget(g)
        v.addWidget(label("COMING SOON", "soonTag"))
        v.addWidget(label("Translate & Dub\nwith Lip Sync", "soonTitle"))
        return f

    def _globe_badge(self) -> QPixmap:
        px = QPixmap(128, 92)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        g = QLinearGradient(0, 0, 128, 92)
        g.setColorAt(0, QColor("#8FB0FF"))
        g.setColorAt(1, QColor("#C79BFF"))
        p.setBrush(QColor("#E6A6F2"))
        p.drawEllipse(QRectF(70, 4, 40, 40))
        p.setBrush(g)
        p.drawEllipse(QRectF(10, 14, 72, 72))
        p.drawPixmap(22, 26, th.pixmap("globe", "#FFFFFF", 48, 1.0, 1.6))
        p.end()
        px.setDevicePixelRatio(2)
        return px

    def select_nav(self, i: int):
        name = self.NAV[i][0]
        if getattr(self, "module", 0) != 0:
            self.module = 0
            self.paint_modules()
        if hasattr(self, "right"):
            self.right.setVisible(True)
        self.nav_group.button(i).setChecked(True)
        page = {"Transcribe": 0, "Files": 1, "Projects": 2, "Speakers": 5, "Vocabulary": 0, "Output": 0,
                "Activity Log": 3, "Settings": 4}[name]
        if page == 1:
            self.load_library()
        elif page == 2:
            self.load_projects()
        elif page == 5:
            self.load_speakers()
        self.pages.setCurrentIndex(page)
        if name in ("Speakers", "Vocabulary", "Output"):
            self.select_tab(self.TABS.index(name), from_nav=True)
        elif name == "Transcribe":
            self.select_tab(0, from_nav=True)

    # ------------------------------------------------------------------ transcribe page
    def _transcribe_page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)
        self.drop = DropZone()
        self.drop.dropped.connect(self.add_paths)
        dz = QVBoxLayout(self.drop)
        dz.setContentsMargins(20, 22, 20, 22)
        dz.setSpacing(8)
        dz.addStretch(1)
        badge = UploadBadge()
        dz.addWidget(badge, 0, Qt.AlignHCenter)
        t = label("Drop your videos, audio files or folders here", "dropTitle")
        t.setAlignment(Qt.AlignCenter)
        dz.addWidget(t)
        f = label("MP4 · MOV · MKV · MP3 · WAV · M4A and more", "dropFormats")
        f.setAlignment(Qt.AlignCenter)
        dz.addWidget(f)
        dz.addSpacing(10)
        split = QHBoxLayout()
        split.setSpacing(0)
        split.addStretch()
        add = QPushButton("   Add Files")
        add.setObjectName("addFiles")
        add.setCursor(Qt.PointingHandCursor)
        ICONS.set(add, "plus", "dark_btn_ink", 16)
        add.clicked.connect(self.pick_files)
        split.addWidget(add)
        more = QToolButton()
        more.setObjectName("addMenu")
        more.setCursor(Qt.PointingHandCursor)
        more.setPopupMode(QToolButton.InstantPopup)
        ICONS.set(more, "chev_down", "dark_btn_ink", 16)
        m = QMenu(more)
        m.addAction("Add files…", self.pick_files)
        m.addAction("Add folder…", self.pick_folder)
        m.addSeparator()
        m.addAction("Clear list", self.clear)
        more.setMenu(m)
        split.addWidget(more)
        split.addStretch()
        dz.addLayout(split)
        o = label("or", "or")
        o.setAlignment(Qt.AlignCenter)
        dz.addWidget(o)
        fold = QPushButton("   Add Folder")
        fold.setObjectName("addFolder")
        fold.setCursor(Qt.PointingHandCursor)
        ICONS.set(fold, "folder", "ink", 18)
        fold.clicked.connect(self.pick_folder)
        dz.addWidget(fold, 0, Qt.AlignHCenter)
        dz.addStretch(1)
        v.addWidget(self.drop, 5)
        v.addWidget(self._files_card(), 6)
        return w

    def _files_card(self):
        c = card()
        v = QVBoxLayout(c)
        v.setContentsMargins(18, 14, 18, 12)
        v.setSpacing(10)
        top = QHBoxLayout()
        self.files_title = label("Files (0)", "h2")
        top.addWidget(self.files_title)
        self.files_note = label("", "hint")
        top.addWidget(self.files_note)
        top.addStretch()
        self.proj_btn = QToolButton()
        self.proj_btn.setPopupMode(QToolButton.InstantPopup)
        self.proj_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.proj_btn.setToolTip("Project — each has its own vocabulary, output folder and Master Excel Log")
        ICONS.set(self.proj_btn, "projects", "ink", 16)
        pm = QMenu(self.proj_btn)
        pm.aboutToShow.connect(lambda m=pm: self.fill_project_menu(m))
        self.proj_btn.setMenu(pm)
        top.addWidget(self.proj_btn)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search files…")
        self.search.setFixedWidth(220)
        self.search.setClearButtonEnabled(True)
        self.search_action = self.search.addAction(th.icon("search", T["muted"], 16), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self.apply_filter)
        top.addWidget(self.search)
        sortb = QToolButton()
        sortb.setToolTip("Sort")
        sortb.setPopupMode(QToolButton.InstantPopup)
        ICONS.set(sortb, "sliders", "ink", 18)
        sm = QMenu(sortb)
        for k, lab in (("added", "Date added"), ("name", "Name"), ("duration", "Duration"), ("status", "Status")):
            sm.addAction(f"Sort by {lab.lower()}", lambda k=k: self.sort_rows(k))
        sortb.setMenu(sm)
        top.addWidget(sortb)
        listb = QToolButton()
        listb.setToolTip("Selection")
        listb.setPopupMode(QToolButton.InstantPopup)
        ICONS.set(listb, "list", "ink", 18)
        lm = QMenu(listb)
        lm.addAction("Select all", lambda: self.set_all_checked(True))
        lm.addAction("Select none", lambda: self.set_all_checked(False))
        lm.addSeparator()
        lm.addAction("Remove selected", self.remove_selected)
        lm.addAction("Remove finished", self.remove_finished)
        lm.addAction("Clear list", self.clear)
        listb.setMenu(lm)
        top.addWidget(listb)
        self.filter = QComboBox()
        self.filter.addItems(["All files", "Queued", "In progress", "Ready", "Failed"])
        self.filter.setFixedWidth(140)
        self.filter.currentIndexChanged.connect(self.apply_filter)
        top.addWidget(self.filter)
        v.addLayout(top)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["", "File", "Duration", "Language", "Status", "Progress", "Added", ""])
        hh = self.table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hh.setHighlightSections(False)
        hh.setSectionResizeMode(QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for col, wd in ((0, 40), (2, 84), (3, 108), (4, 132), (5, 150), (6, 158), (7, 40)):
            self.table.setColumnWidth(col, wd)
        self.table.viewport().installEventFilter(self)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(64)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.cellDoubleClicked.connect(self.on_row_double_click)
        self.allbox = QCheckBox(hh)
        self.allbox.setToolTip("Select all")
        self.allbox.toggled.connect(self.set_all_checked)
        hh.geometriesChanged.connect(self.place_allbox)
        hh.sectionResized.connect(lambda *_: self.place_allbox())
        v.addWidget(self.table, 1)
        self.empty = label("No files yet — drop videos or audio above, or use Add Files.", "hint")
        self.empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty)
        foot = QHBoxLayout()
        self.now_label = label("", "hint")
        foot.addWidget(self.now_label, 1)
        self.overall = QProgressBar()
        self.overall.setTextVisible(False)
        self.overall.setFixedWidth(180)
        self.overall.setVisible(False)
        foot.addWidget(self.overall)
        v.addLayout(foot)
        self.visible_rows: list[Row] = []
        return c

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Resize and hasattr(self, "table") and obj is self.table.viewport():
            narrow = self.table.viewport().width() < 900
            self.table.setColumnHidden(6, narrow)
            self.table.setColumnWidth(5, 120 if narrow else 150)
        return super().eventFilter(obj, ev)

    def on_row_double_click(self, i: int, _c: int):
        if i < len(self.visible_rows):
            r = self.visible_rows[i]
            if r.outputs.get("json"):
                self.edit_row(r)

    def place_allbox(self):
        hh = self.table.horizontalHeader()
        x = hh.sectionViewportPosition(0) + (self.table.columnWidth(0) - 18) // 2
        self.allbox.setGeometry(x, (hh.height() - 18) // 2, 18, 18)

    # ------------------------------------------------------------------ table rows
    def build_row(self, i: int, r: Row):
        t = self.table
        for c in range(8):
            t.setItem(i, c, QTableWidgetItem(""))
        box = QCheckBox()
        box.setChecked(r.checked)
        box.toggled.connect(lambda on, r=r: setattr(r, "checked", on))
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(box, 0, Qt.AlignCenter)
        t.setCellWidget(i, 0, holder)

        fw = QWidget()
        fl = QHBoxLayout(fw)
        fl.setContentsMargins(4, 0, 4, 0)
        fl.setSpacing(12)
        thumb = Thumb(r.path.suffix.lower() in VIDEO_EXT)
        if r.thumb:
            thumb.set_image(r.thumb)
        fl.addWidget(thumb)
        names = QVBoxLayout()
        names.setSpacing(2)
        names.addStretch()
        nm = label(r.path.name, "fname")
        nm.setToolTip(str(r.path))
        nm.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        names.addWidget(nm)
        meta = label(f"{r.path.suffix[1:].upper()} · {human_size(r.size)}", "fmeta")
        names.addWidget(meta)
        names.addStretch()
        fl.addLayout(names, 1)
        t.setCellWidget(i, 1, fw)

        dur = label(hms(r.duration), "sub")
        dur.setContentsMargins(8, 0, 0, 0)
        t.setCellWidget(i, 2, dur)

        lw = QWidget()
        ll = QHBoxLayout(lw)
        ll.setContentsMargins(6, 0, 0, 0)
        lang = label("", "lang")
        lang.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        ll.addWidget(lang, 0, Qt.AlignVCenter)
        ll.addStretch()
        t.setCellWidget(i, 3, lw)

        sw = QWidget()
        sl = QHBoxLayout(sw)
        sl.setContentsMargins(4, 0, 0, 0)
        chip = QLabel()
        chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        sl.addWidget(chip, 0, Qt.AlignVCenter)
        sl.addStretch()
        t.setCellWidget(i, 4, sw)

        pw = QWidget()
        pl = QHBoxLayout(pw)
        pl.setContentsMargins(6, 0, 8, 0)
        pl.setSpacing(10)
        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setRange(0, 1000)
        pl.addWidget(bar, 1)
        pct = label("0%", "sub")
        pct.setFixedWidth(38)
        pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        pl.addWidget(pct)
        t.setCellWidget(i, 5, pw)

        added = label(when(r.added), "sub")
        added.setContentsMargins(8, 0, 0, 0)
        t.setCellWidget(i, 6, added)

        mb = QToolButton()
        mb.setObjectName("more")
        mb.setPopupMode(QToolButton.InstantPopup)
        mb.setCursor(Qt.PointingHandCursor)
        ICONS.set(mb, "more", "sub", 18)
        menu = QMenu(mb)
        menu.aboutToShow.connect(lambda r=r, m=menu: self.fill_row_menu(r, m))
        mb.setMenu(menu)
        t.setCellWidget(i, 7, mb)
        r.w = {"thumb": thumb, "dur": dur, "lang": lang, "chip": chip, "bar": bar, "pct": pct, "row": fw,
               "box": box, "meta": meta}
        self.paint_row(r)

    def paint_row(self, r: Row):
        if not r.w:
            return
        try:
            w = r.w
            w["dur"].setText(hms(r.duration))
            w["meta"].setText(f"{r.path.suffix[1:].upper()} · {human_size(r.size)}")
            lang = CODE_TO_LANG.get(r.language, r.language.upper() if r.language and r.language != "unknown" else "")
            w["lang"].setText(lang or (CODE_TO_LANG.get(self.s.language) or "Auto detect"))
            bg, dot, ink = th.CHIPS[T["name"]][r.state]
            w["chip"].setText(f"<span style='color:{dot}'>●</span>&nbsp; {STATUS_TEXT[r.state]}")
            w["chip"].setStyleSheet(f"background:{bg}; color:{ink}; border-radius:8px; padding:4px 10px; "
                                    f"font-weight:500;")
            w["chip"].setToolTip(r.message)
            w["bar"].setObjectName({"ready": "done", "failed": "failed"}.get(r.state, ""))
            w["bar"].style().unpolish(w["bar"])
            w["bar"].style().polish(w["bar"])
            frac = 1.0 if r.state == "ready" else r.frac
            w["bar"].setValue(int(1000 * frac))
            w["pct"].setText(f"{frac:.0%}")
            w["row"].setToolTip(f"{r.path}\n{r.message}")
            w["thumb"].update()
        except RuntimeError:
            pass

    def refresh_table(self):
        order = {"queued": 3, "transcribing": 0, "processing": 1, "failed": 2, "stopped": 4, "ready": 5}
        keyf = {"added": lambda r: r.added, "name": lambda r: r.path.name.lower(),
                "duration": lambda r: -r.duration, "status": lambda r: order[r.state]}[self.sort_key]
        self.rows.sort(key=keyf)
        self.table.setRowCount(0)
        self.visible_rows = []
        flt = self.filter.currentText() if hasattr(self, "filter") else "All files"
        q = self.search.text().strip().lower() if hasattr(self, "search") else ""
        for r in self.rows:
            r.w = {}
            ok = (flt == "All files" or (flt == "Queued" and r.state in ("queued", "stopped")) or
                  (flt == "In progress" and r.state in ("transcribing", "processing")) or
                  (flt == "Ready" and r.state == "ready") or (flt == "Failed" and r.state == "failed"))
            if ok and (not q or q in r.path.name.lower()):
                self.visible_rows.append(r)
        self.table.setRowCount(len(self.visible_rows))
        for i, r in enumerate(self.visible_rows):
            self.build_row(i, r)
        self.files_title.setText(f"Files ({len(self.rows)})")
        self.empty.setVisible(not self.rows)
        self.table.setVisible(bool(self.rows))
        self.update_summary()
        QTimer.singleShot(0, self.place_allbox)

    def apply_filter(self, *_):
        self.refresh_table()

    def sort_rows(self, key: str):
        self.sort_key = key
        self.refresh_table()

    def set_all_checked(self, on: bool):
        for r in self.visible_rows:
            r.checked = on
            if r.w:
                r.w["box"].setChecked(on)
        if self.allbox.isChecked() != on:
            self.allbox.blockSignals(True)
            self.allbox.setChecked(on)
            self.allbox.blockSignals(False)

    def update_summary(self):
        if not self.rows:
            self.files_note.setText("")
            return
        done = sum(r.state == "ready" for r in self.rows)
        total_d = sum(r.duration for r in self.rows)
        self.files_note.setText(f"  ·  {done} ready  ·  {hms(total_d)} of media")

    def fill_row_menu(self, r: Row, m: QMenu):
        m.clear()
        folder = r.outputs.get("folder")
        a = m.addAction("Edit transcript…", lambda: self.edit_row(r))
        a.setEnabled(bool(r.outputs.get("json")))
        a = m.addAction("Translate & voice in Voice Studio…", lambda: self.send_to_voice(r.outputs.get("json", "")))
        a.setEnabled(bool(r.outputs.get("json")))
        a = m.addAction("Open Word / text file", lambda: self.row_open(r))
        a.setEnabled(bool(r.outputs.get("docx") or r.outputs.get("txt")))
        a = m.addAction("Open output folder", lambda: open_path(folder))
        a.setEnabled(bool(folder))
        m.addAction("Show original file", lambda: open_path(r.path.parent))
        m.addSeparator()
        a = m.addAction("Transcribe again", lambda: self.requeue(r))
        a.setEnabled(not self.running and r.state in ("ready", "failed", "stopped"))
        a = m.addAction("Remove from list", lambda: self.remove_rows([r]))
        a.setEnabled(not self.running or r.state in ("ready", "failed", "stopped"))

    def edit_row(self, r: Row):
        self.open_editor(r.outputs.get("json", ""))

    def open_editor(self, json_path: str):
        from .gui_editor import open_editor

        w = open_editor(json_path, self.collect_settings(), self)
        if w:
            w.saved.connect(self.on_editor_saved)

    def on_editor_saved(self, json_path: str, outputs: dict):
        self.say(f"Transcript corrected and re-exported: {Path(json_path).stem}")
        for r in self.rows:
            if r.outputs.get("json") == json_path:
                r.outputs.update(outputs)
        if self.pages.currentIndex() == 1:
            self.load_library()

    def row_open(self, r: Row):
        for k in ("docx", "txt", "folder"):
            if r.outputs.get(k):
                open_path(r.outputs[k])
                return

    def requeue(self, r: Row):
        r.state, r.frac, r.message = "queued", 0.0, "Waiting to start"
        self.paint_row(r)

    def remove_rows(self, rows):
        if self.running:
            rows = [r for r in rows if r.state in ("ready", "failed", "stopped")]
        for r in rows:
            if r in self.rows:
                self.rows.remove(r)
                self.by_key.pop(r.key, None)
        self.refresh_table()

    def remove_selected(self):
        self.remove_rows([r for r in self.rows if r.checked])

    def remove_finished(self):
        self.remove_rows([r for r in self.rows if r.state == "ready"])

    # ------------------------------------------------------------------ right panel
    def _right_panel(self):
        c = card()
        c.setFixedWidth(410)
        v = QVBoxLayout(c)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)
        seg = QFrame()
        seg.setObjectName("segBar")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(4, 4, 4, 4)
        sl.setSpacing(2)
        self.tab_group = QButtonGroup(self)
        for i, name in enumerate(self.TABS):
            b = QPushButton(name)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.tab_group.addButton(b, i)
            sl.addWidget(b)
        self.tab_group.idClicked.connect(self.select_tab)
        v.addWidget(seg)
        self.tabs = QStackedWidget()
        for build in (self._tab_settings, self._tab_speakers, self._tab_vocab, self._tab_output):
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            inner = QWidget()
            build(inner)
            sc.setWidget(inner)
            self.tabs.addWidget(sc)
        v.addWidget(self.tabs, 1)
        self.start = QPushButton("   Start Transcription")
        self.start.setObjectName("start")
        self.start.setCursor(Qt.PointingHandCursor)
        ICONS.set(self.start, "sparkle", "#FFFFFF", 22)
        self.start.clicked.connect(self.start_batch)
        v.addWidget(self.start)
        self.stop = QPushButton("   Stop after current file")
        self.stop.setObjectName("stop")
        ICONS.set(self.stop, "stop", "ink", 16)
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self.stop_batch)
        v.addWidget(self.stop)
        return c

    def select_tab(self, i: int, from_nav: bool = False):
        self.tab_group.button(i).setChecked(True)
        self.tabs.setCurrentIndex(i)
        if not from_nav:
            nav = {0: 0, 1: 3, 2: 4, 3: 5}[i]
            self.nav_group.button(nav).setChecked(True)
            if self.pages.currentIndex() != 0:
                self.pages.setCurrentIndex(0)

    def _section(self, v: QVBoxLayout, title: str, big: bool = False) -> QVBoxLayout:
        head = QPushButton(title)
        head.setObjectName("section")
        head.setCursor(Qt.PointingHandCursor)
        head.setLayoutDirection(Qt.RightToLeft)
        if not big:
            head.setStyleSheet("font-size:15px;")
        ICONS.set(head, "chev_up", "sub", 16)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 2, 0, 6)
        bl.setSpacing(10)

        def toggle():
            body.setVisible(not body.isVisible())
            ICONS._apply(head, "chev_up" if body.isVisible() else "chev_down", "sub", 16)
        head.clicked.connect(toggle)
        v.addWidget(head)
        v.addWidget(body)
        return bl

    @staticmethod
    def _form(bl: QVBoxLayout) -> QGridLayout:
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        g.setColumnMinimumWidth(0, 82)
        g.setColumnStretch(1, 1)
        bl.addLayout(g)
        return g

    @staticmethod
    def _combo(items, current: int = 0, popup_width: int = 360) -> QComboBox:
        c = QComboBox()
        c.addItems(items)
        c.setCurrentIndex(max(0, current))
        c.setMinimumContentsLength(10)
        c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        c.view().setMinimumWidth(popup_width)
        c.setCursor(Qt.PointingHandCursor)
        return c

    def _tab_settings(self, w: QWidget):
        v = QVBoxLayout(w)
        v.setContentsMargins(2, 4, 6, 4)
        v.setSpacing(8)
        bl = self._section(v, "Transcription Settings", big=True)
        bl.addWidget(label("Accuracy", "h3"))
        g = self._form(bl)
        keys = list(ENGINE_CHOICES)
        cur = next((i for i, k in enumerate(keys) if ENGINE_CHOICES[k] == (self.s.engine, self.s.variant)), 0)
        self.engine = self._combo(keys, cur, 470)
        self.engine.setItemIcon(0, th.icon("bolt", T["accent"], 16))
        self.lang = self._combo(list(LANGUAGES))
        self.lang.setCurrentText(next((k for k, v_ in LANGUAGES.items() if v_ == self.s.language), "Auto detect"))
        self.style_ = self._combo(["Exact verbatim (keep um, uh, repeats)", "Clean verbatim (drop fillers)"],
                                  0 if self.s.verbatim else 1)
        self.enh = self._combo(ENH_LABELS, ENH_VALUES.index(self.s.enhancement) if self.s.enhancement in ENH_VALUES else 0)
        self.enh.setToolTip("Use AI restoration only for noisy or muffled files — on clean audio it can slightly "
                            "reduce accuracy.")
        self.strict = self._combo(REVIEW_LABELS, {0.5: 0, 0.8: 1, 0.95: 2}.get(self.s.review_threshold, 1))
        self.strict.setToolTip("How many uncertain words go to the Review Queue. Thorough catches the most errors.")
        for i, (lab, wd) in enumerate((("Engine", self.engine), ("Language", self.lang), ("Style", self.style_),
                                       ("Audio prep", self.enh), ("Review", self.strict))):
            g.addWidget(label(lab, "sub"), i, 0)
            g.addWidget(wd, i, 1)
        self.cross = QCheckBox("Cross-check with a second engine (≈2× slower)")
        self.cross.setChecked(self.s.cross_check)
        self.cross.setToolTip("Runs an independent model and lists every disagreement for review.")
        self.fuse = QCheckBox("Let it repair words the first engine was unsure of")
        self.fuse.setChecked(self.s.fuse)
        bl.addWidget(self.cross)
        bl.addWidget(self.fuse)
        v.addWidget(hline())

        bl = self._section(v, "Speakers")
        self.diar = Toggle("Label speakers (Speaker 1, Speaker 2…)")
        self.diar.setChecked(self.s.diarize)
        bl.addWidget(self.diar)
        row = QHBoxLayout()
        row.addWidget(label("Number of speakers", "sub"))
        self.nspk = self._combo(["Auto"] + [str(i) for i in range(1, 13)], self.s.num_speakers or 0, 120)
        self.nspk.setFixedWidth(120)
        row.addWidget(self.nspk)
        row.addStretch()
        bl.addLayout(row)
        v.addWidget(hline())

        bl = self._section(v, "Advanced")
        self.fuzzy = QCheckBox("Auto-correct near-misses to these spellings")
        self.fuzzy.setChecked(self.s.fuzzy_vocab)
        self.fuzzy.setToolTip("Uses your Vocabulary list; every change is logged in the Master Excel Log.")
        self.fname = QCheckBox("Use each file name as a hint (e.g. 'EXL town hall.mp4')")
        self.fname.setChecked(self.s.filename_context)
        self.translate = QCheckBox("Also create an English translation (non-English videos)")
        self.translate.setChecked(self.s.translate_english)
        self.precise = QCheckBox("Precise word timing for subtitles & dubbing (Whisper languages, slower)")
        self.precise.setChecked(self.s.precise_timing)
        self.precise.setToolTip("Re-times every word with a separate acoustic model (1,600+ languages incl. Hindi).\n"
                                "English with Parakeet is already precise. Downloads a 330 MB model once.")
        for c in (self.fuzzy, self.fname, self.translate, self.precise):
            bl.addWidget(c)
        v.addStretch()

    def _mirror_check(self, a: QCheckBox, b: QCheckBox):
        a.toggled.connect(lambda on: b.isChecked() != on and b.setChecked(on))
        b.toggled.connect(lambda on: a.isChecked() != on and a.setChecked(on))

    def _tab_speakers(self, w: QWidget):
        v = QVBoxLayout(w)
        v.setContentsMargins(2, 4, 6, 4)
        v.setSpacing(12)
        v.addWidget(label("Speakers", "h2"))
        v.addWidget(label("VERBATIM can tell voices apart and label each line Speaker 1, Speaker 2… in every "
                          "transcript, subtitle and the Master Excel Log.", "hint", wrap=True))
        d2 = Toggle("Label speakers (Speaker 1, Speaker 2…)")
        d2.setChecked(self.diar.isChecked())
        self._mirror_check(self.diar, d2)
        v.addWidget(d2)
        row = QHBoxLayout()
        row.addWidget(label("Number of speakers", "sub"))
        n2 = self._combo(["Auto"] + [str(i) for i in range(1, 13)], self.nspk.currentIndex(), 120)
        n2.setFixedWidth(120)
        self.nspk.currentIndexChanged.connect(lambda i: n2.currentIndex() != i and n2.setCurrentIndex(i))
        n2.currentIndexChanged.connect(lambda i: self.nspk.currentIndex() != i and self.nspk.setCurrentIndex(i))
        row.addWidget(n2)
        row.addStretch()
        v.addLayout(row)
        v.addWidget(label("Tip: setting the exact number of speakers (when you know it) gives the cleanest "
                          "labels. Use Auto for panels and events.", "hint", wrap=True))
        v.addWidget(hline())
        self.spk_names = QCheckBox("Show speaker labels in transcripts")
        self.spk_names.setChecked(self.s.include_speakers)
        v.addWidget(self.spk_names)
        self.recog = QCheckBox("Recognise named speakers in new files")
        self.recog.setChecked(self.s.speaker_library)
        v.addWidget(self.recog)
        v.addWidget(label("Name a speaker once in the transcript editor (click their label) and VERBATIM labels "
                          "that voice automatically from then on.", "hint", wrap=True))
        b = QPushButton("  Manage speaker library")
        ICONS.set(b, "users", "ink", 16)
        b.clicked.connect(lambda: self.select_nav(3))
        v.addWidget(b, 0, Qt.AlignLeft)
        v.addStretch()

    def _tab_vocab(self, w: QWidget):
        v = QVBoxLayout(w)
        v.setContentsMargins(2, 4, 6, 4)
        v.setSpacing(12)
        v.addWidget(label("Vocabulary", "h2"))
        v.addWidget(label("Names, brands and jargon — one per line. Fix a recurring mistake with a rule: "
                          "wrong => right.", "hint", wrap=True))
        self.vocab = QPlainTextEdit(self.s.vocabulary)
        self.vocab.setPlaceholderText("Infinite Story\nTata Power-DDL\nASSOCHAM\nexcel service => EXL Service")
        self.vocab.setMinimumHeight(260)
        v.addWidget(self.vocab, 1)
        self.vocab_count = label("", "hint")
        v.addWidget(self.vocab_count)
        self.vocab.textChanged.connect(self.count_vocab)
        self.count_vocab()
        f2 = QCheckBox("Auto-correct near-misses to these spellings (logged)")
        f2.setChecked(self.fuzzy.isChecked())
        self._mirror_check(self.fuzzy, f2)
        v.addWidget(f2)
        n2 = QCheckBox("Use each file name as a hint")
        n2.setChecked(self.fname.isChecked())
        self._mirror_check(self.fname, n2)
        v.addWidget(n2)

    def count_vocab(self):
        lines = [x.strip() for x in self.vocab.toPlainText().splitlines() if x.strip() and not x.strip().startswith("#")]
        rules = sum("=>" in x for x in lines)
        self.vocab_count.setText(f"{len(lines) - rules} terms · {rules} correction rules")

    def _tab_output(self, w: QWidget):
        v = QVBoxLayout(w)
        v.setContentsMargins(2, 4, 6, 4)
        v.setSpacing(12)
        v.addWidget(label("Output", "h2"))
        v.addWidget(label("Save to", "h3"))
        self.out_label = label(self.s.output_dir, "hint", wrap=True)
        v.addWidget(self.out_label)
        row = QHBoxLayout()
        b = QPushButton("Change folder…")
        b.clicked.connect(self.choose_output)
        row.addWidget(b)
        b = QPushButton("  Open folder")
        ICONS.set(b, "open", "ink", 15)
        b.clicked.connect(lambda: open_path(self.s.output_dir))
        row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        v.addWidget(hline())
        v.addWidget(label("Formats", "h3"))
        grid = QGridLayout()
        self.fmt_boxes = {}
        names = {"txt": "TXT", "srt": "SRT subtitles", "vtt": "VTT subtitles", "csv": "CSV", "json": "JSON",
                 "docx": "Word (DOCX)", "md": "Markdown"}
        for k, fm in enumerate(FORMATS):
            c = QCheckBox(names.get(fm, fm.upper()))
            c.setChecked(fm in self.s.formats)
            self.fmt_boxes[fm] = c
            grid.addWidget(c, k // 2, k % 2)
        v.addLayout(grid)
        v.addWidget(hline())
        v.addWidget(label("Layout", "h3"))
        self.para = QCheckBox("Readable paragraphs (TXT, Word, Markdown)")
        self.para.setChecked(self.s.paragraphs)
        self.tsbox = QCheckBox("Timestamps")
        self.tsbox.setChecked(self.s.include_timestamps)
        s2 = QCheckBox("Speaker labels")
        s2.setChecked(self.spk_names.isChecked())
        self._mirror_check(self.spk_names, s2)
        for c in (self.para, self.tsbox, s2):
            v.addWidget(c)
        v.addWidget(hline())
        b = QPushButton("  Open Master Excel Log")
        ICONS.set(b, "excel", "ink", 16)
        b.clicked.connect(self.open_log)
        v.addWidget(b)
        v.addStretch()

    # ------------------------------------------------------------------ other pages
    def _page_shell(self, title: str):
        c = card()
        v = QVBoxLayout(c)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(14)
        v.addWidget(label(title, "h1"))
        return c, v

    def _soon_page(self, title: str, _desc: str):
        c, v = self._page_shell(title)
        row = QHBoxLayout()
        row.addWidget(label("Coming soon", "pill"))
        row.addStretch()
        v.addLayout(row)
        v.addStretch()
        return c

    def _library_page(self):
        c, v = self._page_shell("Files")
        v.addWidget(label("Everything transcribed into the current output folder (from the Master Log). "
                          "Double-click a row to open it in the transcript editor.", "hint", wrap=True))
        top = QHBoxLayout()
        self.lib_search = QLineEdit()
        self.lib_search.setPlaceholderText("Search transcribed files…")
        self.lib_search.addAction(th.icon("search", T["muted"], 16), QLineEdit.LeadingPosition)
        self.lib_search.textChanged.connect(self.load_library)
        top.addWidget(self.lib_search, 1)
        b = QPushButton("  Open Master Excel Log")
        ICONS.set(b, "excel", "ink", 16)
        b.clicked.connect(self.open_log)
        top.addWidget(b)
        v.addLayout(top)
        self.lib = QTableWidget(0, 7)
        self.lib.setHorizontalHeaderLabels(["File", "Duration", "Language", "Engine", "To review", "Finished", "Status"])
        hh = self.lib.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lib.verticalHeader().setVisible(False)
        self.lib.verticalHeader().setDefaultSectionSize(40)
        self.lib.setShowGrid(False)
        self.lib.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lib.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lib.cellDoubleClicked.connect(self.open_library_row)
        self.lib.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lib.customContextMenuRequested.connect(self.library_menu)
        v.addWidget(self.lib, 1)
        self.lib_note = label("", "hint")
        v.addWidget(self.lib_note)
        self.lib_paths: list[dict] = []
        return c

    def load_library(self, *_):
        db = Path(self.s.output_dir) / ".verbatim" / "ledger.sqlite"
        rows = []
        if db.exists():
            try:
                con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                rows = con.execute("SELECT source_name, duration, language, engine, review_items, finished, status, "
                                   "docx, txt, output_folder, json FROM files ORDER BY id DESC LIMIT 2000").fetchall()
                con.close()
            except sqlite3.Error:
                rows = []
        q = self.lib_search.text().strip().lower()
        rows = [r for r in rows if not q or q in (r[0] or "").lower()]
        self.lib.setRowCount(len(rows))
        self.lib_paths = []
        for i, r in enumerate(rows):
            vals = [r[0], hms(r[1]), CODE_TO_LANG.get(r[2] or "", (r[2] or "").upper()), r[3] or "",
                    str(r[4] or 0), (r[5] or "").replace("T", " ")[:16], r[6] or ""]
            for j, val in enumerate(vals):
                self.lib.setItem(i, j, QTableWidgetItem(str(val)))
            self.lib_paths.append({"docx": r[7], "txt": r[8], "folder": r[9], "json": r[10]})
        self.lib_note.setText(f"{len(rows)} transcribed file(s) in {self.s.output_dir}" if rows else
                              "Nothing transcribed in this output folder yet.")

    def open_library_row(self, r: int, _c: int):
        if r >= len(self.lib_paths):
            return
        d = self.lib_paths[r]
        if d.get("json") and Path(d["json"]).exists():
            self.open_editor(d["json"])
        elif d.get("docx") or d.get("txt") or d.get("folder"):
            open_path(d.get("docx") or d.get("txt") or d.get("folder"))

    def library_menu(self, pos):
        r = self.lib.rowAt(pos.y())
        if r < 0 or r >= len(self.lib_paths):
            return
        d = self.lib_paths[r]
        m = QMenu(self)
        a = m.addAction("Edit transcript…", lambda: self.open_editor(d.get("json") or ""))
        a.setEnabled(bool(d.get("json")))
        a = m.addAction("Translate & voice in Voice Studio…", lambda: self.send_to_voice(d.get("json") or ""))
        a.setEnabled(bool(d.get("json")))
        a = m.addAction("Open Word file", lambda: open_path(d["docx"]))
        a.setEnabled(bool(d.get("docx")))
        a = m.addAction("Open folder", lambda: open_path(d["folder"]))
        a.setEnabled(bool(d.get("folder")))
        m.exec(self.lib.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ projects
    def _projects_page(self):
        c, v = self._page_shell("Projects")
        v.addWidget(label("Group work by client or campaign. Each project has its own vocabulary, output folder and "
                          "Master Excel Log. Double-click a project to work in it.", "hint", wrap=True))
        row = QHBoxLayout()
        b = QPushButton("  New project…")
        ICONS.set(b, "plus", "ink", 15)
        b.clicked.connect(self.new_project)
        row.addWidget(b)
        for text, fn in (("Open", self.open_selected_project), ("Rename…", self.rename_project),
                         ("Output folder…", self.project_folder), ("Remove", self.remove_project)):
            bb = QPushButton(text)
            bb.clicked.connect(fn)
            row.addWidget(bb)
        row.addStretch()
        b = QPushButton("No project")
        b.setToolTip("Work without a project (general vocabulary and output folder)")
        b.clicked.connect(lambda: self.switch_project(""))
        row.addWidget(b)
        v.addLayout(row)
        self.proj_table = QTableWidget(0, 5)
        self.proj_table.setHorizontalHeaderLabels(["Project", "Files", "Hours", "Last transcribed", "Output folder"])
        hh = self.proj_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.proj_table.verticalHeader().setVisible(False)
        self.proj_table.verticalHeader().setDefaultSectionSize(42)
        self.proj_table.setShowGrid(False)
        self.proj_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.proj_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.proj_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.proj_table.cellDoubleClicked.connect(lambda r, _c: self.open_selected_project())
        v.addWidget(self.proj_table, 1)
        self.proj_note = label("", "hint")
        v.addWidget(self.proj_note)
        self.proj_ids: list[str] = []
        return c

    def load_projects(self):
        from .projects import Projects

        ps = Projects()
        self.proj_table.setRowCount(len(ps.items))
        self.proj_ids = []
        for i, p in enumerate(ps.items):
            st = Projects.stats(p)
            active = p["id"] == self.s.active_project
            vals = [("●  " if active else "") + p["name"], str(st["files"]), f"{st['hours']:.1f}",
                    st["last"].replace("T", " ")[:16] or "—", p["output_dir"]]
            for j, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if active and j == 0:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                self.proj_table.setItem(i, j, it)
            self.proj_ids.append(p["id"])
        self.proj_note.setText("No projects yet — create one per client or campaign." if not ps.items else
                               f"{len(ps.items)} project(s). Removing a project from the list never deletes its files.")

    def selected_project(self) -> str:
        rows = self.proj_table.selectionModel().selectedRows()
        return self.proj_ids[rows[0].row()] if rows and rows[0].row() < len(self.proj_ids) else ""

    def new_project(self):
        from .projects import Projects

        name, ok = QInputDialog.getText(self, "New project", "Project name (e.g. client and campaign):")
        if not ok or not name.strip():
            return
        base = self.s.base_output_dir or self.s.output_dir if self.s.active_project else self.s.output_dir
        p = Projects().create(name, base)
        self.say(f"Project created: {p['name']} → {p['output_dir']}")
        self.switch_project(p["id"])
        self.load_projects()

    def open_selected_project(self):
        pid = self.selected_project()
        if pid:
            self.switch_project(pid)
            self.select_nav(0)

    def rename_project(self):
        from .projects import Projects

        pid = self.selected_project()
        ps = Projects()
        p = ps.get(pid)
        if not p:
            return
        name, ok = QInputDialog.getText(self, "Rename project", "New name:", text=p["name"])
        if ok and name.strip():
            ps.update(pid, name=name.strip())
            self.load_projects()
            self.update_project_ui()

    def project_folder(self):
        from .projects import Projects

        pid = self.selected_project()
        ps = Projects()
        p = ps.get(pid)
        if not p:
            return
        d = QFileDialog.getExistingDirectory(self, "Project output folder", p["output_dir"])
        if d:
            ps.update(pid, output_dir=d)
            if pid == self.s.active_project:
                self.s.output_dir = d
                self.out_label.setText(d)
                self.s.save()
            self.load_projects()

    def remove_project(self):
        from .projects import Projects

        pid = self.selected_project()
        p = Projects().get(pid)
        if not p:
            return
        if QMessageBox.question(self, "Remove project", f"Remove “{p['name']}” from the list?\n\nIts transcripts and "
                                f"Master Excel Log stay in:\n{p['output_dir']}") != QMessageBox.Yes:
            return
        if pid == self.s.active_project:
            self.switch_project("")
        Projects().remove(pid)
        self.load_projects()

    def fill_project_menu(self, m: QMenu):
        from .projects import Projects

        m.clear()
        a = m.addAction("No project", lambda: self.switch_project(""))
        a.setCheckable(True)
        a.setChecked(not self.s.active_project)
        for p in Projects().items:
            a = m.addAction(p["name"], lambda pid=p["id"]: self.switch_project(pid))
            a.setCheckable(True)
            a.setChecked(p["id"] == self.s.active_project)
        m.addSeparator()
        m.addAction("New project…", self.new_project)
        m.addAction("Manage projects…", lambda: self.select_nav(2))

    def switch_project(self, pid: str):
        from .projects import Projects

        if self.running:
            QMessageBox.information(self, "Busy", "Switch project after the current batch finishes.")
            return
        ps = Projects()
        cur = ps.get(self.s.active_project) if self.s.active_project else None
        if cur:
            ps.update(cur["id"], vocabulary=self.vocab.toPlainText())
        else:
            self.s.base_vocabulary = self.vocab.toPlainText()
            self.s.base_output_dir = self.s.output_dir
        new = ps.get(pid) if pid else None
        if new:
            self.s.active_project = pid
            self.s.output_dir = new["output_dir"]
            vocab = new.get("vocabulary", "")
            try:
                Path(new["output_dir"]).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            self.say(f"Working in project: {new['name']}")
        else:
            self.s.active_project = ""
            self.s.output_dir = self.s.base_output_dir or self.s.output_dir
            vocab = self.s.base_vocabulary
            self.say("Working without a project")
        self.vocab.setPlainText(vocab)
        self.s.vocabulary = vocab
        self.out_label.setText(self.s.output_dir)
        self.s.save()
        self.update_project_ui()
        if self.pages.currentIndex() == 2:
            self.load_projects()

    def update_project_ui(self):
        from .projects import Projects

        p = Projects().get(self.s.active_project) if self.s.active_project else None
        if self.s.active_project and not p:  # project removed elsewhere
            self.s.active_project = ""
        self.proj_btn.setText(f"  {p['name']}" if p else "  No project")

    # ------------------------------------------------------------------ speakers
    def _speakers_page(self):
        c, v = self._page_shell("Speakers")
        v.addWidget(label("Your speaker library. To add someone, open a transcript in the editor and click their "
                          "speaker label (e.g. “Speaker 2”), type the name and keep “Remember this voice” ticked. "
                          "From then on VERBATIM labels that voice automatically. Voice fingerprints stay on this "
                          "computer.", "hint", wrap=True))
        row = QHBoxLayout()
        for text, fn in (("Rename…", self.rename_library_speaker), ("Delete", self.delete_library_speaker)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        r2 = QCheckBox("Recognise named speakers in new files")
        r2.setChecked(self.recog.isChecked())
        self._mirror_check(self.recog, r2)
        row.addWidget(r2)
        v.addLayout(row)
        self.spk_table = QTableWidget(0, 4)
        self.spk_table.setHorizontalHeaderLabels(["Name", "Voice samples", "Named in files", "Last updated"])
        hh = self.spk_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.spk_table.verticalHeader().setVisible(False)
        self.spk_table.verticalHeader().setDefaultSectionSize(40)
        self.spk_table.setShowGrid(False)
        self.spk_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.spk_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.spk_table.setSelectionMode(QAbstractItemView.SingleSelection)
        v.addWidget(self.spk_table, 1)
        self.spk_note = label("", "hint")
        v.addWidget(self.spk_note)
        return c

    def load_speakers(self):
        from .speakers import SpeakerLibrary

        lib = SpeakerLibrary()
        self.spk_table.setRowCount(len(lib.entries))
        for i, e in enumerate(lib.entries):
            files = e.get("files", [])
            vals = [e["name"], str(len(e.get("prints", []))),
                    ", ".join(files[-3:]) + (f" +{len(files) - 3} more" if len(files) > 3 else ""),
                    (e.get("updated") or e.get("created", "")).replace("T", " ")[:16]]
            for j, val in enumerate(vals):
                self.spk_table.setItem(i, j, QTableWidgetItem(val))
        self.spk_note.setText("No named speakers yet." if not lib.entries else
                              f"{len(lib.entries)} named speaker(s).")

    def selected_speaker(self) -> str:
        rows = self.spk_table.selectionModel().selectedRows()
        return self.spk_table.item(rows[0].row(), 0).text() if rows else ""

    def rename_library_speaker(self):
        from .speakers import SpeakerLibrary

        old = self.selected_speaker()
        if not old:
            return
        new, ok = QInputDialog.getText(self, "Rename speaker", "New name (an existing name merges the two):", text=old)
        if ok and new.strip() and new.strip() != old:
            SpeakerLibrary().rename(old, new)
            self.load_speakers()

    def delete_library_speaker(self):
        from .speakers import SpeakerLibrary

        name = self.selected_speaker()
        if name and QMessageBox.question(self, "Delete speaker", f"Forget {name}'s voice? Existing transcripts keep "
                                         "the name.") == QMessageBox.Yes:
            SpeakerLibrary().delete(name)
            self.load_speakers()

    def _log_page(self):
        c, v = self._page_shell("Activity Log")
        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        v.addWidget(self.log, 1)
        row = QHBoxLayout()
        b = QPushButton("Open full log file")
        b.clicked.connect(lambda: open_path(user_data_dir() / "activity.log"))
        row.addWidget(b)
        b = QPushButton("Clear view")
        b.clicked.connect(self.log.clear)
        row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        return c

    def _app_settings_page(self):
        c, v = self._page_shell("Settings")
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(0, 0, 8, 0)
        iv.setSpacing(14)

        iv.addWidget(label("Appearance", "h3"))
        row = QHBoxLayout()
        row.addWidget(label("Theme", "sub"))
        self.theme_box = self._combo(["Light", "Dark", "Match system"],
                                     {"light": 0, "dark": 1, "system": 2}.get(self.s.theme, 0), 180)
        self.theme_box.setFixedWidth(200)
        self.theme_box.currentIndexChanged.connect(self.change_theme)
        row.addWidget(self.theme_box)
        row.addStretch()
        iv.addLayout(row)
        iv.addWidget(hline())

        iv.addWidget(label("Updates from GitHub", "h3"))
        iv.addWidget(label(f"You are using VERBATIM {__version__} by Infinite Story LLP. VERBATIM is connected to "
                           "GitHub out of the box — no sign-in needed. It checks for new versions every day, tells "
                           "you when one is ready, and installs only after you say yes.", "hint", wrap=True))
        self.ver_label = label(f"You are using VERBATIM {__version__}.", "sub")
        self.gh_status = label("Not checked yet.", "sub", wrap=True)
        iv.addWidget(self.gh_status)
        row = QHBoxLayout()
        b = QPushButton("  Check now")
        ICONS.set(b, "refresh", "ink", 15)
        b.clicked.connect(lambda: self.check_updates(manual=True))
        row.addWidget(b)
        b = QPushButton("Install update")
        b.clicked.connect(self.install_update)
        row.addWidget(b)
        b = QPushButton("Open releases page")
        b.setObjectName("link")
        b.clicked.connect(self.open_releases)
        row.addWidget(b)
        row.addStretch()
        iv.addLayout(row)
        self.auto_upd = QCheckBox("Check GitHub for app and model updates every day (you are always asked "
                                  "before anything installs)")
        self.auto_upd.setChecked(self.s.auto_check_updates)
        iv.addWidget(self.auto_upd)
        iv.addWidget(hline())

        iv.addWidget(label("Speech models", "h3"))
        self.models_box = QVBoxLayout()
        iv.addLayout(self.models_box)
        row = QHBoxLayout()
        b = QPushButton("  Download everything for offline use…")
        ICONS.set(b, "download", "ink", 15)
        b.clicked.connect(self.offer_models)
        row.addWidget(b)
        row.addStretch()
        iv.addLayout(row)
        self.fill_models()
        iv.addWidget(hline())

        iv.addWidget(label("Cloud engines (optional)", "h3"))
        iv.addWidget(label("ElevenLabs Scribe uploads audio to ElevenLabs; Claude translation sends transcript text to "
                           "Anthropic. Use them only where the client's data policy allows.", "hint", wrap=True))
        row = QHBoxLayout()
        b = QPushButton("ElevenLabs API key…")
        b.clicked.connect(self.set_key)
        row.addWidget(b)
        b = QPushButton("Claude API key… (Voice Studio translation)")
        b.clicked.connect(self.set_claude_key)
        row.addWidget(b)
        row.addStretch()
        iv.addLayout(row)
        row = QHBoxLayout()
        b = QPushButton("Azure Speech key… (premium voices)")
        b.clicked.connect(self.set_azure_key)
        row.addWidget(b)
        row.addStretch()
        iv.addLayout(row)
        iv.addWidget(label("Your ElevenLabs key also unlocks ElevenLabs voices and cloud cloning in Voice Lab. Local "
                           "voices stay the default and never leave this computer.", "hint", wrap=True))
        iv.addWidget(hline())

        iv.addWidget(label("Data", "h3"))
        row = QHBoxLayout()
        b = QPushButton("Open VERBATIM data folder")
        b.clicked.connect(lambda: open_path(user_data_dir()))
        row.addWidget(b)
        row.addStretch()
        iv.addLayout(row)
        iv.addWidget(hline())
        iv.addWidget(label("About", "h3"))
        iv.addWidget(label(f"VERBATIM {__version__} — an Infinite Story LLP product. © 2026 Infinite Story LLP. All rights "
                           "reserved. VERBATIM is proprietary software; third-party components remain under their own "
                           "licences.", "hint", wrap=True))
        row = QHBoxLayout()
        for text, name in (("Licence agreement", "LICENSE"), ("Third-party notices", "THIRD_PARTY_NOTICES.md")):
            b = QPushButton(text)
            b.setObjectName("link")
            b.clicked.connect(lambda _=False, n=name: open_path(resource_root() / n if (resource_root() / n).exists()
                                                                else resource_root() / "app" / n))
            row.addWidget(b)
        b = QPushButton("infinitestory.in")
        b.setObjectName("link")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://infinitestory.in")))
        row.addWidget(b)
        row.addStretch()
        iv.addLayout(row)
        iv.addStretch()
        sc.setWidget(inner)
        v.addWidget(sc, 1)
        return c

    def fill_models(self):
        from .models import CATALOG, is_installed

        self.models_box.setSpacing(4)

        while self.models_box.count():
            it = self.models_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for key, m in CATALOG.items():
            try:
                ok = is_installed(key)
            except Exception:
                ok = False
            lab = label(f"{'✓' if ok else '○'}  {m['label']}  ·  {m['size_mb']} MB"
                        f"{'' if ok else '  (downloads when first needed)'}", "sub")
            lab.setMinimumHeight(22)
            self.models_box.addWidget(lab)
        from . import align

        ok = align.is_installed()
        self.models_box.addWidget(label(f"{'✓' if ok else '○'}  Word-timing model (Omnilingual CTC, 1,600+ languages)  ·  "
                                        f"{align.SIZE_MB} MB{'' if ok else '  (downloads when first needed)'}", "sub"))
        from . import tts

        from . import tts_chatterbox

        for eng in ("st", "ko", "zv", "cb"):
            ok = tts.is_installed(eng)
            mb = tts_chatterbox.SIZE_MB if eng == "cb" else tts.ENGINES[eng]["size_mb"]
            self.models_box.addWidget(label(f"{'✓' if ok else '○'}  {extra_model_label('tts-' + eng)}  ·  "
                                            f"{mb} MB{'' if ok else '  (downloads when first needed)'}", "sub"))
        from . import llm

        for key, m in llm.MODELS.items():
            ok = llm.model_path(key) is not None
            self.models_box.addWidget(label(f"{'✓' if ok else '○'}  Offline translation — {m['label']}"
                                            f"{'' if ok else '  (downloads when first used)'}", "sub"))
        for i in range(self.models_box.count()):
            w = self.models_box.itemAt(i).widget()
            if w:
                w.setMinimumHeight(22)

    def change_theme(self, i: int):
        self.s.theme = ("light", "dark", "system")[i]
        self.s.save()
        self.apply_theme()

    # ------------------------------------------------------------------ actions
    def say(self, msg: str):
        line = f"{datetime.now():%H:%M:%S}  {msg}"
        self.log.appendPlainText(line)
        try:
            with open(user_data_dir() / "activity.log", "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now():%Y-%m-%d} {line}\n")
        except OSError:
            pass

    def add_paths(self, paths):
        from .pipeline import collect_media

        new = []
        for p in collect_media(paths):
            if str(p) in self.by_key:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            r = Row(p, datetime.now(), size)
            self.rows.append(r)
            self.by_key[r.key] = r
            new.append(r)
            self.meta.add(p)
        if new:
            self.say(f"Added {len(new)} file(s)")
            self.refresh_table()
        elif paths:
            self.say("No new media files found in what was added")

    def on_meta(self, key: str, dur: float, png: bytes):
        r = self.by_key.get(key)
        if not r:
            return
        r.duration = dur or r.duration
        if png:
            r.thumb = png
            if r.w:
                r.w["thumb"].set_image(png)
        self.paint_row(r)
        self.update_summary()

    def pick_files(self):
        exts = " ".join(f"*{e}" for e in sorted(MEDIA_EXTENSIONS))
        paths, _ = QFileDialog.getOpenFileNames(self, "Add media", "", f"Media ({exts})")
        self.add_paths(paths)

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Add folder")
        if d:
            self.add_paths([d])

    def clear(self):
        if self.running:
            self.remove_finished()
            return
        self.rows, self.by_key = [], {}
        self.refresh_table()

    def choose_output(self):
        d = QFileDialog.getExistingDirectory(self, "Output folder", self.s.output_dir)
        if d:
            self.s.output_dir = d
            self.out_label.setText(d)
            if self.s.active_project:
                from .projects import Projects

                Projects().update(self.s.active_project, output_dir=d)
            self.s.save()

    def set_key(self):
        key, ok = QInputDialog.getText(self, "ElevenLabs API key",
                                       "Paste your ElevenLabs API key (stored in the system keychain):",
                                       QLineEdit.Password)
        if ok and key.strip():
            from .engines.elevenlabs import set_api_key

            set_api_key(key)
            self.say("ElevenLabs API key saved to the system keychain")

    def set_claude_key(self):
        key, ok = QInputDialog.getText(self, "Claude API key",
                                       "Paste your Anthropic (Claude) API key — from console.anthropic.com.\n"
                                       "Stored in the system keychain; used only for Voice Studio translation:",
                                       QLineEdit.Password)
        if ok and key.strip():
            from .translate import set_claude_key

            set_claude_key(key)
            self.say("Claude API key saved to the system keychain")

    def collect_settings(self) -> Settings:
        s = self.s
        s.engine, s.variant = ENGINE_CHOICES[self.engine.currentText()]
        s.language = LANGUAGES[self.lang.currentText()]
        s.verbatim = self.style_.currentIndex() == 0
        s.enhancement = ENH_VALUES[self.enh.currentIndex()]
        s.cross_check = self.cross.isChecked()
        s.fuse = self.fuse.isChecked()
        s.review_threshold = REVIEW_VALUES[self.strict.currentIndex()]
        s.diarize = self.diar.isChecked()
        s.num_speakers = self.nspk.currentIndex() or None
        s.vocabulary = self.vocab.toPlainText()
        if s.active_project:
            from .projects import Projects

            Projects().update(s.active_project, vocabulary=s.vocabulary)
        s.precise_timing = self.precise.isChecked()
        s.speaker_library = self.recog.isChecked()
        s.fuzzy_vocab = self.fuzzy.isChecked()
        s.filename_context = self.fname.isChecked()
        s.translate_english = self.translate.isChecked()
        s.paragraphs = self.para.isChecked()
        s.include_timestamps = self.tsbox.isChecked()
        s.include_speakers = self.spk_names.isChecked()
        s.formats = [k for k, c in self.fmt_boxes.items() if c.isChecked()]
        s.auto_check_updates = self.auto_upd.isChecked()
        s.save()
        return s

    def start_batch(self):
        picked = [r for r in self.rows if r.checked and r.state != "ready"]
        todo = picked or [r for r in self.rows if r.state not in ("ready",)]
        if not todo:
            QMessageBox.information(self, "Nothing to transcribe",
                                    "Add videos or audio files first." if not self.rows else
                                    "Every file in the list is already transcribed. Use ⋯ › Transcribe again to redo one.")
            return
        s = self.collect_settings()
        if not s.formats:
            QMessageBox.information(self, "No output format", "Choose at least one format in the Output tab.")
            return
        if s.engine == "elevenlabs":
            from .engines.elevenlabs import get_api_key

            if not get_api_key():
                QMessageBox.warning(self, "API key needed", "Add your ElevenLabs API key first (Settings page).")
                return
            if QMessageBox.question(self, "Cloud processing",
                                    "ElevenLabs Scribe uploads the audio to ElevenLabs for transcription.\n"
                                    "Only continue if the client's data policy allows this.") != QMessageBox.Yes:
                return
        for r in todo:
            r.state, r.frac, r.message = "queued", 0.0, "Waiting in this batch"
            self.paint_row(r)
        self.batch = todo
        self.running = True
        self.start.setEnabled(False)
        self.start.setText("   Transcribing…")
        self.stop.setEnabled(True)
        self.overall.setVisible(True)
        self.overall.setValue(0)
        self.say(f"Batch started: {len(todo)} file(s) · {self.engine.currentText()} · language "
                 f"{self.lang.currentText()} · cross-check {'on' if s.cross_check else 'off'}")
        self.thread = QThread()
        self.worker = BatchWorker([r.path for r in todo], s)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.status.connect(self.on_status)
        self.worker.result.connect(self.on_result)
        self.worker.finished.connect(self.on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.start()

    def on_status(self, key: str, frac: float, msg: str):
        r = self.by_key.get(key)
        name = Path(key).name
        if r is not None:
            r.state = classify(frac, msg)
            if r.state == "ready" and not msg.startswith(("Completed", "Already")):
                r.state = "processing"
            r.frac = min(frac, 0.99) if r.state not in ("ready", "failed") else frac
            r.message = msg
            self.paint_row(r)
            self.now_label.setText(f"{name} — {msg}"[:150])
        key_ = msg.split(":")[0].split("(")[0].strip()
        last = getattr(self, "_last_key", {})
        if last.get(name) != key_ or msg.startswith(("Completed", "Failed")):
            self.say(f"{name}: {msg}")
        last[name] = key_
        self._last_key = last
        batch = getattr(self, "batch", [])
        if batch:
            prog = sum(1.0 if b.state in ("ready", "failed", "stopped") else b.frac for b in batch) / len(batch)
            self.overall.setValue(int(100 * prog))
        self.update_summary()

    def on_result(self, key: str, info: dict):
        r = self.by_key.get(key)
        if r:
            r.language = info.get("language") or r.language
            r.duration = info.get("duration") or r.duration
            r.outputs = info.get("outputs") or {}
            self.paint_row(r)

    def on_finished(self, out: dict):
        self.running = False
        self.start.setEnabled(True)
        self.start.setText("   Start Transcription")
        self.stop.setEnabled(False)
        self.overall.setVisible(False)
        for r in getattr(self, "batch", []):
            if r.state in ("queued", "processing", "transcribing"):
                r.state, r.message = "stopped", "Not started (batch stopped)"
                self.paint_row(r)
        if out.get("error"):
            self.now_label.setText("Batch error — see Activity Log")
            self.say("Batch error: " + out["error"])
            QMessageBox.critical(self, "Batch error", out["error"])
            return
        msg = f"{out['completed']} completed · {out['failed']} failed · {out['skipped']} already done"
        self.now_label.setText("Batch finished — " + msg)
        self.say("Batch finished — " + msg + f" · Master log: {out['excel']}")
        box = QMessageBox(self)
        box.setWindowTitle("Batch finished")
        box.setText(msg)
        box.setInformativeText(f"Master log: {out['excel']}")
        ob = box.addButton("Open output folder", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is ob:
            open_path(self.s.output_dir)
        self.update_summary()

    def stop_batch(self):
        if self.thread and self.thread.isRunning():
            self.worker.runner.stop_requested = True
            self.stop.setEnabled(False)
            self.say("Stopping after the current file…")
            self.now_label.setText("Stopping after the current file…")

    def open_log(self):
        p = Path(self.s.output_dir) / "MASTER_TRANSCRIPTION_LOG.xlsx"
        if p.exists():
            open_path(p)
        else:
            QMessageBox.information(self, "No log yet", "The Master Excel Log is created after the first batch.")

    def closeEvent(self, e):
        if self.running and QMessageBox.question(
                self, "Transcription running",
                "A batch is still running. Quit anyway? Finished files are kept; the rest can resume later.") \
                != QMessageBox.Yes:
            e.ignore()
            return
        try:
            self.collect_settings()
        except Exception:
            pass
        e.accept()

    # ------------------------------------------------------------------ updates
    def set_azure_key(self):
        from .tts_cloud import azure_key, set_azure

        k, r = azure_key()
        key, ok = QInputDialog.getText(self, "Azure Speech", "Azure Speech key (from the Azure portal › Speech resource "
                                       "› Keys and Endpoint):", QLineEdit.Password, k)
        if not ok:
            return
        region, ok = QInputDialog.getText(self, "Azure Speech", "Region (e.g. centralindia, eastus):", QLineEdit.Normal, r)
        if ok:
            set_azure(key, region)
            self.say("Azure Speech key saved in the system keychain")

    def check_updates(self, manual: bool = False):
        if not manual and self.s.last_update_check:
            try:
                if datetime.now() - datetime.fromisoformat(self.s.last_update_check) < timedelta(hours=20):
                    return
            except ValueError:
                pass
        if getattr(self, "_checking", False):
            return
        self._checking = True
        self.s.last_update_check = datetime.now().isoformat(timespec="seconds")
        self.s.save()
        if manual:
            self.say("Checking GitHub for updates…")
            if hasattr(self, "gh_status"):
                self.gh_status.setText("Checking GitHub…")
        self.uthread = QThread()
        self.uworker = UpdateWorker(self.s.update_manifest_url)
        self.uworker.moveToThread(self.uthread)
        self.uthread.started.connect(self.uworker.run)
        self.uworker.status.connect(self.on_update_status)
        self.uworker.models_found.connect(self.on_models_found)
        self._manual_check = manual
        self.uthread.finished.connect(self.on_update_check_done)
        self.uworker.finished.connect(self.uthread.quit)
        QTimer.singleShot(30000, self.uthread.quit)
        self.uthread.start()

    def on_update_check_done(self):  # slot (runs on the UI thread)
        self._checking = False
        if self._manual_check and getattr(self, "gh_last", None) is None:
            self.say("Couldn't reach GitHub — check the internet connection and try again")

    def on_update_status(self, st):  # slot: updater.ChannelStatus
        self.gh_last = st
        stamp = datetime.now().strftime("%d %b %Y, %H:%M")
        if hasattr(self, "gh_status"):
            self.gh_status.setText(f"{st.summary()}\nLast checked {stamp}.")
        if st.update:
            self.update_info = st.update
            self.on_update_found(st.update.version, st.update.notes)
        elif self._manual_check:
            self.say(st.summary())
            if st.reachable:
                QMessageBox.information(self, "Updates", st.summary())

    def on_update_found(self, version: str, notes: str):
        self.new_version = version
        self.banner_text.setText(f"<b>VERBATIM {version} is available on GitHub.</b>  {notes[:160]}")
        self.banner.setVisible(True)
        if hasattr(self, "upd_btn"):
            self.upd_btn.setText(f"  Update to {version}")
            self.upd_btn.setProperty("accent", True)
            self.upd_btn.style().unpolish(self.upd_btn)
            self.upd_btn.style().polish(self.upd_btn)
        self.say(f"Update available: {version}")

    def header_update_clicked(self):
        if getattr(self, "update_info", None):
            self.install_update()
        else:
            self.check_updates(manual=True)

    def open_releases(self):
        from .updater import channel_urls, releases_page

        st = getattr(self, "gh_last", None)
        url = releases_page(st.url if st and st.latest else channel_urls(self.s.update_manifest_url)[-1])
        QDesktopServices.openUrl(QUrl(url))

    def install_update(self):
        if self.running:
            QMessageBox.information(self, "Busy", "Install the update after the current batch finishes.")
            return
        info = getattr(self, "update_info", None)
        if not info:
            self.check_updates(manual=True)
            return
        notes = (info.notes or "").strip()
        if QMessageBox.question(self, "Install update",
                                f"VERBATIM {info.version} is ready on GitHub.\n\n{notes[:600]}\n\n"
                                "Download and install it now? VERBATIM will close and reopen. "
                                "Your settings, projects, voices and transcripts are kept, and the current "
                                "version is kept as a backup.") != QMessageBox.Yes:
            return
        self.idlg = QProgressDialog(f"Downloading VERBATIM {info.version}…", None, 0, 100, self)
        self.idlg.setWindowTitle("Updating VERBATIM")
        self.idlg.setWindowModality(Qt.WindowModal)
        self.idlg.setMinimumDuration(0)
        self.idlg.setValue(0)
        self.ithread = QThread()
        self.iworker = InstallWorker(info)
        self.iworker.moveToThread(self.ithread)
        self.ithread.started.connect(self.iworker.run)
        self.iworker.progress.connect(self.idlg.setValue)
        self.iworker.done.connect(self.on_install_done)
        self.iworker.done.connect(self.ithread.quit)
        self.ithread.start()

    def on_install_done(self, ok: bool, msg: str):  # slot
        self.idlg.close()
        if not ok:
            QMessageBox.warning(self, "Update failed", f"{msg}\n\nNothing was changed — VERBATIM {__version__} "
                                "is still installed.")
            return
        self.say("Update verified (SHA-256) — installing")
        QMessageBox.information(self, "Updating", msg)
        QApplication.quit()

    # ------------------------------------------------------------------ models
    def offer_models(self):
        from .models import CATALOG, is_installed

        from . import llm, tts

        missing = [k for k in ("whisper-turbo", "parakeet-v3") if not is_installed(k)]
        sizes = {k: CATALOG[k]["size_mb"] for k in missing}
        from . import tts_chatterbox, voicelab
        from .platform_info import models_dir, resource_root

        for eng in ("st", "ko", "zv", "cb"):
            if not tts.is_installed(eng):
                missing.append(f"tts-{eng}")
                sizes[f"tts-{eng}"] = tts_chatterbox.SIZE_MB if eng == "cb" else tts.ENGINES[eng]["size_mb"]
        if not (models_dir() / "separation" / "UVR-MDX-NET-Voc_FT.onnx").exists() and \
                not (resource_root() / "models" / "separation" / "UVR-MDX-NET-Voc_FT.onnx").exists():
            missing.append("sep-uvr")
            sizes["sep-uvr"] = voicelab.UVR_MB
        if llm.model_path("translategemma-4b") is None:
            missing.append("llm-translategemma-4b")
            sizes["llm-translategemma-4b"] = llm.MODELS["translategemma-4b"]["size_mb"]
        if not missing:
            QMessageBox.information(self, "Models", "All recommended models are already on this computer.")
            return
        size = sum(sizes.values())
        names = "\n".join(f"• {extra_model_label(k) or CATALOG[k]['label']} ({sizes[k]} MB)" for k in missing)
        if QMessageBox.question(self, "Download speech models",
                                f"Download these once (about {size / 1000:.1f} GB)?\n\n{names}") == QMessageBox.Yes:
            self.start_model_jobs([(k, None) for k in missing])

    def on_models_found(self, ups):
        lines = "\n".join(f"• {u.label} → {u.version} ({u.size_mb} MB){' — ' + u.notes if u.notes else ''}" for u in ups)
        self.say("Updated speech models available: " + ", ".join(u.label for u in ups))
        if QMessageBox.question(self, "Speech model updates",
                                f"Newer speech models are available:\n\n{lines}\n\nDownload and install them now?") \
                == QMessageBox.Yes:
            self.start_model_jobs([(u.key, u.entry) for u in ups])

    def start_model_jobs(self, jobs):
        if self.running:
            QMessageBox.information(self, "Busy", "Models will download after the current batch — try again then.")
            return
        self.mthread = QThread()
        self.mworker = ModelWorker(jobs)
        self.mworker.moveToThread(self.mthread)
        self.mthread.started.connect(self.mworker.run)
        self.mworker.progress.connect(self.on_model_progress)
        self.mworker.done.connect(self.on_models_done)
        self.mthread.start()

    def on_model_progress(self, m: str):
        self.say(m)
        self.now_label.setText(m[:120])

    def on_models_done(self, names: str):
        self.say(f"Models ready: {names}")
        self.fill_models()
        self.mthread.quit()


def _app():
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("VERBATIM")
    app.setOrganizationName("Infinite Story")
    app.setStyle("Fusion")
    f = app.font()
    if IS_WINDOWS:
        f.setFamily("Segoe UI")
    f.setPointSizeF(max(f.pointSizeF(), 10.0))
    app.setFont(f)
    return app


def main():
    app = _app()
    w = Window()
    w.show()
    return app.exec()


def selftest(png_path: str) -> int:
    """Open the window, save a screenshot after a few seconds and quit (used to verify builds)."""
    app = _app()
    w = Window()
    w.resize(1440, 900)
    w.show()
    QTimer.singleShot(5000, lambda: (w.grab().save(png_path), app.quit()))
    return app.exec()
