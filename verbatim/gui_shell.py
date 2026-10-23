# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""VERBATIM 3.7 shell: sidebar, top bar, job centre (every download / render / generation with a progress
bar), the Home page and the unified Library with play + download on every item."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from . import ui_theme as th
from .gui_player import Cover, Media, fmt, save_copy


def _t() -> dict:
    from . import gui

    return gui.T


def _label(text="", name=None, wrap=False):
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def glyph_button(text: str, glyph: str, name: str = "", size: int = 18) -> QPushButton:
    b = QPushButton(("   " + text) if text else "")
    if name:
        b.setObjectName(name)
    b.setCursor(Qt.PointingHandCursor)
    b.glyph = glyph
    b.setIcon(th.icon(glyph, _t()["ink"] if name not in ("primary", "start") else "#FFFFFF", size))
    b.setIconSize(QSize(size, size))
    return b


# ====================================================================== job centre
class Job(QObject):
    changed = Signal()
    finished = Signal()

    def __init__(self, title: str, kind: str = "task"):
        super().__init__()
        self.title, self.kind = title, kind
        self.frac, self.msg, self.state = 0.0, "Starting…", "running"
        self.files: dict = {}
        self.started = time.time()

    def progress(self, f: float, msg: str = ""):
        self.frac = max(0.0, min(1.0, float(f)))
        if msg:
            self.msg = msg
        self.changed.emit()

    def done(self, files: dict | None = None, msg: str = "Done"):
        self.state, self.frac, self.msg = "done", 1.0, msg
        self.files = {k: v for k, v in (files or {}).items() if v and Path(str(v)).exists()}
        self.changed.emit()
        self.finished.emit()

    def fail(self, err: str):
        self.state, self.msg = "failed", err[:200]
        self.changed.emit()

    def eta(self) -> str:
        if self.state != "running" or self.frac < 0.03:
            return ""
        el = time.time() - self.started
        rest = el * (1 - self.frac) / self.frac
        return f"~{fmt(int(rest * 1000))} left"


class JobCenter(QObject):
    """Every long thing VERBATIM does shows up here with a progress bar (sidebar + top-bar tray)."""
    changed = Signal()
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.jobs: list[Job] = []

    def add(self, title: str, kind: str = "task") -> Job:
        j = Job(title, kind)
        j.changed.connect(self.changed)
        j.finished.connect(self.finished)
        self.jobs.insert(0, j)
        self.jobs = self.jobs[:40]
        self.changed.emit()
        return j

    def running(self) -> list[Job]:
        return [j for j in self.jobs if j.state == "running"]


class JobRow(QFrame):
    def __init__(self, job: Job, compact: bool = False):
        super().__init__()
        self.job = job
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(3)
        top = QHBoxLayout()
        self.title = _label(job.title, "fname")
        self.title.setMaximumWidth(170 if compact else 360)
        top.addWidget(self.title, 1)
        self.pct = _label("", "fmeta")
        top.addWidget(self.pct)
        v.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        v.addWidget(self.bar)
        self.msg = _label("", "hint")
        self.msg.setMaximumWidth(190 if compact else 380)
        v.addWidget(self.msg)
        if not compact:
            self.acts = QHBoxLayout()
            v.addLayout(self.acts)
        self.compact = compact
        job.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        j = self.job
        self.bar.setValue(int(j.frac * 1000))
        self.bar.setObjectName({"done": "done", "failed": "failed"}.get(j.state, ""))
        self.bar.style().unpolish(self.bar)
        self.bar.style().polish(self.bar)
        self.pct.setText({"done": "✓", "failed": "✗"}.get(j.state, f"{int(j.frac * 100)}%"))
        eta = j.eta()
        self.msg.setText((j.msg[:70] + (f"  ·  {eta}" if eta else "")))
        if not self.compact and j.state == "done" and j.files and not self.acts.count():
            for label, path in list(j.files.items())[:4]:
                b = QPushButton("⬇  " + label)
                b.setObjectName("dl")
                b.clicked.connect(lambda _=False, p=path: save_copy(self, p))
                self.acts.addWidget(b)
            self.acts.addStretch()


class JobsPopup(QFrame):
    def __init__(self, center: JobCenter, parent):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("card")
        self.setFixedWidth(440)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.addWidget(_label("Downloads & jobs", "h2"))
        jobs = center.jobs[:12]
        if not jobs:
            v.addWidget(_label("Nothing running. Downloads, renders, songs and films show their progress here.",
                               "hint", wrap=True))
        for j in jobs:
            v.addWidget(JobRow(j))


# ====================================================================== sidebar
NAV = [  # key, label, glyph, section
    ("home", "Home", "home", ""),
    ("transcribe", "Transcribe", "quotes", "CREATE"),
    ("voiceover", "Voiceover", "mic_on", ""),
    ("voice", "Voice Studio", "voice", ""),
    ("music", "Music", "music", ""),
    ("video", "Video Localise", "translate", ""),
    ("film", "Feature Film", "film_reel", ""),
    ("library", "Library", "library", "YOURS"),
    ("activity", "Activity", "clock", ""),
    ("settings", "Settings", "gear", ""),
]


class Wordmark(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(54)

    def paintEvent(self, _):
        from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath

        t = _t()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # logo mark: a gradient disc with a waveform
        g = QLinearGradient(0, 0, 30, 30)
        for i, c in enumerate(th.GRAD):
            g.setColorAt(i / 2, QColor(c))
        path = QPainterPath()
        path.addRoundedRect(4, 12, 30, 30, 9, 9)
        p.fillPath(path, g)
        p.drawPixmap(10, 18, th.pixmap("wave", "#FFFFFF", 18, weight="bold" if False else "regular"))
        f = QFont(th.UI)
        f.setPixelSize(17)
        f.setWeight(QFont.Weight(800))
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        p.setFont(f)
        p.setPen(QColor(t["ink"]))
        p.drawText(44, 31, "VERBATIM")
        f.setPixelSize(10)
        f.setWeight(QFont.Weight(600))
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.5)
        p.setFont(f)
        p.setPen(QColor(t["muted"]))
        p.drawText(45, 45, "by Infinite Story")


class Sidebar(QWidget):
    go = Signal(str)

    def __init__(self, jobs: JobCenter, version: str):
        super().__init__()
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(232)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(2)
        v.addWidget(Wordmark())
        v.addSpacing(10)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for key, label, glyph, section in NAV:
            if section:
                v.addSpacing(10)
                v.addWidget(_label(section, "kicker"))
                v.addSpacing(2)
            b = QPushButton("   " + label)
            b.setObjectName("navItem")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.glyph = glyph
            b.setIconSize(QSize(18, 18))
            b.toggled.connect(lambda on, b=b: self._paint(b))
            b.clicked.connect(lambda _=False, k=key: self.go.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            v.addWidget(b)
            self._paint(b)
        v.addStretch()
        self.jobs_box = QVBoxLayout()
        self.jobs_box.setSpacing(4)
        v.addLayout(self.jobs_box)
        self.jobs = jobs
        jobs.changed.connect(self.fill_jobs)
        v.addSpacing(8)
        bottom = QHBoxLayout()
        self.avatar = _label("", "avatar")
        self.avatar.setFixedSize(34, 34)
        self.avatar.setAlignment(Qt.AlignCenter)
        bottom.addWidget(self.avatar)
        who = QVBoxLayout()
        who.setSpacing(0)
        self.user = _label("", "fname")
        who.addWidget(self.user)
        who.addWidget(_label(f"v{version} · internal", "hint"))
        bottom.addLayout(who, 1)
        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("iconBtn")
        self.theme_btn.setToolTip("Dark / light")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        bottom.addWidget(self.theme_btn)
        v.addLayout(bottom)
        self.retheme()

    def _paint(self, b):
        t = _t()
        b.setIcon(th.icon(b.glyph, t["accent"] if b.isChecked() else t["sub"], 18,
                          weight="fill" if b.isChecked() else "regular"))

    def select(self, key: str):
        b = self.buttons.get(key)
        if b:
            b.setChecked(True)

    def fill_jobs(self):
        while self.jobs_box.count():
            it = self.jobs_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        run = self.jobs.running()[:3]
        if run:
            self.jobs_box.addWidget(_label("IN PROGRESS", "kicker"))
        for j in run:
            self.jobs_box.addWidget(JobRow(j, compact=True))

    def retheme(self):
        for b in self.buttons.values():
            self._paint(b)
        t = _t()
        self.theme_btn.setIcon(th.icon("sun" if t["name"] == "dark" else "moon", t["sub"], 18))


# ====================================================================== top bar
class GlobalProgress(QProgressBar):
    """Thin bar under the top bar: the current main job (compat with the 3.6 ruler API)."""

    def __init__(self):
        super().__init__()
        self.setRange(0, 1000)
        self.setTextVisible(False)
        self.setFixedHeight(3)
        self.setStyleSheet("QProgressBar{max-height:3px;min-height:3px;border-radius:1px;}")
        self.setVisible(False)

    def set_progress(self, frac):
        if frac is None:
            self.setVisible(False)
            return
        self.setVisible(True)
        self.setValue(int(1000 * max(0.0, min(1.0, float(frac)))))

    def busy(self, on: bool):
        self.set_progress(0.0 if on else None)


class TopBar(QWidget):
    search = Signal(str)

    def __init__(self, jobs: JobCenter):
        super().__init__()
        self.jobs = jobs
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = _label("", "display")
        self.tag = _label("", "displayIt")
        titles.addWidget(self.title)
        titles.addWidget(self.tag)
        row.addLayout(titles)
        row.addStretch()
        self.chapters = QHBoxLayout()
        self.chapters.setSpacing(4)
        self.chapters.setContentsMargins(0, 0, 0, 0)
        self.chapter_box = QWidget()
        self.chapter_box.setLayout(self.chapters)
        self.find = QLineEdit()
        self.find.setObjectName("search")
        self.find.setPlaceholderText("Search your library…")
        self.find.setFixedWidth(230)
        self.find.returnPressed.connect(lambda: self.search.emit(self.find.text()))
        self.find.addAction(th.icon("search", _t()["muted"], 16), QLineEdit.LeadingPosition)
        row.addWidget(self.find)
        self.jobs_btn = QPushButton("  Downloads")
        self.jobs_btn.setObjectName("ghost")
        self.jobs_btn.setCursor(Qt.PointingHandCursor)
        self.jobs_btn.setIcon(th.icon("download", _t()["ink"], 16))
        self.jobs_btn.clicked.connect(self.show_jobs)
        row.addWidget(self.jobs_btn)
        self.update_btn = QPushButton("  Update")
        self.update_btn.setObjectName("pillBtn")
        self.update_btn.setProperty("accent", True)
        self.update_btn.setVisible(False)
        row.addWidget(self.update_btn)
        v.addLayout(row)
        crow = QHBoxLayout()
        crow.addWidget(self.chapter_box)
        crow.addStretch()
        v.addLayout(crow)
        self.ruler = GlobalProgress()
        v.addWidget(self.ruler)
        jobs.changed.connect(self.on_jobs)
        # 3.6 compatibility
        self.status = QLabel()
        self.kicker = QLabel()

    def set(self, _kicker: str, title: str, tag: str, chapters: bool):
        self.title.setText(title)
        self.tag.setText(tag)
        self.chapter_box.setVisible(chapters)

    def on_jobs(self):
        n = len(self.jobs.running())
        self.jobs_btn.setText(f"  Downloads · {n} running" if n else "  Downloads")

    def show_jobs(self):
        pop = JobsPopup(self.jobs, self)
        pop.adjustSize()
        g = self.jobs_btn.mapToGlobal(self.jobs_btn.rect().bottomRight())
        pop.move(g.x() - pop.width(), g.y() + 6)
        pop.show()

    def retheme(self):
        self.jobs_btn.setIcon(th.icon("download", _t()["ink"], 16))


# ====================================================================== library rows
class ItemRow(QFrame):
    """One creation: cover · title · type/date · duration · ▶ Play · ⬇ Download (every file) · folder."""

    def __init__(self, it, on_play):
        super().__init__()
        self.it = it
        self.setObjectName("card2")
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 8, 12, 8)
        h.setSpacing(12)
        from .library import GLYPH

        c = Cover(44)
        c.set(GLYPH.get(it.kind, "wave"), len(it.title))
        h.addWidget(c)
        info = QVBoxLayout()
        info.setSpacing(1)
        t = _label(it.title, "fname")
        t.setMinimumWidth(120)
        info.addWidget(t)
        when = (it.when or "").replace("T", " ")[:16]
        info.addWidget(_label(f"{it.sub}   ·   {when}" if when else it.sub, "hint"))
        h.addLayout(info, 1)
        if it.duration:
            h.addWidget(_label(fmt(int(it.duration * 1000)), "time"))
        play = QPushButton()
        play.setObjectName("playBtn")
        play.setFixedSize(36, 36)
        play.setStyleSheet("min-width:36px;max-width:36px;min-height:36px;max-height:36px;border-radius:18px;")
        play.setIcon(th.icon("play", _t()["bg"], 16, weight="fill"))
        play.setToolTip("Play")
        play.setEnabled(bool(it.play))
        play.clicked.connect(lambda: on_play(it))
        h.addWidget(play)
        dl = QToolButton()
        dl.setText("  Download")
        dl.setObjectName("dlTool")
        dl.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        dl.setIcon(th.icon("download", _t()["ink"], 16))
        dl.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(dl)
        for label, path in it.files.items():
            m.addAction(f"{label}  ·  {Path(path).suffix[1:].upper()}", lambda p=path: save_copy(self, p))
        if not it.files:
            m.addAction("Nothing to download yet").setEnabled(False)
        dl.setMenu(m)
        h.addWidget(dl)
        fo = QPushButton()
        fo.setObjectName("iconBtn")
        fo.setToolTip("Show in folder")
        fo.setIcon(th.icon("folder", _t()["sub"], 18))
        fo.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(it.folder)))
        h.addWidget(fo)


def play_item(it):
    from .library import KINDS

    if it.play:
        Media.get().load(it.play, it.title, KINDS.get(it.kind, it.kind))


class LibraryPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.w = window
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        row = QHBoxLayout()
        self.kind = QButtonGroup(self)
        for i, (k, name) in enumerate([("", "All"), ("transcript", "Transcripts"), ("voiceover", "Voiceovers"),
                                       ("music", "Music"), ("video", "Videos"), ("film", "Feature films")]):
            b = QPushButton(name)
            b.setObjectName("chapter")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.kind = k
            self.kind.addButton(b, i)
            row.addWidget(b)
        self.kind.button(0).setChecked(True)
        self.kind.idClicked.connect(lambda _: self.fill())
        row.addStretch()
        self.q = QLineEdit()
        self.q.setObjectName("search")
        self.q.setPlaceholderText("Filter…")
        self.q.setFixedWidth(220)
        self.q.textChanged.connect(lambda _: self.fill())
        row.addWidget(self.q)
        b = QPushButton("Refresh")
        b.setObjectName("ghost")
        b.clicked.connect(self.reload)
        row.addWidget(b)
        v.addLayout(row)
        self.note = _label("", "hint")
        v.addWidget(self.note)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        self.list = QVBoxLayout(inner)
        self.list.setContentsMargins(0, 0, 6, 0)
        self.list.setSpacing(8)
        sc.setWidget(inner)
        v.addWidget(sc, 1)
        self.items = []

    def reload(self):
        from .library import everything

        self.items = everything(self.w.s.output_dir)
        self.fill()

    def fill(self):
        while self.list.count():
            it = self.list.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        k = self.kind.checkedButton().kind if self.kind.checkedButton() else ""
        q = self.q.text().strip().lower()
        shown = [i for i in self.items if (not k or i.kind == k) and (not q or q in i.title.lower())]
        queue = [(i.play, i.title, i.sub) for i in shown if i.play]
        for it in shown[:300]:
            self.list.addWidget(ItemRow(it, lambda x, queue=queue: Media.get().load(x.play, x.title, x.sub,
                                                                                      queue=queue)))
        self.list.addStretch()
        self.note.setText(f"{len(shown)} item(s) in {self.w.s.output_dir}" if shown else
                          "Nothing here yet — everything you make in VERBATIM appears in this library, ready to play "
                          "and download.")


class Tile(QFrame):
    def __init__(self, glyph: str, title: str, text: str, on_click, seed: int = 0):
        super().__init__()
        self.setObjectName("tile")
        self.setCursor(Qt.PointingHandCursor)
        self.on_click = on_click
        self.setMinimumHeight(150)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 16)
        v.setSpacing(6)
        c = Cover(46)
        c.set(glyph, seed)
        v.addWidget(c)
        v.addSpacing(6)
        v.addWidget(_label(title, "tileTitle"))
        v.addWidget(_label(text, "hint", wrap=True))
        v.addStretch()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.on_click()


class HomePage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.w = window
        sc = QScrollArea(self)
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(sc)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 8, 0)
        v.setSpacing(14)
        v.addWidget(_label("CREATE", "kicker"))
        grid = QGridLayout()
        grid.setSpacing(14)
        tiles = [("quotes", "Transcribe", "Batch videos and audio to exact, speaker-labelled text.", "transcribe"),
                 ("mic_on", "Voiceover", "Script in — voice only, or voice with music.", "voiceover"),
                 ("music", "Make a song", "Write lyrics, pick singers — male, female, duet, chorus.", "music"),
                 ("voice", "Clone & direct voices", "Your consented voices, translated and performed.", "voice"),
                 ("translate", "Localise a video", "Every language, subtitles, original music kept.", "video"),
                 ("film_reel", "Dub a feature film", "Each actor's own voice, on the timeline, lip-synced.", "film")]
        for i, (g, title, text, key) in enumerate(tiles):
            grid.addWidget(Tile(g, title, text, lambda k=key: self.w.go(k), i), i // 3, i % 3)
        v.addLayout(grid)
        head = QHBoxLayout()
        head.addWidget(_label("RECENT", "kicker"))
        head.addStretch()
        b = QPushButton("Open library")
        b.setObjectName("link")
        b.clicked.connect(lambda: self.w.go("library"))
        head.addWidget(b)
        v.addSpacing(6)
        v.addLayout(head)
        self.recent = QVBoxLayout()
        self.recent.setSpacing(8)
        v.addLayout(self.recent)
        v.addStretch()
        sc.setWidget(inner)

    def refresh(self):
        from .library import everything

        while self.recent.count():
            it = self.recent.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        items = everything(self.w.s.output_dir)[:8]
        queue = [(i.play, i.title, i.sub) for i in items if i.play]
        for it in items:
            self.recent.addWidget(ItemRow(it, lambda x: Media.get().load(x.play, x.title, x.sub, queue=queue)))
        if not items:
            self.recent.addWidget(_label("Your creations will appear here.", "hint"))


def files_from(res) -> dict:
    """Pull downloadable files out of whatever a job returned (dicts, lists of dicts, nested 'files')."""
    out: dict = {}

    def walk(x, label=""):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, k if not label else f"{label} · {k}")
        elif isinstance(x, (list, tuple)):
            for i, v in enumerate(x[:12]):
                walk(v, label or f"item {i + 1}")
        elif isinstance(x, str) and len(x) < 1024 and ("/" in x or "\\\\" in x):
            try:
                if Path(x).is_file():
                    out[label or Path(x).name] = x
            except OSError:
                pass

    walk(res)
    return out


def track(win, worker, title: str, kind: str = "task"):
    """Show a worker in the job centre: progress bar while it runs, download buttons when it is done."""
    if not hasattr(win, "jobs"):
        return None
    j = win.jobs.add(title, kind)
    worker.progress.connect(j.progress)

    def fin(res, err):
        if err:
            j.fail(err)
        else:
            j.done(files_from(res))
    worker.done.connect(fin)
    return j
