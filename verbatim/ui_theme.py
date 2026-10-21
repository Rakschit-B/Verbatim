# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""VERBATIM 3.0 look & feel: colour tokens (light / dark), line icons and the Qt style sheet."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

LIGHT = {
    "name": "light",
    "bg": "#F4F3FA", "card": "#FFFFFF", "border": "#E9E7F2", "ink": "#1B1A38", "sub": "#66637D",
    "muted": "#9A97AE", "field": "#FFFFFF", "field_border": "#E0DDEB", "hover": "#F3F1FB", "seg": "#F1F0F7",
    "nav_a": "#E8EDFF", "nav_b": "#F7E7FA", "nav_ink": "#3D55E8", "accent": "#4D6BFE", "accent2": "#8C6BFF",
    "pink": "#F07FD8", "dark_btn": "#16152E", "dark_btn_ink": "#FFFFFF", "track": "#ECEBF3",
    "drop_a": "#EEF1FF", "drop_b": "#F9EEF8", "wave": 1.0, "scroll": "#D9D6E5", "row_sel": "#F6F4FD",
    "banner": "#FFF6D6", "banner_ink": "#5A4A00",
}
DARK = {
    "name": "dark",
    "bg": "#100F1F", "card": "#1A1930", "border": "#2B2945", "ink": "#EEEDF8", "sub": "#A7A4C0",
    "muted": "#77748F", "field": "#221F3B", "field_border": "#353252", "hover": "#252342", "seg": "#14132A",
    "nav_a": "#24305E", "nav_b": "#3B2350", "nav_ink": "#AFC0FF", "accent": "#6E87FF", "accent2": "#A68BFF",
    "pink": "#F07FD8", "dark_btn": "#F1F0FA", "dark_btn_ink": "#16152E", "track": "#2B2945",
    "drop_a": "#1D1F3D", "drop_b": "#2A1D3A", "wave": 0.55, "scroll": "#3A3758", "row_sel": "#221F3B",
    "banner": "#3A3218", "banner_ink": "#F3E3A6",
}

# status chip colours: (background, dot, text) per theme
CHIPS = {
    "light": {"queued": ("#F0EFF5", "#8A87A0", "#55526B"), "transcribing": ("#E8EEFF", "#4D6BFE", "#3552E0"),
              "processing": ("#EFEAFE", "#7B5CF0", "#5F43D8"), "ready": ("#E5F6ED", "#1FA463", "#13804C"),
              "failed": ("#FDECEC", "#E0464E", "#BF2F37"), "stopped": ("#F0EFF5", "#B4B1C4", "#6E6B83")},
    "dark": {"queued": ("#2A2844", "#8A87A0", "#C9C6DD"), "transcribing": ("#22305F", "#7D95FF", "#B7C5FF"),
             "processing": ("#30265A", "#A48CFF", "#CFC2FF"), "ready": ("#173B2B", "#3CCB85", "#9DE8C2"),
             "failed": ("#46202A", "#FF6B72", "#FFB3B7"), "stopped": ("#2A2844", "#6E6B83", "#A7A4C0")},
}

# Simple 24×24 line icons (drawn for VERBATIM in the style of the ISC-licensed Lucide set)
ICONS = {
    "home": '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    "file": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>',
    "projects": '<rect x="3" y="7" width="14" height="13" rx="2"/>'
                '<path d="M7 7V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5"/>'
             '<path d="M16 4.6a3.5 3.5 0 0 1 0 6.8"/><path d="M18 14.8c2 .7 3.2 2.4 3.5 5.2"/>',
    "vocab": '<rect x="4" y="5" width="3.2" height="15" rx="1"/><rect x="10" y="8" width="3.2" height="12" rx="1"/>'
             '<path d="m16.2 6.5 3.8 13.5"/>',
    "output": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>'
              '<path d="M12 11v6"/><path d="m9 14 3 3 3-3"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "gear": '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73'
            'l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38'
            'a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18'
            'a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08'
            'a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08'
            'a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    "upload": '<path d="M12 15V4"/><path d="m7 9 5-5 5 5"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "chev_down": '<path d="m6 9 6 6 6-6"/>',
    "chev_up": '<path d="m6 15 6-6 6 6"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "sliders": '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/>'
               '<circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/>'
            '<circle cx="4.5" cy="18" r="1"/>',
    "download": '<path d="M12 4v11"/><path d="m7 10 5 5 5-5"/><path d="M4 20h16"/>',
    "sparkle": '<path fill="currentColor" stroke="none" d="M11 2.5l1.9 5.6 5.6 1.9-5.6 1.9L11 17.5l-1.9-5.6L3.5 10'
               'l5.6-1.9z"/><path fill="currentColor" stroke="none" d="M18.5 14l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6'
               '-2.6-.9 2.6-.9z"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
    "more": '<circle cx="5" cy="12" r="1.6" fill="currentColor" stroke="none"/>'
            '<circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none"/>'
            '<circle cx="19" cy="12" r="1.6" fill="currentColor" stroke="none"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18z"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    "film": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
    "wave": '<path d="M3 12h1M7 9v6M10 5v14M13 8v8M16 10v4M19 7v10M21 12h0"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    "open": '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
    "play": '<path d="M7 4.5v15l12-7.5z" fill="currentColor" stroke="none"/>',
    "mic2": '<path d="M12 3v18M8 7v10M4 10v4M16 7v10M20 10v4"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "bolt": '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    "excel": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="m9 8 6 8M15 8l-6 8"/>',
}


def svg(name: str, color: str, stroke: float = 1.8) -> bytes:
    body = ICONS[name].replace("currentColor", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


def pixmap(name: str, color: str, size: int = 20, ratio: float = 2.0, stroke: float = 1.8) -> QPixmap:
    px = QPixmap(int(size * ratio), int(size * ratio))
    px.fill(Qt.transparent)
    r = QSvgRenderer(QByteArray(svg(name, color, stroke)))
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, px.width(), px.height()))
    p.end()
    px.setDevicePixelRatio(ratio)
    return px


def icon(name: str, color: str, size: int = 20) -> QIcon:
    return QIcon(pixmap(name, color, size))


def write_qss_images(folder: Path, t: dict) -> dict:
    """Small SVGs that the style sheet references by file path (combo arrows, check marks)."""
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    files = {
        "arrow": svg("chev_down", t["sub"], 2.0),
        "check_on": (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 18"><rect x="0.5" y="0.5" width="17" '
                     f'height="17" rx="4.5" fill="{t["accent"]}"/><path d="m4.5 9.3 3 3 6-6.3" fill="none" '
                     f'stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>').encode(),
        "check_off": (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 18"><rect x="0.75" y="0.75" '
                      f'width="16.5" height="16.5" rx="4.5" fill="{t["field"]}" stroke="{t["field_border"]}" '
                      f'stroke-width="1.5"/></svg>').encode(),
    }
    for k, data in files.items():
        p = folder / f"{t['name']}_{k}.svg"
        p.write_bytes(data)
        out[k] = p.as_posix()
    return out


def stylesheet(t: dict, img: dict) -> str:
    return f"""
* {{ outline: 0; }}
QWidget {{ color:{t['ink']}; font-size:13px; background:transparent; }}
QMainWindow, QWidget#root, QDialog, QDialog#editor, QMessageBox, QFileDialog, QInputDialog {{ background:{t['bg']}; }}
QToolTip {{ background:{t['card']}; color:{t['ink']}; border:1px solid {t['border']}; padding:6px 8px; border-radius:6px; }}
QFrame#card {{ background:{t['card']}; border:1px solid {t['border']}; border-radius:18px; }}
QFrame#soon {{ background:{t['card']}; border:1px solid {t['border']}; border-radius:16px; }}
QLabel#tagline {{ color:{t['sub']}; font-size:11px; letter-spacing:4px; }}
QLabel#sub, QLabel#hint {{ color:{t['sub']}; }}
QLabel#hint {{ font-size:12px; }}
QLabel#h1 {{ font-size:22px; font-weight:600; }}
QLabel#h2 {{ font-size:17px; font-weight:600; }}
QLabel#h3 {{ font-size:14px; font-weight:600; }}
QLabel#dropTitle {{ font-size:21px; font-weight:500; }}
QLabel#dropFormats {{ font-size:15px; color:{t['sub']}; }}
QLabel#or {{ color:{t['sub']}; }}
QLabel#soonTag {{ color:{t['accent']}; font-size:11px; font-weight:600; letter-spacing:1.5px; }}
QLabel#soonTitle {{ font-size:16px; font-weight:700; }}
QLabel#pill {{ background:{t['seg']}; color:{t['sub']}; border-radius:9px; padding:2px 8px; font-size:11px; font-weight:600; }}
QLabel#lang {{ background:{t['seg']}; border:1px solid {t['border']}; border-radius:7px; padding:3px 9px; }}
QLabel#fname {{ font-weight:500; }}
QLabel#fmeta {{ color:{t['muted']}; font-size:12px; }}
QLabel#avatar {{ background:{t['dark_btn']}; color:{t['dark_btn_ink']}; border-radius:22px; font-size:17px; font-weight:600; }}
QFrame#banner {{ background:{t['banner']}; border-radius:12px; }}
QFrame#banner QLabel {{ color:{t['banner_ink']}; background:transparent; }}

QFrame#module {{ background:transparent; border-radius:12px; }}
QFrame#moduleOn {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {t['nav_a']}, stop:1 {t['nav_b']}); border-radius:12px; }}
QFrame#module QLabel, QFrame#moduleOn QLabel {{ background:transparent; }}
QLabel#modNum {{ color:{t['muted']}; font-weight:700; font-size:12px; }}
QLabel#modNumOn {{ color:{t['nav_ink']}; font-weight:700; font-size:12px; }}
QLabel#modName {{ color:{t['muted']}; font-weight:600; letter-spacing:1px; }}
QLabel#modNameOn {{ color:{t['nav_ink']}; font-weight:700; letter-spacing:1px; }}

QPushButton {{ background:{t['field']}; border:1px solid {t['field_border']}; border-radius:10px; padding:8px 14px; }}
QPushButton:hover {{ background:{t['hover']}; }}
QPushButton:disabled {{ color:{t['muted']}; }}
QPushButton#nav {{ background:transparent; border:0; border-radius:14px; text-align:left; padding:12px 16px; font-size:14px; }}
QPushButton#nav:hover {{ background:{t['hover']}; }}
QPushButton#nav:checked {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {t['nav_a']}, stop:1 {t['nav_b']}); color:{t['nav_ink']}; font-weight:600; }}
QPushButton#pillBtn {{ border-radius:19px; padding:0 18px; min-height:40px; max-height:40px; font-weight:600; }}
QSlider::groove:horizontal {{ height:4px; background:{t['track']}; border-radius:2px; }}
QSlider::sub-page:horizontal {{ background:{t['accent']}; border-radius:2px; }}
QSlider::handle:horizontal {{ background:{t['card']}; border:2px solid {t['accent']}; width:12px; height:12px;
  margin:-6px 0; border-radius:8px; }}
QPushButton#chip {{ border-radius:8px; padding:4px 6px; font-size:12px; }}
QPushButton#pillBtn[accent="true"] {{ background:{t['accent']}; color:white; border-color:{t['accent']}; }}
QPushButton#addFiles, QToolButton#addMenu {{ background:{t['dark_btn']}; color:{t['dark_btn_ink']}; border:0; font-size:14px; font-weight:600; }}
QPushButton#addFiles {{ border-top-left-radius:20px; border-bottom-left-radius:20px; border-top-right-radius:0; border-bottom-right-radius:0; padding:0 26px 0 22px; min-height:42px; max-height:42px; }}
QToolButton#addMenu {{ border-top-right-radius:20px; border-bottom-right-radius:20px; padding:0 12px; border-left:1px solid {t['muted']}; min-height:42px; max-height:42px; min-width:22px; }}
QToolButton#addMenu::menu-indicator {{ image:none; width:0; }}
QPushButton#addFiles:hover, QToolButton#addMenu:hover {{ background:{t['accent']}; color:white; }}
QPushButton#addFolder {{ background:{t['card']}; border:1px solid {t['border']}; border-radius:20px; padding:0 34px; min-height:42px; max-height:42px; font-size:14px; font-weight:600; }}
QPushButton#addFolder:hover {{ background:{t['hover']}; }}
QPushButton#start {{ border:0; border-radius:16px; color:white; font-size:17px; font-weight:600; padding:16px;
  background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #4D7CFE, stop:0.55 #8C6BFF, stop:1 #F07FD8); }}
QPushButton#start:hover {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #3F6BF0, stop:0.55 #7C5BF0, stop:1 #E56DCB); }}
QPushButton#start:disabled {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #A9B9F5, stop:1 #E9B9DF); }}
QPushButton#stop {{ border-radius:14px; padding:12px; font-weight:500; background:{t['card']}; }}
QPushButton#seg {{ background:transparent; border:0; border-radius:9px; padding:8px 4px; color:{t['sub']}; }}
QPushButton#seg:checked {{ background:{t['card']}; color:{t['ink']}; font-weight:600; border:1px solid {t['border']}; }}
QFrame#segBar {{ background:{t['seg']}; border-radius:12px; }}
QPushButton#section {{ background:transparent; border:0; text-align:left; padding:4px 0; font-size:17px; font-weight:600; }}
QPushButton#link {{ background:transparent; border:0; color:{t['accent']}; padding:2px 4px; font-weight:600; }}
QToolButton {{ background:{t['field']}; border:1px solid {t['field_border']}; border-radius:9px; padding:6px; }}
QToolButton:hover {{ background:{t['hover']}; }}
QToolButton#more {{ background:transparent; border:0; }}
QToolButton::menu-indicator {{ image:none; width:0; }}

QComboBox, QLineEdit, QSpinBox {{ background:{t['field']}; border:1px solid {t['field_border']}; border-radius:10px; padding:8px 10px; selection-background-color:{t['accent']}; }}
QComboBox:hover, QLineEdit:hover {{ border-color:{t['accent2']}; }}
QComboBox::drop-down {{ border:0; width:28px; }}
QComboBox::down-arrow {{ image:url({img['arrow']}); width:14px; height:14px; }}
QComboBox QAbstractItemView {{ background:{t['card']}; border:1px solid {t['border']}; border-radius:8px; padding:4px; selection-background-color:{t['hover']}; selection-color:{t['ink']}; outline:0; }}
QPlainTextEdit {{ background:{t['field']}; border:1px solid {t['field_border']}; border-radius:12px; padding:8px; }}
QPlainTextEdit#log {{ font-family: Menlo, Consolas, monospace; font-size:12px; }}
QCheckBox {{ spacing:10px; background:transparent; }}
QCheckBox::indicator {{ width:18px; height:18px; }}
QCheckBox::indicator:unchecked {{ image:url({img['check_off']}); }}
QCheckBox::indicator:checked {{ image:url({img['check_on']}); }}

QTableWidget {{ background:transparent; border:0; gridline-color:transparent; selection-background-color:{t['row_sel']}; selection-color:{t['ink']}; }}
QTableWidget::item {{ border-bottom:1px solid {t['border']}; padding:0; }}
QHeaderView {{ background:transparent; }}
QHeaderView::section {{ background:{t['seg']}; color:{t['sub']}; border:0; padding:9px 8px; font-weight:500; }}
QHeaderView::section:first {{ border-top-left-radius:10px; border-bottom-left-radius:10px; }}
QHeaderView::section:last {{ border-top-right-radius:10px; border-bottom-right-radius:10px; }}
QProgressBar {{ border:0; background:{t['track']}; border-radius:4px; max-height:8px; min-height:8px; }}
QProgressBar::chunk {{ border-radius:4px; background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #4D7CFE, stop:1 #8C6BFF); }}
QProgressBar#done::chunk {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #4D7CFE, stop:1 #22C38E); }}
QProgressBar#failed::chunk {{ background:#E0464E; }}
QMenu {{ background:{t['card']}; border:1px solid {t['border']}; border-radius:10px; padding:6px; }}
QMenu::item {{ padding:7px 22px 7px 12px; border-radius:6px; }}
QMenu::item:selected {{ background:{t['hover']}; }}
QMenu::separator {{ height:1px; background:{t['border']}; margin:4px 8px; }}
QScrollArea {{ background:transparent; border:0; }}
QScrollArea > QWidget > QWidget {{ background:transparent; }}
QScrollBar:vertical {{ background:transparent; width:10px; margin:2px; }}
QScrollBar::handle:vertical {{ background:{t['scroll']}; border-radius:4px; min-height:30px; }}
QScrollBar:horizontal {{ background:transparent; height:10px; margin:2px; }}
QScrollBar::handle:horizontal {{ background:{t['scroll']}; border-radius:4px; min-width:30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width:0; height:0; background:transparent; }}
QFrame#hline {{ background:{t['border']}; max-height:1px; min-height:1px; border:0; }}
"""
