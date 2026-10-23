# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Playback for every module: one shared media engine (Qt Multimedia), the bottom player bar with full
transport (play/pause, ±10 s, previous/next, timeline scrubbing, elapsed/total, speed, volume), a
picture-in-picture video pane and a full-size video window. Falls back to the system player when Qt
Multimedia is unavailable."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from . import ui_theme as th

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
    HAVE_QTMM = True
except Exception:          # pragma: no cover — very old bundles
    HAVE_QTMM = False

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm", ".mxf"}


def _t() -> dict:
    from . import gui

    return gui.T


def fmt(ms: int) -> str:
    s = max(0, int(ms // 1000))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def save_copy(parent, path: str | Path, title: str = "Download") -> str:
    """'Download' = save a copy of an output wherever the user wants (Downloads by default)."""
    src = Path(path)
    if not src.exists():
        return ""
    start = Path.home() / "Downloads" / src.name
    dest, _ = QFileDialog.getSaveFileName(parent, title, str(start), f"*{src.suffix}")
    if not dest:
        return ""
    shutil.copy2(src, dest)
    return dest


# ====================================================================== engine
class Media(QObject):
    """The one shared player. `load()` plays a file (optionally only start…end seconds)."""
    changed = Signal()                  # new item loaded
    state = Signal(bool)                # playing?
    position = Signal(int, int)         # ms, duration ms
    ended = Signal()
    _inst = None

    @classmethod
    def get(cls) -> "Media":
        if cls._inst is None:
            cls._inst = Media()
        return cls._inst

    def __init__(self):
        super().__init__()
        self.path = ""
        self.title = ""
        self.sub = ""
        self.kind = "audio"
        self.end_ms = 0
        self.queue: list[tuple] = []
        self.qi = -1
        if HAVE_QTMM:
            import os

            self.p = QMediaPlayer()
            self.out = None
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":      # headless tests have no sound device
                self.out = QAudioOutput()
                self.out.setVolume(0.85)
                self.p.setAudioOutput(self.out)
            self.p.positionChanged.connect(self._pos)
            self.p.durationChanged.connect(lambda d: self.position.emit(self.p.position(), d))
            self.p.playbackStateChanged.connect(lambda s: self.state.emit(s == QMediaPlayer.PlayingState))
            self.p.mediaStatusChanged.connect(self._status)
        else:
            self.p = None

    # ------------------------------------------------------------ control
    def load(self, path: str | Path, title: str = "", sub: str = "", start: float = 0.0, end: float | None = None,
             autoplay: bool = True, queue: list[tuple] | None = None):
        path = str(path)
        self.path, self.title, self.sub = path, title or Path(path).stem, sub
        self.kind = "video" if Path(path).suffix.lower() in VIDEO_EXT else "audio"
        self.end_ms = int(end * 1000) if end else 0
        if queue is not None:
            self.queue = queue
            self.qi = next((i for i, q in enumerate(queue) if str(q[0]) == path), -1)
        if self.p is None:
            from .gui_editor import _system_play

            _system_play(Path(path), start)
            self.changed.emit()
            return
        self.p.stop()
        self.p.setSource(QUrl.fromLocalFile(path))
        self._start_ms = int(start * 1000)
        if self._start_ms:
            self.p.setPosition(self._start_ms)
        if autoplay:
            self.p.play()
        self.changed.emit()

    def toggle(self):
        if not self.p or not self.path:
            return
        if self.p.playbackState() == QMediaPlayer.PlayingState:
            self.p.pause()
        else:
            if self.p.mediaStatus() == QMediaPlayer.EndOfMedia:
                self.p.setPosition(0)
            self.p.play()

    def play(self):
        if self.p and self.path:
            self.p.play()

    def pause(self):
        if self.p:
            self.p.pause()

    def stop(self):
        if self.p:
            self.p.stop()

    def seek(self, ms: int):
        if self.p:
            self.p.setPosition(max(0, int(ms)))

    def skip(self, seconds: float):
        if self.p:
            self.seek(self.p.position() + int(seconds * 1000))

    def step(self, d: int):
        if not self.queue:
            self.seek(0)
            return
        i = max(0, min(len(self.queue) - 1, self.qi + d))
        q = self.queue[i]
        self.load(q[0], q[1] if len(q) > 1 else "", q[2] if len(q) > 2 else "", queue=self.queue)

    def set_rate(self, r: float):
        if self.p:
            self.p.setPlaybackRate(r)

    def set_volume(self, v: float):
        if self.p and self.out:
            self.out.setVolume(max(0.0, min(1.0, v)))

    def playing(self) -> bool:
        return bool(self.p) and self.p.playbackState() == QMediaPlayer.PlayingState

    def pos_s(self) -> float:
        return (self.p.position() / 1000.0) if self.p else 0.0

    def has_video(self) -> bool:
        return bool(self.p) and self.p.hasVideo()

    # ------------------------------------------------------------ internals
    def _pos(self, ms: int):
        self.position.emit(ms, self.p.duration())
        if self.end_ms and ms >= self.end_ms:
            self.end_ms = 0
            self.p.pause()
            self.ended.emit()

    def _status(self, st):
        if st == QMediaPlayer.EndOfMedia:
            self.ended.emit()
            if self.queue and self.qi + 1 < len(self.queue):
                self.step(1)


# ====================================================================== widgets
class Cover(QWidget):
    """Square artwork: brand gradient with the item's glyph (song, voice, film, transcript)."""

    def __init__(self, size: int = 48):
        super().__init__()
        self.setFixedSize(size, size)
        self.glyph = "wave"
        self.seed = 0

    def set(self, glyph: str, seed: int = 0):
        self.glyph, self.seed = glyph, seed
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        stops = th.GRAD[self.seed % 3:] + th.GRAD[:self.seed % 3]
        for i, c in enumerate(stops):
            g.setColorAt(i / (len(stops) - 1), QColor(c))
        p.fillPath(path, g)
        s = int(r.width() * 0.5)
        p.drawPixmap(int((r.width() - s) / 2), int((r.height() - s) / 2), th.pixmap(self.glyph, "#FFFFFF", s, weight="fill"))


def icon_button(glyph: str, tip: str, size: int = 20, name: str = "iconBtn") -> QPushButton:
    b = QPushButton()
    b.setObjectName(name)
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    b.glyph = glyph
    b.setIcon(th.icon(glyph, _t()["ink"], size))
    b.setIconSize(QSize(size, size))
    return b


class Timeline(QSlider):
    """Scrubbable timeline: click anywhere to jump, drag to scrub."""
    seek = Signal(int)

    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.setObjectName("timeline")
        self.setRange(0, 0)
        self.dragging = False
        self.sliderPressed.connect(lambda: setattr(self, "dragging", True))
        self.sliderReleased.connect(self._release)
        self.setCursor(Qt.PointingHandCursor)

    def _release(self):
        self.dragging = False
        self.seek.emit(self.value())

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.maximum() > 0:
            v = int(self.minimum() + (self.maximum() - self.minimum()) * e.position().x() / max(1, self.width()))
            self.setValue(v)
            self.seek.emit(v)
        super().mousePressEvent(e)


class VideoPane(QFrame):
    """Picture-in-picture video above the player bar; Expand opens a big window."""

    def __init__(self, media: Media, parent=None):
        super().__init__(parent)
        self.media = media
        self.setObjectName("card")
        self.setFixedSize(400, 252)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        self.vw = QVideoWidget() if HAVE_QTMM else QLabel("Video playback needs Qt Multimedia")
        v.addWidget(self.vw, 1)
        row = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("hint")
        row.addWidget(self.title, 1)
        b = icon_button("open", "Open large", 16)
        b.clicked.connect(self.expand)
        row.addWidget(b)
        b = icon_button("x", "Hide video", 16)
        b.clicked.connect(self.hide)
        row.addWidget(b)
        v.addLayout(row)
        if HAVE_QTMM:
            media.p.setVideoOutput(self.vw)
        self.big = None
        self.hide()

    def expand(self):
        if not HAVE_QTMM:
            return
        d = QDialog(self.window())
        d.setWindowTitle(self.media.title)
        d.resize(1100, 660)
        lay = QVBoxLayout(d)
        lay.setContentsMargins(0, 0, 0, 0)
        vw = QVideoWidget()
        lay.addWidget(vw, 1)
        self.media.p.setVideoOutput(vw)
        d.finished.connect(lambda _: self.media.p.setVideoOutput(self.vw))
        d.show()
        self.big = d


class PlayerBar(QWidget):
    """The bottom transport — always present, drives whatever is playing anywhere in VERBATIM."""

    def __init__(self, window):
        super().__init__()
        self.w = window
        self.m = Media.get()
        self.setObjectName("playerBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(84)
        h = QHBoxLayout(self)
        h.setContentsMargins(18, 10, 18, 10)
        h.setSpacing(14)
        # now playing
        left = QHBoxLayout()
        left.setSpacing(10)
        self.cover = Cover(52)
        left.addWidget(self.cover)
        info = QVBoxLayout()
        info.setSpacing(0)
        self.now = QLabel("Nothing playing")
        self.now.setObjectName("nowTitle")
        self.now_sub = QLabel("Press ▶ on any item")
        self.now_sub.setObjectName("nowSub")
        for lab in (self.now, self.now_sub):
            lab.setMaximumWidth(240)
        info.addStretch()
        info.addWidget(self.now)
        info.addWidget(self.now_sub)
        info.addStretch()
        left.addLayout(info)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(320)
        h.addWidget(lw)
        # transport
        mid = QVBoxLayout()
        mid.setSpacing(2)
        btns = QHBoxLayout()
        btns.setSpacing(6)
        btns.addStretch()
        self.prev = icon_button("skip_back", "Previous (or restart)", 18)
        self.prev.clicked.connect(lambda: self.m.step(-1) if self.m.pos_s() < 3 else self.m.seek(0))
        self.back = icon_button("back10", "Back 10 seconds  ←", 20)
        self.back.clicked.connect(lambda: self.m.skip(-10))
        self.playb = QPushButton()
        self.playb.setObjectName("playBtn")
        self.playb.setCursor(Qt.PointingHandCursor)
        self.playb.setToolTip("Play / pause  (space)")
        self.playb.clicked.connect(self.m.toggle)
        self.fwd = icon_button("fwd10", "Forward 10 seconds  →", 20)
        self.fwd.clicked.connect(lambda: self.m.skip(10))
        self.next = icon_button("skip_fwd", "Next", 18)
        self.next.clicked.connect(lambda: self.m.step(1))
        for b in (self.prev, self.back, self.playb, self.fwd, self.next):
            btns.addWidget(b)
        btns.addStretch()
        mid.addLayout(btns)
        line = QHBoxLayout()
        line.setSpacing(10)
        self.t0 = QLabel("0:00")
        self.t0.setObjectName("time")
        self.t1 = QLabel("0:00")
        self.t1.setObjectName("time")
        self.tl = Timeline()
        self.tl.seek.connect(self.m.seek)
        line.addWidget(self.t0)
        line.addWidget(self.tl, 1)
        line.addWidget(self.t1)
        mid.addLayout(line)
        h.addLayout(mid, 1)
        # right side
        right = QHBoxLayout()
        right.setSpacing(6)
        self.rate = QComboBox()
        for r in (0.75, 1.0, 1.25, 1.5, 2.0):
            self.rate.addItem(f"{r:g}×", r)
        self.rate.setCurrentIndex(1)
        self.rate.setToolTip("Playback speed")
        self.rate.currentIndexChanged.connect(lambda i: self.m.set_rate(self.rate.itemData(i)))
        self.rate.setFixedWidth(74)
        right.addWidget(self.rate)
        self.vol_btn = icon_button("speaker", "Mute", 18)
        self.vol_btn.clicked.connect(self.mute)
        right.addWidget(self.vol_btn)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(85)
        self.vol.setFixedWidth(90)
        self.vol.valueChanged.connect(lambda v: self.m.set_volume(v / 100))
        right.addWidget(self.vol)
        self.vid_btn = icon_button("video", "Show the video", 18)
        self.vid_btn.clicked.connect(self.toggle_video)
        right.addWidget(self.vid_btn)
        self.dl = icon_button("download", "Download this file", 18)
        self.dl.clicked.connect(self.download)
        right.addWidget(self.dl)
        self.reveal = icon_button("folder", "Show in folder", 18)
        self.reveal.clicked.connect(self.show_in_folder)
        right.addWidget(self.reveal)
        rw = QWidget()
        rw.setLayout(right)
        rw.setFixedWidth(340)
        h.addWidget(rw)
        self.video = None
        self.m.changed.connect(self.on_changed)
        self.m.state.connect(self.on_state)
        self.m.position.connect(self.on_pos)
        self.on_state(False)
        self.on_changed()

    # ------------------------------------------------------------ reactions
    def attach_video(self, host: QWidget):
        if HAVE_QTMM:
            self.video = VideoPane(self.m, host)

    def place_video(self, host: QWidget):
        if self.video:
            self.video.move(host.width() - self.video.width() - 22, host.height() - self.height() - self.video.height() - 14)
            self.video.raise_()

    def on_changed(self):
        has = bool(self.m.path)
        self.now.setText(self.m.title if has else "Nothing playing")
        self.now_sub.setText(self.m.sub if has else "Press ▶ on any item — it plays here")
        glyph = {"video": "video"}.get(self.m.kind, "music" if "song" in self.m.sub.lower() or "music" in
                                       self.m.sub.lower() else "wave")
        self.cover.set(glyph, len(self.m.title))
        for b in (self.dl, self.reveal, self.vid_btn):
            b.setEnabled(has)
        self.vid_btn.setVisible(self.m.kind == "video")
        if self.video:
            if self.m.kind == "video":
                self.video.title.setText(self.m.title)
                self.video.show()
                self.place_video(self.video.parentWidget())
            else:
                self.video.hide()

    def on_state(self, playing: bool):
        self.playb.setIcon(th.icon("pause" if playing else "play", _t()["bg"], 20, weight="fill"))
        self.playb.setIconSize(QSize(20, 20))

    def on_pos(self, ms: int, dur: int):
        if not self.tl.dragging:
            self.tl.setRange(0, max(0, dur))
            self.tl.setValue(ms)
        self.t0.setText(fmt(ms if not self.tl.dragging else self.tl.value()))
        self.t1.setText(fmt(dur))

    def toggle_video(self):
        if self.video:
            self.video.setVisible(not self.video.isVisible())
            self.place_video(self.video.parentWidget())

    def mute(self):
        if self.vol.value() > 0:
            self._last = self.vol.value()
            self.vol.setValue(0)
        else:
            self.vol.setValue(getattr(self, "_last", 85))

    def download(self):
        if self.m.path:
            d = save_copy(self, self.m.path)
            if d:
                self.w.say(f"Downloaded → {d}")

    def show_in_folder(self):
        if self.m.path:
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.m.path).parent)))

    def retheme(self):
        for b in self.findChildren(QPushButton):
            g = getattr(b, "glyph", None)
            if g:
                b.setIcon(th.icon(g, _t()["ink"], b.iconSize().width() or 18))
        self.on_state(self.m.playing())
