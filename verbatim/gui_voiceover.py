# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Voiceover Creator page: script → "Voice only" and "Voice + music", side by side, ready to play and download."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
                               QSlider, QVBoxLayout, QWidget)

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


class OutputCard(QFrame):
    """One result ("Voice only" / "Voice + music"): play in the player bar, download MP3 or WAV."""

    def __init__(self, title: str, glyph: str, seed: int):
        super().__init__()
        self.setObjectName("card2")
        self.title = title
        self.files: dict = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)
        top = QHBoxLayout()
        self.cover = Cover(54)
        self.cover.set(glyph, seed)
        top.addWidget(self.cover)
        info = QVBoxLayout()
        info.setSpacing(2)
        info.addWidget(_label(title, "tileTitle"))
        self.meta = _label("Not made yet", "hint")
        info.addWidget(self.meta)
        top.addLayout(info, 1)
        self.play = QPushButton()
        self.play.setObjectName("playBtn")
        self.play.setIcon(th.icon("play", _t()["bg"], 18, weight="fill"))
        self.play.clicked.connect(self.on_play)
        top.addWidget(self.play)
        v.addLayout(top)
        row = QHBoxLayout()
        self.mp3 = QPushButton("⬇  MP3")
        self.mp3.setObjectName("dl")
        self.mp3.clicked.connect(lambda: self.save("MP3"))
        self.wav = QPushButton("⬇  WAV")
        self.wav.setObjectName("dl")
        self.wav.clicked.connect(lambda: self.save("WAV"))
        self.folder = QPushButton("Show in folder")
        self.folder.setObjectName("link")
        self.folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.main()).parent))))
        row.addWidget(self.mp3)
        row.addWidget(self.wav)
        row.addStretch()
        row.addWidget(self.folder)
        v.addLayout(row)
        self.set({}, 0)

    def main(self) -> str:
        return self.files.get("MP3") or self.files.get("WAV") or ""

    def set(self, files: dict, seconds: float, note: str = ""):
        self.files = {k: v for k, v in files.items() if v and Path(v).exists()}
        ok = bool(self.files)
        for b in (self.play, self.mp3, self.wav, self.folder):
            b.setEnabled(ok)
        self.mp3.setEnabled("MP3" in self.files)
        self.wav.setEnabled("WAV" in self.files)
        self.meta.setText((f"{fmt(int(seconds * 1000))}  ·  {note}" if note else fmt(int(seconds * 1000))) if ok
                          else "Not made yet")

    def on_play(self):
        if self.main():
            Media.get().load(self.main(), self.title, "Voiceover")

    def save(self, kind: str):
        p = self.files.get(kind)
        if p:
            save_copy(self, p)


class VoiceoverCreator(QWidget):
    log = Signal(str)

    def __init__(self, window):
        super().__init__()
        self.w = window
        self.thread = None
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)
        h.addWidget(self._editor(), 1)
        h.addWidget(self._results())

    # ------------------------------------------------------------ left: script + choices
    def _editor(self):
        c = _card()
        outer = QVBoxLayout(c)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 8, 0)
        v.setSpacing(12)
        self.title = QLineEdit()
        self.title.setPlaceholderText("Title — e.g. “JK Cement 30 s brand film”")
        v.addWidget(self.title)
        self.script = QPlainTextEdit()
        self.script.setObjectName("script")
        self.script.setPlaceholderText("Write or paste your script.\n\nA blank line between paragraphs gives a longer, "
                                       "breathing pause — and the music swells there.")
        self.script.setMinimumHeight(220)
        self.script.textChanged.connect(self.count)
        v.addWidget(self.script, 2)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(_label("Language", "sub"))
        self.lang = QComboBox()
        from .translate import LANG_NAMES

        for code in ("en", "hi", "es", "fr", "de", "pt", "it", "ar", "ja", "zh", "ko", "ru", "ta", "te", "mr", "gu",
                     "kn", "ml", "pa", "ur", "he", "tr", "id", "bn"):
            self.lang.addItem(LANG_NAMES.get(code, code), code)
        self.lang.currentIndexChanged.connect(self.fill_voices)
        row.addWidget(self.lang)
        row.addWidget(_label("Voice", "sub"))
        self.voice = QComboBox()
        self.voice.setMinimumContentsLength(22)
        row.addWidget(self.voice, 1)
        self.counter = _label("", "hint")
        row.addWidget(self.counter)
        v.addLayout(row)
        v.addWidget(_label("STYLE", "kicker"))
        self.style_grid = QGridLayout()
        self.style_grid.setSpacing(8)
        v.addLayout(self.style_grid)
        srow = QHBoxLayout()
        learn = QPushButton("  Learn a style from audio…")
        learn.setObjectName("ghost")
        learn.setIcon(th.icon("magic", _t()["ink"], 16))
        learn.setToolTip("Give VERBATIM a reference voiceover — it measures pace, melody, pauses and tone and saves "
                         "it as a style you can reuse")
        learn.clicked.connect(self.learn)
        srow.addWidget(learn)
        self.style_about = _label("", "hint", wrap=True)
        srow.addWidget(self.style_about, 1)
        v.addLayout(srow)
        prow = QHBoxLayout()
        prow.addWidget(_label("Pace", "sub"))
        self.pace = QSlider(Qt.Horizontal)
        self.pace.setRange(80, 120)
        self.pace.setValue(100)
        self.pace_lab = _label("1.00×", "time")
        self.pace.valueChanged.connect(lambda x: self.pace_lab.setText(f"{x / 100:.2f}×"))
        prow.addWidget(self.pace, 1)
        prow.addWidget(self.pace_lab)
        v.addLayout(prow)
        v.addWidget(_label("MUSIC (FOR THE VOICE + MUSIC VERSION)", "kicker"))
        seg = QFrame()
        seg.setObjectName("segBar")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(4, 4, 4, 4)
        self.music_mode = QButtonGroup(self)
        for i, name in enumerate(["Compose a bed", "Use my track", "From my songs"]):
            b = QPushButton(name)
            b.setObjectName("seg")
            b.setCheckable(True)
            self.music_mode.addButton(b, i)
            sl.addWidget(b)
        self.music_mode.button(0).setChecked(True)
        self.music_mode.idClicked.connect(self.on_music_mode)
        v.addWidget(seg)
        mrow = QHBoxLayout()
        self.mood = QComboBox()
        from .beds import MOODS

        self.mood.addItem("Match the style", "")
        for m in MOODS:
            self.mood.addItem(m, m)
        mrow.addWidget(self.mood, 1)
        self.track = QLineEdit()
        self.track.setPlaceholderText("Choose a music file…")
        self.track.setReadOnly(True)
        mrow.addWidget(self.track, 1)
        self.pick = QPushButton("Choose…")
        self.pick.clicked.connect(self.choose_track)
        mrow.addWidget(self.pick)
        self.songs = QComboBox()
        mrow.addWidget(self.songs, 1)
        v.addLayout(mrow)
        lrow = QHBoxLayout()
        lrow.addWidget(_label("Music under the voice", "sub"))
        self.level = QSlider(Qt.Horizontal)
        self.level.setRange(-32, -10)
        self.level.setValue(-20)
        self.level_lab = _label("−20 dB", "time")
        self.level.valueChanged.connect(lambda x: self.level_lab.setText(f"{x} dB".replace("-", "−")))
        lrow.addWidget(self.level, 1)
        lrow.addWidget(self.level_lab)
        v.addLayout(lrow)
        v.addStretch()
        sc.setWidget(inner)
        outer.addWidget(sc, 1)
        self.go = QPushButton("   Create voiceover")
        self.go.setObjectName("start")
        self.go.setCursor(Qt.PointingHandCursor)
        self.go.setIcon(th.icon("mic_on", "#FFFFFF", 20, weight="fill"))
        self.go.clicked.connect(self.create)
        outer.addWidget(self.go)
        self.on_music_mode(0)
        return c

    # ------------------------------------------------------------ right: two results
    def _results(self):
        c = _card()
        c.setFixedWidth(420)
        v = QVBoxLayout(c)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)
        v.addWidget(_label("Your voiceover", "h2"))
        self.out_voice = OutputCard("Voice only", "mic_on", 0)
        self.out_music = OutputCard("Voice + music", "music", 1)
        v.addWidget(self.out_voice)
        v.addWidget(self.out_music)
        self.status = _label("Write a script, pick a voice and a style, then Create.", "hint", wrap=True)
        v.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        v.addWidget(self.bar)
        v.addWidget(_label("RECENT", "kicker"))
        self.recent = QVBoxLayout()
        self.recent.setSpacing(6)
        v.addLayout(self.recent)
        v.addStretch()
        return c

    # ------------------------------------------------------------ data
    def refresh(self):
        self.fill_voices()
        self.fill_styles()
        self.fill_songs()
        self.fill_recent()
        self.count()

    def fill_voices(self):
        from . import tts

        lang = self.lang.currentData() or "en"
        cur = self.voice.currentData()
        self.voice.clear()
        try:
            vs = tts.voices_for(lang)
        except Exception:
            vs = []
        for x in vs:
            tag = {"my": "your voice", "cb": "expressive", "az": "Azure", "el": "ElevenLabs"}.get(x.engine, "studio")
            self.voice.addItem(f"{x.name} · {x.gender} · {tag}", x.id)
        if cur:
            i = self.voice.findData(cur)
            if i >= 0:
                self.voice.setCurrentIndex(i)
        if not vs:
            self.voice.addItem("No voices for this language yet — download a voice pack in Voice Studio", "")

    def fill_styles(self):
        from .voiceover import styles

        while self.style_grid.count():
            it = self.style_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.style_group = QButtonGroup(self)
        cur = getattr(self, "style_name", "Warm narrator")
        for i, s in enumerate(styles()):
            b = QPushButton(s.name.replace("&", "&&") + ("  ✦" if s.reference else ""))
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setToolTip(s.about)
            b.setChecked(s.name == cur)
            b.clicked.connect(lambda _=False, s=s: self.pick_style(s))
            self.style_group.addButton(b)
            self.style_grid.addWidget(b, i // 4, i % 4)
        self.pick_style(next((s for s in styles() if s.name == cur), styles()[0]))

    def pick_style(self, s):
        self.style_name = s.name
        self.style_about.setText(f"{s.about}  ·  pace {s.speed:.2f}×, {s.emotion}, {s.fx}" if s.about else s.fx)

    def fill_songs(self):
        from .music_studio import load_history

        self.songs.clear()
        for it in load_history(self.w.s.output_dir):
            f = (it.get("files") or {}).get("wav")
            if f and Path(f).exists():
                self.songs.addItem(f"{it.get('title', 'Song')} — take {it.get('take', 1)}", f)
        if not self.songs.count():
            self.songs.addItem("No songs yet — make one in Music", "")

    def fill_recent(self):
        from .library import creator

        while self.recent.count():
            it = self.recent.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        items = creator(Path(self.w.s.output_dir))[:5]
        from .gui_shell import ItemRow

        for it in items:
            self.recent.addWidget(ItemRow(it, lambda x: Media.get().load(x.play, x.title, x.sub)))
        if not items:
            self.recent.addWidget(_label("Nothing yet.", "hint"))

    def count(self):
        words = len(self.script.toPlainText().split())
        self.counter.setText(f"{words} words · ~{fmt(int(words / 2.5 * 1000))}" if words else "")

    def on_music_mode(self, i: int):
        self.mood.setVisible(i == 0)
        self.track.setVisible(i == 1)
        self.pick.setVisible(i == 1)
        self.songs.setVisible(i == 2)

    def choose_track(self):
        p, _ = QFileDialog.getOpenFileName(self, "Music for the voiceover", str(Path.home() / "Music"),
                                           "Audio (*.mp3 *.wav *.m4a *.aac *.flac *.ogg)")
        if p:
            self.track.setText(p)

    def learn(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Reference voiceovers (one style each)", str(Path.home()),
                                                "Audio or video (*.mp3 *.wav *.m4a *.aac *.flac *.mp4 *.mov)")
        if not paths:
            return
        from .voiceover import learn_style

        made = []
        for p in paths:
            name, ok = QInputDialog.getText(self, "Name this style", f"Style name for {Path(p).name}:",
                                            text=Path(p).stem[:40])
            if not ok:
                continue
            try:
                made.append(learn_style(p, name.strip() or Path(p).stem))
            except Exception as exc:
                QMessageBox.warning(self, "Could not learn the style", f"{Path(p).name}: {exc}")
        if made:
            self.style_name = made[-1].name
            self.fill_styles()
            self.status.setText("Learned: " + ", ".join(s.name for s in made) + " — marked ✦.")
            self.log.emit("Voiceover styles learned: " + ", ".join(s.name for s in made))

    # ------------------------------------------------------------ create
    def create(self):
        if self.thread and self.thread.isRunning():
            return
        from .voiceover import Request, create

        script = self.script.toPlainText().strip()
        if not script:
            QMessageBox.information(self, "Script", "Write or paste the script first.")
            return
        if not self.voice.currentData():
            QMessageBox.information(self, "Voice", "No voice is available for this language yet.")
            return
        mode = self.music_mode.checkedId()
        mfile = self.track.text() if mode == 1 else (self.songs.currentData() or "") if mode == 2 else ""
        if mode in (1, 2) and not mfile:
            QMessageBox.information(self, "Music", "Choose the music first (or pick Compose a bed).")
            return
        req = Request(script=script, title=self.title.text().strip() or script.split("\n")[0][:40],
                      lang=self.lang.currentData(), voice=self.voice.currentData(),
                      voice_name=self.voice.currentText().split(" · ")[0], style=self.style_name,
                      pace=self.pace.value() / 100, music="file" if mfile else "generate", music_file=mfile,
                      mood=self.mood.currentData() or "", music_level=float(self.level.value()))
        out = self.w.s.output_dir
        from . import qt_workers
        from .gui_shell import track

        self.go.setEnabled(False)
        self.bar.setVisible(True)
        self.worker = _Job(lambda p: create(req, out, p))
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(self.on_done)
        track(self.w, self.worker, f"Voiceover: {req.title}")
        self.thread = qt_workers.start(self.worker, self.worker.run, [self.worker.done])

    def on_progress(self, f, m):
        self.bar.setValue(int(1000 * max(0.0, min(1.0, f))))
        self.status.setText(m)

    def on_done(self, res, err):
        self.go.setEnabled(True)
        self.bar.setVisible(False)
        if err:
            self.status.setText("Could not make the voiceover — " + err)
            QMessageBox.warning(self, "Voiceover", err)
            return
        secs = float(res.get("duration") or 0)
        self.out_voice.set({"MP3": res.get("voice_mp3", ""), "WAV": res.get("voice_wav", "")}, secs, res.get("style", ""))
        self.out_music.set({"MP3": res.get("music_mp3", ""), "WAV": res.get("music_wav", "")}, secs + 7,
                           "music follows the voice")
        self.status.setText("Ready — play either version below, or download it.")
        self.fill_recent()
        self.log.emit(f"Voiceover ready: {res.get('folder')}")
        self.out_music.on_play()
