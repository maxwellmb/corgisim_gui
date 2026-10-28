"""Offscreen tests of the Setup View widgets (no corgisim needed)."""
import os

import numpy as np
import pytest
from qtpy import QtCore, QtWidgets

from corgisim_gui.core import model
from corgisim_gui.ui import glyphs, imaging
from corgisim_gui.ui.setup_view import FieldView, OpticalTrainStrip, SetupView, SetupWindow, train_cells


@pytest.fixture(scope="module")
def app():
    from corgisim_gui.app import make_app
    return make_app([], restore=False)


def _job():
    job = model.single_image_job()
    job.output.output_dir = "/tmp/corgisim_gui_test"
    job.scene.point_sources.append(model.PointSource.from_polar(20.0, 300.0, 45.0, label="b"))
    return job


def test_imaging_helpers():
    img = np.zeros((21, 21))
    img[10, 15] = 1.0
    q = imaging.render(img, "asinh", "inferno")
    assert q.width() == 21 and q.height() == 21
    # origin lower: the bright pixel at y=10 stays in the middle row; x=15 on the right
    px = q.pixelColor(15, 10)
    assert px.red() > 200
    assert imaging.lut("viridis").shape == (256, 3)
    r, g, b = imaging.wavelength_rgb(575)
    assert r > 150 and g > 150 and b == 0
    assert imaging.wavelength_rgb(825)[0] < imaging.wavelength_rgb(660)[0]
    assert imaging.normalise(np.full((3, 3), 5.0)).shape == (3, 3)


def test_train_cells_reflect_job():
    job = _job()
    cells = {c.key: c for c in train_cells(job)}
    assert cells["SPAM"].name == "OPEN" and cells["FPAM"].name == "HLC12_C2R5" and cells["LSAM"].name == "NFOV"
    assert cells["FSAM"].name == "R1C1" and "487" in cells["FSAM"].detail
    assert cells["CFAM"].name == "1F" and "575" in cells["CFAM"].detail
    assert cells["DPAM"].name == "IMAGING" and cells["DM"].status == "ok"
    job.instrument.nd = 1
    from corgisim_gui.core import validate
    cells = {c.key: c for c in train_cells(job, validate.validate_job(job))}
    assert cells["FPAM"].status == "err" and "FPAM" in cells["FPAM"].tooltip or cells["FPAM"].tooltip
    job = _job()
    job.instrument = model.InstrumentSpec(cgi_mode="spec", cor_type="spc-spec_band3", bandpass="3F", dpam="PRISM3", slit="R2C2",
                                          dm_solution="spc-spec_ni_2e-8")
    cells = {c.key: c for c in train_cells(job)}
    assert cells["FSAM"].name == "R2C2" and "slit" in cells["FSAM"].detail and cells["FSAM"].extra["slit"] is not None
    assert cells["DPAM"].name == "PRISM3" and cells["SPAM"].name == "SPEC"
    job.instrument.dpam = "None"
    job.instrument.use_fpm = False
    job.instrument.dm_solution = None
    cells = {c.key: c for c in train_cells(job)}
    assert cells["FPAM"].name == "OPEN_34" and cells["FPAM"].status == "off" and cells["DM"].status == "off"


def test_strip_paints_and_hover(app):
    strip = OpticalTrainStrip()
    strip.resize(1200, 160)
    strip.set_job(_job())
    strip.show()
    app.processEvents()
    pix = strip.grab()
    assert not pix.isNull()
    assert len(strip._rects) == 8
    first = strip._rects[0].center()
    assert strip.cell_at(first).key == "DM"
    clicked = []
    strip.cell_clicked.connect(clicked.append)
    from qtpy import QtGui
    ev = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseButtonPress, QtCore.QPointF(first), QtCore.Qt.MouseButton.LeftButton,
                           QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
    strip.mousePressEvent(ev)
    assert clicked == ["DM"]
    strip.close()


def test_field_view_overlays_and_hit_test(app):
    from corgisim_gui.core import field
    job = _job()
    fv = FieldView()
    fv.resize(400, 400)
    fv.show()
    fv.set_preview(field.render_field(job, size_pix=101))
    app.processEvents()
    fv._layout()
    src = [o for o in fv.preview.overlays if o.role == "source"][0]
    w = fv.to_widget(src.data["x"], src.data["y"])
    assert fv.overlay_at(w).label == "b"
    assert fv.overlay_at(QtCore.QPointF(2, 2)) is None
    x, y = fv.to_image(w)
    assert abs(x - src.data["x"]) < 0.01 and abs(y - src.data["y"]) < 0.01
    fv.set_overlay("source", False)
    fv.set_display("log", "viridis")
    assert not fv.grab().isNull()
    fv.set_preview(None)
    assert not fv.grab().isNull()
    fv.close()


def test_setup_view_visits_and_facts(app):
    view = SetupView()
    view.resize(1200, 800)
    view.show()
    job = model.roll_sequence_job()
    job.output.output_dir = "/tmp/x"
    job.scene.point_sources.append(model.PointSource.from_polar(22.0, 350.0, 60.0, label="b"))
    view.set_job(job)
    app.processEvents()
    assert view.visit_combo.count() == 3
    assert view.field.preview.roll_deg == 0.0
    assert view.sources_table.rowCount() == 0          # visit 0 is the reference star
    seen = []
    view.visit_changed.connect(seen.append)
    view.visit_combo.setCurrentIndex(2)
    app.processEvents()
    assert seen == [2] and view.field.preview.roll_deg == 13.0
    assert view.sources_table.rowCount() == 1
    assert "PSF states" in view.cost_label.text()
    cells = {c.key: c for c in view.strip.cells}
    assert cells["DPAM"].name == "IMAGING"
    pol = model.polarimetry_pair_job()
    pol.output.output_dir = "/tmp/x"
    view.set_job(pol, visit=1)
    app.processEvents()
    assert {c.key: c for c in view.strip.cells}["DPAM"].name == "POL45"
    assert [o.role for o in view.field.preview.overlays].count("beam") == 2
    view.set_job(None)
    view.close()


def test_setup_window_examples_and_files(app, tmp_path, cpgs_files):
    w = SetupWindow()
    w.show()
    for ex in ("image", "rolls", "pol", "spec"):
        w.load_example(ex)
        app.processEvents()
        assert w.view.job is not None
    p = tmp_path / "job.json"
    w.view.job.save(str(p))
    w.load_path(str(p))
    assert w.view.job.name == "spec"
    w.load_path([f for f in cpgs_files if f.endswith("cpgs_ref_pol_satspots.xml")][0])
    app.processEvents()
    assert w.view.visit_combo.count() == 7
    assert "cpgs_ref_pol_satspots" in w.windowTitle()
    assert not w.grab().isNull()
    w.close()
