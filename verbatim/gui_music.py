# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Music (3.7, rebuilt): describe the sound, write or generate lyrics, cast every section — male, female,
duet or chorus — and create. Every take plays in the player bar, learns from your 👍 / 👎 and downloads in one
click (song, cast version, stems, lyrics)."""
from __future__ import annotations

import random
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox, QToolButton, QVBoxLayout,
                               QWidget)

from . import music_studio as ms
from . import ui_theme as th
from .gui_player import Cover, Media, fmt, save_copy
from .lyrics import SECTIONS, SINGERS, Part, Sheet


def _t() -> dict:
    from . import gui

    return gui.T


def _label(text="", name=None, wrap=False):
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def _card(name="card"):
    f = QFrame()
    f.setObjectName(name)
    return f


class _Job(QObject):
    progress = Signal(float, str)
    done = Signal(object, str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(lambda f, m: self.progress.emit(float(f), str(m))), "")
        except Exception as exc:
            self.done.emit(None, f"{type(exc).__name__}: {exc}")


# ====================================================================== song sheet editor
class SectionCard(QFrame):
    """One section: its name, who sings it, and its lines."""
    removed = Signal(object)

    def __init__(self, part: Part):
        super().__init__()
        self.setObjectName("card2")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.section = QComboBox()
        self.section.addItems(SECTIONS)
        self.section.setCurrentText(part.section if part.section in SECTIONS else "Verse")
        top.addWidget(self.section)
        self.singer = QComboBox()
        for k, (label, _cap, _n) in SINGERS.items():
            self.singer.addItem(label, k)
        self.singer.setCurrentIndex(max(0, self.singer.findData(part.singer)))
        self.singer.setToolTip("Who sings this section")
        top.addWidget(self.singer, 1)
        rm = QPushButton()
        rm.setObjectName("iconBtn")
        rm.setToolTip("Remove section")
        rm.setIcon(th.icon("x", _t()["sub"], 14))
        rm.clicked.connect(lambda: self.removed.emit(self))
        top.addWidget(rm)
        v.addLayout(top)
        self.text = QPlainTextEdit("\n".join(part.lines))
        self.text.setPlaceholderText("Lines for this section…")
        self.text.setFixedHeight(78)
        v.addWidget(self.text)

    def part(self) -> Part:
        return Part(self.section.currentText(), self.singer.currentData(),
                    [ln.strip() for ln in self.text.toPlainText().splitlines() if ln.strip()])


class LyricsDialog(QDialog):
    """Write lyrics with AI — offline on this computer (Gemma 3) or online (Claude)."""

    def __init__(self, parent, plan: list[tuple[str, str]], style: str):
        super().__init__(parent)
        self.setWindowTitle("Write lyrics with AI")
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.addWidget(_label("What is the song about?", "h2"))
        self.brief = QPlainTextEdit()
        self.brief.setPlaceholderText("e.g. A wedding song for a Punjabi family — two families becoming one, dhol, "
                                      "joy, a chorus everyone can sing")
        self.brief.setFixedHeight(90)
        v.addWidget(self.brief)
        row = QHBoxLayout()
        row.addWidget(_label("Language", "sub"))
        self.lang = QComboBox()
        for code, name in ms.LANGS.items():
            if code not in ("instrumental", "unknown"):
                self.lang.addItem(name, code)
        row.addWidget(self.lang, 1)
        row.addWidget(_label("Writer", "sub"))
        self.engine = QComboBox()
        self.engine.addItem("Offline — Gemma 3 on this computer", "offline")
        self.engine.addItem("Online — Claude (best craft)", "claude")
        row.addWidget(self.engine, 1)
        v.addLayout(row)
        v.addWidget(_label("Sections and singers follow your song sheet: " +
                           " · ".join(f"{s} ({SINGERS[g][0].split(' ·')[0]})" for s, g in plan), "hint", wrap=True))
        self.style = style
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Write")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


# ====================================================================== library rows
class SongRow(QFrame):
    def __init__(self, page, it: dict, queue):
        super().__init__()
        self.page, self.it = page, it
        self.setObjectName("card2")
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(10)
        c = Cover(46)
        c.set("music", hash(it.get("id", "")) % 3)
        h.addWidget(c)
        info = QVBoxLayout()
        info.setSpacing(1)
        info.addWidget(_label(f"{it.get('title', 'Untitled')}  ·  take {it.get('take', 1)}", "fname"))
        f = it.get("files", {}) or {}
        cap = (it.get("caption") or (it.get("request") or {}).get("style") or "")[:90]
        meta = " · ".join(x for x in (f"{it.get('bpm')} BPM" if it.get("bpm") else "", it.get("key") or "",
                                       "cast ✓" if f.get("cast_wav") else "") if x)
        info.addWidget(_label(f"{meta}   {cap}".strip(), "hint"))
        h.addLayout(info, 1)
        if f.get("seconds"):
            h.addWidget(_label(fmt(int(float(f["seconds"]) * 1000)), "time"))
        play = QPushButton()
        play.setObjectName("playBtn")
        play.setStyleSheet("min-width:36px;max-width:36px;min-height:36px;max-height:36px;border-radius:18px;")
        play.setIcon(th.icon("play", _t()["bg"], 16, weight="fill"))
        play.clicked.connect(lambda: page.play(it, queue))
        h.addWidget(play)
        for glyph, ev, tip in (("thumbs_up", "like", "More like this — VERBATIM learns your taste"),
                               ("thumbs_down", "dislike", "Less like this"),
                               ("heart", "favourite", "Favourite")):
            b = QPushButton()
            b.setObjectName("iconBtn")
            b.setToolTip(tip)
            on = (ev == "favourite" and it.get("favourite")) or it.get("rating") == ev
            b.setIcon(th.icon(glyph, _t()["accent"] if on else _t()["sub"], 17, weight="fill" if on else "regular"))
            b.clicked.connect(lambda _=False, e=ev: page.rate(it, e))
            h.addWidget(b)
        dl = QToolButton()
        dl.setText("  Download")
        dl.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        dl.setIcon(th.icon("download", _t()["ink"], 16))
        dl.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(dl)
        labels = [("cast_mp3", "Song — cast singers (MP3)"), ("cast_wav", "Song — cast singers (WAV)"),
                  ("mp3", "Song (MP3)"), ("wav", "Song (WAV)"), ("flac", "Song (FLAC)"), ("with_voice", "With voiceover"),
                  ("vocals", "Vocals stem"), ("instrumental", "Instrumental stem")]
        for k, label in labels:
            p = f.get(k)
            if p and Path(str(p)).exists():
                m.addAction(label, lambda p=p: page.download(it, p))
        for ver in it.get("versions", []) or []:
            if ver.get("mp3") and Path(ver["mp3"]).exists():
                m.addAction(f"Sung by {ver.get('voice')} (MP3)", lambda p=ver["mp3"]: page.download(it, p))
        m.addSeparator()
        m.addAction("Lyrics (TXT)", lambda: page.save_lyrics(it))
        dl.setMenu(m)
        h.addWidget(dl)
        more = QToolButton()
        more.setObjectName("more")
        more.setIcon(th.icon("more", _t()["sub"], 18))
        more.setPopupMode(QToolButton.InstantPopup)
        mm = QMenu(more)
        mm.addAction("Reuse these settings", lambda: page.reuse(it))
        mm.addAction("Re-roll (same settings, new seed)", lambda: page.reroll(it))
        mm.addAction("Remix / extend…", lambda: page.remix(it))
        mm.addAction("Re-cast the singers", lambda: page.recast(it))
        mm.addAction("Sing it in my voice…", lambda: page.sing_as(it))
        mm.addAction("Separate stems", lambda: page.stems(it))
        mm.addAction("Use as voiceover music", lambda: page.use_as_bed(it))
        mm.addSeparator()
        mm.addAction("Show in folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(f.get("wav", "")).parent))))
        more.setMenu(mm)
        h.addWidget(more)


# ====================================================================== page
class MusicStudio(QWidget):
    log = Signal(str)

    def __init__(self, window):
        super().__init__()
        self.w = window
        self.thread = None
        self.cards: list[SectionCard] = []
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)
        h.addWidget(self._create())
        h.addWidget(self._songs(), 1)
        self.load_sheet(Sheet("", "en", [Part(s, g, []) for s, g in
                                         [("Verse", "male"), ("Chorus", "duet"), ("Verse", "female"),
                                          ("Chorus", "chorus3"), ("Bridge", "male"), ("Chorus", "choir")]]))

    # ------------------------------------------------------------ create panel
    def _create(self):
        c = _card()
        c.setFixedWidth(500)
        outer = QVBoxLayout(c)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)
        outer.addWidget(_label("Create a song", "h1"))
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 8, 0)
        v.setSpacing(10)
        self.title = QLineEdit()
        self.title.setPlaceholderText("Song title")
        v.addWidget(self.title)
        srow = QHBoxLayout()
        srow.addWidget(_label("SOUND", "kicker"))
        srow.addStretch()
        insp = QPushButton("  Inspire me")
        insp.setObjectName("link")
        insp.clicked.connect(self.inspire)
        srow.addWidget(insp)
        v.addLayout(srow)
        self.style = QPlainTextEdit()
        self.style.setPlaceholderText("Genre, mood, instruments, production — e.g. “Bollywood romantic, soft piano, "
                                      "strings, tabla groove, warm, cinematic build to a big final chorus”")
        self.style.setFixedHeight(84)
        self.style.textChanged.connect(self.show_taste)
        v.addWidget(self.style)
        self.taste = _label("", "hint", wrap=True)
        v.addWidget(self.taste)
        self.use_taste = QCheckBox("Add what I usually like")
        self.use_taste.setChecked(True)
        v.addWidget(self.use_taste)
        lrow = QHBoxLayout()
        lrow.addWidget(_label("LYRICS & SINGERS", "kicker"))
        lrow.addStretch()
        self.instrumental = QCheckBox("Instrumental")
        self.instrumental.toggled.connect(self.on_instrumental)
        lrow.addWidget(self.instrumental)
        v.addLayout(lrow)
        arow = QHBoxLayout()
        self.write_btn = QPushButton("  Write lyrics with AI")
        self.write_btn.setObjectName("primary")
        self.write_btn.setIcon(th.icon("pen", "#FFFFFF", 16))
        self.write_btn.clicked.connect(self.write_lyrics)
        arow.addWidget(self.write_btn)
        add = QPushButton("+ Section")
        add.setObjectName("ghost")
        add.clicked.connect(lambda: self.add_section(Part("Verse", "male", [])))
        arow.addWidget(add)
        paste = QPushButton("Paste lyrics…")
        paste.setObjectName("ghost")
        paste.setToolTip("Paste lyrics with [Verse] / [Chorus | Duet] headers — VERBATIM builds the sections")
        paste.clicked.connect(self.paste_lyrics)
        arow.addWidget(paste)
        v.addLayout(arow)
        self.sections_box = QVBoxLayout()
        self.sections_box.setSpacing(8)
        self.sections_w = QWidget()
        self.sections_w.setLayout(self.sections_box)
        v.addWidget(self.sections_w)
        vrow = QHBoxLayout()
        vrow.addWidget(_label("Sung in", "sub"))
        self.language = QComboBox()
        for code, name in ms.LANGS.items():
            if code not in ("instrumental", "unknown"):
                self.language.addItem(name, code)
        vrow.addWidget(self.language, 1)
        self.cast = QCheckBox("Enforce the singers")
        self.cast.setChecked(True)
        self.cast.setToolTip("After the song is made, VERBATIM re-voices each section to its singer (male, female, "
                             "duet, chorus layers). Uses the voice engine when installed.")
        vrow.addWidget(self.cast)
        v.addLayout(vrow)
        v.addWidget(_label("SHAPE", "kicker"))
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.addWidget(_label("Length", "sub"), 0, 0)
        self.duration = QSpinBox()
        self.duration.setRange(10, 480)
        self.duration.setValue(150)
        self.duration.setSuffix(" s")
        g.addWidget(self.duration, 0, 1)
        g.addWidget(_label("Takes", "sub"), 0, 2)
        self.takes = QSpinBox()
        self.takes.setRange(1, 4)
        self.takes.setValue(2)
        g.addWidget(self.takes, 0, 3)
        g.addWidget(_label("BPM", "sub"), 1, 0)
        self.bpm = QSpinBox()
        self.bpm.setRange(0, 220)
        self.bpm.setSpecialValueText("Auto")
        g.addWidget(self.bpm, 1, 1)
        g.addWidget(_label("Key", "sub"), 1, 2)
        self.key = QComboBox()
        for k in ms.KEYS:
            self.key.addItem(k or "Auto", k)
        g.addWidget(self.key, 1, 3)
        v.addLayout(g)
        self.avoid = QLineEdit()
        self.avoid.setPlaceholderText("Avoid (e.g. autotune, heavy distortion)")
        v.addWidget(self.avoid)
        qrow = QHBoxLayout()
        self.max_mode = QCheckBox("Max quality (slower)")
        qrow.addWidget(self.max_mode)
        qrow.addStretch()
        qrow.addWidget(_label("Seed", "sub"))
        self.seed = QSpinBox()
        self.seed.setRange(-1, 2_000_000_000)
        self.seed.setValue(-1)
        self.seed.setSpecialValueText("Random")
        qrow.addWidget(self.seed)
        v.addLayout(qrow)
        v.addStretch()
        sc.setWidget(inner)
        outer.addWidget(sc, 1)
        self.status = _label("", "hint", wrap=True)
        outer.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        outer.addWidget(self.bar)
        self.go = QPushButton("   Create song")
        self.go.setObjectName("start")
        self.go.setCursor(Qt.PointingHandCursor)
        self.go.setIcon(th.icon("music", "#FFFFFF", 20, weight="fill"))
        self.go.clicked.connect(self.create)
        outer.addWidget(self.go)
        return c

    def _songs(self):
        c = _card()
        v = QVBoxLayout(c)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(_label("Your songs", "h1"))
        top.addStretch()
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search songs…")
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(lambda _: self.refresh_library())
        top.addWidget(self.search)
        self.fav_only = QCheckBox("Favourites")
        self.fav_only.toggled.connect(lambda _: self.refresh_library())
        top.addWidget(self.fav_only)
        v.addLayout(top)
        self.engine_row = QHBoxLayout()
        v.addLayout(self.engine_row)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self.rows = QVBoxLayout(inner)
        self.rows.setContentsMargins(0, 0, 6, 0)
        self.rows.setSpacing(8)
        sc.setWidget(inner)
        v.addWidget(sc, 1)
        self.fill_engines()
        return c

    # ------------------------------------------------------------ sheet
    def add_section(self, part: Part):
        card = SectionCard(part)
        card.removed.connect(self.remove_section)
        self.cards.append(card)
        self.sections_box.addWidget(card)

    def remove_section(self, card):
        if card in self.cards:
            self.cards.remove(card)
            card.deleteLater()

    def load_sheet(self, sheet: Sheet):
        for c in list(self.cards):
            self.remove_section(c)
        for p in sheet.parts:
            self.add_section(p)
        if sheet.language:
            i = self.language.findData(sheet.language)
            if i >= 0:
                self.language.setCurrentIndex(i)

    def sheet(self) -> Sheet:
        return Sheet(self.title.text().strip(), self.language.currentData(), [c.part() for c in self.cards])

    def on_instrumental(self, on: bool):
        self.sections_w.setVisible(not on)
        self.write_btn.setEnabled(not on)
        self.cast.setEnabled(not on)

    def paste_lyrics(self):
        from .lyrics import parse

        dlg = QDialog(self)
        dlg.setWindowTitle("Paste lyrics")
        dlg.resize(560, 520)
        lay = QVBoxLayout(dlg)
        lay.addWidget(_label("Headers like [Verse 1 | Male], [Chorus | Duet], [Bridge - female], [Chorus | Choir] set "
                             "the singer of each section.", "hint", wrap=True))
        ed = QPlainTextEdit()
        lay.addWidget(ed, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() == QDialog.Accepted and ed.toPlainText().strip():
            parts = parse(ed.toPlainText())
            self.load_sheet(Sheet(self.title.text(), self.language.currentData(), parts))

    def write_lyrics(self):
        plan = [(c.section.currentText(), c.singer.currentData()) for c in self.cards] or None
        from .lyrics import default_plan

        plan = plan or default_plan()
        dlg = LyricsDialog(self, plan, self.style.toPlainText())
        i = dlg.lang.findData(self.language.currentData())
        if i >= 0:
            dlg.lang.setCurrentIndex(i)
        if dlg.exec() != QDialog.Accepted or not dlg.brief.toPlainText().strip():
            return
        brief, lang, engine = dlg.brief.toPlainText().strip(), dlg.lang.currentData(), dlg.engine.currentData()
        if engine == "claude":
            from .translate import get_claude_key

            if not get_claude_key():
                QMessageBox.information(self, "Claude", "Add your Claude API key in Settings first, or use the offline "
                                        "writer.")
                return
        mood = self.style.toPlainText().strip()
        from .lyrics import write

        def done(parts, err):
            self.finish()
            if err:
                QMessageBox.warning(self, "Lyrics", err)
                return
            self.load_sheet(Sheet(self.title.text(), lang, parts))
            i = self.language.findData(lang)
            if i >= 0:
                self.language.setCurrentIndex(i)
            if not self.title.text().strip():
                self.title.setText(brief.split(".")[0][:40])
            self.status.setText("Lyrics written — edit any line, change any singer, then Create song.")

        self.run(lambda p: write(brief, lang, plan, mood, engine, p, seed=random.randint(0, 99999)), done,
                 "Writing lyrics…")

    # ------------------------------------------------------------ taste + inspiration
    def show_taste(self):
        from .taste import enhance

        _s, add, bad = enhance(self.w.s.output_dir, self.style.toPlainText())
        bits = []
        if add:
            bits.append("Learned from your likes: " + ", ".join("+" + a for a in add))
        if bad:
            bits.append("avoiding: " + ", ".join(bad[:3]))
        self.taste.setText("  ·  ".join(bits))
        self.use_taste.setVisible(bool(add or bad))

    def inspire(self):
        lib = ms.prompt_library()
        if not lib:
            return
        k = random.choice(list(lib))
        p = lib[k]
        self.style.setPlainText(p.get("prompt", ""))
        if not self.title.text().strip():
            self.title.setText(p.get("title", ""))
        if p.get("bpm"):
            self.bpm.setValue(int(p["bpm"]))

    # ------------------------------------------------------------ engine status
    def fill_engines(self):
        from . import runtimes
        from .cloud import active_for

        while self.engine_row.count():
            it = self.engine_row.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().setParent(None)
        cloud = active_for("music")
        ok = cloud or (runtimes.is_ready("music") and
                       (ms.checkpoints_root() / "checkpoints" / "acestep-v15-turbo").exists())
        if ok:
            return
        self.engine_row.addWidget(_label("The music engine installs once (about 10 GB). After that, songs are made "
                                         "on this computer — or on your Cloud GPU.", "hint", wrap=True), 1)
        b = QPushButton("Install music engine")
        b.setObjectName("primary")
        b.clicked.connect(self.install)
        self.engine_row.addWidget(b)

    def install(self):
        def work(progress):
            from . import runtimes

            runtimes.ensure("music", lambda f, m: progress(0.4 * f, m))
            ms.ensure_models(lambda f, m: progress(0.4 + 0.6 * f, m))
            return True

        self.run(work, lambda ok, err: (self.finish(), self.fill_engines(),
                                        QMessageBox.warning(self, "Install failed", err) if err
                                        else self.status.setText("Music engine installed.")),
                 "Installing the music engine (one time)…")

    # ------------------------------------------------------------ jobs
    def run(self, fn, done, text):
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, "Busy", "Music is still working on the last job.")
            return
        self.go.setEnabled(False)
        self.bar.setVisible(True)
        self.status.setText(text)
        from . import qt_workers
        from .gui_shell import track

        self.worker = _Job(fn)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(done)
        track(self.w, self.worker, text.rstrip("…. ") or "Music")
        self.thread = qt_workers.start(self.worker, self.worker.run, [self.worker.done])

    def on_progress(self, f, m):
        self.bar.setValue(int(1000 * max(0.0, min(1.0, f))))
        self.status.setText(m)
        self.w.mast.ruler.set_progress(f)

    def finish(self):
        self.go.setEnabled(True)
        self.bar.setVisible(False)
        self.w.mast.ruler.set_progress(None)

    def request(self) -> ms.MusicRequest:
        from .taste import enhance

        style = self.style.toPlainText().strip()
        learned = []
        if self.use_taste.isChecked() and self.use_taste.isVisible():
            style, learned, bad = enhance(self.w.s.output_dir, style)
            avoid = ", ".join(x for x in [self.avoid.text().strip()] + bad[:3] if x)
        else:
            avoid = self.avoid.text().strip()
        sheet = self.sheet()
        inst = self.instrumental.isChecked() or not any(p.lines for p in sheet.parts)
        return ms.MusicRequest(title=self.title.text().strip() or "Untitled", mode="custom", style=style,
                               language="instrumental" if inst else sheet.language, bpm=self.bpm.value() or None,
                               key=self.key.currentData() or "", duration=float(self.duration.value()),
                               takes=self.takes.value(), seed=self.seed.value(), exclude=avoid,
                               max_mode=self.max_mode.isChecked(), sheet={} if inst else sheet.as_dict(),
                               cast=self.cast.isChecked() and not inst, learned=learned)

    def create(self):
        r = self.request()
        if not r.style:
            QMessageBox.information(self, "Sound", "Describe the sound first (or press Inspire me).")
            return
        out = self.w.s.output_dir
        self.run(lambda p: ms.generate(r, out, p), self.on_created, "Composing…")

    def on_created(self, items, err):
        self.finish()
        if err:
            self.status.setText("Could not create the song — " + err)
            QMessageBox.warning(self, "Music", err)
            return
        self.status.setText(f"{len(items)} take(s) ready — ▶ to listen, 👍 / 👎 to teach VERBATIM your taste.")
        self.log.emit(f"Music: {len(items)} take(s) of “{items[0]['title'] if items else ''}”")
        self.refresh_library()
        if items:
            self.play(items[0], None)

    # ------------------------------------------------------------ library
    def refresh_library(self):
        while self.rows.count():
            it = self.rows.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        q = self.search.text().strip().lower() if hasattr(self, "search") else ""
        items = [x for x in ms.load_history(self.w.s.output_dir)
                 if (not q or q in (x.get("title", "") + " " + str(x.get("caption", ""))).lower())
                 and (not self.fav_only.isChecked() or x.get("favourite"))]
        queue = []
        for x in items:
            f = self._main(x)
            if f:
                queue.append((f, f"{x.get('title')} · take {x.get('take')}", "Song"))
        for x in items[:200]:
            self.rows.addWidget(SongRow(self, x, queue))
        if not items:
            self.rows.addWidget(_label("Your songs appear here — every take, ready to play and download.", "hint"))
        self.rows.addStretch()

    @staticmethod
    def _main(it) -> str:
        f = it.get("files", {}) or {}
        for k in ("cast_mp3", "cast_wav", "mp3", "wav"):
            if f.get(k) and Path(str(f[k])).exists():
                return str(f[k])
        return ""

    def play(self, it, queue):
        f = self._main(it)
        if f:
            Media.get().load(f, f"{it.get('title')} · take {it.get('take')}", "Song", queue=queue)

    def _update(self, it, **kw):
        items = ms.load_history(self.w.s.output_dir)
        for x in items:
            if x.get("id") == it.get("id"):
                x.update(kw)
        ms.save_history(self.w.s.output_dir, items)

    def rate(self, it, ev: str):
        from .taste import record

        style = it.get("caption") or (it.get("request") or {}).get("style", "")
        if ev == "favourite":
            self._update(it, favourite=not it.get("favourite"))
            if not it.get("favourite"):
                record(self.w.s.output_dir, "favourite", style)
        else:
            self._update(it, rating=ev)
            record(self.w.s.output_dir, ev, style)
        self.refresh_library()
        self.show_taste()

    def download(self, it, path):
        from .taste import record

        if save_copy(self, path):
            record(self.w.s.output_dir, "download", it.get("caption") or (it.get("request") or {}).get("style", ""))

    def save_lyrics(self, it):
        r = it.get("request") or {}
        sheet = r.get("sheet") or {}
        text = Sheet.from_dict(sheet).to_text() if sheet.get("parts") else r.get("lyrics", "")
        if not text.strip():
            QMessageBox.information(self, "Lyrics", "This take is instrumental.")
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Save lyrics", str(Path.home() / "Downloads" /
                                                                       f"{it.get('title', 'lyrics')}.txt"), "*.txt")
        if dest:
            Path(dest).write_text(text, encoding="utf-8")

    def reuse(self, it):
        r = it.get("request") or {}
        self.title.setText(r.get("title", ""))
        self.style.setPlainText(r.get("style", ""))
        self.bpm.setValue(int(r.get("bpm") or 0))
        self.duration.setValue(int(r.get("duration") or 150))
        self.seed.setValue(int(it.get("seed") or -1))
        sh = r.get("sheet") or {}
        if sh.get("parts"):
            self.load_sheet(Sheet.from_dict(sh))
            self.instrumental.setChecked(False)
        else:
            self.instrumental.setChecked(r.get("language") == "instrumental")

    def reroll(self, it):
        from .taste import record

        record(self.w.s.output_dir, "reroll", it.get("caption") or "")
        self.reuse(it)
        self.seed.setValue(-1)
        self.create()

    def remix(self, it):
        dlg = QDialog(self)
        dlg.setWindowTitle("Remix")
        lay = QVBoxLayout(dlg)
        mode = QComboBox()
        mode.addItem("Cover — same song, new sound", "cover")
        mode.addItem("Repaint a part", "repaint")
        mode.addItem("Extend", "extend")
        lay.addWidget(mode)
        style = QPlainTextEdit((it.get("request") or {}).get("style", ""))
        style.setFixedHeight(80)
        lay.addWidget(_label("New sound", "sub"))
        lay.addWidget(style)
        row = QHBoxLayout()
        row.addWidget(_label("Keep of the original", "sub"))
        strength = QSlider(Qt.Horizontal)
        strength.setRange(10, 95)
        strength.setValue(60)
        row.addWidget(strength)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        a, b = QDoubleSpinBox(), QDoubleSpinBox()
        for x in (a, b):
            x.setRange(0, 600)
            x.setSuffix(" s")
        b.setValue(30)
        row2.addWidget(_label("Repaint from", "sub"))
        row2.addWidget(a)
        row2.addWidget(_label("to", "sub"))
        row2.addWidget(b)
        lay.addLayout(row2)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        r = ms.MusicRequest(**{k: v for k, v in (it.get("request") or {}).items()
                               if k in ms.MusicRequest.__dataclass_fields__})
        r.mode, r.style = mode.currentData(), style.toPlainText().strip() or r.style
        r.source_audio = (it.get("files") or {}).get("wav", "")
        r.cover_strength, r.repaint_start, r.repaint_end = strength.value() / 100, a.value(), b.value()
        r.title = f"{it.get('title')} ({mode.currentText().split(' —')[0].lower()})"
        out = self.w.s.output_dir
        self.run(lambda p: ms.generate(r, out, p), self.on_created, "Remixing…")

    def recast(self, it):
        from .casting import cast

        sheet = (it.get("request") or {}).get("sheet") or {}
        if not sheet.get("parts"):
            QMessageBox.information(self, "Re-cast", "This take has no song sheet (it was instrumental or made in an "
                                    "older version).")
            return
        f = it.get("files") or {}
        stem = Path(f["wav"]).with_name(Path(f["wav"]).stem + " (cast)")

        def done(res, err):
            self.finish()
            if err:
                QMessageBox.warning(self, "Re-cast", err)
                return
            f.update(cast_wav=res["wav"], cast_mp3=res["mp3"], cast_note=res["note"])
            self._update(it, files=f)
            self.status.setText(res["note"])
            self.refresh_library()

        self.run(lambda p: cast(f["wav"], Sheet.from_dict(sheet), stem, p), done, "Casting the singers…")

    def sing_as(self, it):
        from . import voicelab

        voices = [cv for cv in voicelab.library() if cv.consent_id]
        if not voices:
            QMessageBox.information(self, "Sing it in my voice",
                                    "Create a custom voice in Voice Studio › Voice Lab first (with its consent record).")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Sing it in my voice")
        lay = QVBoxLayout(dlg)
        who = QComboBox()
        for cv in voices:
            who.addItem(f"{cv.name}  ·  {cv.owner or cv.character}", cv.id)
        lay.addWidget(who)
        like = QSlider(Qt.Horizontal)
        like.setRange(0, 100)
        like.setValue(70)
        lay.addWidget(_label("Likeness", "sub"))
        lay.addWidget(like)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        vid, k = who.currentData(), like.value() / 100
        wav = (it.get("files") or {}).get("wav", "")

        def done(res, err):
            self.finish()
            if err:
                QMessageBox.warning(self, "Sing it in my voice", err)
                return
            vers = list(it.get("versions") or []) + [res]
            self._update(it, versions=vers)
            self.refresh_library()
            Media.get().load(res["wav"], f"{it.get('title')} — sung by {res['voice']}", "Song")

        self.run(lambda p: ms.sing_as(wav, vid, p, tau=0.45 - 0.3 * k, keep_original=0.25 * (1 - k)), done,
                 "Singing it in your voice…")

    def stems(self, it):
        wav = (it.get("files") or {}).get("wav", "")

        def done(res, err):
            self.finish()
            if err:
                QMessageBox.warning(self, "Stems", err)
                return
            f = dict(it.get("files") or {})
            f.update(vocals=res.get("vocals", ""), instrumental=res.get("instrumental", ""))
            self._update(it, files=f)
            self.refresh_library()
            self.status.setText("Stems ready — in the Download menu of the take.")

        self.run(lambda p: ms.separate_stems(wav, p), done, "Separating vocals and instrumental…")

    def use_as_bed(self, it):
        from .taste import record

        record(self.w.s.output_dir, "bed", it.get("caption") or "")
        self.w.go("voiceover")
        self.w.vo.music_mode.button(2).click()
        self.w.vo.fill_songs()
        i = self.w.vo.songs.findData((it.get("files") or {}).get("wav", ""))
        if i >= 0:
            self.w.vo.songs.setCurrentIndex(i)
