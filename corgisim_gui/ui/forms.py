"""Editable forms for the parts of a Job: scene, instrument, detector, visit, output/run.

Each form has ``load(spec)`` (fill the widgets) and ``apply(spec)`` (write the
widgets back into the dataclass) and emits ``changed`` when the user edits
anything. Choice lists come from :mod:`corgisim_gui.core.tables`, so the filter
list follows the coronagraph, the DPAM list follows the mode, the slit list
follows the band and the DM list follows the coronagraph.
"""
from __future__ import annotations

import json
import os

from qtpy import QtCore, QtWidgets

from ..core import tables
from ..core.model import (DetectorSpec, DiskModel, HostStar, InstrumentSpec, JitterSpec, OutputSpec,
                          PointSource, RunSpec, SatSpotBlock, SatSpotSpec, SceneSpec, Visit)
from .widgets.themed import SectionLabel


# ----------------------------------------------------------------------------- helpers
def _dspin(lo: float, hi: float, step: float = 1.0, decimals: int = 2, suffix: str = "") -> QtWidgets.QDoubleSpinBox:
    s = QtWidgets.QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(decimals)
    if suffix:
        s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    return s


def _ispin(lo: int, hi: int, step: int = 1) -> QtWidgets.QSpinBox:
    s = QtWidgets.QSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setKeyboardTracking(False)
    return s


def _combo(items, data=None) -> QtWidgets.QComboBox:
    c = QtWidgets.QComboBox()
    for i, it in enumerate(items):
        c.addItem(str(it), data[i] if data else it)
    return c


def _set_combo(combo: QtWidgets.QComboBox, value) -> None:
    for i in range(combo.count()):
        if combo.itemData(i) == value or combo.itemText(i) == str(value):
            combo.setCurrentIndex(i)
            return
    combo.setCurrentIndex(0)


def _refill(combo: QtWidgets.QComboBox, items, data=None, keep=None) -> None:
    cur = keep if keep is not None else combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    for i, it in enumerate(items):
        combo.addItem(str(it), data[i] if data else it)
    _set_combo(combo, cur)
    combo.blockSignals(False)


class _Form(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False

    def _wire(self, *widgets) -> None:
        for w in widgets:
            if isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                w.valueChanged.connect(self._edited)
            elif isinstance(w, QtWidgets.QComboBox):
                w.currentIndexChanged.connect(self._edited)
            elif isinstance(w, QtWidgets.QCheckBox):
                w.toggled.connect(self._edited)
            elif isinstance(w, QtWidgets.QLineEdit):
                w.editingFinished.connect(self._edited)
            elif isinstance(w, QtWidgets.QGroupBox):
                w.toggled.connect(self._edited)

    def _edited(self, *_):
        if not self._loading:
            self.changed.emit()


def _browse_file(parent, edit: QtWidgets.QLineEdit, title: str, filt: str) -> None:
    start = edit.text() or os.path.expanduser("~")
    p, _ = QtWidgets.QFileDialog.getOpenFileName(parent, title, start, filt)
    if p:
        edit.setText(p)
        edit.editingFinished.emit()


def _browse_dir(parent, edit: QtWidgets.QLineEdit, title: str) -> None:
    start = edit.text() or os.path.expanduser("~")
    p = QtWidgets.QFileDialog.getExistingDirectory(parent, title, start)
    if p:
        edit.setText(p)
        edit.editingFinished.emit()


def _file_row(parent, edit: QtWidgets.QLineEdit, title: str, filt: str | None) -> QtWidgets.QWidget:
    w = QtWidgets.QWidget()
    h = QtWidgets.QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(edit, 1)
    b = QtWidgets.QPushButton("…")
    b.setFixedWidth(28)
    if filt is None:
        b.clicked.connect(lambda: _browse_dir(parent, edit, title))
    else:
        b.clicked.connect(lambda: _browse_file(parent, edit, title, filt))
    h.addWidget(b)
    return w


# ----------------------------------------------------------------------------- scene
class SceneForm(_Form):
    """Host star, off-axis point sources and the optional disk model."""

    def __init__(self, parent=None, title: str = "Scene", reference: bool = False):
        super().__init__(parent)
        self.reference = reference
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(SectionLabel(title))
        f = QtWidgets.QFormLayout()
        f.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.name = QtWidgets.QLineEdit()
        self.vmag = _dspin(-2, 25, 0.1, 2)
        self.sptype = QtWidgets.QLineEdit()
        self.sptype.setPlaceholderText("e.g. G2V, A0, K5III")
        self.sptype.setToolTip("corgisim accepts letter, digit, optional .digit and luminosity class (O-M, 0-9, I-VII)")
        self.ra = _dspin(0, 360, 0.001, 5, " °")
        self.dec = _dspin(-90, 90, 0.001, 5, " °")
        self.diam = _dspin(0, 50, 0.1, 2, " mas")
        self.diam.setSpecialValueText("none")
        self.spmethod = _combo(["bpgs", "blackbody"])
        self.stokes = QtWidgets.QLineEdit()
        self.stokes.setPlaceholderText("Q U V  (fractions; blank = unpolarized)")
        f.addRow("name", self.name)
        f.addRow("V mag", self.vmag)
        f.addRow("spectral type", self.sptype)
        f.addRow("RA", self.ra)
        f.addRow("Dec", self.dec)
        f.addRow("stellar diameter", self.diam)
        f.addRow("spectrum", self.spmethod)
        f.addRow("Stokes Q U V", self.stokes)
        lay.addLayout(f)
        self._wire(self.name, self.vmag, self.sptype, self.ra, self.dec, self.diam, self.spmethod, self.stokes)

        if not reference:
            lay.addWidget(SectionLabel("Off-axis sources"))
            self.sources = QtWidgets.QTableWidget(0, 5)
            self.sources.setHorizontalHeaderLabels(["label", "V mag", "sep (mas)", "PA (°)", "spectrum file"])
            self.sources.horizontalHeader().setStretchLastSection(True)
            self.sources.verticalHeader().setVisible(False)
            self.sources.setMinimumHeight(110)
            self.sources.setMaximumHeight(170)
            self.sources.cellChanged.connect(self._edited)
            lay.addWidget(self.sources)
            row = QtWidgets.QHBoxLayout()
            add = QtWidgets.QPushButton("Add source")
            add.clicked.connect(lambda: self.add_source(PointSource.from_polar(20.0, 300.0, 45.0, label=f"source {self.sources.rowCount() + 1}")))
            rem = QtWidgets.QPushButton("Remove")
            rem.clicked.connect(self.remove_source)
            row.addWidget(add)
            row.addWidget(rem)
            row.addStretch(1)
            lay.addLayout(row)

            self.disk_group = QtWidgets.QGroupBox("Disk / 2D scene")
            self.disk_group.setCheckable(True)
            self.disk_group.setChecked(False)
            df = QtWidgets.QFormLayout(self.disk_group)
            df.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            self.disk_path = QtWidgets.QLineEdit()
            self.disk_unit = _combo(list(tables.__dict__.get("DISK_UNITS", ("mJy/arcsec^2", "W.m^-2.pixel^-1", "contrast/pixel"))))
            self.disk_contrast = QtWidgets.QLineEdit()
            self.disk_contrast.setPlaceholderText("e.g. 1e-6 (contrast/pixel images)")
            self.prf_path = QtWidgets.QLineEdit()
            self.prf_interp = QtWidgets.QCheckBox("interpolate between PRFs")
            df.addRow("image (FITS)", _file_row(self, self.disk_path, "Disk model image", "FITS (*.fits *.fit);;All files (*)"))
            df.addRow("unit", self.disk_unit)
            df.addRow("contrast", self.disk_contrast)
            df.addRow("PRF cube", _file_row(self, self.prf_path, "PRF cube", "FITS (*.fits);;All files (*)"))
            df.addRow("", self.prf_interp)
            lay.addWidget(self.disk_group)
            self._wire(self.disk_group, self.disk_path, self.disk_unit, self.disk_contrast, self.prf_path, self.prf_interp)
        lay.addStretch(1)

    # -- sources table
    def add_source(self, p: PointSource) -> None:
        self._loading = True
        r = self.sources.rowCount()
        self.sources.insertRow(r)
        for c, t in enumerate([p.label, f"{p.vmag:g}", f"{p.separation_mas:.1f}", f"{p.pa_deg:.1f}", p.spectrum_path or ""]):
            self.sources.setItem(r, c, QtWidgets.QTableWidgetItem(t))
        self._loading = False
        self.changed.emit()

    def remove_source(self) -> None:
        rows = sorted({i.row() for i in self.sources.selectedIndexes()}, reverse=True)
        if not rows and self.sources.rowCount():
            rows = [self.sources.rowCount() - 1]
        for r in rows:
            self.sources.removeRow(r)
        self.changed.emit()

    def _sources(self) -> list[PointSource]:
        out = []
        for r in range(self.sources.rowCount()):
            def cell(c, default=""):
                it = self.sources.item(r, c)
                return it.text().strip() if it else default
            try:
                vmag = float(cell(1, "20"))
                sep = float(cell(2, "0"))
                pa = float(cell(3, "0"))
            except ValueError:
                continue
            p = PointSource.from_polar(vmag, sep, pa, label=cell(0), spectrum_path=cell(4) or None)
            out.append(p)
        return out

    # -- load / apply
    def load(self, scene: SceneSpec) -> None:
        self._loading = True
        h = scene.host
        self.name.setText(h.name)
        self.vmag.setValue(h.vmag)
        self.sptype.setText(h.spectral_type)
        self.ra.setValue(h.ra_deg)
        self.dec.setValue(h.dec_deg)
        self.diam.setValue(h.stellar_diam_mas or 0.0)
        _set_combo(self.spmethod, scene.spmethod)
        self.stokes.setText(" ".join(f"{x:g}" for x in h.stokes[1:]) if h.stokes else "")
        if not self.reference:
            self.sources.setRowCount(0)
            for p in scene.point_sources:
                r = self.sources.rowCount()
                self.sources.insertRow(r)
                for c, t in enumerate([p.label, f"{p.vmag:g}", f"{p.separation_mas:.1f}", f"{p.pa_deg:.1f}", p.spectrum_path or ""]):
                    self.sources.setItem(r, c, QtWidgets.QTableWidgetItem(t))
            d = scene.disk
            self.disk_group.setChecked(bool(d and d.path))
            self.disk_path.setText(d.path if d else "")
            _set_combo(self.disk_unit, d.unit if d else "mJy/arcsec^2")
            self.disk_contrast.setText(f"{d.contrast:g}" if d and d.contrast is not None else "")
            self.prf_path.setText(d.prf_cube_path if d else "")
            self.prf_interp.setChecked(bool(d and d.interpolate_prfs))
        self._loading = False

    def apply(self, scene: SceneSpec) -> SceneSpec:
        h = scene.host
        h.name = self.name.text().strip() or "UNKNOWN"
        h.vmag = self.vmag.value()
        h.spectral_type = self.sptype.text().strip()
        h.ra_deg = self.ra.value()
        h.dec_deg = self.dec.value()
        h.stellar_diam_mas = self.diam.value() or None
        scene.spmethod = self.spmethod.currentData()
        txt = self.stokes.text().replace(",", " ").split()
        try:
            quv = [float(x) for x in txt]
            h.stokes = [1.0, *quv] if len(quv) == 3 else None
        except ValueError:
            h.stokes = None
        scene.ref_flag = self.reference
        if not self.reference:
            scene.point_sources = self._sources()
            if self.disk_group.isChecked() and self.disk_path.text().strip():
                try:
                    contrast = float(self.disk_contrast.text()) if self.disk_contrast.text().strip() else None
                except ValueError:
                    contrast = None
                scene.disk = DiskModel(path=self.disk_path.text().strip(), unit=self.disk_unit.currentData(), contrast=contrast,
                                       prf_cube_path=self.prf_path.text().strip(), interpolate_prfs=self.prf_interp.isChecked())
            else:
                scene.disk = None
        return scene


# ----------------------------------------------------------------------------- instrument
class InstrumentForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(SectionLabel("Instrument"))
        f = QtWidgets.QFormLayout()
        f.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.mode = _combo(["excam", "spec"])
        names = list(tables.PRIMARY_CORONAGRAPHS) + [n for n in tables.CORONAGRAPH_NAMES if n not in tables.PRIMARY_CORONAGRAPHS]
        self.cor = _combo([f"{n}  ({tables.CORONAGRAPHS[n].label})" for n in names], names)
        self.filt = _combo(tables.FILTER_NAMES)
        self.dpam = _combo(tables.DPAM_EXCAM)
        self.slit = _combo(["None"])
        self.slit_ra = _dspin(-5000, 5000, 1, 1, " mas")
        self.slit_dec = _dspin(-5000, 5000, 1, 1, " mas")
        self.nd = _combo([f"{k}: {v[0]} {v[1]}" for k, v in tables.ND_FILTERS.items()], list(tables.ND_FILTERS))
        self.roll = _dspin(-360, 360, 1, 2, " °")
        self.polaxis = _combo([f"{k}: {v}" for k, v in tables.POLAXIS_CHOICES.items()], list(tables.POLAXIS_CHOICES))
        self.use_fpm = QtWidgets.QCheckBox("focal plane mask")
        self.use_lyot = QtWidgets.QCheckBox("Lyot stop")
        self.use_fs = QtWidgets.QCheckBox("field stop")
        self.use_pupil = QtWidgets.QCheckBox("pupil imaging lens")
        self.use_errors = QtWidgets.QCheckBox("wavefront errors")
        self.dm = _combo(["none"], [None])
        self.output_dim = _ispin(11, 1023, 2)
        self.oversamp = _ispin(1, 11)
        self.fsm_x = _dspin(-2000, 2000, 1, 1, " mas")
        self.fsm_y = _dspin(-2000, 2000, 1, 1, " mas")
        f.addRow("mode", self.mode)
        f.addRow("coronagraph", self.cor)
        f.addRow("filter (CFAM)", self.filt)
        f.addRow("DPAM", self.dpam)
        f.addRow("slit (FSAM)", self.slit)
        f.addRow("slit ΔRA / ΔDec", _pair(self.slit_ra, self.slit_dec))
        f.addRow("ND filter", self.nd)
        f.addRow("roll angle", self.roll)
        f.addRow("polaxis", self.polaxis)
        masks = QtWidgets.QWidget()
        ml = QtWidgets.QGridLayout(masks)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addWidget(self.use_fpm, 0, 0)
        ml.addWidget(self.use_lyot, 0, 1)
        ml.addWidget(self.use_fs, 1, 0)
        ml.addWidget(self.use_pupil, 1, 1)
        ml.addWidget(self.use_errors, 2, 0)
        f.addRow("elements", masks)
        f.addRow("DM solution", self.dm)
        f.addRow("image size", _pair(self.output_dim, QtWidgets.QLabel("px, odd")))
        f.addRow("oversampling", self.oversamp)
        f.addRow("FSM offset x / y", _pair(self.fsm_x, self.fsm_y))
        lay.addLayout(f)

        self.sat_group = QtWidgets.QGroupBox("Satellite spots on DM1")
        self.sat_group.setCheckable(True)
        self.sat_group.setChecked(False)
        sf = QtWidgets.QFormLayout(self.sat_group)
        sf.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.sat_pair = _combo([f"CPGS pair id {k}: {v[0]:g} λ/D at {v[1]} deg, contrast {v[2]:g}" for k, v in tables.SATSPOT_PAIR_IDS.items()] + ["custom"],
                               list(tables.SATSPOT_PAIR_IDS) + [None])
        self.sat_pairs = _ispin(1, 2)
        self.sat_sep = _dspin(1, 30, 0.25, 2, " λ/D")
        self.sat_angles = QtWidgets.QLineEdit("0 90")
        self.sat_contrast = QtWidgets.QLineEdit("1e-7")
        sf.addRow("preset", self.sat_pair)
        sf.addRow("pairs", self.sat_pairs)
        sf.addRow("separation", self.sat_sep)
        sf.addRow("angles (°)", self.sat_angles)
        sf.addRow("contrast", self.sat_contrast)
        self.sat_pair.currentIndexChanged.connect(self._sat_preset)
        lay.addWidget(self.sat_group)

        self.jit_group = QtWidgets.QGroupBox("Finite stellar diameter and jitter")
        self.jit_group.setCheckable(True)
        self.jit_group.setChecked(False)
        jf = QtWidgets.QFormLayout(self.jit_group)
        jf.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.jit_preset = _combo([f"{k} ({v} offsets)" for k, v in tables.JITTER_PRESETS.items() if k != "none"],
                                 [k for k in tables.JITTER_PRESETS if k != "none"])
        self.jit_diam = QtWidgets.QCheckBox("finite stellar diameter (from the host star)")
        self.jit_add = QtWidgets.QCheckBox("add pointing jitter")
        self.jit_sx = _dspin(0, 50, 0.1, 2, " mas")
        self.jit_sy = _dspin(0, 50, 0.1, 2, " mas")
        jf.addRow("offset preset", self.jit_preset)
        jf.addRow("", self.jit_diam)
        jf.addRow("", self.jit_add)
        jf.addRow("jitter σx / σy", _pair(self.jit_sx, self.jit_sy))
        lay.addWidget(self.jit_group)
        lay.addStretch(1)

        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.cor.currentIndexChanged.connect(self._cor_changed)
        self.filt.currentIndexChanged.connect(self._filter_changed)
        self._wire(self.mode, self.cor, self.filt, self.dpam, self.slit, self.slit_ra, self.slit_dec, self.nd, self.roll, self.polaxis,
                   self.use_fpm, self.use_lyot, self.use_fs, self.use_pupil, self.use_errors, self.dm, self.output_dim, self.oversamp,
                   self.fsm_x, self.fsm_y, self.sat_group, self.sat_pairs, self.sat_sep, self.sat_angles, self.sat_contrast,
                   self.jit_group, self.jit_preset, self.jit_diam, self.jit_add, self.jit_sx, self.jit_sy)
        self._cor_changed()
        self._mode_changed()

    # -- dependent lists
    def _mode_changed(self, *_):
        spec = self.mode.currentData() == "spec"
        _refill(self.dpam, tables.DPAM_SPEC if spec else tables.DPAM_EXCAM)
        self.slit.setEnabled(spec)
        self.slit_ra.setEnabled(spec)
        self.slit_dec.setEnabled(spec)
        if not self._loading:
            # pick a coronagraph of the right mode
            c = tables.CORONAGRAPHS.get(self.cor.currentData())
            if c is not None and c.cgi_mode != self.mode.currentData():
                _set_combo(self.cor, "spc-spec_band3" if spec else "hlc_band1")
        self._filter_changed()

    def _cor_changed(self, *_):
        name = self.cor.currentData()
        c = tables.CORONAGRAPHS.get(name)
        if c is None:
            return
        _refill(self.filt, tables.allowed_filters(name) or list(tables.FILTER_NAMES))
        if self.filt.currentData() not in tables.allowed_filters(name):
            _set_combo(self.filt, f"{c.bands[0]}F")
        sols = tables.dm_solutions_for(name)
        _refill(self.dm, ["none"] + [d.label for d in sols], [None] + [d.rootname for d in sols])
        if not self._loading and self.dm.currentData() is None and sols:
            _set_combo(self.dm, sols[0].rootname)
        if not self._loading and c.cgi_mode != self.mode.currentData():
            _set_combo(self.mode, c.cgi_mode)
        self._filter_changed()

    def _filter_changed(self, *_):
        f = tables.FILTERS.get(self.filt.currentData())
        band = f.band if f else 0
        slits = tables.SLITS_BY_BAND.get(band, ("None",))
        _refill(self.slit, slits)

    def _sat_preset(self, *_):
        k = self.sat_pair.currentData()
        if k is None:
            return
        sep, angles, contrast = tables.SATSPOT_PAIR_IDS[k]
        self.sat_pairs.setValue(2)
        self.sat_sep.setValue(sep)
        self.sat_angles.setText(" ".join(f"{a:g}" for a in angles))
        self.sat_contrast.setText(f"{contrast:g}")

    # -- load / apply
    def load(self, inst: InstrumentSpec) -> None:
        self._loading = True
        _set_combo(self.mode, inst.cgi_mode)
        _set_combo(self.cor, inst.cor_type)
        self._cor_changed()
        self._mode_changed()
        _set_combo(self.filt, inst.bandpass)
        self._filter_changed()
        _set_combo(self.dpam, inst.dpam)
        _set_combo(self.slit, inst.slit or "None")
        self.slit_ra.setValue(inst.slit_ra_offset_mas)
        self.slit_dec.setValue(inst.slit_dec_offset_mas)
        _set_combo(self.nd, inst.nd)
        self.roll.setValue(inst.roll_angle_deg)
        _set_combo(self.polaxis, inst.polaxis)
        self.use_fpm.setChecked(inst.use_fpm)
        self.use_lyot.setChecked(inst.use_lyot_stop)
        self.use_fs.setChecked(inst.use_field_stop)
        self.use_pupil.setChecked(inst.use_pupil_lens)
        self.use_errors.setChecked(inst.use_errors)
        _set_combo(self.dm, inst.dm_solution)
        self.output_dim.setValue(inst.output_dim)
        self.oversamp.setValue(inst.oversampling_factor)
        self.fsm_x.setValue(inst.fsm_x_offset_mas)
        self.fsm_y.setValue(inst.fsm_y_offset_mas)
        s = inst.satspots
        self.sat_group.setChecked(s is not None)
        if s is not None:
            match = next((k for k, v in tables.SATSPOT_PAIR_IDS.items() if v[0] == s.sep_lamD and list(v[1]) == list(s.angle_deg) and v[2] == s.contrast and s.num_pairs == 2), None)
            _set_combo(self.sat_pair, match)
            self.sat_pairs.setValue(s.num_pairs)
            self.sat_sep.setValue(s.sep_lamD)
            self.sat_angles.setText(" ".join(f"{a:g}" for a in s.angle_deg))
            self.sat_contrast.setText(f"{s.contrast:g}")
        j = inst.jitter
        self.jit_group.setChecked(j is not None and j.preset != "none")
        if j is not None:
            _set_combo(self.jit_preset, j.preset)
            self.jit_diam.setChecked(j.use_finite_stellar_diam)
            self.jit_add.setChecked(j.add_jitter)
            self.jit_sx.setValue(j.jitter_sigma_x_mas)
            self.jit_sy.setValue(j.jitter_sigma_y_mas)
        self._loading = False

    def apply(self, inst: InstrumentSpec) -> InstrumentSpec:
        inst.cgi_mode = self.mode.currentData()
        inst.cor_type = self.cor.currentData()
        inst.bandpass = self.filt.currentData()
        inst.dpam = self.dpam.currentData() or "None"
        inst.slit = self.slit.currentData() or "None"
        inst.slit_ra_offset_mas = self.slit_ra.value()
        inst.slit_dec_offset_mas = self.slit_dec.value()
        inst.nd = int(self.nd.currentData())
        inst.roll_angle_deg = self.roll.value()
        inst.polaxis = int(self.polaxis.currentData())
        inst.use_fpm = self.use_fpm.isChecked()
        inst.use_lyot_stop = self.use_lyot.isChecked()
        inst.use_field_stop = self.use_fs.isChecked()
        inst.use_pupil_lens = self.use_pupil.isChecked()
        inst.use_errors = self.use_errors.isChecked()
        inst.dm_solution = self.dm.currentData()
        inst.output_dim = int(self.output_dim.value())
        inst.oversampling_factor = int(self.oversamp.value())
        inst.fsm_x_offset_mas = self.fsm_x.value()
        inst.fsm_y_offset_mas = self.fsm_y.value()
        if self.sat_group.isChecked():
            try:
                angles = [float(a) for a in self.sat_angles.text().replace(",", " ").split()]
                contrast = float(self.sat_contrast.text())
            except ValueError:
                angles, contrast = [0.0, 90.0], 1e-7
            inst.satspots = SatSpotSpec(int(self.sat_pairs.value()), self.sat_sep.value(), angles, contrast)
        else:
            inst.satspots = None
        if self.jit_group.isChecked():
            inst.jitter = JitterSpec(self.jit_preset.currentData(), self.jit_sx.value(), self.jit_sy.value(),
                                     self.jit_diam.isChecked(), self.jit_add.isChecked())
        else:
            inst.jitter = None
        return inst


def _pair(a: QtWidgets.QWidget, b: QtWidgets.QWidget) -> QtWidgets.QWidget:
    w = QtWidgets.QWidget()
    h = QtWidgets.QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(a, 1)
    h.addWidget(b, 1)
    return w


# ----------------------------------------------------------------------------- detector
class DetectorForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(SectionLabel("Detector (EMCCD)"))
        f = QtWidgets.QFormLayout()
        f.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.gain = _dspin(1, 7000, 10, 1)
        self.pc = QtWidgets.QCheckBox("photon counting (header flag)")
        self.cr = _dspin(0, 100, 1, 2, " hits/cm²/s")
        self.fast = _combo(["auto", "true (fast gain model)", "false (full gain model)"], ["auto", True, False])
        self.cicq = _combo(["roman (gain-register CIC on)", "0 (off, much faster)"], ["roman", 0])
        self.full = QtWidgets.QCheckBox("full 1024×1024 frame (needed for L1)")
        self.loc_x = _ispin(0, 1023)
        self.loc_y = _ispin(0, 1023)
        self.extra = QtWidgets.QLineEdit()
        self.extra.setPlaceholderText('JSON, e.g. {"read_noise": 100, "dark_rate": 0.001}')
        self.extra.setToolTip("\n".join(f"{k}: {v}" for k, v in tables.EMCCD_DOC.items()))
        f.addRow("EM gain", self.gain)
        f.addRow("", self.pc)
        f.addRow("cosmic rays", self.cr)
        f.addRow("gain model", self.fast)
        f.addRow("gain-register CIC", self.cicq)
        f.addRow("", self.full)
        f.addRow("image centre x / y", _pair(self.loc_x, self.loc_y))
        f.addRow("other keywords", self.extra)
        lay.addLayout(f)
        lay.addStretch(1)
        self._wire(self.gain, self.pc, self.cr, self.fast, self.cicq, self.full, self.loc_x, self.loc_y, self.extra)

    def load(self, det: DetectorSpec) -> None:
        self._loading = True
        self.gain.setValue(det.em_gain)
        self.pc.setChecked(det.photon_counting)
        self.cr.setValue(det.cr_rate)
        _set_combo(self.fast, det.fast_gain_mode)
        _set_combo(self.cicq, det.gain_CIC_Q)
        self.full.setChecked(det.full_frame)
        self.loc_x.setValue(det.loc_x)
        self.loc_y.setValue(det.loc_y)
        self.extra.setText(json.dumps(det.extra_emccd_keywords) if det.extra_emccd_keywords else "")
        self._loading = False

    def apply(self, det: DetectorSpec) -> DetectorSpec:
        det.em_gain = self.gain.value()
        det.photon_counting = self.pc.isChecked()
        det.cr_rate = self.cr.value()
        det.fast_gain_mode = self.fast.currentData()
        det.gain_CIC_Q = self.cicq.currentData()
        det.full_frame = self.full.isChecked()
        det.loc_x = int(self.loc_x.value())
        det.loc_y = int(self.loc_y.value())
        txt = self.extra.text().strip()
        try:
            det.extra_emccd_keywords = json.loads(txt) if txt else {}
            if not isinstance(det.extra_emccd_keywords, dict):
                det.extra_emccd_keywords = {}
        except ValueError:
            det.extra_emccd_keywords = {}
        return det


# ----------------------------------------------------------------------------- visit (single image)
class VisitForm(_Form):
    """Exposure settings of one visit (the Image Lab's single visit)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(SectionLabel("Exposure"))
        f = QtWidgets.QFormLayout()
        f.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.vistype = _combo(tables.VISIT_TYPES)
        self.exptime = _dspin(0.001, 100000, 1, 3, " s")
        self.n_frames = _ispin(0, 10000)
        self.sat_group = QtWidgets.QGroupBox("Satellite-spot frames (background, +, −)")
        self.sat_group.setCheckable(True)
        self.sat_group.setChecked(False)
        sf = QtWidgets.QFormLayout(self.sat_group)
        self.sat_n = _ispin(1, 1000)
        self.sat_exp = _dspin(0.001, 100000, 1, 3, " s")
        self.sat_gain = _dspin(1, 7000, 10, 1)
        sf.addRow("frames of each", self.sat_n)
        sf.addRow("exposure", self.sat_exp)
        sf.addRow("EM gain", self.sat_gain)
        f.addRow("visit type", self.vistype)
        f.addRow("exposure time", self.exptime)
        f.addRow("frames", self.n_frames)
        lay.addLayout(f)
        lay.addWidget(self.sat_group)
        lay.addStretch(1)
        self._wire(self.vistype, self.exptime, self.n_frames, self.sat_group, self.sat_n, self.sat_exp, self.sat_gain)

    def load(self, v: Visit) -> None:
        self._loading = True
        _set_combo(self.vistype, v.vistype)
        self.exptime.setValue(v.exptime_s)
        self.n_frames.setValue(v.n_frames)
        self.sat_group.setChecked(v.satspots is not None)
        if v.satspots is not None:
            self.sat_n.setValue(v.satspots.n_frames)
            self.sat_exp.setValue(v.satspots.exptime_s)
            self.sat_gain.setValue(v.satspots.em_gain)
        self._loading = False

    def apply(self, v: Visit) -> Visit:
        v.vistype = self.vistype.currentData()
        v.exptime_s = self.exptime.value()
        v.n_frames = int(self.n_frames.value())
        v.satspots = SatSpotBlock(int(self.sat_n.value()), self.sat_exp.value(), self.sat_gain.value()) if self.sat_group.isChecked() else None
        return v


# ----------------------------------------------------------------------------- output / run
class OutputRunForm(_Form):
    def __init__(self, parent=None, max_jobs: int = 8):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(SectionLabel("Output"))
        f = QtWidgets.QFormLayout()
        f.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.outdir = QtWidgets.QLineEdit()
        self.save_fits = QtWidgets.QCheckBox("write detector frames")
        self.l1 = QtWidgets.QCheckBox("as L1 (corgidrp headers, cgi_<visitid>_<time>_l1_.fits)")
        self.noiseless = QtWidgets.QCheckBox("write the noiseless scene per visit")
        self.subfolders = QtWidgets.QCheckBox("one folder per visit (V<visitid>)")
        self.overwrite = QtWidgets.QCheckBox("overwrite existing files")
        self.visit_root = QtWidgets.QLineEdit()
        self.visit_root.setMaxLength(16)
        self.visit_root.setToolTip("16 digits: program, execution, campaign, segment, observation; the 3-digit visit number is appended")
        f.addRow("folder", _file_row(self, self.outdir, "Output folder", None))
        f.addRow("", self.save_fits)
        f.addRow("", self.l1)
        f.addRow("", self.noiseless)
        f.addRow("", self.subfolders)
        f.addRow("", self.overwrite)
        f.addRow("VISITID root", self.visit_root)
        lay.addLayout(f)
        lay.addWidget(SectionLabel("Run"))
        r = QtWidgets.QFormLayout()
        r.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.engine = _combo(["stepwise (progress per frame, disks, parallel frames)", "corgisim (observation.generate_observation_sequence)"], ["stepwise", "corgisim"])
        self.n_jobs = _ispin(1, max(1, max_jobs))
        self.n_jobs.setToolTip("Detector frames simulated at the same time (spawned processes). Capped by this machine's RAM: about 13 GB per full frame.")
        self.seed = QtWidgets.QLineEdit()
        self.seed.setPlaceholderText("blank = random")
        r.addRow("engine", self.engine)
        r.addRow("parallel frames", self.n_jobs)
        r.addRow("random seed", self.seed)
        lay.addLayout(r)
        lay.addStretch(1)
        self._wire(self.outdir, self.save_fits, self.l1, self.noiseless, self.subfolders, self.overwrite, self.visit_root, self.engine, self.n_jobs, self.seed)

    def load(self, out: OutputSpec, run: RunSpec) -> None:
        self._loading = True
        self.outdir.setText(out.output_dir)
        self.save_fits.setChecked(out.save_fits)
        self.l1.setChecked(out.write_as_l1)
        self.noiseless.setChecked(out.save_noiseless)
        self.subfolders.setChecked(out.visit_subfolders)
        self.overwrite.setChecked(out.overwrite)
        self.visit_root.setText(out.visit_id_root)
        _set_combo(self.engine, run.engine)
        self.n_jobs.setValue(max(1, min(self.n_jobs.maximum(), run.n_jobs)))
        self.seed.setText("" if run.seed is None else str(run.seed))
        self._loading = False

    def apply(self, out: OutputSpec, run: RunSpec) -> None:
        out.output_dir = self.outdir.text().strip()
        out.save_fits = self.save_fits.isChecked()
        out.write_as_l1 = self.l1.isChecked()
        out.save_noiseless = self.noiseless.isChecked()
        out.visit_subfolders = self.subfolders.isChecked()
        out.overwrite = self.overwrite.isChecked()
        out.visit_id_root = self.visit_root.text().strip() or "0200001001001001"
        run.engine = self.engine.currentData()
        run.n_jobs = int(self.n_jobs.value())
        txt = self.seed.text().strip()
        try:
            run.seed = int(txt) if txt else None
        except ValueError:
            run.seed = None
