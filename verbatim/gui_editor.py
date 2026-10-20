"""Transcript editor window: listen, correct, rename speakers, save → every export is rewritten."""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAbstractTextDocumentLayout, QColor, QKeySequence, QPalette, QShortcut, QTextDocument
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem, QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import ui_theme as th
from .editing import EditSession, segment_html
from .platform_info import IS_MAC, IS_WINDOWS, ffmpeg_path


def _T() -> dict:
    from . import gui

    return gui.T


def mmss(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"


# ====================================================================== audio
class AudioPlayer(QObject):
    """Plays a slice of the original media with the system player (no extra Qt modules needed)."""
    stopped = Signal()

    def __init__(self):
        super().__init__()
        self.proc = None
        self.started = 0.0
        self.offset = 0.0
        self.length = 0.0
        self.tmp = Path(tempfile.gettempdir()) / f"verbatim_play_{os.getpid()}.wav"
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._tick)

    def playing(self) -> bool:
        return self.started > 0

    def position(self) -> float:
        return self.offset + (time.monotonic() - self.started) if self.playing() else self.offset

    def play(self, media: Path, start: float, length: float = 120.0) -> str | None:
        self.stop()
        flags = 0x08000000 if IS_WINDOWS else 0
        r = subprocess.run([ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-ss", f"{start:.3f}",
                            "-i", str(media), "-t", f"{length:.3f}", "-vn", "-ac", "1", "-ar", "22050", "-c:a",
                            "pcm_s16le", str(self.tmp)], capture_output=True, creationflags=flags)
        if r.returncode != 0 or not self.tmp.exists():
            return (r.stderr or b"").decode(errors="replace")[-300:] or "could not read audio"
        try:
            if IS_WINDOWS:
                import winsound

                winsound.PlaySound(str(self.tmp), winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                cmd = ["afplay", str(self.tmp)] if IS_MAC else ["paplay", str(self.tmp)]
                self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            return str(exc)
        import wave

        with wave.open(str(self.tmp)) as w:
            self.length = w.getnframes() / w.getframerate()
        self.offset, self.started = start, time.monotonic()
        self.timer.start()
        return None

    def stop(self):
        if IS_WINDOWS:
            try:
                import winsound

                winsound.PlaySound(None, 0)
            except Exception:
                pass
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None
        was = self.playing()
        self.started = 0.0
        self.timer.stop()
        if was:
            self.stopped.emit()

    def _tick(self):
        if not self.playing():
            return
        done = time.monotonic() - self.started >= self.length
        if self.proc is not None and self.proc.poll() is not None:
            done = True
        if done:
            self.stop()

    def __del__(self):
        try:
            self.tmp.unlink(missing_ok=True)
        except Exception:
            pass


# ====================================================================== rich text cells
class HtmlDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        html = index.data(Qt.UserRole + 1) or opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else None
        if style:
            style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        doc = QTextDocument()
        doc.setDefaultFont(opt.font)
        doc.setTextWidth(opt.rect.width() - 16)
        doc.setHtml(f"<div style='color:{_T()['ink']}'>{html}</div>")
        painter.save()
        painter.translate(opt.rect.left() + 8, opt.rect.top() + max(4, (opt.rect.height() - doc.size().height()) / 2))
        ctx = QAbstractTextDocumentLayout.PaintContext()
        ctx.palette.setColor(QPalette.Text, QColor(_T()["ink"]))
        doc.documentLayout().draw(painter, ctx)
        painter.restore()

    def sizeHint(self, option, index):
        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        table = self.parent()
        width = table.columnWidth(index.column()) if hasattr(table, "columnWidth") else option.rect.width()
        doc.setTextWidth(max(200, width - 16))
        doc.setHtml(index.data(Qt.UserRole + 1) or index.data() or "")
        return QSize(int(doc.idealWidth()), int(doc.size().height()) + 14)

    def createEditor(self, parent, option, index):
        e = QLineEdit(parent)
        e.setFrame(False)
        return e

    def setEditorData(self, editor, index):
        editor.setText(index.data(Qt.EditRole) or "")


class SpeakerDelegate(QStyledItemDelegate):
    def __init__(self, names_fn, parent=None):
        super().__init__(parent)
        self.names_fn = names_fn

    def createEditor(self, parent, option, index):
        c = QComboBox(parent)
        c.setEditable(True)
        c.addItems(self.names_fn())
        return c

    def setEditorData(self, editor, index):
        editor.setCurrentText(index.data(Qt.EditRole) or "")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText().strip(), Qt.EditRole)


# ====================================================================== window
class EditorWindow(QDialog):
    saved = Signal(str, dict)  # json path, outputs

    def __init__(self, json_path: str, settings, parent=None):
        super().__init__(parent)
        self.s = settings
        self.ed = EditSession(json_path)
        self.dirty = False
        self.loading = False
        self.player = AudioPlayer()
        self.player.stopped.connect(self.on_stopped)
        self.setWindowTitle(f"Edit transcript — {self.ed.payload.get('source_file', Path(json_path).stem)}")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(1180, 820)
        self.setObjectName("editor")
        T = _T()
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(12)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        name = QLabel(self.ed.payload.get("source_file", ""))
        name.setObjectName("h2")
        titles.addWidget(name)
        info = self.ed.payload.get("info", {})
        lang = self.ed.t.language
        self.meta = QLabel(f"{mmss(info.get('duration', 0))} · {lang} · {self.ed.t.engine} {self.ed.t.model}".strip())
        self.meta.setObjectName("hint")
        titles.addWidget(self.meta)
        head.addLayout(titles, 1)
        self.play_btn = QPushButton("  Play line")
        self.play_btn.setIcon(th.icon("play", T["ink"], 14))
        self.play_btn.setToolTip("Play the selected line and keep going (Space)")
        self.play_btn.clicked.connect(self.toggle_play)
        head.addWidget(self.play_btn)
        b = QPushButton("  Open folder")
        b.setIcon(th.icon("open", T["ink"], 15))
        b.clicked.connect(self.open_folder)
        head.addWidget(b)
        self.save_btn = QPushButton("  Save && update exports")
        self.save_btn.setObjectName("start")
        self.save_btn.setStyleSheet("font-size:14px; padding:10px 18px;")
        self.save_btn.setIcon(th.icon("check", "#FFFFFF", 16))
        self.save_btn.clicked.connect(self.save)
        head.addWidget(self.save_btn)
        v.addLayout(head)

        bar = QHBoxLayout()
        lab = QLabel("Speakers")
        lab.setObjectName("h3")
        bar.addWidget(lab)
        self.spk_row = QHBoxLayout()
        self.spk_row.setSpacing(6)
        bar.addLayout(self.spk_row)
        bar.addStretch()
        self.only_review = QCheckBox("Only lines with uncertain words")
        self.only_review.toggled.connect(self.apply_filter)
        bar.addWidget(self.only_review)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find…")
        self.find.setFixedWidth(200)
        self.find.addAction(th.icon("search", T["muted"], 16), QLineEdit.LeadingPosition)
        self.find.textChanged.connect(self.apply_filter)
        bar.addWidget(self.find)
        v.addLayout(bar)

        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 10, 10, 10)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Time", "Speaker", "Text  (double-click to edit)"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setColumnWidth(0, 86)
        self.table.setColumnWidth(1, 150)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setItemDelegateForColumn(2, HtmlDelegate(self.table))
        self.table.setItemDelegateForColumn(1, SpeakerDelegate(self.ed.speakers, self.table))
        self.table.itemChanged.connect(self.on_item_changed)
        self.table.cellClicked.connect(self.on_click)
        cl.addWidget(self.table)
        v.addWidget(card, 1)

        foot = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("hint")
        foot.addWidget(self.status, 1)
        legend = QLabel(f"<span style='background:{self.hl()[0]}; color:{self.hl()[1]}'>&nbsp;highlighted&nbsp;</span>"
                        "&nbsp; = uncertain word · click a time to hear that line · Space = play / stop")
        legend.setObjectName("hint")
        foot.addWidget(legend)
        v.addLayout(foot)
        QShortcut(QKeySequence(Qt.Key_Space), self.table, activated=self.toggle_play)
        self.table.viewport().installEventFilter(self)
        self.fill()
        self.refresh_speakers()

    # ------------------------------------------------------------ data → table
    @staticmethod
    def hl() -> tuple[str, str]:
        return ("#FFE7A3", "#5A4300") if _T()["name"] == "light" else ("#5A4A14", "#FFE7A3")

    def fill(self):
        self.loading = True
        segs = self.ed.t.segments
        self.table.setRowCount(len(segs))
        for i, seg in enumerate(segs):
            it = QTableWidgetItem(mmss(seg.start))
            it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            it.setForeground(QColor(_T()["sub"]))
            self.table.setItem(i, 0, it)
            sp = QTableWidgetItem(seg.speaker or "")
            self.table.setItem(i, 1, sp)
            self.set_text_item(i)
        self.table.resizeRowsToContents()
        self.loading = False
        self.update_status()

    def set_text_item(self, i: int):
        seg = self.ed.t.segments[i]
        it = self.table.item(i, 2) or QTableWidgetItem()
        it.setData(Qt.EditRole, seg.text.strip())
        it.setData(Qt.UserRole + 1, segment_html(seg, self.ed.threshold, self.hl()))
        if self.table.item(i, 2) is None:
            self.table.setItem(i, 2, it)

    def uncertain(self, seg) -> int:
        return sum(1 for w in seg.words if w.prob is not None and w.prob < self.ed.threshold)

    def update_status(self):
        n = sum(1 for s in self.ed.t.segments if self.uncertain(s))
        state = "Unsaved changes" if self.dirty else "All changes saved"
        self.status.setText(f"{len(self.ed.t.segments)} lines · {n} with uncertain words · {state}")
        self.save_btn.setEnabled(self.dirty)

    def refresh_speakers(self):
        while self.spk_row.count():
            w = self.spk_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        for name in self.ed.speakers():
            b = QPushButton(name)
            b.setObjectName("pillBtn")
            b.setStyleSheet("min-height:30px; max-height:30px; border-radius:15px; padding:0 14px;")
            b.setToolTip("Rename this speaker everywhere in the file (and remember the voice)")
            b.clicked.connect(lambda _=False, n=name: self.rename_speaker(n))
            self.spk_row.addWidget(b)

    def apply_filter(self, *_):
        q = self.find.text().strip().lower()
        only = self.only_review.isChecked()
        for i, seg in enumerate(self.ed.t.segments):
            hide = (only and not self.uncertain(seg)) or (q and q not in seg.text.lower()
                                                         and q not in (seg.speaker or "").lower())
            self.table.setRowHidden(i, bool(hide))

    # ------------------------------------------------------------ edits
    def on_item_changed(self, it: QTableWidgetItem):
        if self.loading:
            return
        i, col = it.row(), it.column()
        if col == 2:
            if self.ed.set_text(i, it.data(Qt.EditRole) or ""):
                self.mark_dirty()
            self.loading = True
            self.set_text_item(i)
            self.loading = False
            self.table.resizeRowToContents(i)
        elif col == 1:
            new = (it.text() or "").strip()
            if new and new != self.ed.t.segments[i].speaker:
                self.ed.set_speaker(i, new)
                self.mark_dirty()
                self.refresh_speakers()

    def rename_speaker(self, old: str):
        from .speakers import SpeakerLibrary

        lib = SpeakerLibrary()
        dlg = QDialog(self)
        dlg.setWindowTitle("Rename speaker")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"Rename “{old}” everywhere in this file to:"))
        box = QComboBox()
        box.setEditable(True)
        box.addItems([n for n in lib.names() if n != old])
        box.setCurrentText("" if old.startswith("Speaker ") else old)
        lay.addWidget(box)
        prof = self.ed.profile(old)
        remember = QCheckBox("Remember this voice — label it automatically in future files")
        remember.setChecked(prof is not None)
        remember.setEnabled(prof is not None)
        if prof is None:
            remember.setToolTip("No voice fingerprint for this speaker (transcribed before 3.1, or too little speech).")
        lay.addWidget(remember)
        row = QHBoxLayout()
        row.addStretch()
        ok = QPushButton("Rename")
        ok.setDefault(True)
        ok.clicked.connect(dlg.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dlg.reject)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        if dlg.exec() != QDialog.Accepted:
            return
        new = box.currentText().strip()
        if not new:
            return
        if new != old and self.ed.rename_speaker(old, new):
            self.mark_dirty()
            self.loading = True
            for i, seg in enumerate(self.ed.t.segments):
                self.table.item(i, 1).setText(seg.speaker or "")
            self.loading = False
        if remember.isChecked() and prof is not None:
            lib.enroll(new, prof, source=self.ed.payload.get("source_file", ""))
            self.status.setText(f"{new}'s voice saved — VERBATIM will recognise it in new files.")
        self.refresh_speakers()

    def mark_dirty(self):
        self.dirty = True
        self.update_status()

    def save(self):
        if not self.dirty:
            return True
        self.player.stop()
        try:
            out = self.ed.save(self.s)
        except Exception as exc:
            QMessageBox.warning(self, "Could not save", f"{type(exc).__name__}: {exc}")
            return False
        self.dirty = False
        self.update_status()
        self.status.setText(self.status.text() + " — all exports and the Master Excel Log updated")
        self.saved.emit(str(self.ed.path), out)
        return True

    # ------------------------------------------------------------ audio
    def media(self) -> Path | None:
        p = self.ed.source
        return p if p.exists() else None

    def on_click(self, row: int, col: int):
        if col == 0:
            self.play_row(row)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self.table.resizeRowsToContents)

    def eventFilter(self, obj, ev):
        if obj is self.table.viewport() and ev.type() == QEvent.MouseButtonDblClick:
            idx = self.table.indexAt(ev.position().toPoint())
            if idx.isValid() and idx.column() == 0:
                self.play_row(idx.row())
                return True
        return super().eventFilter(obj, ev)

    def toggle_play(self):
        if self.player.playing():
            self.player.stop()
            return
        rows = self.table.selectionModel().selectedRows()
        self.play_row(rows[0].row() if rows else 0)

    def play_row(self, row: int):
        m = self.media()
        if m is None:
            self.status.setText("Original media not found (moved or renamed) — playback unavailable.")
            return
        seg = self.ed.t.segments[row]
        err = self.player.play(m, max(0.0, seg.start - 0.15))
        if err:
            self.status.setText("Could not play audio: " + err)
            return
        self.play_btn.setText("  Stop")
        self.follow = QTimer(self)
        self.follow.setInterval(250)
        self.follow.timeout.connect(self.follow_playback)
        self.follow.start()

    def follow_playback(self):
        if not self.player.playing():
            return
        pos = self.player.position()
        for i, seg in enumerate(self.ed.t.segments):
            if seg.start <= pos < seg.end + 0.3:
                if self.table.currentRow() != i:
                    self.table.selectRow(i)
                    self.table.scrollToItem(self.table.item(i, 0), QAbstractItemView.EnsureVisible)
                break

    def on_stopped(self):
        self.play_btn.setText("  Play line")
        if getattr(self, "follow", None):
            self.follow.stop()

    def open_folder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ed.path.parent)))

    def closeEvent(self, e):
        if self.dirty:
            r = QMessageBox.question(self, "Unsaved changes", "Save your changes before closing?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel or (r == QMessageBox.Save and not self.save()):
                e.ignore()
                return
        self.player.stop()
        e.accept()

    def reject(self):  # Esc
        self.close()


def open_editor(json_path: str, settings, parent=None) -> EditorWindow | None:
    if not json_path or not Path(json_path).exists():
        QMessageBox.information(parent, "No transcript data",
                                "This file's transcript data (JSON) was not found — transcribe it again to edit.")
        return None
    w = EditorWindow(json_path, settings, parent)
    w.setAttribute(Qt.WA_DeleteOnClose, True)
    w.show()
    return w

