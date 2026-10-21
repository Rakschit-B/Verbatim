# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Module 04 — Video Localise. One film in; a dubbed, subtitled (optionally lip-synced) film out per language."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar,
                               QPushButton, QRadioButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from . import ui_theme as th

LANGS = ["hi", "en", "es", "fr", "de", "pt", "it", "ar", "ja", "zh", "ko", "ru", "bn", "ta", "te", "mr", "gu",
         "kn", "ml", "pa", "ur", "he", "tr", "id"]
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm", ".mxf"}


def _t() -> dict:
    from . import gui

    return gui.T


def _label(text="", name=None, wrap=False):
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def _card():
    f = QFrame()
    f.setObjectName("card")
    return f


class _Job(QObject):
    progress = Signal(float, str)
    done = Signal(object, str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.stop = False

    def run(self):
        try:
            self.done.emit(self.fn(lambda f, m: self.progress.emit(float(f), str(m)), lambda: self.stop), "")
        except Exception as exc:
            self.done.emit(None, f"{type(exc).__name__}: {exc}")


class FilmCard(QFrame):
    """The film: a still from the video in a letterbox frame with crop marks and a timecode slate."""
    dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(250)
        self.still: QPixmap | None = None
        self.name = ""
        self.meta = ""
        self.hover = False

    def set_film(self, name: str, meta: str, png: bytes):
        self.name, self.meta = name, meta
        px = QPixmap()
        self.still = px if png and px.loadFromData(png) else None
        self.update()

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
        for u in e.mimeData().urls():
            if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in VIDEO_EXT:
                self.dropped.emit(u.toLocalFile())
                return

    def paintEvent(self, _):
        from .gui_score import crop_marks, font

        t = _t()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(t["accent"] if self.hover else t["border"]), 1.5 if self.hover else 1,
                      Qt.DashLine if self.hover else Qt.SolidLine))
        p.setBrush(QColor(t["soft"] if self.hover else t["card"]))
        p.drawRoundedRect(r, 6, 6)
        crop_marks(p, r, QColor(t["muted"]))
        frame = r.adjusted(28, 28, -28, -64)
        ar = 16 / 9
        w = min(frame.width(), frame.height() * ar)
        h = w / ar
        box = QRectF(frame.center().x() - w / 2, frame.top() + (frame.height() - h) / 2, w, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#0B0A09"))
        p.drawRect(box)
        if self.still:
            s = self.still.scaled(int(box.width() * 2), int(box.height() * 2), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            s.setDevicePixelRatio(2)
            p.drawPixmap(QPointF(box.center().x() - s.width() / 4, box.center().y() - s.height() / 4), s)
        else:
            p.setPen(QColor(t["muted"]))
            p.setFont(font(th.DISPLAY, 30, italic=True))
            p.drawText(box, Qt.AlignCenter, "Drop the film here")
        # sprocket holes along both edges of the frame
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t["card"]))
        for k in range(int(box.width() // 18)):
            x = box.left() + 9 + k * 18
            p.drawRoundedRect(QRectF(x - 4, box.top() + 4, 8, 5), 1.5, 1.5)
            p.drawRoundedRect(QRectF(x - 4, box.bottom() - 9, 8, 5), 1.5, 1.5)
        # slate
        p.setPen(QColor(t["ink"]))
        p.setFont(font(th.UI, 14, 600))
        p.drawText(QRectF(r.left() + 28, r.bottom() - 58, r.width() - 56, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   self.name or "No film yet")
        p.setPen(QColor(t["sub"]))
        p.setFont(font(th.MONO, 10, 400, spacing=1.2))
        p.drawText(QRectF(r.left() + 28, r.bottom() - 36, r.width() - 56, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   self.meta or "MP4 · MOV · MKV · drop a video or press Choose film")


class VideoStudio(QWidget):
    log = Signal(str)

    def __init__(self, window):
        super().__init__()
        self.w = window
        self.thread = None
        self.video = ""
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)
        h.addWidget(self._left(), 1)
        h.addWidget(self._right())

    # ------------------------------------------------------------ left: film + languages + results
    def _left(self):
        c = _card()
        v = QVBoxLayout(c)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(_label("The film", "h2"))
        top.addStretch()
        pick = QPushButton("Choose film…")
        pick.clicked.connect(self.choose)
        top.addWidget(pick)
        v.addLayout(top)
        self.film = FilmCard()
        self.film.dropped.connect(self.set_video)
        v.addWidget(self.film, 3)
        row = QHBoxLayout()
        row.addWidget(_label("Into", "h2"))
        row.addWidget(_label("Pick every language you want — each becomes its own dubbed film.", "hint"), 1)
        v.addLayout(row)
        grid = QGridLayout()
        grid.setSpacing(6)
        from .translate import LANG_NAMES

        self.lang_btns: dict[str, QPushButton] = {}
        for i, code in enumerate(LANGS):
            b = QPushButton(LANG_NAMES.get(code, code))
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(code == "hi")
            self.lang_btns[code] = b
            grid.addWidget(b, i // 8, i % 8)
        v.addLayout(grid)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["LANGUAGE", "STATUS", "FILM", "NOTES"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.cellDoubleClicked.connect(self.open_row)
        v.addWidget(self.table, 2)
        acts = QHBoxLayout()
        b = QPushButton("Play film")
        b.clicked.connect(lambda: self.open_row(self.table.currentRow(), 2))
        acts.addWidget(b)
        b = QPushButton("Edit lines in Voice Studio")
        b.setToolTip("Every language is a normal Voice Studio job — re-direct or re-take any line, then re-render")
        b.clicked.connect(self.edit_in_voice)
        acts.addWidget(b)
        b = QPushButton("Open folder")
        b.clicked.connect(self.open_folder)
        acts.addWidget(b)
        acts.addStretch()
        v.addLayout(acts)
        return c

    # ------------------------------------------------------------ right: how
    def _right(self):
        c = _card()
        c.setFixedWidth(410)
        outer = QVBoxLayout(c)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(10)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(2, 0, 6, 0)
        v.setSpacing(10)
        v.addWidget(_label("Voices", "h2"))
        self.voice_mode = QButtonGroup(self)
        own = QRadioButton("Keep each speaker's own voice")
        own.setChecked(True)
        studio = QRadioButton("Studio voices (expressive, no cloning)")
        self.voice_mode.addButton(own, 0)
        self.voice_mode.addButton(studio, 1)
        v.addWidget(own)
        v.addWidget(_label("VERBATIM learns each speaker from the film itself and speaks the new language in their "
                           "voice. A rights confirmation is recorded in the Consent register.", "hint", wrap=True))
        self.consent = QLineEdit()
        self.consent.setPlaceholderText("Rights confirmed by (your name)")
        v.addWidget(self.consent)
        v.addWidget(studio)
        self.voice_mode.idToggled.connect(lambda i, on: self.consent.setEnabled(self.voice_mode.checkedId() == 0))
        v.addWidget(self._rule())
        v.addWidget(_label("Translation", "h2"))
        self.translator = QComboBox()
        self.translator.addItem("TranslateGemma — offline, private", "translategemma")
        self.translator.addItem("Claude — best nuance (cloud)", "claude")
        self.translator.addItem("OPUS-MT — offline, fast", "opus")
        v.addWidget(self.translator)
        self.style = QComboBox()
        for k, name in (("natural", "Natural spoken (recommended)"), ("faithful", "Faithful"),
                        ("creative", "Creative / transcreation")):
            self.style.addItem(name, k)
        v.addWidget(self.style)
        self.direct = QCheckBox("Direct the performance (emotion && emphasis per line)")
        self.direct.setChecked(True)
        v.addWidget(self.direct)
        v.addWidget(self._rule())
        v.addWidget(_label("Picture & sound", "h2"))
        self.keep_bg = QCheckBox("Keep the original music && effects")
        self.keep_bg.setChecked(True)
        v.addWidget(self.keep_bg)
        self.subs_soft = QCheckBox("Subtitle track inside the film")
        self.subs_soft.setChecked(True)
        v.addWidget(self.subs_soft)
        self.subs_burn = QCheckBox("Burn subtitles into the picture")
        v.addWidget(self.subs_burn)
        self.lipsync = QCheckBox("Lip-sync the faces  ·  Cloud GPU, beta")
        self.lipsync.setToolTip("Re-times every mouth to the new language with LatentSync 1.6 on your Cloud GPU "
                                "(Settings › Cloud GPU). Needs an NVIDIA GPU with 18 GB+.")
        v.addWidget(self.lipsync)
        self.quality = QComboBox()
        self.quality.addItem("Studio quality (slower, best)", "studio")
        self.quality.addItem("Standard (faster)", "standard")
        v.addWidget(self.quality)
        v.addStretch()
        sc.setWidget(inner)
        outer.addWidget(sc, 1)
        self.status = _label("Choose a film, tick the languages, press Localise.", "hint", wrap=True)
        outer.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        outer.addWidget(self.bar)
        self.go = QPushButton("   Localise the film")
        self.go.setObjectName("start")
        self.go.setCursor(Qt.PointingHandCursor)
        self.w.icons.set(self.go, "translate", "accent_ink", 20)
        self.go.clicked.connect(self.start)
        outer.addWidget(self.go)
        self.stop_btn = QPushButton("Stop after this language")
        self.stop_btn.setObjectName("stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        outer.addWidget(self.stop_btn)
        return c

    @staticmethod
    def _rule():
        f = QFrame()
        f.setObjectName("hline")
        return f

    # ------------------------------------------------------------ actions
    def refresh(self):
        from .cloud import active_for

        cloud = active_for("lipsync")
        self.lipsync.setEnabled(cloud)
        if not cloud:
            self.lipsync.setChecked(False)
            self.lipsync.setText("Lip-sync the faces  ·  needs a Cloud GPU (Settings)")
        else:
            self.lipsync.setText("Lip-sync the faces  ·  Cloud GPU, beta")

    def choose(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose the film", str(Path.home() / "Movies"),
                                           "Video (*.mp4 *.mov *.mkv *.m4v *.avi *.webm *.mxf)")
        if p:
            self.set_video(p)

    def set_video(self, path: str):
        import subprocess

        from .audio import probe
        from .platform_info import IS_WINDOWS, ffmpeg_path

        self.video = path
        dur, png = 0.0, b""
        try:
            dur = probe(Path(path)).duration or 0.0
        except Exception:
            pass
        try:
            r = subprocess.run([ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error",
                                "-ss", f"{min(max(dur * 0.2, 0), 60):.2f}", "-i", path, "-frames:v", "1",
                                "-vf", "scale=960:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                               capture_output=True, timeout=40, creationflags=0x08000000 if IS_WINDOWS else 0)
            png = r.stdout if r.returncode == 0 else b""
        except Exception:
            pass
        tc = f"{int(dur // 3600):02d}:{int(dur // 60 % 60):02d}:{int(dur % 60):02d}"
        self.film.set_film(Path(path).name, f"TC {tc}  ·  {Path(path).suffix[1:].upper()}  ·  {Path(path).parent}", png)
        self.status.setText("Ready. Tick the languages and press Localise.")

    def request(self):
        from .localise import LocaliseRequest

        langs = [k for k, b in self.lang_btns.items() if b.isChecked()]
        return LocaliseRequest(video=self.video, languages=langs,
                               voice_mode="own" if self.voice_mode.checkedId() == 0 else "studio",
                               consent_person=self.consent.text().strip(), translator=self.translator.currentData(),
                               style=self.style.currentData(), direct=self.direct.isChecked(),
                               keep_background=self.keep_bg.isChecked(), subtitles_soft=self.subs_soft.isChecked(),
                               subtitles_burn=self.subs_burn.isChecked(), lipsync=self.lipsync.isChecked(),
                               quality=self.quality.currentData())

    def start(self):
        if self.thread and self.thread.isRunning():
            return
        r = self.request()
        if not r.video:
            QMessageBox.information(self, "Choose a film", "Choose or drop a video first.")
            return
        if not r.languages:
            QMessageBox.information(self, "Languages", "Tick at least one language.")
            return
        if r.voice_mode == "own" and not r.consent_person:
            QMessageBox.information(self, "Rights", "To keep the speakers' own voices, type who confirmed the rights "
                                    "(it is recorded in the Consent register) — or choose Studio voices.")
            return
        from . import qt_workers
        from .translate import LANG_NAMES

        self.table.setRowCount(0)
        self.rows = {}
        for code in r.languages:
            i = self.table.rowCount()
            self.table.insertRow(i)
            self.table.setItem(i, 0, QTableWidgetItem(LANG_NAMES.get(code, code)))
            self.table.setItem(i, 1, QTableWidgetItem("Queued"))
            self.table.setItem(i, 2, QTableWidgetItem(""))
            self.table.setItem(i, 3, QTableWidgetItem(""))
            self.rows[LANG_NAMES.get(code, code)] = i
        settings = copy.deepcopy(self.w.collect_settings())
        self.go.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.bar.setVisible(True)
        self.w.mast.ruler.set_progress(0.0)
        from .localise import run

        self.worker = _Job(lambda p, stop: run(r, settings, p, stop))
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(self.on_done)
        self.thread = qt_workers.start(self.worker, self.worker.run, [self.worker.done])
        self.log.emit(f"Video Localise: {Path(r.video).name} → {', '.join(r.languages)}")

    def stop(self):
        if getattr(self, "worker", None):
            self.worker.stop = True
            self.status.setText("Stopping after the current language…")

    def on_progress(self, f: float, m: str):
        self.bar.setValue(int(1000 * max(0.0, min(1.0, f))))
        self.w.mast.ruler.set_progress(f)
        self.status.setText(m)
        name = m.split(":", 1)[0]
        if name in getattr(self, "rows", {}):
            it = self.table.item(self.rows[name], 1)
            if it:
                it.setText(m.split(":", 1)[1].strip()[:60])

    def on_done(self, res, err):
        self.go.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.bar.setVisible(False)
        self.w.mast.ruler.set_progress(None)
        if err:
            self.status.setText("Localisation stopped — " + err)
            QMessageBox.warning(self, "Video Localise", err)
            self.log.emit("Video Localise failed: " + err)
            return
        from .translate import LANG_NAMES

        self.result = res
        for code, out in res.get("results", {}).items():
            i = self.rows.get(LANG_NAMES.get(code, code))
            if i is None:
                continue
            self.table.item(i, 1).setText("✓ Ready")
            it = QTableWidgetItem(Path(out.get("film") or out.get("mix") or "").name)
            it.setData(Qt.UserRole, json.dumps(out))
            self.table.setItem(i, 2, it)
            self.table.item(i, 3).setText("; ".join(out.get("notes", []))[:200])
        self.status.setText("Every language is ready — double-click a row to play it.")
        self.log.emit(f"Video Localise finished: {len(res.get('results', {}))} language(s)")

    def _row_out(self, row: int) -> dict:
        it = self.table.item(row, 2) if row >= 0 else None
        try:
            return json.loads(it.data(Qt.UserRole)) if it and it.data(Qt.UserRole) else {}
        except ValueError:
            return {}

    def open_row(self, row: int, _c: int = 0):
        out = self._row_out(row)
        f = out.get("film") or out.get("mix")
        if f and Path(f).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(f))

    def open_folder(self):
        out = self._row_out(self.table.currentRow())
        f = out.get("folder") or (str(Path(self.video).parent) if self.video else "")
        if f:
            QDesktopServices.openUrl(QUrl.fromLocalFile(f))

    def edit_in_voice(self):
        res = getattr(self, "result", None)
        if res and res.get("transcript"):
            self.w.send_to_voice(res["transcript"])
