"""Offscreen tests of the Image Lab, Sequence Builder, Sim Console and Launcher (no simulation)."""
import os
import tempfile

import pytest
from qtpy import QtCore, QtWidgets

from corgisim_gui.core import model
from corgisim_gui.core.queue import JobQueue


@pytest.fixture(scope="module")
def app():
    os.environ["CORGISIM_GUI_HOME"] = tempfile.mkdtemp()
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
    QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, tempfile.mkdtemp())
    from corgisim_gui.app import make_app
    return make_app([], restore=False)


def test_forms_round_trip(app):
    from corgisim_gui.ui.forms import DetectorForm, InstrumentForm, OutputRunForm, SceneForm, VisitForm
    job = model.single_image_job()
    job.scene.point_sources.append(model.PointSource.from_polar(20.0, 300.0, 45.0, label="b"))
    job.scene.host.stokes = [1.0, 0.1, 0.0, 0.0]
    job.instrument = model.InstrumentSpec(cgi_mode="spec", cor_type="spc-spec_band3", bandpass="3B", dpam="PRISM3", slit="R2C2",
                                          nd=0, roll_angle_deg=12.5, dm_solution="spc-spec_ni_4e-9", output_dim=101,
                                          satspots=model.SatSpotSpec.from_pair_id(2), jitter=model.JitterSpec("mintest", 0.5, 0.7))
    job.detector = model.DetectorSpec(em_gain=250.0, photon_counting=True, cr_rate=0.0, fast_gain_mode=True, gain_CIC_Q=0,
                                      full_frame=False, loc_x=400, loc_y=600, extra_emccd_keywords={"read_noise": 100})
    job.visits[0] = model.Visit(vistype="CGIVST_TDD_OBS_HOWFSC", exptime_s=42.0, n_frames=3, satspots=model.SatSpotBlock(2, 1.5, 300.0))
    job.output = model.OutputSpec(output_dir="/tmp/x", save_fits=True, write_as_l1=False, save_noiseless=False, visit_subfolders=False, overwrite=True, visit_id_root="1234567890123456")
    job.run = model.RunSpec(engine="corgisim", n_jobs=2, seed=99)
    sf, inf, df, vf, of = SceneForm(), InstrumentForm(), DetectorForm(), VisitForm(), OutputRunForm(max_jobs=4)
    sf.load(job.scene); inf.load(job.instrument); df.load(job.detector); vf.load(job.visits[0]); of.load(job.output, job.run)
    back = model.single_image_job()
    sf.apply(back.scene); inf.apply(back.instrument); df.apply(back.detector); vf.apply(back.visits[0]); of.apply(back.output, back.run)
    assert back.scene.host.stokes == [1.0, 0.1, 0.0, 0.0]
    assert len(back.scene.point_sources) == 1 and abs(back.scene.point_sources[0].separation_mas - 300.0) < 0.1
    assert back.instrument.cor_type == "spc-spec_band3" and back.instrument.bandpass == "3B" and back.instrument.slit == "R2C2"
    assert back.instrument.dm_solution == "spc-spec_ni_4e-9" and back.instrument.output_dim == 101
    assert back.instrument.satspots.angle_deg == [45.0, 135.0] and back.instrument.jitter.preset == "mintest"
    assert back.detector.em_gain == 250.0 and back.detector.fast_gain_mode is True and back.detector.gain_CIC_Q == 0
    assert back.detector.extra_emccd_keywords == {"read_noise": 100} and back.detector.full_frame is False
    assert back.visits[0].vistype == "CGIVST_TDD_OBS_HOWFSC" and back.visits[0].satspots.em_gain == 300.0
    assert back.output.visit_id_root == "1234567890123456" and back.run.engine == "corgisim" and back.run.n_jobs == 2 and back.run.seed == 99
    # dependent lists
    inf.cor.setCurrentIndex([inf.cor.itemData(i) for i in range(inf.cor.count())].index("hlc_band4"))
    assert inf.mode.currentData() == "excam"
    assert [inf.filt.itemData(i) for i in range(inf.filt.count())] == ["4F", "4A", "4B", "4C"]
    assert inf.dm.currentData() == "hlc_ni_3e-8"
    assert [inf.dpam.itemData(i) for i in range(inf.dpam.count())] == ["None", "POL0", "POL45"]


def test_imagelab_window(app, tmp_path):
    from corgisim_gui.ui.imagelab_window import ImageLabWindow
    w = ImageLabWindow()
    w.show()
    w.load_example("spec")
    app.processEvents()
    assert w.setup.job.instrument.cgi_mode == "spec"
    w.inst_form.roll.setValue(33.0)
    w._refresh_setup()
    assert w.job.visits[0].roll_angle_deg == 33.0 and w.setup.field.preview.roll_deg == 33.0
    queued = []
    w.queue_handler = lambda job: (queued.append(job), True)[1]
    w.queue_job()
    assert queued and queued[0].n_visits == 1
    sent = []
    w.sequence_handler = sent.append
    w.to_sequence()
    assert sent and sent[0].kind == "sequence"
    p = tmp_path / "lab.json"
    w.job_path = str(p)
    w.save_job()
    assert model.Job.load(str(p)).instrument.roll_angle_deg == 33.0
    # an invalid setup disables Simulate
    w.inst_form.nd.setCurrentIndex(1)
    w._refresh_setup()
    assert not w.simulate_btn.isEnabled()
    assert w.strip_status("FPAM") == "err"
    w.close()


def test_sequence_window(app, cpgs_files, tmp_path):
    from corgisim_gui.ui.sequence_window import SequenceWindow
    w = SequenceWindow()
    w.show()
    app.processEvents()
    assert w.model.rowCount() == 3
    w.add_visit()
    assert w.model.rowCount() == 4 and w.current_row() == 3
    idx = w.model.index(3, 3)
    assert w.model.setData(idx, "45.5")
    assert w.job.visits[3].roll_angle_deg == 45.5
    assert w.model.setData(w.model.index(3, 10), "2")
    assert w.job.visits[3].satspots.n_frames == 2
    assert w.model.setData(w.model.index(3, 10), "0")
    assert w.job.visits[3].satspots is None
    w.duplicate_visit()
    assert w.model.rowCount() == 5 and w.job.visits[4].label.endswith("copy")
    w.move_visit(-1)
    assert w.current_row() == 3
    w.remove_visit()
    assert w.model.rowCount() == 4
    job = w.import_cpgs([f for f in cpgs_files if f.endswith("cpgs_ref_pol_satspots.xml")][0], show_notes=False)
    app.processEvents()
    assert job is not None and w.model.rowCount() == 7 and w.ref_enable.isChecked()
    w.table.selectRow(1)
    app.processEvents()
    assert w.setup.visit_index == 1
    assert {c.key: c for c in w.setup.strip.cells}["DPAM"].name == "POL0"
    sent = []
    w.imagelab_handler = sent.append
    w.to_imagelab()
    assert sent and sent[0].n_visits == 1 and sent[0].instrument.dpam == "POL0"
    queued = []
    w.queue_handler = lambda job: (queued.append(job), True)[1]
    w.queue_job()
    assert queued and queued[0].n_visits == 7
    assert w.import_cpgs(str(tmp_path / "missing.xml"), show_notes=False) is None
    w.close()


def test_console_window_queue_ops(app, tmp_path):
    from corgisim_gui.ui.console_window import ConsoleWindow
    q = JobQueue(store_dir=str(tmp_path))
    q.paused = True
    w = ConsoleWindow(queue=q, restore=False)
    w.show()
    job = model.roll_sequence_job()
    job.output.output_dir = str(tmp_path / "out")
    a = w.enqueue(job, "sequence")
    b = w.enqueue(job, "sequence")
    assert w.model.rowCount() == 2 and all(j.status == "waiting" for j in q.jobs)
    assert os.path.exists(a.job_path)
    w.table.selectRow(1)
    w.move_selected(-1)
    assert q.jobs[0] is b
    w.table.selectRow(0)
    w.remove_selected()
    assert q.jobs == [a]
    q.save()
    q2 = JobQueue(store_dir=str(tmp_path))
    assert q2.load() == 1 and q2.jobs[0].name == a.name
    w._timer.stop()
    w.close()


def test_launcher_and_app_wiring(app):
    from corgisim_gui.app import ToolWindows, parse_args
    from corgisim_gui.ui.launcher import LauncherWindow
    w = LauncherWindow()
    w.show()
    tools = ToolWindows(w)
    assert w.wait_environment(120000)
    keys = [r[0] for r in w.env_rows]
    assert "corgisim" in keys and "machine" in keys
    lab = tools.open_imagelab()
    seq = tools.open_sequence()
    con = tools.open_console()
    con.queue.paused = True
    lab.queue_job()
    assert con.model.rowCount() == 1
    seq.to_imagelab()
    assert tools.windows["imagelab"] is lab
    args = parse_args(["--tool", "console", "--theme", "neon"])
    assert args.tool == ["console"] and args.theme == "neon"
    for win in (lab, seq, con, w):
        if hasattr(win, "_timer"):
            win._timer.stop()
        win.close()
