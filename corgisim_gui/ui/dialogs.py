"""Small dialogs shared by the windows."""
from __future__ import annotations

import os

from qtpy import QtWidgets

from ..core.model import Job
from .widgets.themed import SectionLabel


def text_dialog(parent, title: str, text: str, mono: bool = True):
    """A scrollable read-only text box (tracebacks, logs, notes)."""
    d = QtWidgets.QDialog(parent)
    d.setWindowTitle(title)
    d.resize(760, 520)
    lay = QtWidgets.QVBoxLayout(d)
    ed = QtWidgets.QPlainTextEdit()
    if mono:
        ed.setProperty("role", "log")
    ed.setReadOnly(True)
    ed.setPlainText(text)
    lay.addWidget(ed, 1)
    bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
    bb.rejected.connect(d.reject)
    bb.accepted.connect(d.accept)
    lay.addWidget(bb)
    d.open()
    return d


class JobPreviewDialog(QtWidgets.QDialog):
    """Read-only JSON of a job, with Save as…"""

    def __init__(self, job: Job, parent=None, title: str = "Job file"):
        super().__init__(parent)
        self.job = job
        self.setWindowTitle(title)
        self.resize(760, 640)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(SectionLabel(f"{job.name}: {job.n_visits} visit(s), {job.total_frames} frame(s)"))
        ed = QtWidgets.QPlainTextEdit()
        ed.setProperty("role", "log")
        ed.setReadOnly(True)
        ed.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        ed.setPlainText(job.to_json())
        lay.addWidget(ed, 1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        save = QtWidgets.QPushButton("Save as…")
        save.clicked.connect(self.save)
        close = QtWidgets.QPushButton("Close")
        close.setProperty("role", "primary")
        close.clicked.connect(self.accept)
        row.addWidget(save)
        row.addWidget(close)
        lay.addLayout(row)

    def save(self):
        start = os.path.join(self.job.output.output_dir or os.path.expanduser("~"), f"{self.job.name}.json")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save job", start, "Job JSON (*.json)")
        if path:
            self.job.save(path)


class NotesDialog(QtWidgets.QDialog):
    """What the CPGS translation did and what corgisim ignores: shown after an import."""

    def __init__(self, title: str, notes: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 420)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(SectionLabel(f"{len(notes)} note(s)"))
        lst = QtWidgets.QListWidget()
        lst.setWordWrap(True)
        for n in notes:
            lst.addItem(n)
        lay.addWidget(lst, 1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
