# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Module 02 — Voice Studio: translate a transcript (or write a script), direct the performance, voice it with
studio, expressive or custom voices, add a music bed that follows the voice, export.

Tabs: Translation & voiceover · Voice Lab (custom voices from your recordings) · Consent register.
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
from .tts import voices_for as _voices_for

TARGETS = ["hi", "en", "es", "fr", "de", "it", "pt", "ru", "ja", "zh", "he", "ar", "ko", "tr", "nl", "id",
           "ta", "te", "mr", "gu", "kn", "ml", "pa", "ur", "bn",
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


def perf_text(ln) -> str:
    if not ln.emotion:
        return "—"
    from .direction import info

    strength = "subtle" if ln.intensity < 0.4 else ("strong" if ln.intensity >= 0.7 else "natural")
    t = f"{info(ln.emotion)['label']} · {strength}"
    if ln.emphasis:
        t += f" · stress: {ln.emphasis}"
    return t


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
        for i, name in enumerate(["Translation && voiceover", "Voice Lab", "Consent register"]):
            b = QPushButton(name)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.sub.addButton(b, i)
            sl.addWidget(b)
        self.sub.button(0).setChecked(True)
        self.sub.idClicked.connect(lambda i: (self.stack.setCurrentIndex(i), self.right.setVisible(i == 0),
                                              i == 1 and self.load_lab(), i == 2 and self.load_consent()))
        top.addWidget(seg)
        top.addStretch()
        v.addLayout(top)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._translation_view())
        self.stack.addWidget(self._lab_view())
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
        b = QPushButton("  New from script…")
        self.w.icons.set(b, "plus", "ink", 14)
        b.setToolTip("Write or paste a script — VERBATIM voices it (and adds music), no video needed.")
        b.clicked.connect(self.new_script)
        row.addWidget(b)
        r = QToolButton()
        r.setToolTip("Refresh list")
        self.w.icons.set(r, "refresh", "ink", 16)
        r.clicked.connect(self.refresh_sources)
        row.addWidget(r)
        v.addLayout(row)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Time", "Speaker", "Original", "Translation  (double-click to edit)",
                                              "Meaning check", "Fit", "Performance"])
        hh = self.table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 64)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(5, 120)
        hh.setSectionResizeMode(6, QHeaderView.Fixed)
        self.table.setColumnWidth(6, 170)
        self.table.setColumnHidden(4, True)
        self.table.cellDoubleClicked.connect(self.on_cell_double)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.line_menu)
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
            self.lang.addItem(LANG_NAMES[code] + ("" if _voices_for(code) else "  (subtitles only)"), code)
        self.lang.currentIndexChanged.connect(self.on_lang)
        g.addRow(_label("Into", "sub"), self.lang)
        self.engine = QComboBox()
        self.engine.addItem("TranslateGemma 4B — offline, 55 languages", ("translategemma", "translategemma-4b"))
        self.engine.addItem("TranslateGemma 12B — offline, best (16 GB RAM)", ("translategemma", "translategemma-12b"))
        for mid, name in CLAUDE_MODELS.items():
            self.engine.addItem(f"Claude — {name}", ("claude", mid))
        self.engine.addItem("OPUS-MT — offline, basic (small download)", ("opus", ""))
        self.engine.currentIndexChanged.connect(self.on_engine)
        self.engine.view().setMinimumWidth(360)
        for combo in (self.lang, self.engine):
            combo.setMinimumContentsLength(14)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        g.addRow(_label("Engine", "sub"), self.engine)
        self.style_box = QComboBox()
        self.style_box.addItem("Natural spoken (recommended)", "natural")
        self.style_box.addItem("Faithful — close to the original", "faithful")
        self.style_box.addItem("Creative — ads & brand films", "creative")
        self.style_box.setMinimumContentsLength(14)
        self.style_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.style_box.currentIndexChanged.connect(self.on_style)
        g.addRow(_label("Style", "sub"), self.style_box)
        v.addLayout(g)
        self.engine_hint = _label("Offline uses open models downloaded once per language. Claude is best for names, "
                                  "idioms and corporate tone (needs your API key; text is sent to Anthropic).",
                                  "hint", wrap=True)
        v.addWidget(self.engine_hint)
        self.polish = QCheckBox("Native-speaker polish (second pass)")
        self.polish.setChecked(True)
        self.polish.setToolTip("Claude re-reads every line as a native voice director and fixes anything stiff or literal.")
        v.addWidget(self.polish)
        self.only_new = QCheckBox("Keep lines I edited (translate the rest)")
        self.only_new.setChecked(True)
        v.addWidget(self.only_new)
        self.translate_btn = QPushButton("  Translate")
        self.w.icons.set(self.translate_btn, "globe", "ink", 16)
        self.translate_btn.clicked.connect(self.do_translate)
        v.addWidget(self.translate_btn)
        tools = QHBoxLayout()
        self.check_btn = QPushButton("Check meaning")
        self.check_btn.setToolTip("Translate every line back into the original language so you can verify the meaning.")
        self.check_btn.clicked.connect(self.do_check)
        tools.addWidget(self.check_btn)
        self.short_btn = QPushButton("Shorten long lines")
        self.short_btn.setToolTip("Claude rewrites lines flagged 'too long' so they fit their time slot.")
        self.short_btn.clicked.connect(self.do_shorten)
        tools.addWidget(self.short_btn)
        v.addLayout(tools)
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
        row = QHBoxLayout()
        row.addWidget(_label("Quality", "sub"))
        self.quality = QComboBox()
        self.quality.addItem("Standard", "standard")
        self.quality.addItem("Studio (slower)", "studio")
        self.quality.setToolTip("Studio takes about twice as long and gives the richest, smoothest voice.")
        row.addWidget(self.quality)
        row.addStretch()
        v.addLayout(row)
        self.mix = QCheckBox("Mix over the original sound (ducked)")
        self.mix.setChecked(True)
        self.video = QCheckBox("Create the dubbed video (MP4)")
        self.video.setChecked(True)
        v.addWidget(self.mix)
        self.keep_bg = QCheckBox("Keep original music && effects")
        self.keep_bg.setToolTip("Separates the original voice from the soundtrack, so the dub plays over the original "
                                "music and sound effects — like a studio dub.")
        v.addWidget(self.keep_bg)
        v.addWidget(self.video)
        hl = QFrame()
        hl.setObjectName("hline")
        v.addWidget(hl)
        v.addWidget(_label("Performance", "h2"))
        v.addWidget(_label("A voice director marks every line — emotion, strength and the words to stress — so the "
                           "voice rises and falls with the meaning. Double-click a line's Performance cell to change it.",
                           "hint", wrap=True))
        row = QHBoxLayout()
        self.direct_btn = QPushButton("  Direct the performance")
        self.w.icons.set(self.direct_btn, "bolt", "ink", 15)
        self.direct_btn.setToolTip("Claude directs the whole script when your Claude key is set; otherwise VERBATIM's "
                                   "built-in rules mark each line (offline).")
        self.direct_btn.clicked.connect(self.do_direct)
        row.addWidget(self.direct_btn, 1)
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(_label("Your voices speak with", "sub"))
        self.clone_engine = QComboBox()
        self.clone_engine.addItem("Best available (offline first)", "auto")
        self.clone_engine.addItem("Chatterbox — expressive, 23 languages", "chatterbox")
        self.clone_engine.addItem("Studio performance + your tone (OpenVoice)", "openvoice")
        self.clone_engine.addItem("ZipVoice — English, fast", "zipvoice")
        self.clone_engine.addItem("ElevenLabs — cloud clone", "elevenlabs")
        from .tts import omni_enabled

        if omni_enabled():
            self.clone_engine.addItem("Legacy designer (non-commercial)", "omnivoice")
        self.clone_engine.setMinimumContentsLength(10)
        self.clone_engine.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.clone_engine, 1)
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(_label("Finish", "sub"))
        from .fx import PRESETS

        self.fx_preset = QComboBox()
        self.fx_preset.addItem("Clean (no effects)", "")
        for name in PRESETS:
            self.fx_preset.addItem(name, name)
        self.fx_preset.setToolTip("Studio finishing: EQ, de-esser, compression, loudness — or a creative effect.")
        self.fx_preset.setMinimumContentsLength(10)
        self.fx_preset.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.fx_preset, 1)
        v.addLayout(row)
        hl = QFrame()
        hl.setObjectName("hline")
        v.addWidget(hl)
        v.addWidget(_label("Music", "h2"))
        v.addWidget(_label("Add a music track: it plays full in the intro, dips under the voice, swells in pauses, "
                           "follows the emotion of each line, and fades out at the end.", "hint", wrap=True))
        row = QHBoxLayout()
        self.music_file = QLineEdit()
        self.music_file.setReadOnly(True)
        self.music_file.setPlaceholderText("No music")
        row.addWidget(self.music_file, 1)
        b = QPushButton("Choose…")
        b.clicked.connect(self.pick_music)
        row.addWidget(b)
        b = QToolButton()
        b.setToolTip("Remove music")
        self.w.icons.set(b, "trash", "ink", 13)
        b.clicked.connect(lambda: self.music_file.setText(""))
        row.addWidget(b)
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(_label("Mix", "sub"))
        from .music import MODES

        self.music_mode = QComboBox()
        for k, t in MODES.items():
            self.music_mode.addItem(t, k)
        self.music_mode.setMinimumContentsLength(10)
        self.music_mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.music_mode, 1)
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(_label("Music under voice", "sub"))
        self.music_level = QComboBox()
        for t, dbv in (("Very low (−24 dB)", -24.0), ("Low (−20 dB)", -20.0), ("Present (−16 dB)", -16.0),
                       ("Forward (−12 dB)", -12.0)):
            self.music_level.addItem(t, dbv)
        self.music_level.setCurrentIndex(1)
        row.addWidget(self.music_level, 1)
        v.addLayout(row)
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
        self.on_engine()
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
        ok = bool(_voices_for(code))
        self.gen_btn.setEnabled(ok)
        n = len(_voices_for(code))
        self.voice_note.setText(f"{n} natural voices for {LANG_NAMES.get(code, code)} (offline). Pick one per speaker; "
                                "▶ plays a sample." if ok else f"No local voice for {LANG_NAMES.get(code, code)} yet — "
                                "you still get the translation and subtitles.")
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
        if self.job and self.job.engine:
            k = self.engine.findData((self.job.engine, self.job.model))
            if k >= 0:
                self.engine.setCurrentIndex(k)
        if self.job:
            self.pace.setCurrentIndex({0.9: 0, 1.0: 1, 1.1: 2}.get(round(self.job.speed, 1), 1))
            self.style_box.setCurrentIndex(max(0, self.style_box.findData(self.job.style)))
            self.quality.setCurrentIndex(max(0, self.quality.findData(self.job.quality)))
            self._restore_job_ui()
        self.fill()

    def _restore_job_ui(self):
        j = self.job
        self.clone_engine.setCurrentIndex(max(0, self.clone_engine.findData(j.clone_engine)))
        self.fx_preset.setCurrentIndex(max(0, self.fx_preset.findData(j.fx_preset or "")))
        self.music_file.setText(j.music.get("file", ""))
        self.music_mode.setCurrentIndex(max(0, self.music_mode.findData(j.music.get("mode", "follow"))))
        self.music_level.setCurrentIndex(max(0, self.music_level.findData(float(j.music.get("duck_db", -20.0)))))
        self.keep_bg.setChecked(bool(j.keep_background))
        has_media = bool(j.media) and not j.sequential
        for wdg in (self.mix, self.keep_bg, self.video):
            wdg.setEnabled(has_media)

    # ------------------------------------------------------------ table
    def fill(self):
        self.loading = True
        lines = self.job.lines if self.job else []
        self.table.setRowCount(len(lines))
        warn = QColor("#C2410C") if _T()["name"] == "light" else QColor("#FDBA74")
        okc = QColor("#15803D") if _T()["name"] == "light" else QColor("#86EFAC")
        for i, ln in enumerate(lines):
            for col, val in enumerate([mmss(ln.start), ln.speaker, ln.source, ln.text, ln.check, ln.fit,
                                       perf_text(ln)]):
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
                if col == 6:
                    it.setToolTip("Double-click to direct this line: emotion, strength, words to stress")
                    it.setForeground(QColor(_T()["accent"]) if ln.emotion else QColor(_T()["sub"]))
                if col == 5 and val:
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
            self.table.item(it.row(), 5).setText("")
            self.table.item(it.row(), 4).setText("")
            ln.check = ""
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
            from .tts import default_voices

            for vv in options:
                box.addItem(vv.label + {"ko": "  · Kokoro"}.get(vv.engine, ""), vv.id)
            want = self.job.voices.get(spk) or default_voices(self.job.tgt_lang, len(self.job.speakers()))[k]
            if isinstance(want, int):
                want = f"ko:{want}"
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
            self.job.voices[spk] = str(sid)
            if save:
                self.job.save()

    def preview(self, sid, spk):
        from .tts import VOICES, is_installed

        if not self.job:
            return
        v = VOICES.get(str(sid))
        if v and not is_installed(v.engine):
            QMessageBox.information(self, "Voices", "This voice downloads once (Voice Studio › Voice Lab › Voice "
                                    "engines, or the first time you generate a voiceover).")
            return
        ln0 = next((ln for ln in self.job.lines if ln.speaker == spk and ln.text.strip()), None)
        text = ln0.text if ln0 else {"hi": "नमस्ते, यह आवाज़ का एक नमूना है।"}.get(
            self.job.tgt_lang, "Hello, this is a sample of this voice.")
        dirn = {"emotion": ln0.emotion, "intensity": ln0.intensity, "emphasis": ln0.emphasis} if ln0 else None
        lang, quality, ce = self.job.tgt_lang, self.quality.currentData(), self.clone_engine.currentData()

        def work(progress):
            import numpy as np

            from .dub import _write_wav
            from .tts import Synth

            progress(0.3, "Speaking a sample…")
            a = Synth(progress=progress, quality=quality, clone_engine=ce).speak(text[:220], lang, str(sid), 1.0, dirn)
            tmp = Path(tempfile.gettempdir()) / "verbatim_voice_preview.wav"
            _write_wav(tmp, a if len(a) else np.zeros(1000, dtype=np.float32))
            return tmp

        self.run(work, self.on_preview, "Preparing a sample…")

    def on_preview(self, tmp, err):
        self.busy(False)
        if err:
            self.status.setText(f"Preview failed: {err}")
            return
        from .gui_editor import AudioPlayer

        if self.preview_player is None:
            self.preview_player = AudioPlayer()
        e = self.preview_player.play(tmp, 0.0, 30.0)
        self.status.setText("Could not play: " + e if e else "Playing sample")

    # ------------------------------------------------------------ actions
    def busy(self, on: bool, text: str = ""):
        self.translate_btn.setEnabled(not on)
        self.gen_btn.setEnabled(not on and bool(_voices_for(self.lang.currentData())))
        self.check_btn.setEnabled(not on)
        self.short_btn.setEnabled(not on)
        if hasattr(self, "direct_btn"):
            self.direct_btn.setEnabled(not on)
        self.source.setEnabled(not on)
        self.lang.setEnabled(not on)
        self.bar.setVisible(on)
        if text:
            self.status.setText(text)

    def run(self, fn, done_cb, start_text):
        if self.thread and self.thread.isRunning():
            return
        self.busy(True, start_text)
        from . import qt_workers

        self.worker = Job(fn)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(done_cb)
        self.thread = qt_workers.start(self.worker, self.worker.run, [self.worker.done])

    def on_progress(self, f: float, msg: str):
        self.bar.setValue(int(1000 * max(0.0, min(1.0, f))))
        self.status.setText(msg)

    def do_translate(self):
        if not self.job:
            QMessageBox.information(self, "Choose a transcript", "Choose a transcribed file first.")
            return
        kind, model = self.engine.currentData()
        if kind == "claude" and self._need_key():
            return
        job, vocab = self.job, self.w.vocab.toPlainText()
        keep = self.only_new.isChecked()
        polish = self.polish.isChecked()
        job.style = self.style_box.currentData()
        if not keep:
            for ln in job.lines:
                ln.edited = False

        def work(progress):
            from .dub import translate_job
            from .translate import build

            return translate_job(job, build(kind, model or "claude-sonnet-5-5", progress), vocab, progress,
                                 polish=polish and kind == "claude")

        self.run(work, self.on_translated, "Translating…")

    def on_engine(self, *_):
        kind, _m = self.engine.currentData()
        self.polish.setVisible(kind == "claude")
        self.short_btn.setToolTip("Claude rewrites lines flagged 'too long' so they fit their time slot "
                                  "(needs your Claude key, whichever engine translated).")
        hints = {"translategemma": "Google TranslateGemma runs on this computer — private and free. First use downloads "
                                   "the engine and model once (2.5 GB for 4B, 7.3 GB for 12B).",
                 "claude": "Best for names, idioms and brand tone; with polish, a native-speaker pass fixes anything "
                           "stiff. Needs your Claude API key; text is sent to Anthropic.",
                 "opus": "Small, fast, basic quality — use only when the others are not available."}
        self.engine_hint.setText(hints.get(kind, ""))

    def on_style(self, *_):
        if self.job:
            self.job.style = self.style_box.currentData()

    def _need_key(self) -> bool:
        from .translate import get_claude_key

        if get_claude_key():
            return False
        QMessageBox.information(self, "Claude API key needed", "Add your Claude API key in Settings › Cloud engines.")
        return True

    def do_check(self):
        if not self.job or not any(ln.text.strip() for ln in self.job.lines):
            QMessageBox.information(self, "Translate first", "Translate the lines first.")
            return
        kind, model = self.engine.currentData()
        if kind == "opus":
            kind, model = "translategemma", "translategemma-4b"
        if kind == "claude" and self._need_key():
            return
        job = self.job

        def work(progress):
            from .dub import check_meaning
            from .translate import build

            return check_meaning(job, build(kind, model or "claude-sonnet-5-5", progress), progress)

        self.run(work, self.on_checked, "Checking meaning…")

    def on_checked(self, job, err):
        self.busy(False)
        if err:
            QMessageBox.warning(self, "Meaning check failed", err)
            return
        self.table.setColumnHidden(4, False)
        self.fill()
        self.status.setText("Meaning check ready — compare the Original and Meaning check columns.")

    def do_shorten(self):
        if not self.job or not any(ln.fit.startswith("too long") for ln in self.job.lines):
            QMessageBox.information(self, "Nothing to shorten", "No lines are flagged too long. Generate the "
                                    "voiceover first; lines that do not fit are flagged.")
            return
        if self._need_key():
            return
        kind, model = self.engine.currentData()
        job, vocab = self.job, self.w.vocab.toPlainText()

        def work(progress):
            from .dub import shorten_long_lines
            from .translate import ClaudeTranslator

            return shorten_long_lines(job, ClaudeTranslator(model=model if kind == "claude" else "claude-sonnet-5-5"),
                                      vocab)

        self.run(work, self.on_shortened, "Shortening long lines…")

    def on_shortened(self, n, err):
        self.busy(False)
        if err:
            QMessageBox.warning(self, "Could not shorten", err)
            return
        self.fill()
        self.status.setText(f"{n} line(s) shortened (marked as edited). Generate the voiceover again.")

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
        self.job.quality = self.quality.currentData()
        self.job.clone_engine = self.clone_engine.currentData()
        self.job.fx_preset = self.fx_preset.currentData() or ""
        self.job.keep_background = self.keep_bg.isChecked()
        mf = self.music_file.text().strip()
        self.job.music = {"file": mf, "mode": self.music_mode.currentData(),
                          "duck_db": self.music_level.currentData()} if mf else {}
        job, mix, video = self.job, self.mix.isChecked(), self.video.isChecked()

        def work(progress):
            from .dub import render
            from .tts import Synth

            return render(job, Synth(progress=progress, quality=job.quality, clone_engine=job.clone_engine,
                                     eleven_model=job.eleven_model), progress, mix=mix, video=video)

        self.run(work, self.on_rendered, "Preparing voices…")

    def on_rendered(self, out, err):
        self.busy(False)
        if err:
            self.status.setText("Voiceover failed — " + err)
            QMessageBox.warning(self, "Voiceover failed", err)
            return
        self.fill()
        issues = sum(1 for ln in self.job.lines if ln.fit.startswith("too long"))
        made = [k for k in ("video", "music_mix", "mix", "voice", "srt") if out.get(k)]
        self.log.emit(f"Voiceover ready: {Path(self.job.source_json).stem} — {LANG_NAMES.get(self.job.tgt_lang)}")
        box = QMessageBox(self)
        box.setWindowTitle("Voiceover ready")
        names = {"video": "dubbed video (MP4)", "mix": "voiceover mixed with original", "voice": "voice-only track",
                 "srt": "subtitles", "music_mix": "voiceover with music (WAV + MP3)"}
        box.setText("Created: " + ", ".join(names[k] for k in made) + ".")
        info = (f"{issues} line(s) are longer than their slot — shorten them (orange in the Fit column) and generate "
                "again." if issues else "Every line fits its time slot.")
        err2 = out.get("video_error") or out.get("mix_error") or out.get("music_error") or out.get("background_error")
        if err2:
            info += "\n\nNote: " + err2[:200]
        box.setInformativeText(info)
        ob = box.addButton("Open folder", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is ob:
            _open(out.get("folder"))

    # ------------------------------------------------------------ performance direction
    def on_cell_double(self, row: int, col: int):
        if col != 6 or not self.job:
            return
        from PySide6.QtWidgets import QSlider

        from .direction import EMOTIONS, ORDER

        ln = self.job.lines[row]
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Direct line {row + 1}")
        dlg.resize(460, 260)
        f = QFormLayout(dlg)
        f.addRow(_label(ln.text or ln.source, "sub", wrap=True))
        emo = QComboBox()
        for k in ORDER:
            emo.addItem(EMOTIONS[k]["label"], k)
        emo.setCurrentIndex(max(0, emo.findData(ln.emotion or "neutral")))
        strength = QSlider(Qt.Horizontal)
        strength.setRange(1, 10)
        strength.setValue(int(round((ln.intensity or 0.5) * 10)))
        emph = QLineEdit(ln.emphasis)
        emph.setPlaceholderText("words to stress, comma-separated")
        f.addRow("Emotion", emo)
        f.addRow("Strength", strength)
        f.addRow("Stress", emph)
        btns = QHBoxLayout()
        btns.addStretch()
        cancel, ok = QPushButton("Cancel"), QPushButton("Apply")
        ok.setDefault(True)
        cancel.clicked.connect(dlg.reject)
        ok.clicked.connect(dlg.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        f.addRow(btns)
        if dlg.exec() == QDialog.Accepted:
            ln.emotion, ln.intensity, ln.emphasis = emo.currentData(), strength.value() / 10, emph.text().strip()
            ln.fit = ""
            self.job.save()
            self.fill()

    def line_menu(self, pos):
        from PySide6.QtWidgets import QMenu

        row = self.table.rowAt(pos.y())
        if row < 0 or not self.job:
            return
        ln = self.job.lines[row]
        m = QMenu(self)
        a_play = m.addAction("▶  Hear this line")
        a_take = m.addAction("↻  New take of this line")
        a_dir = m.addAction("Direct this line…")
        act = m.exec(self.table.viewport().mapToGlobal(pos))
        if act is a_take:
            ln.take += 1
            ln.fit = ""
            self.job.save()
            self.preview_line(row)
        elif act is a_play:
            self.preview_line(row)
        elif act is a_dir:
            self.on_cell_double(row, 6)

    def preview_line(self, row: int):
        ln = self.job.lines[row]
        if not ln.text.strip():
            return
        sid = self.job.voices.get(ln.speaker) or ""
        if ln.voice:
            sid = ln.voice
        job = self.job

        def work(progress):
            import numpy as np

            from .dub import _speak_cached, _write_wav
            from .tts import Synth

            dirn = {"emotion": ln.emotion or "neutral", "intensity": ln.intensity, "emphasis": ln.emphasis}
            synth = Synth(progress=progress, quality=job.quality, clone_engine=job.clone_engine)
            a = _speak_cached(job, synth, ln, sid, job.speed * (ln.pace or 1.0), dirn)
            tmp = Path(tempfile.gettempdir()) / "verbatim_line_preview.wav"
            _write_wav(tmp, a if len(a) else np.zeros(1000, dtype=np.float32))
            return tmp

        self.run(work, self.on_preview, f"Voicing line {row + 1}…")

    def do_direct(self):
        if not self.job or not any(ln.text.strip() for ln in self.job.lines):
            QMessageBox.information(self, "Translate first", "Translate the lines (or write a script) first.")
            return
        from .translate import get_claude_key

        use_claude = bool(get_claude_key())
        kind, model = self.engine.currentData()
        job = self.job

        def work(progress):
            from .dub import direct_job

            tr = None
            if use_claude:
                from .translate import ClaudeTranslator

                tr = ClaudeTranslator(model=model if kind == "claude" else "claude-sonnet-5-5")
            progress(0.2, "The director is reading the whole script…" if tr else "Marking the performance…")
            return direct_job(job, tr)

        self.run(work, self.on_directed, "Directing the performance…")

    def on_directed(self, n, err):
        self.busy(False)
        if err:
            QMessageBox.warning(self, "Could not direct", err)
            return
        self.fill()
        self.status.setText(f"{n} line(s) directed. Double-click a Performance cell to fine-tune, then generate.")

    def pick_music(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose a music track", str(Path.home() / "Music"),
                                           "Audio (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.aiff *.aif)")
        if p:
            self.music_file.setText(p)

    def new_script(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("New voiceover from a script")
        dlg.resize(680, 560)
        f = QFormLayout(dlg)
        title = QLineEdit()
        title.setPlaceholderText("e.g. A Million Moments — brand film")
        lang = QComboBox()
        for code in TARGETS[:25]:
            if lang.findData(code) < 0:
                lang.addItem(LANG_NAMES[code], code)
        tgt = QComboBox()
        tgt.addItem("Same language (no translation)", "")
        for code in TARGETS[:25]:
            if tgt.findData(code) < 0:
                tgt.addItem(LANG_NAMES[code], code)
        text = QPlainTextEdit()
        text.setPlaceholderText("Paste the script. One sentence per line is not needed — VERBATIM splits sentences. "
                                "Leave a blank line between paragraphs for a longer pause.")
        f.addRow("Title", title)
        f.addRow("Script language", lang)
        f.addRow("Voice it in", tgt)
        f.addRow(text)
        btns = QHBoxLayout()
        btns.addStretch()
        cancel, ok = QPushButton("Cancel"), QPushButton("Create")
        ok.setDefault(True)
        cancel.clicked.connect(dlg.reject)
        ok.clicked.connect(dlg.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        f.addRow(btns)
        if dlg.exec() != QDialog.Accepted or not text.toPlainText().strip():
            return
        from .dub import new_script_job

        folder = Path(self.w.s.output_dir) / "Voice Studio scripts"
        job = new_script_job(text.toPlainText(), lang.currentData(), title.text().strip() or "Voiceover", folder,
                             tgt.currentData() or "")
        self.loading = True
        i = self.lang.findData(job.tgt_lang)
        if i >= 0:
            self.lang.setCurrentIndex(i)
        self.source.addItem(f"Script: {title.text().strip() or 'Voiceover'}", job.source_json)
        self.source.setCurrentIndex(self.source.count() - 1)
        self.loading = False
        self.job = job
        job.save()
        self._restore_job_ui()
        self.fill()
        self.status.setText("Script ready. Direct the performance, choose a voice and music, then generate."
                            if all(ln.text for ln in job.lines) else "Script ready — translate it, then generate.")

    # ------------------------------------------------------------ Voice Lab
    def _lab_view(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addWidget(_label("Make a voice from a recording — your own narration, or a speaker who has given consent. "
                           "VERBATIM removes any music under the voice, picks the cleanest 6–12 seconds and keeps it as "
                           "the voice reference. Your voices appear at the top of every voice list (★).", "hint", wrap=True))
        row = QHBoxLayout()
        b = QPushButton("  Create voice from a recording…")
        self.w.icons.set(b, "mic2", "ink", 15)
        b.clicked.connect(self.create_voice)
        row.addWidget(b)
        b = QPushButton("  Re-voice a recording…")
        self.w.icons.set(b, "wave", "ink", 15)
        b.setToolTip("Perform a line yourself (or use any recording) and hear it in another voice — your timing, "
                     "pitch and emotion are kept.")
        b.clicked.connect(self.revoice)
        row.addWidget(b)
        for text, fn in (("Play sample", self.play_lab), ("Import voices…", self.import_voices),
                         ("Export…", self.export_voices), ("Clone to ElevenLabs", self.clone_eleven),
                         ("Delete", self.delete_voice)):
            bb = QPushButton(text)
            bb.clicked.connect(fn)
            row.addWidget(bb)
        row.addStretch()
        v.addLayout(row)
        self.ltable = QTableWidget(0, 6)
        self.ltable.setHorizontalHeaderLabels(["Voice", "Gender", "Character", "Recorded in", "Source", "ElevenLabs"])
        hh = self.ltable.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.ltable.verticalHeader().setVisible(False)
        self.ltable.verticalHeader().setDefaultSectionSize(40)
        self.ltable.setShowGrid(False)
        self.ltable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.ltable.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.ltable.setSelectionMode(QAbstractItemView.SingleSelection)
        v.addWidget(self.ltable, 1)
        v.addWidget(_label("Voice engines", "h2"))
        self.packs_box = QVBoxLayout()
        v.addLayout(self.packs_box)
        row = QHBoxLayout()
        self.lnote = _label("", "hint", wrap=True)
        row.addWidget(self.lnote, 1)
        b = QPushButton("Test voice engines")
        b.setToolTip("Speaks a test line with every installed engine and your voices, and saves the results in "
                     "“VERBATIM diagnostics” inside your output folder.")
        b.clicked.connect(self.run_diag)
        row.addWidget(b)
        v.addLayout(row)
        self.lids = []
        return w

    def run_diag(self):
        out = Path(self.w.s.output_dir) / "VERBATIM diagnostics"

        def work(progress):
            from .voicelab import run_diagnostics

            return run_diagnostics(out, progress)

        self.run(work, lambda rep, err: (self.busy(False), QMessageBox.warning(self, "Diagnostics failed", err) if err
                                         else (_open(rep.parent), self.status.setText("Diagnostics saved."))),
                 "Testing voice engines…")

    def load_lab(self):
        from . import tts, tts_chatterbox, voicelab

        try:
            voicelab.import_bundled()
        except Exception:
            pass
        vs = voicelab.library()
        self.ltable.setRowCount(len(vs))
        self.lids = []
        for i, cv in enumerate(vs):
            for j, val in enumerate([cv.name, cv.gender, cv.character, LANG_NAMES.get(cv.lang, cv.lang), cv.source,
                                     "cloned" if cv.eleven_id else "—"]):
                self.ltable.setItem(i, j, QTableWidgetItem(val))
            self.lids.append(cv.id)
        while self.packs_box.count():
            it = self.packs_box.takeAt(0)
            if it.layout():
                while it.layout().count():
                    ww = it.layout().takeAt(0).widget()
                    if ww:
                        ww.deleteLater()
            elif it.widget():
                it.widget().deleteLater()
        packs = [("cb", "Expressive voices — Chatterbox (emotion, 23 languages incl. Hindi & Hebrew, speaks your "
                        "custom voices)", tts_chatterbox.SIZE_MB),
                 ("op", "OpenVoice V2 — keeps a performance, swaps the voice's tone colour", 150),
                 ("zv", "ZipVoice — fast English voice cloning", tts.ENGINES["zv"]["size_mb"]),
                 ("st", "Studio voices — Supertonic (10 voices × 31 languages)", tts.ENGINES["st"]["size_mb"]),
                 ("ko", "Kokoro — Chinese and extra English voices", tts.ENGINES["ko"]["size_mb"])]
        from . import runtimes
        from .platform_info import models_dir

        def installed(key):
            if key == "op":
                return (models_dir() / "openvoice" / "converter" / "checkpoint.pth").exists() and runtimes.is_ready("voice")
            return tts.is_installed(key)

        for key, text, mb in packs:
            row = QHBoxLayout()
            ok = installed(key)
            row.addWidget(_label(("✓  " if ok else "○  ") + text, "sub" if ok else "hint", wrap=True), 1)
            if not ok:
                b = QPushButton(f"Download ({mb / 1000:.1f} GB)" if mb >= 1000 else f"Download ({mb} MB)")
                b.clicked.connect(lambda _=False, k=key: self.download_pack(k))
                row.addWidget(b)
            self.packs_box.addLayout(row)
        self.lnote.setText(f"{len(vs)} custom voice(s). Everything above runs offline once downloaded.")

    def download_pack(self, key: str):
        def work(progress):
            from . import runtimes, tts
            from .download import hf_files
            from .platform_info import models_dir

            if key == "op":
                runtimes.ensure("voice", lambda f, m: progress(0.4 * f, m))
                hf_files("myshell-ai/OpenVoiceV2", models_dir() / "openvoice",
                         lambda f, m: progress(0.4 + 0.6 * f, m), exclude=r"\.DS_Store")
            else:
                tts.ensure(key, progress)
            return key

        self.run(work, self.on_pack, "Downloading voice engine (one time)…")

    def on_pack(self, key, err):
        self.busy(False)
        if err:
            QMessageBox.warning(self, "Download failed", err)
        else:
            self.status.setText("Voice engine installed — works offline from now on.")
        self.load_lab()
        self.fill_voices()

    def _selected_voice(self):
        rows = self.ltable.selectionModel().selectedRows()
        return self.lids[rows[0].row()] if rows else None

    def create_voice(self):
        import getpass

        dlg = QDialog(self)
        dlg.setWindowTitle("Create a voice from a recording")
        dlg.resize(560, 420)
        f = QFormLayout(dlg)
        path = QLineEdit()
        path.setReadOnly(True)
        pick = QPushButton("Choose…")
        pr = QHBoxLayout()
        pr.addWidget(path, 1)
        pr.addWidget(pick)
        pick.clicked.connect(lambda: path.setText(QFileDialog.getOpenFileName(
            dlg, "Recording", str(Path.home()), "Audio or video (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.mp4 *.mov)")[0]
            or path.text()))
        name = QLineEdit()
        name.setPlaceholderText("e.g. Rakschit — warm narrator")
        gender = QComboBox()
        gender.addItems(["male", "female"])
        character = QLineEdit("warm narrator")
        lang = QComboBox()
        for code in ("en", "hi", "es", "fr", "de", "it", "pt", "ru", "ja", "zh", "he", "ar"):
            lang.addItem(LANG_NAMES[code], code)
        owner = QLineEdit(getpass.getuser())
        owner.setPlaceholderText("Whose voice is this?")
        rights = QCheckBox("I own this recording, or the speaker has given written consent to clone their voice.")
        rights.setStyleSheet("QCheckBox { font-weight: 600; }")
        f.addRow("Recording", pr)
        f.addRow("Voice name", name)
        f.addRow("Gender", gender)
        f.addRow("Character", character)
        f.addRow("Recorded in", lang)
        f.addRow("Speaker", owner)
        f.addRow(rights)
        btns = QHBoxLayout()
        btns.addStretch()
        cancel, ok = QPushButton("Cancel"), QPushButton("Create voice")
        ok.setDefault(True)
        cancel.clicked.connect(dlg.reject)
        ok.clicked.connect(dlg.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        f.addRow(btns)
        while dlg.exec() == QDialog.Accepted:
            if not path.text() or not name.text().strip() or not owner.text().strip():
                QMessageBox.warning(dlg, "Missing information", "Choose a recording, name the voice and the speaker.")
                continue
            if not rights.isChecked():
                QMessageBox.warning(dlg, "Consent needed", "Confirm you own the recording or hold the speaker's consent.")
                continue
            break
        else:
            return
        from .consent import ConsentRegister

        reg = ConsentRegister()
        e = reg.valid_for(owner.text().strip()) or reg.add_declaration(
            owner.text().strip(), f"I confirm I own the recording “{Path(path.text()).name}” or hold the speaker's "
            f"written consent to create the voice “{name.text().strip()}” for Infinite Story LLP work.",
            recorded_by=getpass.getuser())
        args = dict(path=path.text(), name=name.text().strip(), gender=gender.currentText(),
                    character=character.text().strip() or "custom voice", lang=lang.currentData(),
                    owner=owner.text().strip(), rights="declared in VERBATIM", consent_id=e["id"])

        def work(progress):
            from .voicelab import create_from_recording

            return create_from_recording(progress=progress, **args)

        self.sub.button(1).setChecked(True)
        self.run(work, self.on_voice_created, "Creating the voice…")

    def on_voice_created(self, cv, err):
        self.busy(False)
        if err:
            QMessageBox.warning(self, "Could not create the voice", err)
            return
        self.log.emit(f"Custom voice created: {cv.name}")
        self.status.setText(f"Voice “{cv.name}” is ready — it is now at the top of the voice lists.")
        self.load_lab()
        self.fill_voices()
        self._refresh_log()

    def play_lab(self):
        vid = self._selected_voice()
        if not vid:
            return
        from .voicelab import get

        cv = get(vid)
        if cv and cv.ref_wav.exists():
            from .gui_editor import AudioPlayer

            if self.preview_player is None:
                self.preview_player = AudioPlayer()
            self.preview_player.play(cv.ref_wav, 0.0, 30.0)

    def clone_eleven(self):
        vid = self._selected_voice()
        if not vid:
            return
        from .voicelab import get, save

        cv = get(vid)
        if QMessageBox.question(self, "Clone to ElevenLabs", f"Upload the reference recording of “{cv.name}” to your "
                                "ElevenLabs account to create an instant voice clone? The audio leaves this "
                                "computer.") != QMessageBox.Yes:
            return

        def work(progress):
            from .tts_cloud import ElevenLabs

            files = [p for p in (cv.folder / "full_voice.wav", cv.ref_wav) if p.exists()][:1] or [cv.ref_wav]
            cv.eleven_id = ElevenLabs().clone(f"{cv.name} (VERBATIM)", files)
            save(cv)
            return cv

        self.run(work, lambda c, e: (self.busy(False), e and QMessageBox.warning(self, "Clone failed", e),
                                     self.load_lab()), "Uploading to ElevenLabs…")

    def revoice(self):
        """Voice changer: a recording in → the same performance in another voice out."""
        from .tts import voices_for

        dlg = QDialog(self)
        dlg.setWindowTitle("Re-voice a recording")
        dlg.resize(560, 260)
        f = QFormLayout(dlg)
        path = QLineEdit()
        path.setReadOnly(True)
        pick = QPushButton("Choose…")
        pr = QHBoxLayout()
        pr.addWidget(path, 1)
        pr.addWidget(pick)
        pick.clicked.connect(lambda: path.setText(QFileDialog.getOpenFileName(
            dlg, "Your performance", str(Path.home()), "Audio or video (*.wav *.mp3 *.m4a *.aac *.flac *.mp4 *.mov)")[0]
            or path.text()))
        target = QComboBox()
        for v in voices_for("en"):
            if v.engine in ("my", "st", "cb"):
                target.addItem(v.label, v.id)
        engine = QComboBox()
        engine.addItem("Chatterbox voice changer (23 languages)", "chatterbox")
        engine.addItem("OpenVoice tone colour (keeps every nuance)", "openvoice")
        f.addRow("Performance", pr)
        f.addRow("New voice", target)
        f.addRow("Method", engine)
        btns = QHBoxLayout()
        btns.addStretch()
        cancel, ok = QPushButton("Cancel"), QPushButton("Re-voice")
        cancel.clicked.connect(dlg.reject)
        ok.clicked.connect(dlg.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        f.addRow(btns)
        if dlg.exec() != QDialog.Accepted or not path.text():
            return
        src, vid, how = path.text(), target.currentData(), engine.currentData()
        out_dir = Path(self.w.s.output_dir) / "Voice Studio" / "Re-voiced"

        def work(progress):
            from .voicelab import revoice

            return revoice(src, vid, how, out_dir, progress)

        self.run(work, lambda p, err: (self.busy(False), QMessageBox.warning(self, "Re-voice failed", err) if err
                                       else (self.status.setText(f"Re-voiced: {Path(p).name}"), _open(Path(p).parent))),
                 "Re-voicing your performance…")

    def import_voices(self):
        import getpass

        from .voicelab import PACK_EXT, import_pack

        p, _ = QFileDialog.getOpenFileName(self, "Import voices", str(Path.home()), f"VERBATIM voices (*{PACK_EXT})")
        if not p:
            return
        if QMessageBox.question(self, "Import voices", "Only import voices you have the right to use. The owner named "
                                "in the pack is recorded in the consent register. Continue?") != QMessageBox.Yes:
            return
        try:
            got = import_pack(p, recorded_by=getpass.getuser())
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        self.status.setText(f"Imported {len(got)} voice(s): " + ", ".join(cv.name for cv in got) if got else
                            "Those voices are already in your library.")
        self.load_lab()
        self.fill_voices()
        self._refresh_log()

    def export_voices(self):
        from .voicelab import PACK_EXT, export_pack

        vid = self._selected_voice()
        ids = [vid] if vid else list(self.lids)
        if not ids:
            return
        p, _ = QFileDialog.getSaveFileName(self, "Export voices", str(Path.home() / f"VERBATIM voices{PACK_EXT}"),
                                           f"VERBATIM voices (*{PACK_EXT})")
        if p:
            out = export_pack(ids, p)
            self.status.setText(f"Exported {len(ids)} voice(s) to {out.name} — share it privately.")

    def delete_voice(self):
        vid = self._selected_voice()
        if vid and QMessageBox.question(self, "Delete voice", "Delete this custom voice from this computer?") \
                == QMessageBox.Yes:
            from .voicelab import delete

            delete(vid)
            self.load_lab()
            self.fill_voices()

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
