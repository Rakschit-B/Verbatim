# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""VERBATIM 3.7 "Studio" look: a dark creative-studio theme (default) and a clean light theme.

Interface type: Manrope (OFL). Timecodes: JetBrains Mono (OFL). Devanagari: Mukta (OFL).
Brand accent: Infinite Story gradient (violet → magenta → coral). Icons: Phosphor (MIT).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .icons_phosphor import GLYPHS

UI = "Manrope"
DISPLAY = "Manrope"
MONO = "JetBrains Mono"

GRAD = ("#7B5CFF", "#D94CFF", "#FF6A5C")        # brand gradient stops

DARK = {
    "name": "dark",
    "bg": "#0B0B10", "side": "#0E0E15", "card": "#15151E", "card2": "#1C1C27", "border": "#262635",
    "ink": "#F5F5FA", "sub": "#A3A3B8", "muted": "#6C6C82", "field": "#1A1A24", "field_border": "#2C2C3D",
    "hover": "#20202C", "seg": "#12121A", "track": "#2A2A3A", "scroll": "#33334A", "row_sel": "#1F1F2C",
    "dark_btn": "#F5F5FA", "dark_btn_ink": "#0B0B10", "banner": "#1C1C27", "banner_ink": "#F5F5FA",
    "accent": "#9B7BFF", "accent_ink": "#FFFFFF", "soft": "#231C3F", "player": "#101018",
    "ok": "#3DDC97", "warn": "#FFB547", "bad": "#FF5C6C", "wave": 0.6,
}
LIGHT = {
    "name": "light",
    "bg": "#FFFFFF", "side": "#F7F7F9", "card": "#FFFFFF", "card2": "#F6F6F8", "border": "#E7E7EC",
    "ink": "#0C0C12", "sub": "#5E5E70", "muted": "#9A9AAB", "field": "#FFFFFF", "field_border": "#DCDCE4",
    "hover": "#F1F1F5", "seg": "#F1F1F4", "track": "#E4E4EA", "scroll": "#CFCFD9", "row_sel": "#F3F0FF",
    "dark_btn": "#0C0C12", "dark_btn_ink": "#FFFFFF", "banner": "#0C0C12", "banner_ink": "#FFFFFF",
    "accent": "#6A45FF", "accent_ink": "#FFFFFF", "soft": "#EFEAFF", "player": "#FFFFFF",
    "ok": "#0FA56A", "warn": "#C97A00", "bad": "#E0313F", "wave": 1.0,
}

# Kept for pages that colour-code areas (the accent is shared; the icon identifies the area).
MODULES = [
    {"key": "transcribe", "num": "01", "name": "Transcribe", "icon": "quotes", "tag": "Every word, on the record.",
     "light": ("#6A45FF", "#FFFFFF", "#EFEAFF"), "dark": ("#9B7BFF", "#FFFFFF", "#231C3F")},
    {"key": "voice", "num": "02", "name": "Voice", "icon": "voice", "tag": "Translate, direct and perform.",
     "light": ("#6A45FF", "#FFFFFF", "#EFEAFF"), "dark": ("#9B7BFF", "#FFFFFF", "#231C3F")},
    {"key": "music", "num": "03", "name": "Music", "icon": "vinyl", "tag": "Write it. Sing it. Own it.",
     "light": ("#6A45FF", "#FFFFFF", "#EFEAFF"), "dark": ("#9B7BFF", "#FFFFFF", "#231C3F")},
    {"key": "video", "num": "04", "name": "Video", "icon": "video", "tag": "Localise the whole film.",
     "light": ("#6A45FF", "#FFFFFF", "#EFEAFF"), "dark": ("#9B7BFF", "#FFFFFF", "#231C3F")},
]

CHIPS = {
    "light": {"queued": ("#F1F1F4", "#9A9AAB", "#5E5E70"), "transcribing": ("#EFEAFF", "#6A45FF", "#4B2BD6"),
              "processing": ("#FCEBFF", "#B83BE0", "#8E1FB3"), "ready": ("#E3F7EE", "#0FA56A", "#0A7A4E"),
              "failed": ("#FDE8EA", "#E0313F", "#B01F2C"), "stopped": ("#F1F1F4", "#B9B9C6", "#6C6C82")},
    "dark": {"queued": ("#1C1C27", "#6C6C82", "#C4C4D4"), "transcribing": ("#231C3F", "#9B7BFF", "#CFC2FF"),
             "processing": ("#2E1A39", "#D94CFF", "#F0B8FF"), "ready": ("#123126", "#3DDC97", "#A6F0CE"),
             "failed": ("#3A161C", "#FF5C6C", "#FFB3BA"), "stopped": ("#1C1C27", "#6C6C82", "#A3A3B8")},
}

ICONS = GLYPHS["regular"]


def tokens(base: dict, module: int = 0) -> dict:
    t = dict(base)
    t.update(accent2=t["accent"], nav_ink=t["accent"], nav_a=t["soft"], nav_b=t["soft"], pink=GRAD[1],
             drop_a=t["soft"], drop_b=t["soft"], module=module, rail=t["side"], rail_ink=t["ink"],
             rail_sub=t["muted"], rule=t["border"])
    return t


def load_fonts(folder: Path) -> list[str]:
    fams: list[str] = []
    for f in sorted(folder.glob("*.ttf")):
        i = QFontDatabase.addApplicationFont(str(f))
        if i >= 0:
            fams += QFontDatabase.applicationFontFamilies(i)
    return sorted(set(fams))


def svg(name: str, color: str, stroke: float = 1.8, weight: str = "") -> bytes:
    if not weight:
        weight = "light" if stroke <= 1.6 else "regular"
    body = GLYPHS.get(weight, GLYPHS["regular"]).get(name) or GLYPHS["regular"].get(name, "")
    body = body.replace("currentColor", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" fill="{color}">{body}</svg>').encode()


def pixmap(name: str, color: str, size: int = 20, ratio: float = 2.0, stroke: float = 1.8,
           weight: str = "") -> QPixmap:
    px = QPixmap(int(size * ratio), int(size * ratio))
    px.fill(Qt.transparent)
    r = QSvgRenderer(QByteArray(svg(name, color, stroke, weight)))
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, px.width(), px.height()))
    p.end()
    px.setDevicePixelRatio(ratio)
    return px


def icon(name: str, color: str, size: int = 20, weight: str = "") -> QIcon:
    return QIcon(pixmap(name, color, size, weight=weight))


def write_qss_images(folder: Path, t: dict) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    tag = f"studio_{t['name']}"
    files = {
        "arrow": svg("chev_down", t["sub"]),
        "up": svg("chev_up", t["sub"]),
        "check_on": (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 18"><rect x="0.5" y="0.5" width="17" '
                     f'height="17" rx="5" fill="{t["accent"]}"/><path d="m4.5 9.3 3 3 6-6.3" fill="none" '
                     f'stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>').encode(),
        "check_off": (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 18"><rect x="0.75" y="0.75" '
                      f'width="16.5" height="16.5" rx="5" fill="{t["field"]}" stroke="{t["field_border"]}" '
                      f'stroke-width="1.5"/></svg>').encode(),
        "radio_on": (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 18"><circle cx="9" cy="9" r="8.2" '
                     f'fill="{t["field"]}" stroke="{t["accent"]}" stroke-width="1.5"/><circle cx="9" cy="9" r="4.5" '
                     f'fill="{t["accent"]}"/></svg>').encode(),
        "radio_off": (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 18"><circle cx="9" cy="9" r="8.2" '
                      f'fill="{t["field"]}" stroke="{t["field_border"]}" stroke-width="1.5"/></svg>').encode(),
    }
    for k, data in files.items():
        p = folder / f"{tag}_{k}.svg"
        p.write_bytes(data)
        out[k] = p.as_posix()
    return out


def stylesheet(t: dict, img: dict) -> str:
    acc = t["accent"]
    g = f"qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {GRAD[0]}, stop:0.55 {GRAD[1]}, stop:1 {GRAD[2]})"
    gh = "qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #6A4BF0, stop:0.55 #C63BEE, stop:1 #F0584A)"
    return f"""
* {{ outline: 0; }}
QWidget {{ color:{t['ink']}; font-family:"{UI}", "Mukta", "Helvetica Neue", "Segoe UI", sans-serif; font-size:13px;
  background:transparent; }}
QMainWindow, QWidget#root, QWidget#content, QDialog, QDialog#editor, QMessageBox, QFileDialog, QInputDialog {{ background:{t['bg']}; }}
QWidget#sidebar {{ background:{t['side']}; border-right:1px solid {t['border']}; }}
QWidget#playerBar {{ background:{t['player']}; border-top:1px solid {t['border']}; }}
QToolTip {{ background:{t['card2']}; color:{t['ink']}; border:1px solid {t['border']}; padding:6px 9px; border-radius:8px; }}
QFrame#card {{ background:{t['card']}; border:1px solid {t['border']}; border-radius:16px; }}
QFrame#card2 {{ background:{t['card2']}; border:1px solid {t['border']}; border-radius:14px; }}
QFrame#tile {{ background:{t['card']}; border:1px solid {t['border']}; border-radius:18px; }}
QFrame#tile:hover {{ border-color:{acc}; }}
QFrame#soon {{ background:{t['card']}; border:1px solid {t['border']}; border-radius:16px; }}
QLabel#tagline, QLabel#kicker {{ color:{t['muted']}; font-size:11px; font-weight:700; letter-spacing:1.2px; }}
QLabel#kickerAcc {{ color:{acc}; font-size:11px; font-weight:700; letter-spacing:1.2px; }}
QLabel#sub, QLabel#hint {{ color:{t['sub']}; }}
QLabel#hint {{ font-size:12px; }}
QLabel#display {{ font-size:28px; font-weight:800; letter-spacing:-0.5px; }}
QLabel#displayIt {{ font-size:15px; font-weight:500; color:{t['sub']}; }}
QLabel#hero {{ font-size:38px; font-weight:800; letter-spacing:-1px; }}
QLabel#h1 {{ font-size:22px; font-weight:800; letter-spacing:-0.3px; }}
QLabel#h2 {{ font-size:15px; font-weight:700; }}
QLabel#h3 {{ font-size:14px; font-weight:700; }}
QLabel#tileTitle {{ font-size:15px; font-weight:700; }}
QLabel#dropTitle {{ font-size:22px; font-weight:700; }}
QLabel#dropFormats {{ font-size:12px; color:{t['sub']}; }}
QLabel#or {{ color:{t['muted']}; font-size:12px; }}
QLabel#soonTag {{ color:{acc}; font-size:11px; font-weight:700; letter-spacing:1px; }}
QLabel#soonTitle {{ font-size:16px; font-weight:700; }}
QLabel#pill {{ background:{t['card2']}; color:{t['sub']}; border-radius:9px; padding:2px 8px; font-size:11px; font-weight:600; }}
QLabel#badge {{ background:{acc}; color:white; border-radius:8px; padding:0 5px; font-size:10px; font-weight:800; }}
QLabel#lang {{ background:{t['card2']}; border:1px solid {t['border']}; border-radius:8px; padding:3px 9px; font-size:11px; }}
QLabel#fname {{ font-weight:600; }}
QLabel#fmeta, QLabel#time {{ color:{t['muted']}; font-family:"{MONO}"; font-size:11px; }}
QLabel#avatar {{ background:{g}; color:white; border-radius:17px; font-size:14px; font-weight:800; }}
QLabel#nowTitle {{ font-weight:700; }}
QLabel#nowSub {{ color:{t['sub']}; font-size:12px; }}
QFrame#banner {{ background:{t['banner']}; border-radius:12px; }}
QFrame#banner QLabel {{ color:{t['banner_ink']}; background:transparent; }}

QPushButton {{ background:{t['card2']}; border:1px solid {t['border']}; border-radius:10px; padding:8px 14px; font-weight:600; }}
QPushButton:hover {{ background:{t['hover']}; border-color:{t['field_border']}; }}
QPushButton:pressed {{ background:{t['seg']}; }}
QPushButton:disabled {{ color:{t['muted']}; }}
QPushButton#navItem {{ background:transparent; border:0; border-radius:10px; text-align:left; padding:9px 12px;
  color:{t['sub']}; font-size:13px; font-weight:600; }}
QPushButton#navItem:hover {{ background:{t['hover']}; color:{t['ink']}; }}
QPushButton#navItem:checked {{ background:{t['soft']}; color:{t['ink']}; }}
QPushButton#chapter {{ background:transparent; border:0; border-radius:16px; padding:6px 14px; color:{t['sub']}; font-weight:600; }}
QPushButton#chapter:hover {{ background:{t['hover']}; color:{t['ink']}; }}
QPushButton#chapter:checked {{ background:{t['ink']}; color:{t['bg']}; }}
QPushButton#pillBtn {{ border-radius:18px; padding:0 16px; min-height:36px; max-height:36px; font-weight:700; }}
QPushButton#pillBtn[accent="true"], QPushButton#primary {{ background:{g}; color:white; border:0; border-radius:18px;
  padding:0 18px; min-height:36px; font-weight:700; }}
QPushButton#pillBtn[accent="true"]:hover, QPushButton#primary:hover {{ background:{gh}; }}
QPushButton#ghost {{ background:transparent; border:1px solid {t['border']}; border-radius:18px; padding:0 14px;
  min-height:36px; font-weight:600; }}
QPushButton#ghost:hover {{ background:{t['hover']}; }}
QPushButton#iconBtn, QToolButton#iconBtn {{ background:transparent; border:0; border-radius:18px; padding:6px; }}
QPushButton#iconBtn:hover, QToolButton#iconBtn:hover {{ background:{t['hover']}; }}
QPushButton#playBtn {{ background:{t['ink']}; border:0; border-radius:22px; min-width:44px; max-width:44px;
  min-height:44px; max-height:44px; padding:0; }}
QPushButton#playBtn:hover {{ background:{acc}; }}
QPushButton#dl {{ background:transparent; border:1px solid {t['border']}; border-radius:16px; padding:5px 12px; font-weight:600; }}
QPushButton#dl:hover {{ background:{acc}; color:white; border-color:{acc}; }}
QSlider::groove:horizontal {{ height:4px; background:{t['track']}; border-radius:2px; }}
QSlider::sub-page:horizontal {{ background:{g}; border-radius:2px; }}
QSlider::handle:horizontal {{ background:{"#FFFFFF" if t["name"] == "dark" else t["ink"]}; border:0; width:12px; height:12px; margin:-4px 0; border-radius:6px; }}
QSlider#timeline::groove:horizontal {{ height:5px; }}
QPushButton#chip {{ border-radius:14px; padding:5px 10px; font-size:12px; font-weight:600; }}
QPushButton#chip:checked {{ background:{acc}; color:white; border-color:{acc}; }}
QPushButton#addFiles {{ background:{g}; color:white; border:0; font-size:14px; font-weight:700; }}
QToolButton#addMenu {{ background:{GRAD[2]}; color:white; border:0; }}
QPushButton#addFiles {{ border-top-left-radius:22px; border-bottom-left-radius:22px; border-top-right-radius:0; border-bottom-right-radius:0; padding:0 26px 0 22px; min-height:44px; max-height:44px; }}
QToolButton#addMenu {{ border-top-right-radius:22px; border-bottom-right-radius:22px; padding:0 12px; border-left:1px solid rgba(255,255,255,0.35); min-height:44px; max-height:44px; min-width:22px; }}
QToolButton#addMenu::menu-indicator {{ image:none; width:0; }}
QPushButton#addFiles:hover, QToolButton#addMenu:hover {{ background:{gh}; }}
QPushButton#addFolder {{ background:transparent; border:1px solid {t['field_border']}; border-radius:22px; padding:0 30px; min-height:44px; max-height:44px; font-size:14px; font-weight:700; }}
QPushButton#addFolder:hover {{ background:{t['hover']}; }}
QPushButton#start {{ border:0; border-radius:14px; color:white; background:{g}; font-size:15px; font-weight:800; padding:15px; }}
QPushButton#start:hover {{ background:{gh}; }}
QPushButton#start:disabled {{ background:{t['track']}; color:{t['muted']}; }}
QPushButton#stop {{ border-radius:12px; padding:10px; font-weight:600; background:transparent; border:1px solid {t['border']}; }}
QPushButton#seg {{ background:transparent; border:0; border-radius:9px; padding:7px 10px; color:{t['sub']}; font-weight:600; }}
QPushButton#seg:checked {{ background:{t['card']}; color:{t['ink']}; border:1px solid {t['border']}; }}
QFrame#segBar {{ background:{t['seg']}; border-radius:12px; }}
QPushButton#section {{ background:transparent; border:0; text-align:left; padding:4px 0; font-size:15px; font-weight:700; }}
QPushButton#link {{ background:transparent; border:0; color:{acc}; padding:2px 4px; font-weight:700; }}
QPushButton#link:hover {{ text-decoration:underline; }}
QToolButton {{ background:{t['card2']}; border:1px solid {t['border']}; border-radius:10px; padding:6px; }}
QToolButton:hover {{ background:{t['hover']}; }}
QToolButton#more {{ background:transparent; border:0; }}
QToolButton::menu-indicator {{ image:none; width:0; }}
QTabWidget::pane {{ border:0; }}
QTabBar::tab {{ background:transparent; border:0; border-radius:14px; padding:7px 14px; margin-right:6px; color:{t['sub']}; font-weight:600; }}
QTabBar::tab:hover {{ background:{t['hover']}; color:{t['ink']}; }}
QTabBar::tab:selected {{ background:{t['ink']}; color:{t['bg']}; }}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{ background:{t['field']}; border:1px solid {t['field_border']}; border-radius:10px;
  padding:8px 10px; selection-background-color:{acc}; selection-color:white; }}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color:{t['muted']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{ border-color:{acc}; }}
QLineEdit#search {{ border-radius:18px; padding:8px 14px; background:{t['card2']}; }}
QComboBox::drop-down {{ border:0; width:26px; }}
QComboBox::down-arrow {{ image:url({img['arrow']}); width:12px; height:12px; }}
QComboBox QAbstractItemView {{ background:{t['card2']}; border:1px solid {t['border']}; border-radius:10px; padding:4px;
  selection-background-color:{t['soft']}; selection-color:{t['ink']}; outline:0; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin:border; subcontrol-position:top right; width:20px; border:0; background:transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin:border; subcontrol-position:bottom right; width:20px; border:0; background:transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image:url({img['up']}); width:9px; height:9px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image:url({img['arrow']}); width:9px; height:9px; }}
QPlainTextEdit, QTextEdit {{ background:{t['field']}; border:1px solid {t['field_border']}; border-radius:12px; padding:10px; }}
QPlainTextEdit#log {{ font-family:"{MONO}"; font-size:11px; }}
QPlainTextEdit#script {{ font-size:15px; line-height:150%; }}
QCheckBox, QRadioButton {{ spacing:10px; background:transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width:18px; height:18px; }}
QCheckBox::indicator:unchecked {{ image:url({img['check_off']}); }}
QCheckBox::indicator:checked {{ image:url({img['check_on']}); }}
QRadioButton::indicator:unchecked {{ image:url({img['radio_off']}); }}
QRadioButton::indicator:checked {{ image:url({img['radio_on']}); }}

QTableWidget, QTreeWidget, QListWidget {{ background:transparent; border:0; gridline-color:transparent;
  selection-background-color:{t['row_sel']}; selection-color:{t['ink']}; }}
QTableWidget::item {{ border-bottom:1px solid {t['border']}; padding:0 4px; }}
QListWidget::item {{ padding:8px; border-radius:10px; }}
QListWidget::item:selected {{ background:{t['row_sel']}; color:{t['ink']}; }}
QHeaderView {{ background:transparent; }}
QHeaderView::section {{ background:transparent; color:{t['muted']}; border:0; border-bottom:1px solid {t['border']};
  padding:8px 8px; font-size:11px; font-weight:700; letter-spacing:0.8px; }}
QProgressBar {{ border:0; background:{t['track']}; border-radius:3px; max-height:6px; min-height:6px; }}
QProgressBar::chunk {{ border-radius:3px; background:{g}; }}
QProgressBar#done::chunk {{ background:{t['ok']}; }}
QProgressBar#failed::chunk {{ background:{t['bad']}; }}
QMenu {{ background:{t['card2']}; border:1px solid {t['border']}; border-radius:12px; padding:6px; }}
QMenu::item {{ padding:8px 22px 8px 12px; border-radius:8px; }}
QMenu::item:selected {{ background:{t['soft']}; color:{t['ink']}; }}
QMenu::separator {{ height:1px; background:{t['border']}; margin:4px 8px; }}
QScrollArea {{ background:transparent; border:0; }}
QScrollArea > QWidget > QWidget {{ background:transparent; }}
QScrollBar:vertical {{ background:transparent; width:9px; margin:2px; }}
QScrollBar::handle:vertical {{ background:{t['scroll']}; border-radius:4px; min-height:30px; }}
QScrollBar:horizontal {{ background:transparent; height:9px; margin:2px; }}
QScrollBar::handle:horizontal {{ background:{t['scroll']}; border-radius:4px; min-width:30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width:0; height:0; background:transparent; }}
QFrame#hline, QFrame#rule {{ background:{t['border']}; max-height:1px; min-height:1px; border:0; }}
QSplitter::handle {{ background:{t['border']}; }}
"""
