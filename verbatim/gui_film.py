# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Feature Film: dub a Hollywood or Bollywood film into another language in each actor's own voice, on the
exact timeline, with lip-sync — on this Mac/PC up to 25 minutes, longer on a 40-core-GPU Mac, an NVIDIA PC or
the Cloud GPU. Every actor's voice is used only after a rights confirmation is recorded."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QRadioButton, QScrollArea,
                               QVBoxLayout, QWidget)

from . import ui_theme as th
from .gui_player import Media, fmt, save_copy
from .gui_video import LANGS, FilmCard


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
        self.stop = False

    def run(self):
        try:
            self.done.emit(self.fn(lambda f, m: self.progress.emit(float(f), str(m)), lambda: self.stop), "")
        except Exception as exc:
            self.done.emit(None, f"{type(exc).__name__}: {exc}")


class ActorRow(QFrame):
    def __init__(self, page, actor: dict, idx: int):
        super().__init__()
        self.page, self.actor = page, actor
        self.setObjectName("card2")
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(10)
        play = QPushButton()
        play.setObjectName("playBtn")
        play.setStyleSheet("min-width:34px;max-width:34px;min-height:34px;max-height:34px;border-radius:17px;")
        play.setIcon(th.icon("play", _t()["bg"], 14, weight="fill"))
        play.setToolTip("Hear this actor")
        s, e = actor["sample"]
        play.clicked.connect(lambda: Media.get().load(page.video, f"{actor['speaker']} — sample", "Feature film",
                                                       start=max(0.0, s - 0.2), end=e + 0.3))
        h.addWidget(play)
        info = QVBoxLayout()
        info.setSpacing(1)
        self.name = QLineEdit()
        self.name.setPlaceholderText(f"Actor name ({actor['speaker']})")
        info.addWidget(self.name)
        info.addWidget(_label(f"{actor['lines']} lines · {fmt(int(actor['seconds'] * 1000))} on screen · "
                              f"“{actor['text'][:60]}”", "hint"))
        h.addLayout(info, 1)
        self.voice = QComboBox()
        self.voice.addItem("Their own voice (cloned)", "")
        from . import tts

        for v in tts.voices_for(page.first_lang(), extended=True)[:40]:
            self.voice.addItem(f"{v.name} · {v.gender}", v.id)
        self.voice.setMinimumWidth(230)
        h.addWidget(self.voice)


class FeatureFilm(QWidget):
    log = Signal(str)

    def __init__(self, window):
        super().__init__()
        self.w = window
        self.thread = None
        self.video = ""
        self.analysis = None
        self.actor_rows: list[ActorRow] = []
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)
        h.addWidget(self._left(), 1)
        h.addWidget(self._right())

    # ------------------------------------------------------------ left: film, actors, results
    def _left(self):
        c = _card()
        outer = QVBoxLayout(c)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 8, 0)
        v.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(_label("1 · The film", "h2"))
        top.addStretch()
        b = QPushButton("Choose film…")
        b.setObjectName("ghost")
        b.clicked.connect(self.choose)
        top.addWidget(b)
        v.addLayout(top)
        self.film = FilmCard()
        self.film.setMinimumHeight(240)
        self.film.dropped.connect(self.set_video)
        v.addWidget(self.film)
        self.gate = _label("", "hint", wrap=True)
        v.addWidget(self.gate)
        row = QHBoxLayout()
        row.addWidget(_label("2 · The actors", "h2"))
        row.addStretch()
        self.analyse_btn = QPushButton("  Find the actors")
        self.analyse_btn.setObjectName("primary")
        self.analyse_btn.setIcon(th.icon("users", "#FFFFFF", 16))
        self.analyse_btn.clicked.connect(self.analyse)
        row.addWidget(self.analyse_btn)
        v.addLayout(row)
        v.addWidget(_label("VERBATIM listens to the film, separates every speaking actor, and lets you hear each one. "
                           "Name them, and choose their own cloned voice (default) or another voice.", "hint", wrap=True))
        self.actors = QVBoxLayout()
        self.actors.setSpacing(8)
        v.addLayout(self.actors)
        v.addWidget(_label("3 · Languages", "h2"))
        grid = QGridLayout()
        grid.setSpacing(6)
        from .translate import LANG_NAMES

        self.lang_btns = {}
        for i, code in enumerate(LANGS):
            b = QPushButton(LANG_NAMES.get(code, code))
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setChecked(code == "hi")
            self.lang_btns[code] = b
            grid.addWidget(b, i // 8, i % 8)
        v.addLayout(grid)
        v.addWidget(_label("RESULTS", "kicker"))
        self.results = QVBoxLayout()
        self.results.setSpacing(8)
        v.addLayout(self.results)
        v.addStretch()
        sc.setWidget(inner)
        outer.addWidget(sc, 1)
        return c

    # ------------------------------------------------------------ right: rights, quality, readiness
    def _right(self):
        c = _card()
        c.setFixedWidth(420)
        outer = QVBoxLayout(c)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(10)
        v.addWidget(_label("Rights", "h2"))
        v.addWidget(_label("Cloning an actor's voice needs the rights holder's permission (studio, producer or the "
                           "actor). Your confirmation is recorded in the Consent register with this film.", "hint",
                           wrap=True))
        self.rights_by = QLineEdit()
        self.rights_by.setPlaceholderText("Rights confirmed by (your name)")
        v.addWidget(self.rights_by)
        self.rights_ok = QCheckBox("We hold the rights to dub this film")
        v.addWidget(self.rights_ok)
        v.addWidget(self._rule())
        v.addWidget(_label("Picture & sound", "h2"))
        self.keep_bg = QCheckBox("Keep the original music && effects")
        self.keep_bg.setChecked(True)
        v.addWidget(self.keep_bg)
        self.subs = QCheckBox("Subtitle track in the new language")
        self.subs.setChecked(True)
        v.addWidget(self.subs)
        v.addWidget(_label("Lip-sync", "sub"))
        self.lip = QButtonGroup(self)
        for i, (key, text) in enumerate([("auto", "On — best available"), ("local", "On — this computer only"),
                                         ("off", "Off — voice only")]):
            r = QRadioButton(text)
            r.key = key
            self.lip.addButton(r, i)
            v.addWidget(r)
        self.lip.button(0).setChecked(True)
        self.translator = QComboBox()
        self.translator.addItem("Translate offline (TranslateGemma)", "translategemma")
        self.translator.addItem("Translate with Claude (best for film dialogue)", "claude")
        v.addWidget(self.translator)
        self.quality = QComboBox()
        self.quality.addItem("Studio quality voices", "studio")
        self.quality.addItem("Standard (faster)", "standard")
        v.addWidget(self.quality)
        v.addWidget(self._rule())
        v.addWidget(_label("Ready on this computer?", "h2"))
        self.ready = QVBoxLayout()
        self.ready.setSpacing(6)
        v.addLayout(self.ready)
        v.addStretch()
        sc.setWidget(inner)
        outer.addWidget(sc, 1)
        self.status = _label("Choose a film to begin.", "hint", wrap=True)
        outer.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        outer.addWidget(self.bar)
        self.go = QPushButton("   Dub the film")
        self.go.setObjectName("start")
        self.go.setIcon(th.icon("film_reel", "#FFFFFF", 20, weight="fill"))
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

    # ------------------------------------------------------------ readiness
    def refresh(self):
        from . import lipsync, tts, tts_chatterbox
        from .cloud import active_for

        while self.ready.count():
            it = self.ready.takeAt(0)
            if it.layout():
                while it.layout().count():
                    x = it.layout().takeAt(0)
                    if x.widget():
                        x.widget().deleteLater()
            elif it.widget():
                it.widget().deleteLater()
        items = [("Voice cloning (Chatterbox)", tts_chatterbox.is_installed(), "cb",
                  f"{tts_chatterbox.SIZE_MB / 1000:.1f} GB"),
                 ("Tone colour (OpenVoice)", tts.openvoice_ready(), "op", "1.5 GB"),
                 ("Lip-sync on this computer", lipsync.installed(), "lip", f"{lipsync.SIZE_MB} MB"),
                 ("Cloud GPU (for long films)", active_for("lipsync"), "", "")]
        for text, ok, key, size in items:
            row = QHBoxLayout()
            row.addWidget(_label(("✓  " if ok else "○  ") + text, "sub" if ok else "hint"), 1)
            if not ok and key:
                b = QPushButton(f"Get · {size}")
                b.setObjectName("dl")
                b.clicked.connect(lambda _=False, k=key: self.install(k))
                row.addWidget(b)
            self.ready.addLayout(row)
        self.update_gate()

    def install(self, key: str):
        def work(progress, _stop):
            if key == "lip":
                from . import lipsync

                lipsync.ensure(progress)
            elif key == "cb":
                from . import tts

                tts.ensure("cb", progress)
            elif key == "op":
                from .music_studio import ensure_tone_engine

                ensure_tone_engine(progress)
            return {}

        self.run(work, lambda r, e: (self.finish(), self.refresh(),
                                     QMessageBox.warning(self, "Download", e) if e else None), "Downloading…")

    def update_gate(self):
        if not self.video:
            self.gate.setText("")
            return
        from . import lipsync
        from .cloud import active_for

        dur = getattr(self, "duration", 0.0)
        hw = getattr(self, "hw", None) or lipsync.hardware()
        self.hw = hw
        lim = lipsync.allowed_minutes(hw, cloud=active_for("lipsync"))
        where = ("Cloud GPU" if active_for("lipsync") else f"{hw.get('gpu_cores')}-core GPU" if hw.get("gpu_cores")
                 else "NVIDIA GPU" if hw.get("nvidia") else "this computer")
        if dur / 60 > lim:
            self.gate.setText(f"⚠  This film is {dur / 60:.0f} min. Lip-sync on {where} works up to {lim:.0f} min — "
                              "set up the Cloud GPU, use a 40-core-GPU Mac, or turn lip-sync off. Dubbing itself has "
                              "no limit.")
        else:
            est = dur * 25 / 8 / 60          # ~8 fps locally
            self.gate.setText(f"✓  {dur / 60:.1f} min — fits on {where}. Lip-sync here takes about "
                              f"{max(1, round(est))} min; voices and translation add to that.")

    # ------------------------------------------------------------ film + actors
    def choose(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose the film", str(Path.home() / "Movies"),
                                           "Video (*.mp4 *.mov *.mkv *.m4v *.avi *.webm *.mxf)")
        if p:
            self.set_video(p)

    def set_video(self, path: str):
        from .gui_video import VideoStudio

        self.video = path
        VideoStudio.set_video(self, path)          # same still + slate as Video Localise
        try:
            from .audio import probe

            self.duration = float(probe(Path(path)).duration or 0)
        except Exception:
            self.duration = 0.0
        self.analysis = None
        self.clear_actors()
        self.update_gate()
        self.status.setText("Now press Find the actors.")

    def first_lang(self) -> str:
        return next((k for k, b in self.lang_btns.items() if b.isChecked()), "hi")

    def clear_actors(self):
        while self.actors.count():
            it = self.actors.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.actor_rows = []

    def analyse(self):
        if not self.video:
            QMessageBox.information(self, "Film", "Choose a film first.")
            return
        from .localise import analyse

        settings = copy.deepcopy(self.w.collect_settings())
        video = self.video

        def done(res, err):
            self.finish()
            if err:
                QMessageBox.warning(self, "Find the actors", err)
                return
            self.analysis = res
            self.clear_actors()
            for i, a in enumerate(res["actors"]):
                row = ActorRow(self, a, i)
                self.actor_rows.append(row)
                self.actors.addWidget(row)
            self.status.setText(f"{len(res['actors'])} speaking actor(s) found — name them, pick voices, then Dub "
                                "the film.")

        self.run(lambda p, s: analyse(video, settings, p), done, "Listening to the film…")

    # ------------------------------------------------------------ run
    def run(self, fn, done, text):
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, "Busy", "Feature Film is still working.")
            return
        from . import qt_workers
        from .gui_shell import track

        self.go.setEnabled(False)
        self.analyse_btn.setEnabled(False)
        self.bar.setVisible(True)
        self.status.setText(text)
        self.worker = _Job(fn)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(done)
        track(self.w, self.worker, text.rstrip("…. "))
        self.thread = qt_workers.start(self.worker, self.worker.run, [self.worker.done])

    def on_progress(self, f, m):
        self.bar.setValue(int(1000 * max(0.0, min(1.0, f))))
        self.status.setText(m)
        self.w.mast.ruler.set_progress(f)

    def finish(self):
        self.go.setEnabled(True)
        self.analyse_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.bar.setVisible(False)
        self.w.mast.ruler.set_progress(None)

    def stop(self):
        if getattr(self, "worker", None):
            self.worker.stop = True
            self.status.setText("Stopping after the current language…")

    def start(self):
        from .localise import LocaliseRequest, run

        if not self.video:
            QMessageBox.information(self, "Film", "Choose a film first.")
            return
        langs = [k for k, b in self.lang_btns.items() if b.isChecked()]
        if not langs:
            QMessageBox.information(self, "Languages", "Tick at least one language.")
            return
        own = any(not r.voice.currentData() for r in self.actor_rows) or not self.actor_rows
        if own and (not self.rights_ok.isChecked() or not self.rights_by.text().strip()):
            QMessageBox.information(self, "Rights", "Confirm the rights and type who confirmed them — or give every "
                                    "actor another voice.")
            return
        lip = self.lip.checkedButton().key
        if lip != "off":
            from . import lipsync
            from .cloud import active_for

            lim = lipsync.allowed_minutes(getattr(self, "hw", None), cloud=active_for("lipsync"))
            if getattr(self, "duration", 0) / 60 > lim:
                QMessageBox.information(self, "Lip-sync", self.gate.text())
                return
        names = {r.actor["speaker"]: r.name.text().strip() for r in self.actor_rows if r.name.text().strip()}
        voices = {r.actor["speaker"]: r.voice.currentData() for r in self.actor_rows if r.voice.currentData()}
        req = LocaliseRequest(video=self.video, languages=langs, voice_mode="own" if own else "studio",
                              consent_person=self.rights_by.text().strip(), translator=self.translator.currentData(),
                              direct=True, keep_background=self.keep_bg.isChecked(),
                              subtitles_soft=self.subs.isChecked(), lipsync=lip != "off",
                              lipsync_mode="auto" if lip == "auto" else "local", quality=self.quality.currentData(),
                              voices=voices, names=names, kind="film",
                              transcript=(self.analysis or {}).get("transcript", ""))
        settings = copy.deepcopy(self.w.collect_settings())
        self.stop_btn.setEnabled(True)
        self.run(lambda p, stop: run(req, settings, p, stop), self.on_done, f"Dubbing {Path(self.video).name}…")
        self.log.emit(f"Feature Film: {Path(self.video).name} → {', '.join(langs)}")

    def on_done(self, res, err):
        self.finish()
        if err:
            self.status.setText("Stopped — " + err)
            QMessageBox.warning(self, "Feature Film", err)
            return
        from .translate import LANG_NAMES

        while self.results.count():
            it = self.results.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        from .gui_shell import ItemRow
        from .library import Item

        for code, out in (res.get("results") or {}).items():
            files = {k: v for k, v in {"Film (MP4)": out.get("film", ""), "Lip-synced (MP4)": out.get("lipsync", ""),
                                       "Dialogue (WAV)": out.get("voice", ""), "Subtitles (SRT)": out.get("srt", "")
                                       }.items() if v and Path(v).exists()}
            play = files.get("Lip-synced (MP4)") or files.get("Film (MP4)") or ""
            it = Item("film", f"{Path(self.video).stem} — {LANG_NAMES.get(code, code)}",
                      "; ".join(out.get("notes", []))[:120] or "Feature film", "", 0.0, play, files,
                      str(Path(play).parent) if play else "")
            self.results.addWidget(ItemRow(it, lambda x: Media.get().load(x.play, x.title, "Feature film")))
        self.status.setText("Done — play each language below, or download it.")
