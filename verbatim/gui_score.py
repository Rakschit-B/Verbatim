# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Signature widgets of the "Score" design language: the module Rail, the Masthead, the timecode Ruler,
crop marks and the speech-envelope waveform."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from . import ui_theme as th


def _t() -> dict:
    from . import gui

    return gui.T


def font(family: str, px: float, weight: int = 400, italic: bool = False, spacing: float = 0.0) -> QFont:
    f = QFont(family)
    f.setPixelSize(int(round(px)))
    f.setWeight(QFont.Weight(weight))
    f.setItalic(italic)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def envelope(n: int, seed: int = 7) -> list[float]:
    """A deterministic speech-like amplitude envelope (syllables grouped into words and phrases)."""
    out = []
    for i in range(n):
        x = i / max(1, n - 1)
        syll = abs(math.sin(i * 0.9 + seed)) ** 1.6
        word = 0.55 + 0.45 * math.sin(i * 0.23 + seed * 0.7)
        phrase = 0.5 + 0.5 * math.sin(x * math.pi * 3.2 + seed * 0.3)
        gap = 0.12 if (i + seed) % 23 in (0, 1) else 1.0           # breaths between phrases
        out.append(max(0.04, min(1.0, syll * word * (0.35 + 0.65 * phrase) * gap)))
    return out


def crop_marks(p: QPainter, r: QRectF, color: QColor, size: float = 10, inset: float = 6):
    """Printer's crop marks at the four corners of `r` — the Score's framing device."""
    p.setPen(QPen(color, 1))
    for cx, cy, sx, sy in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                           (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
        x, y = cx + sx * inset, cy + sy * inset
        p.drawLine(QPointF(x, y), QPointF(x + sx * size, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + sy * size))


# ====================================================================== Rail
class RailModule(QWidget):
    clicked = Signal(int)

    def __init__(self, index: int):
        super().__init__()
        self.index = index
        self.on = False
        self.hover = False
        self.setFixedSize(92, 84)
        self.setCursor(Qt.PointingHandCursor)
        m = th.MODULES[index]
        self.setToolTip(f"{m['num']} — {m['name']}: {m['tag']}")

    def enterEvent(self, _):
        self.hover = True
        self.update()

    def leaveEvent(self, _):
        self.hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.index)

    def paintEvent(self, _):
        t = _t()
        m = th.MODULES[self.index]
        acc = QColor(m[t["name"]][0])
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        if self.on:
            p.fillRect(QRectF(0, 10, 3, self.height() - 20), acc)
        ink = QColor(t["rail_ink"])
        sub = QColor(t["rail_sub"])
        p.setFont(font(th.DISPLAY, 38, italic=self.on))
        p.setPen(acc if self.on else (ink if self.hover else sub))
        p.drawText(QRectF(0, 6, self.width(), 46), Qt.AlignHCenter | Qt.AlignVCenter, m["num"])
        p.setFont(font(th.MONO, 9, 600 if self.on else 400, spacing=1.6))
        p.setPen(ink if (self.on or self.hover) else sub)
        p.drawText(QRectF(0, 52, self.width(), 18), Qt.AlignHCenter | Qt.AlignVCenter, m["name"].upper())
        if self.on:     # small playhead triangle under the name
            cx = self.width() / 2
            p.setPen(Qt.NoPen)
            p.setBrush(acc)
            p.drawPolygon(QPolygonF([QPointF(cx - 4, 74), QPointF(cx + 4, 74), QPointF(cx, 79)]))


class RailIcon(QPushButton):
    """Square icon button on the rail (activity, settings, theme, updates)."""

    def __init__(self, glyph: str, tip: str):
        super().__init__()
        self.glyph = glyph
        self.dot = False
        self.on = False
        self.setToolTip(tip)
        self.setFixedSize(92, 46)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background:transparent; border:0; }")

    def paintEvent(self, _):
        t = _t()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = t["rail_ink"] if (self.underMouse() or self.on) else t["rail_sub"]
        if self.on:
            p.fillRect(QRectF(0, 8, 3, self.height() - 16), QColor(t["accent"]))
        px = th.pixmap(self.glyph, col, 22, weight="fill" if self.on else "light")
        p.drawPixmap(int((self.width() - 22) / 2), int((self.height() - 22) / 2), px)
        if self.dot:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(th.MODULES[0][t["name"]][0]))
            p.drawEllipse(QRectF(self.width() / 2 + 7, 9, 8, 8))


class Monogram(QWidget):
    """Top of the rail: the VERBATIM 'V' set in Instrument Serif italic over a hairline."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(92, 92)
        self.setToolTip("VERBATIM — an Infinite Story LLP product")

    def paintEvent(self, _):
        t = _t()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setPen(QColor(t["rail_ink"]))
        p.setFont(font(th.DISPLAY, 56, italic=True))
        p.drawText(QRectF(0, 0, self.width(), 66), Qt.AlignHCenter | Qt.AlignBottom, "V")
        p.setPen(QColor(t["accent"]))
        p.setFont(font(th.MONO, 8, 600, spacing=2.2))
        p.drawText(QRectF(0, 66, self.width(), 14), Qt.AlignHCenter | Qt.AlignVCenter, "VERBATIM")
        p.setPen(QPen(QColor(t["rail_sub"]), 1))
        p.drawLine(QPointF(22, 90), QPointF(self.width() - 22, 90))


class Spine(QWidget):
    """Vertical book-spine imprint on the rail: 'INFINITE STORY — VERBATIM x.y'."""

    def __init__(self, text: str):
        super().__init__()
        self.text = text
        self.setFixedWidth(92)
        self.setMinimumHeight(60)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def paintEvent(self, _):
        t = _t()
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        f = font(th.MONO, 9, 400, spacing=2.4)
        p.setFont(f)
        w = p.fontMetrics().horizontalAdvance(self.text)
        if w + 20 > self.height():
            return
        p.setPen(QColor(t["rail_sub"]))
        p.translate(self.width() / 2 + 4, self.height() - 10)
        p.rotate(-90)
        p.drawText(QPointF(0, 0), self.text)


class Rail(QWidget):
    module_clicked = Signal(int)

    def __init__(self, version: str):
        super().__init__()
        self.setFixedWidth(92)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("rail")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 14)
        v.setSpacing(2)
        v.addWidget(Monogram())
        v.addSpacing(14)
        self.mods = []
        for i in range(len(th.MODULES)):
            b = RailModule(i)
            b.clicked.connect(self.module_clicked)
            v.addWidget(b)
            self.mods.append(b)
        v.addWidget(Spine(f"INFINITE STORY  —  VERBATIM {version}"), 1)
        self.log_btn = RailIcon("clock", "Activity log")
        self.settings_btn = RailIcon("gear", "Settings")
        self.theme_btn = RailIcon("moon", "Light / dark")
        self.update_btn = RailIcon("download", "Check for updates")
        for b in (self.update_btn, self.theme_btn, self.log_btn, self.settings_btn):
            v.addWidget(b)
        self.avatar = QLabel()
        self.avatar.setObjectName("avatar")
        self.avatar.setFixedSize(34, 34)
        self.avatar.setAlignment(Qt.AlignCenter)
        v.addSpacing(8)
        v.addWidget(self.avatar, 0, Qt.AlignHCenter)

    def set_module(self, k: int | None, util: str = ""):
        for i, b in enumerate(self.mods):
            b.on = i == k
            b.update()
        self.log_btn.on = util == "log"
        self.settings_btn.on = util == "settings"
        for b in (self.log_btn, self.settings_btn):
            b.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(_t()["rail"]))


# ====================================================================== Ruler
class Ruler(QWidget):
    """Timecode ruler with a playhead in the module colour — the Score's signature pattern.
    `set_progress(None)` parks the playhead; a value 0–1 drives it; `busy(True)` sweeps it."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(28)
        self.pos = 0.618
        self._sweep = QTimer(self)
        self._sweep.setInterval(40)
        self._sweep.timeout.connect(self._tick)
        self._phase = 0.0

    def sizeHint(self):
        return QSize(600, 28)

    def set_progress(self, frac: float | None):
        self.pos = 0.618 if frac is None else max(0.0, min(1.0, float(frac)))
        self.update()

    def busy(self, on: bool):
        if on and not self._sweep.isActive():
            self._sweep.start()
        elif not on:
            self._sweep.stop()
            self.set_progress(None)

    def _tick(self):
        self._phase = (self._phase + 0.004) % 1.0
        self.pos = self._phase
        self.update()

    def paintEvent(self, _):
        t = _t()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        base = h - 1
        ink, sub = QColor(t["ink"]), QColor(t["muted"])
        p.setPen(QPen(ink, 1))
        p.drawLine(QPointF(0, base + 0.5), QPointF(w, base + 0.5))
        p.setFont(font(th.MONO, 9, 400, spacing=0.6))
        step = 8
        for i, x in enumerate(range(0, w, step)):
            if i % 20 == 0:
                p.setPen(QPen(ink, 1))
                p.drawLine(QPointF(x + 0.5, base), QPointF(x + 0.5, base - 14))
                secs = i // 20 * 10
                p.setPen(sub)
                p.drawText(QPointF(x + 4, base - 7), f"{secs // 3600:02d}:{secs // 60 % 60:02d}:{secs % 60:02d}")
            elif i % 5 == 0:
                p.setPen(QPen(ink, 1))
                p.drawLine(QPointF(x + 0.5, base), QPointF(x + 0.5, base - 5))
            elif i % 20 not in (1, 2, 3, 4, 6, 7, 8, 9):    # keep the timecode label area clear
                p.setPen(QPen(sub, 1))
                p.drawLine(QPointF(x + 0.5, base), QPointF(x + 0.5, base - 2.5))
            else:
                p.setPen(QPen(sub, 1))
                p.drawLine(QPointF(x + 0.5, base), QPointF(x + 0.5, base - 2))
        acc = QColor(t["accent"])
        x = self.pos * (w - 1)
        p.setPen(QPen(acc, 2))
        p.drawLine(QPointF(x, 3), QPointF(x, base))
        p.setPen(Qt.NoPen)
        p.setBrush(acc)
        p.drawPolygon(QPolygonF([QPointF(x - 5, 0), QPointF(x + 5, 0), QPointF(x, 6)]))


# ====================================================================== Masthead
class Masthead(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(0)
        self.kicker = QLabel()
        self.kicker.setObjectName("kicker")
        top.addWidget(self.kicker)
        top.addStretch()
        self.status = QLabel()
        self.status.setObjectName("kicker")
        top.addWidget(self.status)
        v.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(14)
        self.title = QLabel()
        self.title.setObjectName("display")
        self.tag = QLabel()
        self.tag.setObjectName("displayIt")
        row.addWidget(self.title, 0, Qt.AlignBottom)
        row.addWidget(self.tag, 0, Qt.AlignBottom)
        row.addStretch()
        self.chapters = QHBoxLayout()
        self.chapters.setSpacing(0)
        self.chapter_box = QWidget()
        self.chapter_box.setLayout(self.chapters)
        self.chapters.setContentsMargins(0, 0, 0, 6)
        row.addWidget(self.chapter_box, 0, Qt.AlignBottom)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        row.addLayout(self.actions)
        v.addLayout(row)
        v.addSpacing(4)
        self.ruler = Ruler()
        v.addWidget(self.ruler)

    def set(self, kicker: str, title: str, tag: str, chapters: bool):
        self.kicker.setText(kicker)
        self.title.setText(title)
        self.tag.setText(tag)
        self.chapter_box.setVisible(chapters)
        self.ruler.update()
