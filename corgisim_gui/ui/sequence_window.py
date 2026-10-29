"""Sequence Builder: a table of visits (by hand, from templates or from a CPGS file) plus the shared setup.

Left: the visits table and, below it, tabs for the target scene, the reference
scene, the instrument, the detector and the output. Right: the Setup View for
the selected visit. The job is saved as JSON or queued in the Sim Console.
"""
from __future__ import annotations

import os
from typing import Any

from qtpy import QtCore, QtGui, QtWidgets

from .. import theming
from ..backend import default_backend
from ..core import cost, model, tables
from ..core.cpgs import CpgsError, job_from_cpgs, read_cpgs, summarize
from ..core.model import Job, SatSpotBlock, Visit
from ..core.queue import machine_limits
from .base import ThemedWindow
from .dialogs import JobPreviewDialog, NotesDialog, text_dialog
from .forms import DetectorForm, InstrumentForm, OutputRunForm, SceneForm
from .setup_view import SetupView
from .widgets.themed import Chip, Panel, SectionLabel

Qt = QtCore.Qt

COLUMNS = [
    ("#", None), ("label", "label"), ("type", "vistype"), ("roll (°)", "roll_angle_deg"), ("frames", "n_frames"),
    ("exp (s)", "exptime_s"), ("gain", "em_gain"), ("PC", "photon_counting"), ("DPAM", "dpam"), ("ref", "is_reference"),
    ("spot frames", "sat_n"), ("spot exp (s)", "sat_exp"), ("spot gain", "sat_gain"), ("visit #", "visit_num"), ("est. time", None),
]


class VisitsModel(QtCore.QAbstractTableModel):
    """Editable table over ``job.visits``."""

    edited = QtCore.Signal()

    def __init__(self, job: Job, parent=None):
        super().__init__(parent)
        self.job = job
        self._est: dict[int, float] = {}

    def set_job(self, job: Job):
        self.beginResetModel()
        self.job = job
        self.endResetModel()

    def refresh(self):
        self.beginResetModel()
        try:
            est = cost.estimate(self.job)
            self._est = {d["index"]: d["seconds"] for d in est.per_visit}
        except Exception:  # noqa: BLE001
            self._est = {}
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.job.visits)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section][0]
        if role == Qt.ItemDataRole.DisplayRole:
            return section + 1
        return None

    def flags(self, index):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        key = COLUMNS[index.column()][1]
        if key in ("photon_counting", "is_reference"):
            return f | Qt.ItemFlag.ItemIsUserCheckable
        if key is not None:
            return f | Qt.ItemFlag.ItemIsEditable
        return f

    def _value(self, v: Visit, key: str) -> Any:
        if key == "sat_n":
            return v.satspots.n_frames if v.satspots else 0
        if key == "sat_exp":
            return v.satspots.exptime_s if v.satspots else 0.0
        if key == "sat_gain":
            return v.satspots.em_gain if v.satspots else 0.0
        if key == "em_gain":
            return v.em_gain if v.em_gain is not None else self.job.detector.em_gain
        if key == "photon_counting":
            return self.job.visit_photon_counting(v)
        if key == "dpam":
            return v.dpam if v.dpam is not None else self.job.instrument.dpam
        return getattr(v, key)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        v = self.job.visits[index.row()]
        key = COLUMNS[index.column()][1]
        if role == Qt.ItemDataRole.CheckStateRole and key in ("photon_counting", "is_reference"):
            return Qt.CheckState.Checked if self._value(v, key) else Qt.CheckState.Unchecked
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if key is None:
                if index.column() == 0:
                    return index.row() + 1
                sec = self._est.get(index.row())
                return cost.pretty_seconds(sec) if sec is not None else ""
            if key in ("photon_counting", "is_reference"):
                return None
            val = self._value(v, key)
            if key == "vistype":
                return val.replace("CGIVST_TDD_", "") if role == Qt.ItemDataRole.DisplayRole else val
            if key == "dpam" and val == "None":
                return "imaging" if role == Qt.ItemDataRole.DisplayRole else val
            if isinstance(val, float):
                return f"{val:g}"
            return val
        if role == Qt.ItemDataRole.ForegroundRole and key == "is_reference" and v.is_reference:
            return QtGui.QColor(theming.current_theme().palette.secondary)
        if role == Qt.ItemDataRole.TextAlignmentRole and key in ("roll_angle_deg", "n_frames", "exptime_s", "em_gain", "sat_n", "sat_exp", "sat_gain") or index.column() in (0, len(COLUMNS) - 1):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            return {"vistype": "one of " + ", ".join(tables.VISIT_TYPES),
                    "dpam": "imaging, POL0, POL45 (excam) or None, PRISM2, PRISM3 (spec)",
                    "sat_n": "satellite-spot frames of each kind (background, positive, negative); 0 = none",
                    "em_gain": "EM gain for this visit (blank entry = detector default)",
                    "visit_num": "3-digit visit number appended to the VISITID root"}.get(key, "")
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid():
            return False
        v = self.job.visits[index.row()]
        key = COLUMNS[index.column()][1]
        try:
            if role == Qt.ItemDataRole.CheckStateRole:
                on = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value, 2, True)
                if key == "photon_counting":
                    v.photon_counting = on
                elif key == "is_reference":
                    v.is_reference = on
                    if on and self.job.reference_scene is None:
                        self.job.reference_scene = model.SceneSpec(host=model.HostStar(vmag=3.0, spectral_type="A0V", name="REFERENCE"), ref_flag=True)
            elif key == "label":
                v.label = str(value)
            elif key == "vistype":
                s = str(value).strip().upper()
                if not s.startswith("CGIVST_"):
                    s = "CGIVST_TDD_" + s
                v.vistype = s
            elif key == "roll_angle_deg":
                v.roll_angle_deg = float(value)
            elif key == "n_frames":
                v.n_frames = max(0, int(float(value)))
            elif key == "exptime_s":
                v.exptime_s = float(value)
            elif key == "em_gain":
                s = str(value).strip()
                v.em_gain = float(s) if s else None
            elif key == "dpam":
                s = str(value).strip()
                v.dpam = "None" if s.lower() in ("", "none", "imaging") else s.upper()
            elif key == "visit_num":
                s = str(value).strip()
                v.visit_num = s.zfill(3)[-3:] if s else ""
            elif key in ("sat_n", "sat_exp", "sat_gain"):
                n = int(float(value)) if key == "sat_n" else (v.satspots.n_frames if v.satspots else 1)
                if key == "sat_n" and n <= 0:
                    v.satspots = None
                else:
                    if v.satspots is None:
                        v.satspots = SatSpotBlock(n_frames=1, exptime_s=1.0, em_gain=self.job.detector.em_gain)
                    if key == "sat_n":
                        v.satspots.n_frames = n
                    elif key == "sat_exp":
                        v.satspots.exptime_s = float(value)
                    else:
                        v.satspots.em_gain = float(value)
            else:
                return False
        except (TypeError, ValueError):
            return False
        self.dataChanged.emit(index, index)
        self.edited.emit()
        return True


class SequenceWindow(ThemedWindow):
    job_queued = QtCore.Signal(object)
    send_to_imagelab = QtCore.Signal(object)

    def __init__(self, parent=None, backend=None):
        super().__init__(parent, title="Sequence Builder")
        self.setObjectName("SequenceWindow")
        self.backend = backend or default_backend()
        self.settings = theming.theme_manager().settings()
        self.job: Job = model.roll_sequence_job()
        self.job.output.output_dir = os.path.join(os.path.expanduser("~"), "corgisim_out")
        self.job_path: str | None = None
        self.queue_handler = None
        self.imagelab_handler = None
        self.model = VisitsModel(self.job)
        self.model.edited.connect(self._on_edited)
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(200)
        self._refresh_timer.timeout.connect(self._refresh)
        self._build_menus()
        self._build_body()
        self.load_job(self.job)
        self.resize(1560, 940)
        geo = self.settings.value("sequence/geometry")
        if geo is not None:
            self.restoreGeometry(geo)

    # ------------------------------------------------------------------ menus
    def _build_menus(self):
        f = self.add_menu("&File")
        self._act(f, "New sequence", self.new_job, "Ctrl+N")
        self._act(f, "Open job…", self.open_job_dialog, "Ctrl+O")
        self._act(f, "Import CPGS file…", self.import_cpgs_dialog, "Ctrl+I")
        f.addSeparator()
        self._act(f, "Save job", self.save_job, "Ctrl+S")
        self._act(f, "Save job as…", self.save_job_as, "Ctrl+Shift+S")
        f.addSeparator()
        t = f.addMenu("Templates")
        self._act(t, "Reference + target at two rolls", lambda: self.load_template("rolls"))
        self._act(t, "Polarimetry pair (POL0, POL45)", lambda: self.load_template("pol"))
        self._act(t, "Target at two rolls with satellite spots", lambda: self.load_template("satspots"))
        f.addSeparator()
        self._act(f, "Close", self.close, "Ctrl+W")
        e = self.add_menu("&Visits")
        self._act(e, "Add visit", self.add_visit, "Ctrl+Shift+N")
        self._act(e, "Duplicate selected", self.duplicate_visit, "Ctrl+D")
        self._act(e, "Remove selected", self.remove_visit, "Delete")
        self._act(e, "Move up", lambda: self.move_visit(-1), "Ctrl+Up")
        self._act(e, "Move down", lambda: self.move_visit(1), "Ctrl+Down")
        r = self.add_menu("&Run")
        self._act(r, "Queue in Sim Console", self.queue_job, "Ctrl+Q")
        self._act(r, "Open selected visit in Image Lab", self.to_imagelab)
        v = self.add_menu("&View")
        self._act(v, "Job JSON", self.view_json)
        self._act(v, "Import notes", self.view_notes)
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
        split = QtWidgets.QSplitter(Qt.Orientation.Horizontal)

        left = QtWidgets.QSplitter(Qt.Orientation.Vertical)
        vpanel = Panel()
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setMinimumSectionSize(40)
        hh.setStretchLastSection(True)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Interactive)
        hh.resizeSection(1, 150)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)
        vpanel.layout().addWidget(self.table, 1)
        brow = QtWidgets.QHBoxLayout()
        for text, slot in (("Add visit", self.add_visit), ("Duplicate", self.duplicate_visit), ("Remove", self.remove_visit),
                           ("▲", lambda: self.move_visit(-1)), ("▼", lambda: self.move_visit(1))):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(lambda _=False, s=slot: s())
            brow.addWidget(b)
        brow.addStretch(1)
        self.totals = QtWidgets.QLabel("")
        self.totals.setProperty("role", "hint")
        brow.addWidget(self.totals)
        vpanel.layout().addLayout(brow)
        self.visits_label = SectionLabel("Visits")
        left.addWidget(self._section(self.visits_label, vpanel))

        self.scene_form = SceneForm(title="Target")
        self.ref_form = SceneForm(title="Reference star", reference=True)
        self.ref_enable = QtWidgets.QCheckBox("this sequence has a reference star (PSF reference, ref_flag)")
        self.inst_form = InstrumentForm()
        self.det_form = DetectorForm()
        lim = machine_limits()
        self.out_form = OutputRunForm(max_jobs=cost.max_parallel_jobs(lim["memory_gb"] or 16.0, lim["cpus"]))
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._scroll(self.scene_form), "Target")
        refbox = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(refbox)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.ref_enable)
        rl.addWidget(self.ref_form)
        self.tabs.addTab(self._scroll(refbox), "Reference")
        self.tabs.addTab(self._scroll(self.inst_form), "Instrument")
        self.tabs.addTab(self._scroll(self.det_form), "Detector")
        self.tabs.addTab(self._scroll(self.out_form), "Output && run")
        for form in (self.scene_form, self.ref_form, self.inst_form, self.det_form, self.out_form):
            form.changed.connect(self._on_edited)
        self.ref_enable.toggled.connect(self._on_edited)
        fpanel = Panel()
        fpanel.layout().addWidget(self.tabs)
        left.addWidget(self._section(SectionLabel("Shared setup"), fpanel))
        left.setSizes([360, 520])
        split.addWidget(left)

        right = QtWidgets.QWidget()
        rlay = QtWidgets.QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.setSpacing(gap)
        self.setup = SetupView()
        self.setup.visit_changed.connect(self._select_row)
        rlay.addWidget(self.setup, 1)
        run_panel = Panel(layout="h")
        self.queue_btn = QtWidgets.QPushButton("Queue in console")
        self.queue_btn.setProperty("role", "primary")
        self.queue_btn.clicked.connect(self.queue_job)
        self.save_btn = QtWidgets.QPushButton("Save job…")
        self.save_btn.clicked.connect(self.save_job_as)
        self.lab_btn = QtWidgets.QPushButton("Open visit in Image Lab")
        self.lab_btn.clicked.connect(self.to_imagelab)
        self.cpgs_btn = QtWidgets.QPushButton("Import CPGS…")
        self.cpgs_btn.clicked.connect(self.import_cpgs_dialog)
        for b in (self.cpgs_btn, self.lab_btn, self.save_btn, self.queue_btn):
            run_panel.layout().addWidget(b)
        run_panel.layout().addStretch(1)
        self.cost_label = QtWidgets.QLabel("")
        self.cost_label.setProperty("role", "hint")
        run_panel.layout().addWidget(self.cost_label)
        self.status_chip = Chip("", "dim")
        self.status_chip.setVisible(False)
        run_panel.layout().addWidget(self.status_chip)
        rlay.addWidget(run_panel)
        split.addWidget(right)
        split.setSizes([700, 860])
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)
        self.statusBar()

    @staticmethod
    def _section(label, body):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(label)
        lay.addWidget(body, 1)
        return w

    @staticmethod
    def _scroll(w):
        box = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(w)
        lay.addStretch(1)
        s = QtWidgets.QScrollArea()
        s.setWidgetResizable(True)
        s.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        s.setWidget(box)
        return s

    # ------------------------------------------------------------------ job <-> widgets
    def load_job(self, job: Job, path: str | None = None):
        job.kind = "sequence"
        self.job = job
        self.job_path = path
        self.model.set_job(job)
        self.scene_form.load(job.scene)
        self.ref_enable.blockSignals(True)
        self.ref_enable.setChecked(job.reference_scene is not None)
        self.ref_enable.blockSignals(False)
        self.ref_form.load(job.reference_scene or model.SceneSpec(host=model.HostStar(vmag=3.0, spectral_type="A0V", name="REFERENCE"), ref_flag=True))
        self.inst_form.load(job.instrument)
        self.det_form.load(job.detector)
        self.out_form.load(job.output, job.run)
        self._refresh()
        if job.visits:
            self.table.selectRow(0)
        self.setWindowTitle(f"Sequence Builder - {job.name}" + (f" ({os.path.basename(path)})" if path else ""))

    def apply_forms(self) -> Job:
        job = self.job
        self.scene_form.apply(job.scene)
        if self.ref_enable.isChecked():
            if job.reference_scene is None:
                job.reference_scene = model.SceneSpec(host=model.HostStar(vmag=3.0, spectral_type="A0V", name="REFERENCE"), ref_flag=True)
            self.ref_form.apply(job.reference_scene)
        else:
            job.reference_scene = None
            for v in job.visits:
                v.is_reference = False
        self.inst_form.apply(job.instrument)
        self.det_form.apply(job.detector)
        self.out_form.apply(job.output, job.run)
        return job

    def _on_edited(self):
        self._refresh_timer.start()

    def _refresh(self):
        self.apply_forms()
        self.model.refresh()
        row = self.current_row()
        self.setup.set_job(self.job, visit=row if row is not None else 0)
        est = cost.estimate(self.job)
        self.totals.setText(f"{self.job.n_visits} visits, {self.job.total_frames} frames, {cost.pretty_seconds(self.job.total_exposure_s)} of exposure")
        self.cost_label.setText(f"~{est.pretty_time}, {est.propagations} propagations, {est.memory_gb:.0f} GB")
        self.visits_label.setRawText(f"Visits · {self.job.n_visits}")
        errs = [i for i in self.setup.issues if i.level == "error"]
        self.queue_btn.setEnabled(not errs)
        self.status_chip.setVisible(bool(errs))
        if errs:
            self.status_chip.setText(f"{len(errs)} error(s)")
            self.status_chip.set_kind("err")

    # ------------------------------------------------------------------ visits
    def current_row(self) -> int | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return rows[0].row() if rows else None

    def _on_selection(self, *_):
        row = self.current_row()
        if row is not None and row != self.setup.visit_index:
            self.setup.set_job(self.job, visit=row)

    def _select_row(self, index: int):
        if index != self.current_row():
            self.table.selectRow(index)

    def add_visit(self):
        row = self.current_row()
        base = self.job.visits[row] if row is not None and self.job.visits else None
        v = Visit(label=f"visit {len(self.job.visits) + 1}", roll_angle_deg=base.roll_angle_deg if base else self.job.instrument.roll_angle_deg,
                  n_frames=base.n_frames if base else 10, exptime_s=base.exptime_s if base else 100.0)
        self.model.beginInsertRows(QtCore.QModelIndex(), len(self.job.visits), len(self.job.visits))
        self.job.visits.append(v)
        self.model.endInsertRows()
        self._refresh()
        self.table.selectRow(len(self.job.visits) - 1)

    def duplicate_visit(self):
        row = self.current_row()
        if row is None:
            return
        v = Visit(**{k: (SatSpotBlock(**vars(val)) if isinstance(val, SatSpotBlock) else (list(val) if isinstance(val, list) else val))
                     for k, val in vars(self.job.visits[row]).items()})
        v.visit_num = ""
        v.label = (v.label + " copy").strip()
        self.model.beginInsertRows(QtCore.QModelIndex(), row + 1, row + 1)
        self.job.visits.insert(row + 1, v)
        self.model.endInsertRows()
        self._refresh()
        self.table.selectRow(row + 1)

    def remove_visit(self):
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()}, reverse=True)
        if not rows or len(self.job.visits) - len(rows) < 1:
            return
        for r in rows:
            self.model.beginRemoveRows(QtCore.QModelIndex(), r, r)
            del self.job.visits[r]
            self.model.endRemoveRows()
        self._refresh()
        self.table.selectRow(min(rows[-1], len(self.job.visits) - 1))

    def move_visit(self, delta: int):
        row = self.current_row()
        if row is None:
            return
        k = row + delta
        if not 0 <= k < len(self.job.visits):
            return
        self.job.visits.insert(k, self.job.visits.pop(row))
        self._refresh()
        self.table.selectRow(k)

    # ------------------------------------------------------------------ files
    def new_job(self):
        job = model.roll_sequence_job()
        job.output.output_dir = self.job.output.output_dir
        self.load_job(job)

    def load_template(self, kind: str):
        if kind == "pol":
            job = model.polarimetry_pair_job()
        elif kind == "satspots":
            job = model.roll_sequence_job(with_reference=False)
            job.name = "rolls with satellite spots"
            job.instrument.satspots = model.SatSpotSpec.from_pair_id(0)
            for v in job.visits:
                v.satspots = SatSpotBlock(n_frames=2, exptime_s=5.0, em_gain=200.0)
        else:
            job = model.roll_sequence_job()
        job.output.output_dir = self.job.output.output_dir
        self.load_job(job)

    def open_job_dialog(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open job", self.job.output.output_dir or self.backend.home(), "Job JSON (*.json)")
        if p:
            self.load_job(Job.load(p), p)

    def import_cpgs_dialog(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import CPGS file", self.backend.home(), "CPGS XML (*.xml)")
        if p:
            self.import_cpgs(p)

    def import_cpgs(self, path: str, show_notes: bool = True) -> Job | None:
        try:
            cpgs = read_cpgs(path)
            job = job_from_cpgs(cpgs, output_dir=self.job.output.output_dir)
        except (CpgsError, KeyError, ValueError, OSError) as exc:
            box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.Warning, "Not a CPGS file corgisim can simulate",
                                        f"{os.path.basename(path)}\n\n{type(exc).__name__}: {exc}", QtWidgets.QMessageBox.StandardButton.Ok, self)
            box.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
            box.open()                       # not exec(): never block the event loop (or the tests)
            self.statusBar().showMessage(f"could not import {os.path.basename(path)}: {exc}", 10000)
            return None
        s = summarize(cpgs)
        self.load_job(job)
        self.statusBar().showMessage(f"imported {s['label']}: {s['coronagraph']} {s['filter']}, {s['n_simulated_visits']} of {s['n_visits']} visits simulated", 10000)
        if show_notes and job.notes:
            NotesDialog(f"CPGS import: {os.path.basename(path)}", job.notes, self).open()
        return job

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
            self.setWindowTitle(f"Sequence Builder - {self.job.name} ({os.path.basename(p)})")

    def view_json(self):
        self.apply_forms()
        JobPreviewDialog(self.job, self, title=f"{self.job.name} - job file").open()

    def view_notes(self):
        NotesDialog("Notes", self.job.notes or ["(no notes)"], self).open()

    # ------------------------------------------------------------------ hand-offs
    def queue_job(self):
        self.apply_forms()
        job = self.job.copy()
        if self.queue_handler is not None and self.queue_handler(job):
            self.statusBar().showMessage(f"queued {job.name} ({job.n_visits} visits) in the Sim Console", 5000)
        self.job_queued.emit(job)

    def to_imagelab(self):
        self.apply_forms()
        row = self.current_row() or 0
        job = self.job.copy()
        v = job.visits[row]
        job.visits = [v]
        job.instrument.roll_angle_deg = v.roll_angle_deg
        job.instrument.dpam = self.job.visit_dpam(v)
        job.detector.em_gain = self.job.visit_gain(v)
        job.detector.photon_counting = self.job.visit_photon_counting(v)
        if v.is_reference and job.reference_scene is not None:
            job.scene = job.reference_scene
        job.reference_scene = None
        job.kind = "image"
        job.name = f"{self.job.name} {v.label}".strip()
        if self.imagelab_handler is not None:
            self.imagelab_handler(job)
        self.send_to_imagelab.emit(job)

    def theme_changed(self, theme):
        self.setup.theme_changed(theme)
        self.model.layoutChanged.emit()

    def closeEvent(self, event):
        self.settings.setValue("sequence/geometry", self.saveGeometry())
        super().closeEvent(event)
