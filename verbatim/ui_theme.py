# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""VERBATIM "Score" — the 3.6 design language.

The app is laid out like a film score / editorial broadsheet:
  * Paper (light) and Ink (dark) grounds, hairline rules instead of drop shadows, 4 px corners.
  * Each module owns a broadcast colour — 01 Transcribe = Tally, 02 Voice = Ultramarine,
    03 Music = Saffron, 04 Video = Jade. The whole interface re-tints when you change module.
  * Type: Instrument Serif for display (numerals, page titles), Hanken Grotesk for the interface,
    JetBrains Mono for timecodes and kicker labels. Mukta covers Devanagari.
  * Signature pattern: the Ruler — a timecode ruler with a playhead in the module colour
    (see gui_score.py).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .icons_phosphor import GLYPHS

DISPLAY = "Instrument Serif"
UI = "Hanken Grotesk"
MONO = "JetBrains Mono"

LIGHT = {
    "name": "light",
    "bg": "#F2EEE6", "card": "#FBF9F5", "border": "#DCD5C8", "ink": "#16130F", "sub": "#655E54",
    "muted": "#9D9589", "field": "#FFFFFF", "field_border": "#D6CEBF", "hover": "#EAE4D8", "seg": "#E7E1D5",
    "rail": "#16130F", "rail_ink": "#F2EEE6", "rail_sub": "#8E877C", "rule": "#16130F",
    "dark_btn": "#16130F", "dark_btn_ink": "#F2EEE6", "track": "#E2DBCE",
    "scroll": "#CFC7B8", "row_sel": "#EFE9DE", "banner": "#16130F", "banner_ink": "#F2EEE6",
    "wave": 1.0,
}
DARK = {
    "name": "dark",
    "bg": "#0F0E0C", "card": "#171512", "border": "#2B2722", "ink": "#F2EEE6", "sub": "#ABA397",
    "muted": "#6E675D", "field": "#1D1A16", "field_border": "#36312A", "hover": "#24201B", "seg": "#1A1814",
    "rail": "#050504", "rail_ink": "#F2EEE6", "rail_sub": "#6E675D", "rule": "#F2EEE6",
    "dark_btn": "#F2EEE6", "dark_btn_ink": "#16130F", "track": "#2B2722",
    "scroll": "#3A352E", "row_sel": "#201D19", "banner": "#F2EEE6", "banner_ink": "#16130F",
    "wave": 0.6,
}

# Module broadcast colours: (accent, ink on accent, soft tint) for light / dark grounds.
MODULES = [
    {"key": "transcribe", "num": "01", "name": "Transcribe", "icon": "quotes", "tag": "Every word, on the record.",
     "light": ("#F2461B", "#FFFFFF", "#F9DCCF"), "dark": ("#FF6A3D", "#16130F", "#3A1A10")},
    {"key": "voice", "num": "02", "name": "Voice", "icon": "voice", "tag": "Translate, direct and perform.",
     "light": ("#2B3BEA", "#FFFFFF", "#DCDFFB"), "dark": ("#7381FF", "#0F0E0C", "#191C46")},
    {"key": "music", "num": "03", "name": "Music", "icon": "vinyl", "tag": "Score it. Sing it. Own it.",
     "light": ("#E39A00", "#16130F", "#F8E8BE"), "dark": ("#FFC233", "#16130F", "#3A2D07")},
    {"key": "video", "num": "04", "name": "Video", "icon": "video", "tag": "Localise the whole film.",
     "light": ("#00976F", "#FFFFFF", "#CFEDE2"), "dark": ("#2BD1A3", "#0F0E0C", "#0B3329")},
]

# status chip colours: (background, dot, text) per theme
CHIPS = {
    "light": {"queued": ("#E9E3D7", "#9D9589", "#655E54"), "transcribing": ("#F9DCCF", "#F2461B", "#B5300E"),
              "processing": ("#DCDFFB", "#2B3BEA", "#1F2CB0"), "ready": ("#CFEDE2", "#00976F", "#00704F"),
              "failed": ("#F7D4D4", "#C8222B", "#9C1A21"), "stopped": ("#E9E3D7", "#B4AC9F", "#6E675D")},
    "dark": {"queued": ("#24201B", "#6E675D", "#C9C1B5"), "transcribing": ("#3A1A10", "#FF6A3D", "#FFB59C"),
             "processing": ("#191C46", "#7381FF", "#BAC1FF"), "ready": ("#0B3329", "#2BD1A3", "#9DEBD3"),
             "failed": ("#3F1418", "#FF5A63", "#FFB0B4"), "stopped": ("#24201B", "#6E675D", "#ABA397")},
}

ICONS = GLYPHS["regular"]          # names available to callers


def tokens(base: dict, module: int = 0) -> dict:
    """Theme tokens tinted for a module (0–3)."""
    t = dict(base)
    m = MODULES[max(0, min(module, len(MODULES) - 1))]
    acc, acc_ink, soft = m[base["name"]]
    t.update(accent=acc, accent_ink=acc_ink, soft=soft, accent2=acc, nav_ink=acc, nav_a=soft, nav_b=soft,
             pink=acc, drop_a=soft, drop_b=soft, module=module)
    return t


def load_fonts(folder: Path) -> list[str]:
    """Register the bundled typefaces (OFL). Returns the families that loaded."""
    fams: list[str] = []
    for f in sorted(folder.glob("*.ttf")):
        i = QFontDatabase.addApplicationFont(str(f))
        if i >= 0:
            fams += QFontDatabase.applicationFontFamilies(i)
    return sorted(set(fams))


def svg(name: str, color: str, stroke: float = 1.8, weight: str = "") -> bytes:
    """A Phosphor glyph as SVG. `stroke` picks the weight when `weight` is empty (≤1.3 light, ≥2.4 bold-ish fill)."""
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
    """Small SVGs that the style sheet references by file path (combo arrows, check marks, spin arrows)."""
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    tag = f"{t['name']}{t.get('module', 0)}"
    files = {
        "arrow": svg("chev_down", t["sub"], weight="bold" if "bold" in GLYPHS else "regular"),
        "up": svg("chev_up", t["sub"]),
        "check_on": (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 18"><rect x="0.5" y="0.5" width="17" '
                     f'height="17" rx="3" fill="{t["accent"]}"/><path d="m4.5 9.3 3 3 6-6.3" fill="none" '
                     f'stroke="{t["accent_ink"]}" stroke-width="2" stroke-linecap="square"/></svg>').encode(),
        "check_off": (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 18"><rect x="0.75" y="0.75" '
                      f'width="16.5" height="16.5" rx="3" fill="{t["field"]}" stroke="{t["field_border"]}" '
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
    acc, acc_ink = t["accent"], t["accent_ink"]
    return f"""
* {{ outline: 0; }}
QWidget {{ color:{t['ink']}; font-family:"{UI}", "Mukta", "Helvetica Neue", "Segoe UI", sans-serif; font-size:13px;
  background:transparent; }}
QMainWindow, QWidget#root, QDialog, QDialog#editor, QMessageBox, QFileDialog, QInputDialog {{ background:{t['bg']}; }}
QToolTip {{ background:{t['ink']}; color:{t['bg']}; border:0; padding:6px 9px; border-radius:3px; }}
QFrame#card {{ background:{t['card']}; border:1px solid {t['border']}; border-radius:6px; }}
QFrame#soon {{ background:{t['card']}; border:1px solid {t['border']}; border-radius:6px; }}
QLabel#tagline, QLabel#kicker {{ color:{t['sub']}; font-family:"{MONO}"; font-size:10px; letter-spacing:2px; }}
QLabel#kickerAcc {{ color:{acc}; font-family:"{MONO}"; font-size:10px; font-weight:600; letter-spacing:2px; }}
QLabel#sub, QLabel#hint {{ color:{t['sub']}; }}
QLabel#hint {{ font-size:12px; }}
QLabel#display {{ font-family:"{DISPLAY}"; font-size:46px; font-weight:400; }}
QLabel#displayIt {{ font-family:"{DISPLAY}"; font-style:italic; font-size:46px; font-weight:400; color:{acc}; }}
QLabel#h1 {{ font-family:"{DISPLAY}"; font-size:30px; font-weight:400; }}
QLabel#h2 {{ font-size:16px; font-weight:600; }}
QLabel#h3 {{ font-size:14px; font-weight:600; }}
QLabel#dropTitle {{ font-family:"{DISPLAY}"; font-size:40px; font-weight:400; }}
QLabel#dropFormats {{ font-family:"{MONO}"; font-size:11px; letter-spacing:1.5px; color:{t['sub']}; }}
QLabel#or {{ color:{t['sub']}; font-family:"{DISPLAY}"; font-style:italic; font-size:16px; }}
QLabel#soonTag {{ color:{acc}; font-family:"{MONO}"; font-size:10px; font-weight:600; letter-spacing:2px; }}
QLabel#soonTitle {{ font-family:"{DISPLAY}"; font-size:22px; }}
QLabel#pill {{ background:{t['seg']}; color:{t['sub']}; border-radius:3px; padding:2px 7px; font-family:"{MONO}"; font-size:10px; }}
QLabel#lang {{ background:{t['seg']}; border:1px solid {t['border']}; border-radius:3px; padding:3px 9px; font-family:"{MONO}"; font-size:11px; }}
QLabel#fname {{ font-weight:500; }}
QLabel#fmeta {{ color:{t['muted']}; font-family:"{MONO}"; font-size:11px; }}
QLabel#avatar {{ background:{acc}; color:{acc_ink}; border-radius:17px; font-family:"{DISPLAY}"; font-size:19px; }}
QFrame#banner {{ background:{t['banner']}; border-radius:4px; }}
QFrame#banner QLabel {{ color:{t['banner_ink']}; background:transparent; }}
QFrame#banner QPushButton#link {{ color:{acc}; }}

QPushButton {{ background:{t['field']}; border:1px solid {t['field_border']}; border-radius:4px; padding:7px 14px; }}
QPushButton:hover {{ border-color:{t['ink']}; }}
QPushButton:pressed {{ background:{t['hover']}; }}
QPushButton:disabled {{ color:{t['muted']}; border-color:{t['border']}; }}
QPushButton#chapter {{ background:transparent; border:0; border-bottom:2px solid transparent; border-radius:0;
  padding:6px 2px 8px 2px; margin-right:18px; color:{t['sub']}; font-size:13px; font-weight:500; }}
QPushButton#chapter:hover {{ color:{t['ink']}; }}
QPushButton#chapter:checked {{ color:{t['ink']}; border-bottom:2px solid {acc}; font-weight:600; }}
QPushButton#pillBtn {{ border-radius:17px; padding:0 16px; min-height:34px; max-height:34px; font-weight:600; }}
QPushButton#pillBtn[accent="true"] {{ background:{acc}; color:{acc_ink}; border-color:{acc}; }}
QPushButton#ghost {{ background:transparent; border:1px solid {t['border']}; border-radius:17px; padding:0 14px;
  min-height:34px; max-height:34px; font-weight:500; }}
QPushButton#ghost:hover {{ border-color:{t['ink']}; }}
QSlider::groove:horizontal {{ height:2px; background:{t['track']}; }}
QSlider::sub-page:horizontal {{ background:{acc}; }}
QSlider::handle:horizontal {{ background:{t['ink']}; width:4px; height:16px; margin:-7px 0; border-radius:1px; }}
QSlider::handle:horizontal:hover {{ background:{acc}; }}
QPushButton#chip {{ border-radius:3px; padding:4px 6px; font-family:"{MONO}"; font-size:11px; }}
QPushButton#chip:checked {{ background:{acc}; color:{acc_ink}; border-color:{acc}; }}
QPushButton#addFiles, QToolButton#addMenu {{ background:{t['dark_btn']}; color:{t['dark_btn_ink']}; border:0; font-size:14px; font-weight:600; }}
QPushButton#addFiles {{ border-top-left-radius:22px; border-bottom-left-radius:22px; border-top-right-radius:0; border-bottom-right-radius:0; padding:0 26px 0 22px; min-height:44px; max-height:44px; }}
QToolButton#addMenu {{ border-top-right-radius:22px; border-bottom-right-radius:22px; padding:0 12px; border-left:1px solid {t['sub']}; min-height:44px; max-height:44px; min-width:22px; }}
QToolButton#addMenu::menu-indicator {{ image:none; width:0; }}
QPushButton#addFiles:hover, QToolButton#addMenu:hover {{ background:{acc}; color:{acc_ink}; }}
QPushButton#addFolder {{ background:transparent; border:1px solid {t['ink']}; border-radius:22px; padding:0 30px; min-height:44px; max-height:44px; font-size:14px; font-weight:600; }}
QPushButton#addFolder:hover {{ background:{t['ink']}; color:{t['bg']}; }}
QPushButton#start {{ border:0; border-radius:4px; color:{acc_ink}; background:{acc}; font-size:16px; font-weight:600;
  padding:16px; text-align:center; }}
QPushButton#start:hover {{ background:{t['ink']}; color:{t['bg']}; }}
QPushButton#start:disabled {{ background:{t['track']}; color:{t['muted']}; }}
QPushButton#stop {{ border-radius:4px; padding:11px; font-weight:500; background:transparent; border:1px solid {t['border']}; }}
QPushButton#seg {{ background:transparent; border:0; border-radius:3px; padding:7px 6px; color:{t['sub']}; font-weight:500; }}
QPushButton#seg:checked {{ background:{t['ink']}; color:{t['bg']}; font-weight:600; }}
QFrame#segBar {{ background:{t['seg']}; border-radius:5px; }}
QPushButton#section {{ background:transparent; border:0; text-align:left; padding:4px 0; font-size:15px; font-weight:600; }}
QPushButton#link {{ background:transparent; border:0; color:{acc}; padding:2px 4px; font-weight:600; }}
QPushButton#link:hover {{ text-decoration:underline; }}
QToolButton {{ background:{t['field']}; border:1px solid {t['field_border']}; border-radius:4px; padding:6px; }}
QToolButton:hover {{ border-color:{t['ink']}; }}
QToolButton#more {{ background:transparent; border:0; }}
QToolButton::menu-indicator {{ image:none; width:0; }}
QTabWidget::pane {{ border:0; border-top:1px solid {t['border']}; top:-1px; }}
QTabBar::tab {{ background:transparent; border:0; border-bottom:2px solid transparent; padding:8px 2px; margin-right:20px;
  color:{t['sub']}; font-weight:500; }}
QTabBar::tab:hover {{ color:{t['ink']}; }}
QTabBar::tab:selected {{ color:{t['ink']}; border-bottom:2px solid {acc}; font-weight:600; }}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{ background:{t['field']}; border:1px solid {t['field_border']}; border-radius:4px;
  padding:7px 10px; selection-background-color:{acc}; selection-color:{acc_ink}; }}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color:{t['ink']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color:{acc}; }}
QComboBox::drop-down {{ border:0; width:26px; }}
QComboBox::down-arrow {{ image:url({img['arrow']}); width:12px; height:12px; }}
QComboBox QAbstractItemView {{ background:{t['card']}; border:1px solid {t['ink']}; border-radius:3px; padding:4px;
  selection-background-color:{t['hover']}; selection-color:{t['ink']}; outline:0; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin:border; subcontrol-position:top right; width:20px;
  border:0; border-left:1px solid {t['border']}; background:transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin:border; subcontrol-position:bottom right; width:20px;
  border:0; border-left:1px solid {t['border']}; background:transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image:url({img['up']}); width:9px; height:9px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image:url({img['arrow']}); width:9px; height:9px; }}
QPlainTextEdit, QTextEdit {{ background:{t['field']}; border:1px solid {t['field_border']}; border-radius:4px; padding:8px; }}
QPlainTextEdit#log {{ font-family:"{MONO}"; font-size:11px; }}
QCheckBox, QRadioButton {{ spacing:10px; background:transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width:18px; height:18px; }}
QCheckBox::indicator:unchecked {{ image:url({img['check_off']}); }}
QCheckBox::indicator:checked {{ image:url({img['check_on']}); }}
QRadioButton::indicator:unchecked {{ image:url({img['radio_off']}); }}
QRadioButton::indicator:checked {{ image:url({img['radio_on']}); }}

QTableWidget, QTreeWidget, QListWidget {{ background:transparent; border:0; gridline-color:transparent;
  selection-background-color:{t['row_sel']}; selection-color:{t['ink']}; }}
QTableWidget::item {{ border-bottom:1px solid {t['border']}; padding:0; }}
QListWidget::item {{ padding:6px; border-bottom:1px solid {t['border']}; }}
QListWidget::item:selected {{ background:{t['row_sel']}; color:{t['ink']}; border-left:2px solid {acc}; }}
QHeaderView {{ background:transparent; }}
QHeaderView::section {{ background:transparent; color:{t['sub']}; border:0; border-bottom:1px solid {t['ink']};
  padding:8px 8px; font-family:"{MONO}"; font-size:10px; letter-spacing:1.5px; }}
QProgressBar {{ border:0; background:{t['track']}; border-radius:0; max-height:4px; min-height:4px; }}
QProgressBar::chunk {{ background:{acc}; }}
QProgressBar#done::chunk {{ background:{t['ink']}; }}
QProgressBar#failed::chunk {{ background:#C8222B; }}
QMenu {{ background:{t['card']}; border:1px solid {t['ink']}; border-radius:3px; padding:5px; }}
QMenu::item {{ padding:7px 22px 7px 12px; border-radius:2px; }}
QMenu::item:selected {{ background:{acc}; color:{acc_ink}; }}
QMenu::separator {{ height:1px; background:{t['border']}; margin:4px 8px; }}
QScrollArea {{ background:transparent; border:0; }}
QScrollArea > QWidget > QWidget {{ background:transparent; }}
QScrollBar:vertical {{ background:transparent; width:8px; margin:2px; }}
QScrollBar::handle:vertical {{ background:{t['scroll']}; border-radius:3px; min-height:30px; }}
QScrollBar::handle:vertical:hover {{ background:{t['ink']}; }}
QScrollBar:horizontal {{ background:transparent; height:8px; margin:2px; }}
QScrollBar::handle:horizontal {{ background:{t['scroll']}; border-radius:3px; min-width:30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width:0; height:0; background:transparent; }}
QFrame#hline {{ background:{t['border']}; max-height:1px; min-height:1px; border:0; }}
QFrame#rule {{ background:{t['rule']}; max-height:1px; min-height:1px; border:0; }}
QSplitter::handle {{ background:{t['border']}; }}
"""
