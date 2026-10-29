"""Image Lab: set up one scene, instrument and detector, preview the noiseless scene, simulate frames.

Left: the forms (scene, instrument, detector, exposure and output). Right: the
Setup View (live) and the Result viewer (noiseless scene and detector frames of
the last run). Runs go through :class:`RunnerProcess`, one at a time; the job
can also be saved, sent to the Sequence Builder or queued in the Sim Console.
"""
from __future__ import annotations

import datetime as _dt
import os

from qtpy import QtCore, QtGui, QtWidgets

from .. import theming
from ..backend import default_backend
from ..core import cost, model
from ..core.model import Job
from ..core.queue import gui_home, machine_limits
from ..core.validate import has_errors, validate_job
from .base import ThemedWindow
from .dialogs import JobPreviewDialog, NotesDialog, text_dialog
from .forms import DetectorForm, InstrumentForm, OutputRunForm, SceneForm, VisitForm
from .image_view import ImageView
from .runner_process import RunnerProcess
from .setup_view import SetupView
from .widgets.themed import Chip, Panel, SectionLabel


def _scroll(w: QtWidgets.QWidget) -> QtWidgets.QScrollArea:
    s = QtWidgets.QScrollArea()
    s.setWidgetResizable(True)
    s.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
    s.setWidget(w)
    return s


class ImageLabWindow(ThemedWindow):
    job_queued = QtCore.Signal(object)
    send_to_sequence = QtCore.Signal(object)
    run_finished = QtCore.Signal(bool)

    def __init__(self, parent=None, backend=None):
        super().__init__(parent, title="Image Lab")
        self.setObjectName("ImageLabWindow")
        self.backend = backend or default_backend()
        self.settings = theming.theme_manager().settings()
        self.job: Job = model.single_image_job()
        self.job.output.output_dir = os.path.join(os.path.expanduser("~"), "corgisim_out")
        self.job_path: str | None = None
        self.queue_handler = None          # callable(job) -> bool, set by app.ToolWindows
        self.sequence_handler = None       # callable(job)
        self.runner = RunnerProcess(self, self.backend)
        self.runner.line.connect(self._on_line)
        self.runner.event.connect(self._on_event)
        self.runner.finished.connect(self._on_finished)
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(200)
        self._refresh_timer.timeout.connect(self._refresh_setup)
        self._build_menus()
        self._build_body()
        self.load_job(self.job)
        self.resize(1480, 900)
        geo = self.settings.value("imagelab/geometry")
        if geo is not None:
            self.restoreGeometry(geo)

    # ------------------------------------------------------------------ menus
    def _build_menus(self):
        f = self.add_menu("&File")
        self._act(f, "New single image", self.new_job, "Ctrl+N")
        self._act(f, "Open job…", self.open_job_dialog, "Ctrl+O")
        self._act(f, "Open CPGS file…", self.open_cpgs_dialog)
        f.addSeparator()
        self._act(f, "Save job", self.save_job, "Ctrl+S")
        self._act(f, "Save job as…", self.save_job_as, "Ctrl+Shift+S")
        f.addSeparator()
        ex = f.addMenu("Examples")
        for key, text in (("image", "HLC band 1 with two companions"), ("pol", "Polarimetry (POL0)"),
                          ("spec", "Spectroscopy band 3 with prism and slit"), ("wfov", "SPC wide FOV band 4")):
            self._act(ex, text, lambda k=key: self.load_example(k))
        f.addSeparator()
        self._act(f, "Close", self.close, "Ctrl+W")
        r = self.add_menu("&Run")
        self.preview_act = self._act(r, "Preview noiseless scene", self.preview, "Ctrl+P")
        self.simulate_act = self._act(r, "Simulate frames", self.simulate, "Ctrl+Return")
        self.abort_act = self._act(r, "Abort", self.abort, "Ctrl+.")
        r.addSeparator()
        self._act(r, "Queue in Sim Console", self.queue_job, "Ctrl+Q")
        self._act(r, "Send to Sequence Builder", self.to_sequence)
        v = self.add_menu("&View")
        self._act(v, "Job JSON", self.view_json)
        self._act(v, "Run log", self.view_log)
        self._act(v, "Job notes", self.view_notes)
        self.add_theme_menu()
        self.add_help_menu()

    @staticmethod
    def _act(menu, text, slot, shortcut=None):
        a = menu.addAction(text)
        a.triggered.connect(lambda _=False: slot())
        if shortcut:
            a.setShortcut(QtGui.QKeySequence(shortcut))
        return a

    # ------------------------------------------------------------------ body
    def _build_body(self):
        theme = theming.current_theme()
        gap = theme.density.gap
        central = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(gap, gap, gap, gap)
        outer.setSpacing(gap)
        self.setCentralWidget(central)

        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        # forms
        self.scene_form = SceneForm(title="Host star")
        self.inst_form = InstrumentForm()
        self.det_form = DetectorForm()
        self.visit_form = VisitForm()
        lim = machine_limits()
        self.out_form = OutputRunForm(max_jobs=cost.max_parallel_jobs(lim["memory_gb"] or 16.0, lim["cpus"]) if lim else 1)
        self.tabs = QtWidgets.QTabWidget()
        for title, w in (("Scene", self.scene_form), ("Instrument", self.inst_form), ("Detector", self.det_form)):
            self.tabs.addTab(_scroll(self._wrap(w)), title)
        both = QtWidgets.QWidget()
        bl = QtWidgets.QVBoxLayout(both)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.visit_form)
        bl.addWidget(self.out_form)
        self.tabs.addTab(_scroll(self._wrap(both)), "Exposure && output")
        for form in (self.scene_form, self.inst_form, self.det_form, self.visit_form, self.out_form):
            form.changed.connect(self._on_edited)
        left = Panel()
        left.layout().addWidget(self.tabs)
        split.addWidget(left)

        # right: setup / result
        right = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(gap)
        self.right_tabs = QtWidgets.QTabWidget()
        self.setup = SetupView()
        self.right_tabs.addTab(self.setup, "Setup")
        self.result = ImageView()
        self.right_tabs.addTab(self.result, "Result")
        rl.addWidget(self.right_tabs, 1)

        # run row
        run_panel = Panel(layout="v")
        row = QtWidgets.QHBoxLayout()
        self.preview_btn = QtWidgets.QPushButton("Preview noiseless scene")
        self.preview_btn.setToolTip("Propagate the scene through the optics and show it; no detector (Ctrl+P)")
        self.preview_btn.clicked.connect(self.preview)
        self.simulate_btn = QtWidgets.QPushButton("Simulate")
        self.simulate_btn.setProperty("role", "primary")
        self.simulate_btn.setToolTip("Propagate, then simulate the detector frames and write them (Ctrl+Return)")
        self.simulate_btn.clicked.connect(self.simulate)
        self.abort_btn = QtWidgets.QPushButton("Abort")
        self.abort_btn.clicked.connect(self.abort)
        self.abort_btn.setEnabled(False)
        self.queue_btn = QtWidgets.QPushButton("Queue in console")
        self.queue_btn.clicked.connect(self.queue_job)
        self.seq_btn = QtWidgets.QPushButton("To Sequence Builder")
        self.seq_btn.clicked.connect(self.to_sequence)
        self.save_btn = QtWidgets.QPushButton("Save job…")
        self.save_btn.clicked.connect(self.save_job_as)
        for b in (self.preview_btn, self.simulate_btn, self.abort_btn, self.queue_btn, self.seq_btn, self.save_btn):
            row.addWidget(b)
        row.addStretch(1)
        self.cost_label = QtWidgets.QLabel("")
        self.cost_label.setProperty("role", "hint")
        row.addWidget(self.cost_label)
        run_panel.layout().addLayout(row)
        prow = QtWidgets.QHBoxLayout()
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label = QtWidgets.QLabel("ready")
        self.status_chip = Chip("idle", "dim")
        prow.addWidget(self.status_chip)
        prow.addWidget(self.status_label, 1)
        prow.addWidget(self.progress, 2)
        run_panel.layout().addLayout(prow)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setProperty("role", "log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setMaximumHeight(150)
        run_panel.layout().addWidget(self.log)
        rl.addWidget(run_panel)
        split.addWidget(right)
        split.setSizes([520, 960])
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)
        self.statusBar()

    @staticmethod
    def _wrap(w: QtWidgets.QWidget) -> QtWidgets.QWidget:
        box = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(w)
        lay.addStretch(1)
        return box

    # ------------------------------------------------------------------ job <-> forms
    def load_job(self, job: Job, path: str | None = None) -> None:
        if job.n_visits != 1:
            job = job.copy()
            job.visits = job.visits[:1] or [model.Visit(label="single image")]
            job.kind = "image"
        self.job = job
        self.job_path = path
        self.scene_form.load(job.scene)
        self.inst_form.load(job.instrument)
        self.det_form.load(job.detector)
        self.visit_form.load(job.visits[0])
        self.out_form.load(job.output, job.run)
        self._refresh_setup()
        self.setWindowTitle(f"Image Lab - {job.name}" + (f" ({os.path.basename(path)})" if path else ""))

    def apply_forms(self) -> Job:
        job = self.job
        self.scene_form.apply(job.scene)
        self.inst_form.apply(job.instrument)
        self.det_form.apply(job.detector)
        v = job.visits[0]
        self.visit_form.apply(v)
        v.roll_angle_deg = job.instrument.roll_angle_deg
        v.dpam = None
        self.out_form.apply(job.output, job.run)
        job.kind = "image"
        return job

    def _on_edited(self):
        self._refresh_timer.start()

    def strip_status(self, key: str) -> str | None:
        """Validation status of one optical-train cell (tests)."""
        return next((c.status for c in self.setup.strip.cells if c.key == key), None)

    def _refresh_setup(self):
        self.apply_forms()
        self.setup.set_job(self.job)
        est = cost.estimate(self.job)
        self.cost_label.setText(f"~{est.pretty_time}, {est.propagations} propagations, {est.frames + est.satspot_frames} frame(s)")
        errs = [i for i in self.setup.issues if i.level == "error"]
        self.simulate_btn.setEnabled(not errs and not self.runner.running)
        self.preview_btn.setEnabled(not errs and not self.runner.running)
        self.simulate_btn.setToolTip("Fix the errors in the Setup checks first" if errs else "Propagate, then simulate the detector frames and write them (Ctrl+Return)")

    # ------------------------------------------------------------------ file actions
    def new_job(self):
        job = model.single_image_job()
        job.output.output_dir = self.job.output.output_dir
        self.load_job(job)

    def load_example(self, kind: str):
        job = model.single_image_job()
        if kind == "pol":
            job.name = "polarimetry"
            job.instrument.dpam = "POL0"
            job.scene.point_sources.append(model.PointSource.from_polar(21.0, 300.0, 200.0, label="b"))
        elif kind == "spec":
            job.name = "spectroscopy"
            job.instrument = model.InstrumentSpec(cgi_mode="spec", cor_type="spc-spec_band3", bandpass="3F", dpam="PRISM3",
                                                  slit="R1C2", dm_solution="spc-spec_ni_2e-8")
            job.scene.point_sources.append(model.PointSource.from_polar(18.0, 270.0, 90.0, label="b"))
        elif kind == "wfov":
            job.name = "wide fov"
            job.instrument = model.InstrumentSpec(cor_type="spc-wide_band4", bandpass="4F", dm_solution="spc-wide_ni_5e-9")
            job.scene.point_sources.append(model.PointSource.from_polar(19.0, 700.0, 30.0, label="b"))
            job.scene.point_sources.append(model.PointSource.from_polar(21.0, 1000.0, 250.0, label="c"))
        else:
            job.name = "hlc band 1"
            job.scene.point_sources.append(model.PointSource.from_polar(20.0, 300.0, 45.0, label="b"))
            job.scene.point_sources.append(model.PointSource.from_polar(22.5, 480.0, 200.0, label="c"))
        job.output.output_dir = self.job.output.output_dir
        self.load_job(job)

    def open_job_dialog(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open job", self.job.output.output_dir or self.backend.home(), "Job JSON (*.json)")
        if p:
            self.load_job(Job.load(p), p)

    def open_cpgs_dialog(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open CPGS file", self.backend.home(), "CPGS XML (*.xml)")
        if p:
            from ..core.cpgs import load_job_from_cpgs
            job = load_job_from_cpgs(p, output_dir=self.job.output.output_dir)
            self.load_job(job)
            self.statusBar().showMessage(f"first of {job.n_visits} visits loaded; use the Sequence Builder for the whole file", 8000)

    def save_job(self):
        if not self.job_path:
            return self.save_job_as()
        self.apply_forms()
        self.job.save(self.job_path)
        self.statusBar().showMessage(f"saved {self.job_path}", 5000)

    def save_job_as(self):
        self.apply_forms()
        start = self.job_path or os.path.join(self.job.output.output_dir or self.backend.home(), f"{self.job.name}.json")
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save job", start, "Job JSON (*.json)")
        if p:
            self.job.save(p)
            self.job_path = p
            self.setWindowTitle(f"Image Lab - {self.job.name} ({os.path.basename(p)})")

    def view_json(self):
        self.apply_forms()
        JobPreviewDialog(self.job, self, title=f"{self.job.name} - job file").open()

    def view_log(self):
        text_dialog(self, "Run log", "\n".join(self.runner.log) if self.runner.log else "(no run yet)")

    def view_notes(self):
        NotesDialog("Job notes", self.job.notes or ["(no notes)"], self).open()

    # ------------------------------------------------------------------ running
    def _job_file_for_run(self, preview: bool) -> str:
        d = os.path.join(gui_home(), "imagelab")
        os.makedirs(d, exist_ok=True)
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        job = self.job.copy()
        job.run.preview_only = preview
        path = os.path.join(d, f"{stamp}_{'preview' if preview else 'simulate'}.json")
        job.save(path)
        return path

    def _start(self, preview: bool):
        if self.runner.running:
            return
        self.apply_forms()
        issues = validate_job(self.job)
        if has_errors(issues):
            text_dialog(self, "The job has errors", "\n".join(str(i) for i in issues), mono=False)
            return
        if self.job.output.save_fits and self.job.output.output_dir:
            self.backend.makedirs(self.job.output.output_dir)
        path = self._job_file_for_run(preview)
        self.result.clear()
        self.log.clear()
        cmd = self.runner.start(path, n_jobs=self.job.run.n_jobs, workdir=self.job.output.output_dir)
        self.log.appendPlainText("$ " + " ".join(cmd))
        self.progress.setValue(0)
        self.status_label.setText("starting…")
        self.status_chip.setText("preview" if preview else "running")
        self.status_chip.set_kind("run")
        self._set_running(True)
        self.right_tabs.setCurrentWidget(self.result)

    def preview(self):
        self._start(preview=True)

    def simulate(self):
        self._start(preview=False)

    def abort(self):
        self.runner.abort()
        self.status_label.setText("aborting…")

    def _set_running(self, on: bool):
        self.abort_btn.setEnabled(on)
        self.abort_act.setEnabled(on)
        self.preview_btn.setEnabled(not on)
        self.simulate_btn.setEnabled(not on)
        self.tabs.setEnabled(not on)

    def _on_line(self, line: str, stream: str):
        if line.startswith("corgisim_gui ") or stream == "stderr" or "Error" in line or "Warning" in line or line.startswith("$"):
            self.log.appendPlainText(line)

    def _on_event(self, ev):
        p = self.runner.parser
        if ev.kind in ("visit", "psf", "psf_done", "frame", "job"):
            self.status_label.setText(p.status_text())
            self.progress.setValue(int(100 * p.fraction))
        elif ev.kind == "preview":
            self.result.add_file(ev.data["path"], f"noiseless {os.path.basename(ev.data['path'])}", select=True)
        elif ev.kind == "output":
            self.result.add_file(ev.data["path"], os.path.basename(ev.data["path"]), select=True)
        elif ev.kind == "error":
            self.status_label.setText(ev.data.get("msg", "error"))

    def _on_finished(self, code: int, aborted: bool):
        p = self.runner.parser
        self._set_running(False)
        ok = code == 0 and p.finished is not False and not aborted
        self.progress.setValue(100 if ok else int(100 * p.fraction))
        if aborted:
            self.status_label.setText("aborted")
            self.status_chip.setText("aborted")
            self.status_chip.set_kind("warn")
        elif ok:
            n = len(p.outputs)
            self.status_label.setText(f"done in {p.elapsed or 0:.0f} s: {n} frame{'s' if n != 1 else ''} written, {len(p.previews)} noiseless image(s)")
            self.status_chip.setText("done")
            self.status_chip.set_kind("ok")
        else:
            err = p.errors[-1] if p.errors else f"exit code {code}"
            self.status_label.setText(f"failed: {err}")
            self.status_chip.setText("failed")
            self.status_chip.set_kind("err")
            if p.traceback:
                self.log.appendPlainText(p.traceback)
        self._refresh_setup()
        self.run_finished.emit(ok)

    # ------------------------------------------------------------------ hand-offs
    def queue_job(self):
        self.apply_forms()
        job = self.job.copy()
        if self.queue_handler is not None and self.queue_handler(job):
            self.statusBar().showMessage(f"queued {job.name} in the Sim Console", 5000)
        self.job_queued.emit(job)

    def to_sequence(self):
        self.apply_forms()
        job = self.job.copy()
        job.kind = "sequence"
        if self.sequence_handler is not None:
            self.sequence_handler(job)
        self.send_to_sequence.emit(job)

    def theme_changed(self, theme):
        self.setup.theme_changed(theme)
        self.result.theme_changed()

    def closeEvent(self, event):
        if self.runner.running:
            r = QtWidgets.QMessageBox.question(self, "A simulation is running", "Abort it and close?",
                                               QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
            if r != QtWidgets.QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.runner.abort()
            self.runner.wait(5000)
        self.settings.setValue("imagelab/geometry", self.saveGeometry())
        super().closeEvent(event)
