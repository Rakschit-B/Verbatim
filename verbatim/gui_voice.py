"""Module 02 — Voice Studio: translate a transcript, voice it with stock voices, export.

Also holds the voice consent register (required before cloning, which arrives in Phase 4).
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from PySide6.QtCore import QDate, QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateEdit, QDialog, QFileDialog,
                               QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from .translate import CLAUDE_MODELS, LANG_NAMES
from .tts import VOICES

TARGETS = ["hi", "bn", "ta", "te", "mr", "gu", "kn", "ml", "pa", "ur", "en", "es", "fr", "de", "it", "pt", "ar",
           "ja", "zh", "id", "ru"]


def _T():
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


def _open(p):
    if p:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))


def mmss(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"


# ====================================================================== workers
class Job(QObject):
    progress = Signal(float, str)
    done = Signal(object, str)  # result, error

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            res = self.fn(lambda f, m: self.progress.emit(float(f), str(m)))
            self.done.emit(res, "")
        except Exception as exc:
            self.done.emit(None, f"{type(exc).__name__}: {exc}")


# ====================================================================== page
class VoiceStudio(QWidget):
    log = Signal(str)

    def __init__(self, window):
        super().__init__()
        self.w = window          # main Window (settings, icons, say)
        self.job = None
        self.loading = False
        self.thread = None
        self.preview_player = None
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)
        h.addWidget(self._center(), 1)
        h.addWidget(self._right())
        self.refresh_sources()

    # ------------------------------------------------------------ layout
    def _center(self):
        c = _card()
        v = QVBoxLayout(c)
        v.setContentsMargins(22, 18, 22, 14)
        v.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(_label("Voice Studio", "h1"))
        top.addSpacing(16)
        seg = QFrame()
        seg.setObjectName("segBar")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(4, 4, 4, 4)
        self.sub = QButtonGroup(self)
        for i, name in enumerate(["Translation && voiceover", "Consent register"]):
            b = QPushButton(name)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.sub.addButton(b, i)
            sl.addWidget(b)
        self.sub.button(0).setChecked(True)
        self.sub.idClicked.connect(lambda i: (self.stack.setCurrentIndex(i), self.right.setVisible(i == 0),
                                              i == 1 and self.load_consent()))
        top.addWidget(seg)
        top.addStretch()
        v.addLayout(top)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._translation_view())
        self.stack.addWidget(self._consent_view())
        v.addWidget(self.stack, 1)
        return c

    def _translation_view(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        row = QHBoxLayout()
        row.addWidget(_label("Transcript", "sub"))
        self.source = QComboBox()
        self.source.setMinimumContentsLength(30)
        self.source.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.source.currentIndexChanged.connect(self.on_source)
        row.addWidget(self.source, 1)
        b = QPushButton("Open transcript file…")
        b.clicked.connect(self.pick_json)
        row.addWidget(b)
        r = QToolButton()
        r.setToolTip("Refresh list")
        self.w.icons.set(r, "refresh", "ink", 16)
        r.clicked.connect(self.refresh_sources)
        row.addWidget(r)
        v.addLayout(row)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Time", "Speaker", "Original", "Translation  (double-click to edit)", "Fit"])
        hh = self.table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 64)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(4, 120)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.itemChanged.connect(self.on_edit)
        v.addWidget(self.table, 1)
        self.empty = _label("Choose a transcribed file above. Its lines appear here, ready to translate.", "hint")
        self.empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty)
        foot = QHBoxLayout()
        self.status = _label("", "hint")
        foot.addWidget(self.status, 1)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        self.bar.setFixedWidth(200)
        self.bar.setVisible(False)
        foot.addWidget(self.bar)
        v.addLayout(foot)
        return w

    def _right(self):
        c = _card()
        c.setFixedWidth(410)
        self.right = c
        outer = QVBoxLayout(c)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(12)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(2, 0, 6, 0)
        v.setSpacing(10)
        v.addWidget(_label("Translate", "h2"))
        g = QFormLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        self.lang = QComboBox()
        for code in TARGETS:
            self.lang.addItem(LANG_NAMES[code] + ("" if code in VOICES else "  (subtitles only)"), code)
        self.lang.currentIndexChanged.connect(self.on_lang)
        g.addRow(_label("Into", "sub"), self.lang)
        self.engine = QComboBox()
        self.engine.addItem("Offline — free & private", ("offline", ""))
        for mid, name in CLAUDE_MODELS.items():
            self.engine.addItem(f"Claude — {name}", ("claude", mid))
        self.engine.view().setMinimumWidth(360)
        for combo in (self.lang, self.engine):
            combo.setMinimumContentsLength(14)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        g.addRow(_label("Engine", "sub"), self.engine)
        v.addLayout(g)
        self.engine_hint = _label("Offline uses open models downloaded once per language. Claude is best for names, "
                                  "idioms and corporate tone (needs your API key; text is sent to Anthropic).",
                                  "hint", wrap=True)
        v.addWidget(self.engine_hint)
        self.only_new = QCheckBox("Keep lines I edited (translate the rest)")
        self.only_new.setChecked(True)
        v.addWidget(self.only_new)
        self.translate_btn = QPushButton("  Translate")
        self.w.icons.set(self.translate_btn, "globe", "ink", 16)
        self.translate_btn.clicked.connect(self.do_translate)
        v.addWidget(self.translate_btn)
        hl = QFrame()
        hl.setObjectName("hline")
        v.addWidget(hl)
        v.addWidget(_label("Voiceover", "h2"))
        self.voice_note = _label("", "hint", wrap=True)
        v.addWidget(self.voice_note)
        self.voice_box = QVBoxLayout()
        self.voice_box.setSpacing(8)
        v.addLayout(self.voice_box)
        row = QHBoxLayout()
        row.addWidget(_label("Pace", "sub"))
        self.pace = QComboBox()
        self.pace.setMinimumContentsLength(10)
        self.pace.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.pace.addItems(["Relaxed (0.9×)", "Natural (1.0×)", "Brisk (1.1×)"])
        self.pace.setCurrentIndex(1)
        row.addWidget(self.pace)
        row.addStretch()
        v.addLayout(row)
        self.mix = QCheckBox("Mix over the original sound (ducked)")
        self.mix.setChecked(True)
        self.video = QCheckBox("Create the dubbed video (MP4)")
        self.video.setChecked(True)
        v.addWidget(self.mix)
        v.addWidget(self.video)
        v.addStretch()
        sc.setWidget(inner)
        outer.addWidget(sc, 1)
        self.gen_btn = QPushButton("   Generate voiceover")
        self.gen_btn.setObjectName("start")
        self.gen_btn.setCursor(Qt.PointingHandCursor)
        self.w.icons.set(self.gen_btn, "mic", "#FFFFFF", 20)
        self.gen_btn.clicked.connect(self.do_render)
        outer.addWidget(self.gen_btn)
        self.open_btn = QPushButton("  Open Voice Studio folder")
        self.open_btn.setObjectName("stop")
        self.w.icons.set(self.open_btn, "open", "ink", 15)
        self.open_btn.clicked.connect(lambda: self.job and _open(self.job.path.parent))
        outer.addWidget(self.open_btn)
        self.on_lang()
        return c

    # ------------------------------------------------------------ sources
    def refresh_sources(self):
        cur = self.source.currentData()
        self.loading = True
        self.source.clear()
        self.source.addItem("— choose a transcribed file —", "")
        db = Path(self.w.s.output_dir) / ".verbatim" / "ledger.sqlite"
        seen = set()
        if db.exists():
            try:
                con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                for name, js, lang in con.execute("SELECT source_name, json, language FROM files WHERE status='Completed' "
                                                  "AND json IS NOT NULL ORDER BY id DESC LIMIT 500"):
                    if js and js not in seen and Path(js).exists():
                        seen.add(js)
                        self.source.addItem(f"{name}   ·   {LANG_NAMES.get(lang, lang)}", js)
                con.close()
            except sqlite3.Error:
                pass
        if cur and cur not in seen:
            self.source.addItem(Path(cur).stem, cur)
        self.loading = False
        if cur:
            self.select_source(cur)

    def select_source(self, json_path: str):
        i = self.source.findData(json_path)
        if i < 0:
            self.source.addItem(Path(json_path).stem, json_path)
            i = self.source.count() - 1
        self.source.setCurrentIndex(i)

    def pick_json(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open a VERBATIM transcript", self.w.s.output_dir, "Transcript (*.json)")
        if p:
            self.select_source(p)

    def on_source(self, *_):
        if self.loading:
            return
        self.load_job()

    def on_lang(self, *_):
        code = self.lang.currentData()
        ok = code in VOICES
        self.gen_btn.setEnabled(ok)
        self.voice_note.setText("Stock voices (Kokoro, offline). Pick a voice for each speaker; ▶ plays a sample."
                                if ok else f"No local voice for {LANG_NAMES.get(code, code)} yet — you still get the "
                                "translation and subtitles. Voices: English, Hindi, Spanish, French, Italian, "
                                "Portuguese, Japanese, Chinese.")
        if not self.loading:
            self.load_job()

    def load_job(self):
        js = self.source.currentData()
        self.job = None
        if not js:
            self.fill()
            return
        from .dub import new_job

        try:
            self.job = new_job(js, self.lang.currentData())
        except Exception as exc:
            self.status.setText(f"Could not open this transcript: {exc}")
        if self.job and self.job.engine and self.job.engine != "offline":
            k = self.engine.findData(("claude", self.job.model))
            if k >= 0:
                self.engine.setCurrentIndex(k)
        if self.job:
            self.pace.setCurrentIndex({0.9: 0, 1.0: 1, 1.1: 2}.get(round(self.job.speed, 1), 1))
        self.fill()

    # ------------------------------------------------------------ table
    def fill(self):
        self.loading = True
        lines = self.job.lines if self.job else []
        self.table.setRowCount(len(lines))
        warn = QColor("#C2410C") if _T()["name"] == "light" else QColor("#FDBA74")
        okc = QColor("#15803D") if _T()["name"] == "light" else QColor("#86EFAC")
        for i, ln in enumerate(lines):
            for col, val in enumerate([mmss(ln.start), ln.speaker, ln.source, ln.text, ln.fit]):
                it = QTableWidgetItem(val)
                if col != 3:
                    it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                if col == 0:
                    it.setForeground(QColor(_T()["sub"]))
                if col == 3 and ln.edited:
                    it.setToolTip("Edited by you — kept when re-translating")
                    f = it.font()
                    f.setItalic(True)
                    it.setFont(f)
                if col == 4 and val:
                    it.setForeground(warn if val.startswith(("too long", "shifted", "no ")) else okc)
                    if val.startswith("too long"):
                        it.setToolTip("Shorten this translation, or choose a brisker pace")
                self.table.setItem(i, col, it)
        self.table.resizeRowsToContents()
        self.loading = False
        self.empty.setVisible(not lines)
        self.table.setVisible(bool(lines))
        self.fill_voices()
        if self.job:
            done = sum(1 for x in lines if x.text.strip())
            issues = sum(1 for x in lines if x.fit.startswith("too long"))
            s = f"{len(lines)} lines · {done} translated"
            if self.job.translated:
                s += f" ({self.job.engine}{' ' + self.job.model if self.job.model else ''})"
            if self.job.rendered:
                s += f" · voiceover made {self.job.rendered.replace('T', ' ')[:16]}"
                s += f" · {issues} line(s) too long" if issues else " · all lines fit"
            self.status.setText(s)

    def on_edit(self, it: QTableWidgetItem):
        if self.loading or not self.job or it.column() != 3:
            return
        ln = self.job.lines[it.row()]
        new = " ".join((it.text() or "").split())
        if new != ln.text:
            ln.text, ln.edited, ln.fit = new, True, ""
            self.job.save()
            self.loading = True
            f = it.font()
            f.setItalic(True)
            it.setFont(f)
            self.table.item(it.row(), 4).setText("")
            self.loading = False
            self.table.resizeRowToContents(it.row())

    def fill_voices(self):
        from .tts import voices_for

        while self.voice_box.count():
            item = self.voice_box.takeAt(0)
            lay = item.layout()
            if lay:
                while lay.count():
                    w = lay.takeAt(0).widget()
                    if w:
                        w.deleteLater()
            elif item.widget():
                item.widget().deleteLater()
        self.voice_combos = {}
        if not self.job:
            return
        options = voices_for(self.job.tgt_lang)
        if not options:
            return
        for k, spk in enumerate(self.job.speakers()):
            row = QHBoxLayout()
            name = _label(spk, "sub")
            name.setFixedWidth(100)
            name.setToolTip(spk)
            row.addWidget(name)
            box = QComboBox()
            box.setMinimumContentsLength(10)
            box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            for sid, lab in options:
                box.addItem(lab, sid)
            want = self.job.voices.get(spk, options[k % len(options)][0])
            idx = box.findData(want)
            box.setCurrentIndex(idx if idx >= 0 else 0)
            box.currentIndexChanged.connect(lambda _i, s=spk, b=box: self.set_voice(s, b.currentData()))
            self.set_voice(spk, box.currentData(), save=False)
            row.addWidget(box, 1)
            pb = QToolButton()
            pb.setToolTip("Play a sample")
            self.w.icons.set(pb, "play", "ink", 14)
            pb.clicked.connect(lambda _=False, b=box, s=spk: self.preview(b.currentData(), s))
            row.addWidget(pb)
            self.voice_box.addLayout(row)
            self.voice_combos[spk] = box

    def set_voice(self, spk, sid, save=True):
        if self.job:
            self.job.voices[spk] = int(sid)
            if save:
                self.job.save()

    def preview(self, sid, spk):
        from .gui_editor import AudioPlayer
        from .tts import Synth, is_installed

        if not self.job:
            return
        if not is_installed():
            QMessageBox.information(self, "Voice model", "The voice model (330 MB) downloads the first time you "
                                    "generate a voiceover. Click Generate voiceover once, then previews work.")
            return
        text = next((ln.text for ln in self.job.lines if ln.speaker == spk and ln.text.strip()), "") or \
            {"hi": "नमस्ते, यह आवाज़ का एक नमूना है।", "en": "Hello, this is a sample of this voice."}.get(
                self.job.tgt_lang, "Hello, this is a sample of this voice.")
        try:
            import numpy as np

            from .dub import _write_wav

            a = Synth().speak(text[:220], self.job.tgt_lang, int(sid), 1.0)
            tmp = Path(tempfile.gettempdir()) / "verbatim_voice_preview.wav"
            _write_wav(tmp, a if len(a) else np.zeros(1000, dtype=np.float32))
            if self.preview_player is None:
                self.preview_player = AudioPlayer()
            err = self.preview_player.play(tmp, 0.0, 30.0)
            if err:
                self.status.setText("Could not play: " + err)
        except Exception as exc:
            self.status.setText(f"Preview failed: {exc}")

    # ------------------------------------------------------------ actions
    def busy(self, on: bool, text: str = ""):
        self.translate_btn.setEnabled(not on)
        self.gen_btn.setEnabled(not on and self.lang.currentData() in VOICES)
        self.source.setEnabled(not on)
        self.lang.setEnabled(not on)
        self.bar.setVisible(on)
        if text:
            self.status.setText(text)

    def run(self, fn, done_cb, start_text):
        if self.thread and self.thread.isRunning():
            return
        self.busy(True, start_text)
        self.thread = QThread()
        self.worker = Job(fn)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(done_cb)
        self.worker.done.connect(self.thread.quit)
        self.thread.start()

    def on_progress(self, f: float, msg: str):
        self.bar.setValue(int(1000 * max(0.0, min(1.0, f))))
        self.status.setText(msg)

    def do_translate(self):
        if not self.job:
            QMessageBox.information(self, "Choose a transcript", "Choose a transcribed file first.")
            return
        kind, model = self.engine.currentData()
        if kind == "claude":
            from .translate import get_claude_key

            if not get_claude_key():
                QMessageBox.information(self, "Claude API key needed",
                                        "Add your Claude API key in Settings › Cloud engines, or use the Offline engine.")
                return
        job, vocab = self.job, self.w.vocab.toPlainText()
        keep = self.only_new.isChecked()
        if not keep:
            for ln in job.lines:
                ln.edited = False

        def work(progress):
            from .dub import translate_job
            from .translate import build

            return translate_job(job, build(kind, model or "claude-sonnet-5-5", progress), vocab, progress)

        self.run(work, self.on_translated, "Translating…")

    def on_translated(self, job, err):
        self.busy(False)
        if err:
            self.status.setText("Translation failed — " + err)
            QMessageBox.warning(self, "Translation failed", err)
            return
        self.job = job
        self.fill()
        self.log.emit(f"Translated {Path(job.source_json).stem} → {LANG_NAMES.get(job.tgt_lang)} ({job.engine})")

    def do_render(self):
        if not self.job:
            QMessageBox.information(self, "Choose a transcript", "Choose a transcribed file first.")
            return
        missing = sum(1 for ln in self.job.lines if not ln.text.strip())
        if missing == len(self.job.lines):
            QMessageBox.information(self, "Translate first", "Translate the lines first (or type them in).")
            return
        if missing and QMessageBox.question(self, "Untranslated lines", f"{missing} line(s) have no translation and "
                                            "will be silent. Continue?") != QMessageBox.Yes:
            return
        self.job.speed = (0.9, 1.0, 1.1)[self.pace.currentIndex()]
        job, mix, video = self.job, self.mix.isChecked(), self.video.isChecked()

        def work(progress):
            from .dub import render
            from .tts import Synth

            return render(job, Synth(progress=progress), progress, mix=mix, video=video)

        self.run(work, self.on_rendered, "Preparing voices…")

    def on_rendered(self, out, err):
        self.busy(False)
        if err:
            self.status.setText("Voiceover failed — " + err)
            QMessageBox.warning(self, "Voiceover failed", err)
            return
        self.fill()
        issues = sum(1 for ln in self.job.lines if ln.fit.startswith("too long"))
        made = [k for k in ("video", "mix", "voice", "srt") if out.get(k)]
        self.log.emit(f"Voiceover ready: {Path(self.job.source_json).stem} — {LANG_NAMES.get(self.job.tgt_lang)}")
        box = QMessageBox(self)
        box.setWindowTitle("Voiceover ready")
        names = {"video": "dubbed video (MP4)", "mix": "voiceover mixed with original", "voice": "voice-only track",
                 "srt": "translated subtitles"}
        box.setText("Created: " + ", ".join(names[k] for k in made) + ".")
        info = (f"{issues} line(s) are longer than their slot — shorten them (orange in the Fit column) and generate "
                "again." if issues else "Every line fits its time slot.")
        if out.get("mix_error") or out.get("video_error"):
            info += "\n\nNote: " + (out.get("video_error") or out.get("mix_error"))[:200]
        box.setInformativeText(info)
        ob = box.addButton("Open folder", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is ob:
            _open(out.get("folder"))

    # ------------------------------------------------------------ consent register
    def _consent_view(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addWidget(_label("A signed consent form is required before anyone's voice can be cloned (voice cloning "
                           "arrives in the next phase). Stock voices need no consent. Every entry is listed in the "
                           "Master Excel Log (“Voice Consent” sheet) and the form is kept safely in VERBATIM's data "
                           "folder.", "hint", wrap=True))
        row = QHBoxLayout()
        b = QPushButton("  Add consent…")
        self.w.icons.set(b, "plus", "ink", 15)
        b.clicked.connect(self.add_consent)
        row.addWidget(b)
        for text, fn in (("Open signed form", self.open_form), ("Revoke…", self.revoke_consent)):
            bb = QPushButton(text)
            bb.clicked.connect(fn)
            row.addWidget(bb)
        row.addStretch()
        v.addLayout(row)
        self.ctable = QTableWidget(0, 6)
        self.ctable.setHorizontalHeaderLabels(["Person", "Status", "Covers", "Signed", "Expires", "Project"])
        hh = self.ctable.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.ctable.verticalHeader().setVisible(False)
        self.ctable.verticalHeader().setDefaultSectionSize(40)
        self.ctable.setShowGrid(False)
        self.ctable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.ctable.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.ctable.setSelectionMode(QAbstractItemView.SingleSelection)
        v.addWidget(self.ctable, 1)
        self.cnote = _label("", "hint")
        v.addWidget(self.cnote)
        self.cids = []
        return w

    def load_consent(self):
        from .consent import ConsentRegister

        reg = ConsentRegister()
        self.ctable.setRowCount(len(reg.entries))
        self.cids = []
        for i, e in enumerate(reg.entries):
            st = reg.status(e)
            vals = [e["person"], st, e["scope"], e["signed"], e.get("expires") or "—", e.get("project") or "—"]
            for j, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if j == 1:
                    it.setForeground(QColor("#15803D" if st == "Valid" else "#B91C1C"))
                self.ctable.setItem(i, j, it)
            self.cids.append(e["id"])
        self.cnote.setText(f"{len(reg.entries)} consent record(s)." if reg.entries else "No consent records yet.")

    def _selected_consent(self):
        rows = self.ctable.selectionModel().selectedRows()
        return self.cids[rows[0].row()] if rows else None

    def add_consent(self):
        from .consent import SCOPES, ConsentRegister

        dlg = QDialog(self)
        dlg.setWindowTitle("Add voice consent")
        dlg.resize(520, 420)
        f = QFormLayout(dlg)
        person = QLineEdit()
        person.setPlaceholderText("Full name of the speaker")
        form = QLineEdit()
        form.setReadOnly(True)
        form.setPlaceholderText("Signed form (PDF or photo)")
        pick = QPushButton("Choose…")
        fr = QHBoxLayout()
        fr.addWidget(form, 1)
        fr.addWidget(pick)
        pick.clicked.connect(lambda: form.setText(QFileDialog.getOpenFileName(
            dlg, "Signed consent form", "", "Forms (*.pdf *.jpg *.jpeg *.png *.heic *.docx)")[0] or form.text()))
        scope = QComboBox()
        scope.addItems(SCOPES)
        signed = QDateEdit(QDate.currentDate())
        signed.setCalendarPopup(True)
        has_exp = QCheckBox("Expires")
        exp = QDateEdit(QDate.currentDate().addYears(1))
        exp.setCalendarPopup(True)
        exp.setEnabled(False)
        has_exp.toggled.connect(exp.setEnabled)
        er = QHBoxLayout()
        er.addWidget(has_exp)
        er.addWidget(exp, 1)
        from .projects import Projects

        proj = QLineEdit()
        p = Projects().get(self.w.s.active_project) if self.w.s.active_project else None
        proj.setText(p["name"] if p else "")
        notes = QPlainTextEdit()
        notes.setMaximumHeight(70)
        f.addRow("Person", person)
        f.addRow("Signed form", fr)
        f.addRow("Covers", scope)
        f.addRow("Signed on", signed)
        f.addRow("", er)
        f.addRow("Project", proj)
        f.addRow("Notes", notes)
        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Cancel")
        ok = QPushButton("Add to register")
        ok.setDefault(True)
        cancel.clicked.connect(dlg.reject)
        ok.clicked.connect(dlg.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        f.addRow(btns)
        while dlg.exec() == QDialog.Accepted:
            try:
                import getpass

                ConsentRegister().add(person.text(), form.text(), scope.currentText(),
                                      signed.date().toString(Qt.ISODate),
                                      exp.date().toString(Qt.ISODate) if has_exp.isChecked() else "",
                                      proj.text().strip(), notes.toPlainText().strip(), getpass.getuser())
                self.log.emit(f"Voice consent recorded: {person.text().strip()}")
                self._refresh_log()
                break
            except ValueError as exc:
                QMessageBox.warning(dlg, "Missing information", str(exc))
        self.load_consent()

    def open_form(self):
        from .consent import ConsentRegister

        eid = self._selected_consent()
        e = next((x for x in ConsentRegister().entries if x["id"] == eid), None)
        if e:
            _open(e["form"])

    def revoke_consent(self):
        from PySide6.QtWidgets import QInputDialog

        from .consent import ConsentRegister

        eid = self._selected_consent()
        if not eid:
            return
        reason, ok = QInputDialog.getText(self, "Revoke consent", "Reason (kept in the register):")
        if ok:
            ConsentRegister().revoke(eid, reason.strip())
            self.load_consent()
            self._refresh_log()

    def _refresh_log(self):
        try:
            from .master_log import MasterLog

            MasterLog(Path(self.w.s.output_dir)).export_excel()
        except Exception:
            pass
