# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Module 03 — Music Studio page: compose (left), your library of takes (centre), engine status (top)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QScrollArea, QSlider, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import music_studio as ms


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

    def run(self):
        try:
            self.done.emit(self.fn(lambda f, m: self.progress.emit(float(f), str(m))), "")
        except Exception as exc:
            self.done.emit(None, f"{type(exc).__name__}: {exc}")


class Dial(QWidget):
    """Labelled 0–100 slider (Suno-style dial)."""

    def __init__(self, name: str, left: str, right: str, value: int, tip: str = ""):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        top = QHBoxLayout()
        top.addWidget(_label(name, "sub"))
        top.addStretch()
        self.val = _label(str(value), "hint")
        top.addWidget(self.val)
        v.addLayout(top)
        self.s = QSlider(Qt.Horizontal)
        self.s.setRange(0, 100)
        self.s.setValue(value)
        self.s.valueChanged.connect(lambda x: self.val.setText(str(x)))
        v.addWidget(self.s)
        ends = QHBoxLayout()
        ends.addWidget(_label(left, "hint"))
        ends.addStretch()
        ends.addWidget(_label(right, "hint"))
        v.addLayout(ends)
        self.setToolTip(tip)

    def value(self) -> int:
        return self.s.value()


class MusicStudio(QWidget):
    log = Signal(str)

    def __init__(self, window):
        super().__init__()
        self.w = window
        self.thread = None
        self.player = None
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)
        h.addWidget(self._composer())
        h.addWidget(self._library(), 1)
        self.refresh_library()

    # ------------------------------------------------------------ composer (left)
    def _composer(self):
        c = _card()
        c.setFixedWidth(440)
        outer = QVBoxLayout(c)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(_label("Compose", "h2"))
        top.addStretch()
        seg = QFrame()
        seg.setObjectName("segBar")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(4, 4, 4, 4)
        self.mode = QButtonGroup(self)
        for i, name in enumerate(["Simple", "Custom", "Remix"]):
            b = QPushButton(name)
            b.setObjectName("seg")
            b.setCheckable(True)
            self.mode.addButton(b, i)
            sl.addWidget(b)
        self.mode.button(1).setChecked(True)
        self.mode.idClicked.connect(self.on_mode)
        top.addWidget(seg)
        outer.addLayout(top)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(2, 0, 6, 0)
        v.setSpacing(10)
        self.title = QLineEdit()
        self.title.setPlaceholderText("Track title")
        v.addWidget(self.title)
        # simple
        self.simple_box = QWidget()
        sv = QVBoxLayout(self.simple_box)
        sv.setContentsMargins(0, 0, 0, 0)
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText("Describe the song — e.g. “An uplifting Hindi wedding song with dhol, "
                                            "a female lead and a big singalong chorus”. VERBATIM writes the style, "
                                            "lyrics and structure for you.")
        self.description.setMaximumHeight(110)
        sv.addWidget(self.description)
        v.addWidget(self.simple_box)
        # custom
        self.custom_box = QWidget()
        cv = QVBoxLayout(self.custom_box)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(_label("Style", "sub"))
        row.addStretch()
        b = QPushButton("Prompt library…")
        b.setObjectName("link")
        b.clicked.connect(self.pick_prompt)
        row.addWidget(b)
        cv.addLayout(row)
        self.style = QPlainTextEdit()
        self.style.setPlaceholderText("Genre, mood, instruments, production — e.g. “cinematic corporate, warm piano, "
                                      "swelling strings, hopeful, builds to a confident finale”")
        self.style.setMaximumHeight(90)
        cv.addWidget(self.style)
        row = QHBoxLayout()
        row.addWidget(_label("Lyrics", "sub"))
        row.addStretch()
        self.instrumental = QCheckBox("Instrumental")
        self.instrumental.setChecked(True)
        self.instrumental.toggled.connect(lambda on: (self.lyrics.setEnabled(not on), self.tags_row.setEnabled(not on)))
        row.addWidget(self.instrumental)
        cv.addLayout(row)
        from PySide6.QtWidgets import QGridLayout

        tags = QGridLayout()
        tags.setSpacing(4)
        tags.setContentsMargins(0, 0, 0, 0)
        for k, t in enumerate(("[Intro]", "[Verse]", "[Pre-Chorus]", "[Chorus]", "[Bridge]", "[Drop]", "[Solo]",
                               "[Outro]")):
            tb = QPushButton(t)
            tb.setObjectName("chip")
            tb.clicked.connect(lambda _=False, t=t: self.lyrics.insertPlainText(("\n" if self.lyrics.toPlainText() else "")
                                                                                 + t + "\n"))
            tags.addWidget(tb, k // 4, k % 4)
        self.tags_row = QWidget()
        self.tags_row.setLayout(tags)
        self.tags_row.setEnabled(False)
        cv.addWidget(self.tags_row)
        self.lyrics = QPlainTextEdit()
        self.lyrics.setPlaceholderText("[Verse]\nWrite your lyrics with section tags…\n\n[Chorus]\n…")
        self.lyrics.setEnabled(False)
        self.lyrics.setMinimumHeight(120)
        cv.addWidget(self.lyrics)
        v.addWidget(self.custom_box)
        # remix
        self.remix_box = QWidget()
        rv = QVBoxLayout(self.remix_box)
        rv.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.src = QLineEdit()
        self.src.setReadOnly(True)
        self.src.setPlaceholderText("Source track (yours or a take from the library)")
        row.addWidget(self.src, 1)
        b = QPushButton("Choose…")
        b.clicked.connect(lambda: self.src.setText(QFileDialog.getOpenFileName(
            self, "Source track", str(Path.home()), "Audio (*.wav *.mp3 *.flac *.m4a *.aac)")[0] or self.src.text()))
        row.addWidget(b)
        rv.addLayout(row)
        self.remix_kind = QComboBox()
        self.remix_kind.addItem("Cover — same song, new style", "cover")
        self.remix_kind.addItem("Repaint — redo a section", "repaint")
        self.remix_kind.addItem("Extend — continue the track (base model)", "extend")
        rv.addWidget(self.remix_kind)
        row = QHBoxLayout()
        row.addWidget(_label("Section", "sub"))
        self.rs, self.re_ = QDoubleSpinBox(), QDoubleSpinBox()
        for sp in (self.rs, self.re_):
            sp.setRange(-1, 600)
            sp.setSuffix(" s")
        self.re_.setValue(-1)
        row.addWidget(self.rs)
        row.addWidget(_label("to", "hint"))
        row.addWidget(self.re_)
        rv.addLayout(row)
        self.cover_strength = Dial("Keep from the original", "loose", "close", 60,
                                   "How much of the source melody and structure to keep in a cover")
        rv.addWidget(self.cover_strength)
        v.addWidget(self.remix_box)
        # metadata
        g = QFormLayout()
        g.setHorizontalSpacing(10)
        self.lang = QComboBox()
        for k, name in ms.LANGS.items():
            if k != "instrumental":
                self.lang.addItem(name, k)
        self.lang.setCurrentIndex(max(0, self.lang.findData("en")))
        g.addRow(_label("Vocals in", "sub"), self.lang)
        mrow = QHBoxLayout()
        self.bpm = QSpinBox()
        self.bpm.setRange(0, 300)
        self.bpm.setSpecialValueText("Auto")
        self.key = QComboBox()
        for k in ms.KEYS:
            self.key.addItem(k or "Auto key", k)
        self.ts = QComboBox()
        for k, n in ms.TIME_SIGS.items():
            self.ts.addItem(n, k)
        mrow.addWidget(self.bpm)
        mrow.addWidget(self.key, 1)
        mrow.addWidget(self.ts)
        g.addRow(_label("BPM · key", "sub"), mrow)
        drow = QHBoxLayout()
        self.duration = QSpinBox()
        self.duration.setRange(10, 600)
        self.duration.setValue(60)
        self.duration.setSuffix(" s")
        self.takes = QSpinBox()
        self.takes.setRange(1, 4)
        self.takes.setValue(2)
        self.takes.setSuffix(" takes")
        drow.addWidget(self.duration)
        drow.addWidget(self.takes)
        g.addRow(_label("Length", "sub"), drow)
        v.addLayout(g)
        # dials
        v.addWidget(_label("Creative controls", "h3"))
        self.influence = Dial("Style influence", "loose", "strict", 70, "How closely the music follows your style")
        self.weird = Dial("Weirdness", "safe", "wild", 35, "How adventurous the composition is")
        self.variety = Dial("Variety", "exact", "reinterpret", 0, "Let the song planner rewrite your style prompt")
        for d in (self.influence, self.weird, self.variety):
            v.addWidget(d)
        self.exclude = QLineEdit()
        self.exclude.setPlaceholderText("Exclude — e.g. male vocals, electric guitar, drums")
        v.addWidget(self.exclude)
        row = QHBoxLayout()
        self.max_mode = QCheckBox("Max mode (richer, slower)")
        row.addWidget(self.max_mode)
        row.addStretch()
        row.addWidget(_label("Seed", "sub"))
        self.seed = QSpinBox()
        self.seed.setRange(-1, 2 ** 31 - 1)
        self.seed.setSpecialValueText("Random")
        self.seed.setValue(-1)
        row.addWidget(self.seed)
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(_label("Master to", "sub"))
        self.lufs = QComboBox()
        for t, x in (("Streaming / social (−14 LUFS)", -14.0), ("Broadcast (−23 LUFS)", -23.0),
                     ("Under a voiceover (−18 LUFS)", -18.0)):
            self.lufs.addItem(t, x)
        row.addWidget(self.lufs, 1)
        v.addLayout(row)
        b = QPushButton("  Score a voiceover…")
        self.w.icons.set(b, "mic2", "ink", 15)
        b.setToolTip("Writes music to the exact length and emotional arc of a Voice Studio voiceover, then mixes it under "
                     "the voice.")
        b.clicked.connect(self.score_voiceover)
        v.addWidget(b)
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
        self.go = QPushButton("   Create music")
        self.go.setObjectName("start")
        self.go.setCursor(Qt.PointingHandCursor)
        self.w.icons.set(self.go, "sparkle", "#FFFFFF", 20)
        self.go.clicked.connect(self.create)
        outer.addWidget(self.go)
        self.voice_job = ""
        self.on_mode(1)
        return c

    def on_mode(self, i: int):
        self.simple_box.setVisible(i == 0)
        self.custom_box.setVisible(i == 1)
        self.remix_box.setVisible(i == 2)

    # ------------------------------------------------------------ library (centre)
    def _library(self):
        c = _card()
        v = QVBoxLayout(c)
        v.setContentsMargins(22, 18, 22, 14)
        v.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(_label("Music Studio", "h1"))
        top.addSpacing(10)

        top.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search your music…")
        self.search.setFixedWidth(200)
        self.search.textChanged.connect(self.refresh_library)
        top.addWidget(self.search)
        self.fav_only = QCheckBox("Favourites")
        self.fav_only.toggled.connect(self.refresh_library)
        top.addWidget(self.fav_only)
        v.addLayout(top)
        self.engine_row = QHBoxLayout()
        v.addLayout(self.engine_row)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["", "Title", "Take", "Length", "BPM · Key", "Style", "Created"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.cellDoubleClicked.connect(lambda r, c: self.play())
        v.addWidget(self.table, 1)
        self.empty = _label("Your music appears here. Describe a song on the left and press Create music — every take is "
                            "kept with its seed so you can re-roll, remix or reuse it.", "hint", wrap=True)
        self.empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty)
        acts = QHBoxLayout()
        for text, fn, tip in (("▶  Play", self.play, "Play the selected take"),
                              ("■", self.stop, "Stop"),
                              ("♥  Favourite", self.favourite, "Keep this take"),
                              ("Re-roll", self.reroll, "Same settings, new seed"),
                              ("Reuse", self.reuse, "Load this take's settings into the composer"),
                              ("Remix…", self.remix, "Cover, repaint or extend this take"),
                              ("Stems", self.stems, "Separate vocals and instrumental"),
                              ("Use as voiceover bed", self.use_as_bed, "Send this take to Voice Studio as the music bed"),
                              ("Open folder", self.open_folder, "")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            acts.addWidget(b)
        acts.addStretch()
        v.addLayout(acts)
        self.fill_engines()
        return c

    def fill_engines(self):
        from . import runtimes

        while self.engine_row.count():
            it = self.engine_row.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().setParent(None)
        rt = runtimes.is_ready("music")
        mdl = (ms.checkpoints_root() / "checkpoints" / "acestep-v15-turbo").exists()
        ok = rt and mdl
        self.engine_row.addWidget(_label(("✓  Music engine ready — works offline." if ok else
                                          "○  The music engine installs once (about 10 GB, ACE-Step 1.5). After that "
                                          "everything runs on this computer."), "sub" if ok else "hint", wrap=True), 1)
        if not ok:
            b = QPushButton("Install music engine")
            b.clicked.connect(self.install)
            self.engine_row.addWidget(b)

    def items(self) -> list[dict]:
        return ms.load_history(self.w.s.output_dir)

    def refresh_library(self, *_):
        q = self.search.text().strip().lower() if hasattr(self, "search") else ""
        rows = [it for it in self.items() if (not q or q in (it.get("title", "") + " " + (it.get("caption") or "")).lower())
                and (not self.fav_only.isChecked() or it.get("favourite"))]
        self.rows = rows
        self.table.setRowCount(len(rows))
        for i, it in enumerate(rows):
            f = it.get("files", {})
            vals = ["♥" if it.get("favourite") else "", it.get("title", ""), str(it.get("take", "")),
                    f"{int(f.get('seconds', 0)) // 60}:{int(f.get('seconds', 0)) % 60:02d}",
                    f"{it.get('bpm') or '—'} · {it.get('key') or '—'}", (it.get("caption") or "")[:120],
                    (it.get("created") or "").replace("T", " ")[:16]]
            for j, val in enumerate(vals):
                self.table.setItem(i, j, QTableWidgetItem(val))
        self.empty.setVisible(not rows)
        self.table.setVisible(bool(rows))

    def selected(self) -> dict | None:
        r = self.table.selectionModel().selectedRows()
        return self.rows[r[0].row()] if r else None

    # ------------------------------------------------------------ actions
    def request(self) -> ms.MusicRequest:
        mode = {0: "simple", 1: "custom", 2: self.remix_kind.currentData()}[self.mode.checkedId()]
        return ms.MusicRequest(
            title=self.title.text().strip() or "Untitled", mode="score" if self.voice_job and mode == "custom" else mode,
            description=self.description.toPlainText().strip(), style=self.style.toPlainText().strip(),
            lyrics="" if self.instrumental.isChecked() else self.lyrics.toPlainText().strip(),
            language="instrumental" if self.instrumental.isChecked() and mode != "simple" else self.lang.currentData(),
            bpm=self.bpm.value() or None, key=self.key.currentData(), time_signature=self.ts.currentData(),
            duration=float(self.duration.value()), takes=self.takes.value(), seed=self.seed.value(),
            style_influence=self.influence.value(), weirdness=self.weird.value(), variety=self.variety.value(),
            exclude=self.exclude.text().strip(), max_mode=self.max_mode.isChecked(), source_audio=self.src.text(),
            cover_strength=self.cover_strength.value() / 100, repaint_start=self.rs.value(), repaint_end=self.re_.value(),
            master_lufs=self.lufs.currentData(), voice_job=self.voice_job)

    def run(self, fn, done, text):
        if self.thread and self.thread.isRunning():
            return
        self.go.setEnabled(False)
        self.bar.setVisible(True)
        self.status.setText(text)
        self.thread = QThread()
        self.worker = _Job(fn)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(done)
        self.worker.done.connect(self.thread.quit)
        self.thread.start()

    def on_progress(self, f, m):
        self.bar.setValue(int(1000 * max(0.0, min(1.0, f))))
        self.status.setText(m)

    def finish(self):
        self.go.setEnabled(True)
        self.bar.setVisible(False)

    def create(self):
        r = self.request()
        if r.mode == "simple" and not r.description:
            QMessageBox.information(self, "Describe the song", "Write a short description of the music first.")
            return
        if r.mode in ("custom", "score") and not r.style:
            QMessageBox.information(self, "Style", "Describe the style, or pick one from the Prompt library.")
            return
        if r.mode in ("cover", "repaint", "extend") and not r.source_audio:
            QMessageBox.information(self, "Source track", "Choose the track to remix.")
            return
        out = self.w.s.output_dir
        self.run(lambda p: ms.generate(r, out, p), self.on_created, "Composing…")

    def on_created(self, items, err):
        self.finish()
        if err:
            self.status.setText("Music failed — " + err)
            QMessageBox.warning(self, "Music Studio", err)
            return
        self.status.setText(f"{len(items)} take(s) ready.")
        self.log.emit(f"Music Studio: {len(items)} take(s) of “{items[0]['title']}”" if items else "Music Studio")
        self.voice_job = ""
        self.refresh_library()
        self.fill_engines()
        if items:
            self.table.selectRow(0)
            self.play()

    def install(self):
        def work(progress):
            from . import runtimes

            runtimes.ensure("music", lambda f, m: progress(0.4 * f, m))
            ms.ensure_models(lambda f, m: progress(0.4 + 0.6 * f, m))
            return True

        self.run(work, lambda ok, err: (self.finish(), self.fill_engines(),
                                        QMessageBox.warning(self, "Install failed", err) if err
                                        else self.status.setText("Music engine installed — works offline now.")),
                 "Installing the music engine (one time)…")

    def pick_prompt(self):
        lib = ms.prompt_library()
        dlg = QDialog(self)
        dlg.setWindowTitle("Prompt library — 299 tested styles + Infinite Story presets")
        dlg.resize(760, 560)
        v = QVBoxLayout(dlg)
        top = QHBoxLayout()
        q = QLineEdit()
        q.setPlaceholderText("Search: corporate, phonk, ballad, wedding…")
        genre = QComboBox()
        genre.addItem("All genres", "")
        for gname in sorted({p.get("genre") or "" for p in lib.values()}):
            if gname:
                genre.addItem(gname.replace("-", " ").title(), gname)
        top.addWidget(q, 1)
        top.addWidget(genre)
        v.addLayout(top)
        lst = QListWidget()
        v.addWidget(lst, 1)
        preview = _label("", "hint", wrap=True)
        v.addWidget(preview)

        def fill():
            lst.clear()
            for pid, p in sorted(lib.items(), key=lambda kv: (kv[1].get("useCase") != "Infinite Story preset",
                                                                kv[1].get("genre") or "", kv[1]["title"])):
                if genre.currentData() and p.get("genre") != genre.currentData():
                    continue
                if q.text() and q.text().lower() not in (p["title"] + p["prompt"] + (p.get("useCase") or "")).lower():
                    continue
                it = QListWidgetItem(f"{p['title']}   ·   {(p.get('genre') or '').replace('-', ' ')}")
                it.setData(Qt.UserRole, pid)
                lst.addItem(it)

        q.textChanged.connect(fill)
        genre.currentIndexChanged.connect(fill)
        lst.currentItemChanged.connect(lambda it, _p: preview.setText(lib[it.data(Qt.UserRole)]["prompt"] if it else ""))
        fill()
        btns = QHBoxLayout()
        btns.addStretch()
        cancel, ok = QPushButton("Cancel"), QPushButton("Use this style")
        cancel.clicked.connect(dlg.reject)
        ok.clicked.connect(dlg.accept)
        lst.itemDoubleClicked.connect(lambda _: dlg.accept())
        btns.addWidget(cancel)
        btns.addWidget(ok)
        v.addLayout(btns)
        if dlg.exec() == QDialog.Accepted and lst.currentItem():
            p = lib[lst.currentItem().data(Qt.UserRole)]
            self.style.setPlainText(p["prompt"])
            if p.get("bpm"):
                self.bpm.setValue(int(p["bpm"]))
            if not self.title.text():
                self.title.setText(p["title"])

    def score_voiceover(self):
        start = str(Path(self.w.s.output_dir))
        p, _ = QFileDialog.getOpenFileName(self, "Choose a Voice Studio voiceover", start, "Voiceover (*.voice.json)")
        if not p:
            return
        try:
            r = ms.score_for_voiceover(p, self.style.toPlainText())
        except Exception as exc:
            QMessageBox.warning(self, "Score a voiceover", str(exc))
            return
        self.voice_job = p
        self.mode.button(1).setChecked(True)
        self.on_mode(1)
        self.title.setText(r.title)
        self.style.setPlainText(r.style)
        self.instrumental.setChecked(True)
        self.bpm.setValue(int(r.bpm or 0))
        self.duration.setValue(int(round(r.duration)))
        self.lufs.setCurrentIndex(max(0, self.lufs.findData(-18.0)))
        self.status.setText(f"Brief written for a {int(r.duration)} s voiceover — adjust anything, then Create music. "
                            "The takes are mixed under the voice automatically.")

    def play(self):
        it = self.selected()
        if not it:
            return
        from .gui_editor import AudioPlayer

        f = it["files"].get("with_voice") or it["files"].get("wav")
        if self.player is None:
            self.player = AudioPlayer()
        err = self.player.play(Path(f), 0.0, 600.0)
        self.status.setText("Could not play: " + err if err else f"Playing “{it['title']}” take {it['take']}")

    def stop(self):
        if self.player:
            try:
                self.player.stop()
            except Exception:
                pass

    def favourite(self):
        it = self.selected()
        if not it:
            return
        items = self.items()
        for x in items:
            if x["id"] == it["id"]:
                x["favourite"] = not x.get("favourite")
        ms.save_history(self.w.s.output_dir, items)
        self.refresh_library()

    def reuse(self):
        it = self.selected()
        if not it:
            return
        r = it.get("request", {})
        self.title.setText(r.get("title", ""))
        self.style.setPlainText(r.get("style", ""))
        self.description.setPlainText(r.get("description", ""))
        self.lyrics.setPlainText(r.get("lyrics", ""))
        self.instrumental.setChecked(r.get("language") == "instrumental")
        self.bpm.setValue(int(r.get("bpm") or 0))
        self.duration.setValue(int(r.get("duration") or 60))
        self.seed.setValue(int(it.get("seed") or -1))
        self.mode.button(1).setChecked(True)
        self.on_mode(1)

    def reroll(self):
        it = self.selected()
        if not it:
            return
        self.reuse()
        self.seed.setValue(-1)
        self.create()

    def remix(self):
        it = self.selected()
        if not it:
            return
        self.src.setText(it["files"]["wav"])
        self.mode.button(2).setChecked(True)
        self.on_mode(2)
        self.title.setText(f"{it['title']} (remix)")

    def stems(self):
        it = self.selected()
        if not it:
            return
        self.run(lambda p: ms.separate_stems(it["files"]["wav"], p),
                 lambda res, err: (self.finish(), QMessageBox.warning(self, "Stems", err) if err else
                                   (self.status.setText("Stems saved next to the take."),
                                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(res["vocals"]).parent))))),
                 "Separating vocals and instrumental…")

    def use_as_bed(self):
        it = self.selected()
        if not it:
            return
        self.w.select_module(1)
        self.w.voice.music_file.setText(it["files"]["wav"])
        self.w.say(f"Music bed set to “{it['title']}” take {it['take']}")

    def open_folder(self):
        it = self.selected()
        p = Path(it["files"]["wav"]).parent if it else ms.library_dir(self.w.s.output_dir)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
