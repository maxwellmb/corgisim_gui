"""Offscreen screenshots of every window per theme (docs/screenshots)."""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CORGISIM_GUI_HOME", tempfile.mkdtemp())
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from qtpy import QtCore  # noqa: E402

QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, tempfile.mkdtemp())
from corgisim_gui import theming  # noqa: E402
from corgisim_gui.app import make_app  # noqa: E402
from corgisim_gui.core import model  # noqa: E402
from corgisim_gui.core.queue import JobQueue  # noqa: E402
from corgisim_gui.ui.console_window import ConsoleWindow  # noqa: E402
from corgisim_gui.ui.imagelab_window import ImageLabWindow  # noqa: E402
from corgisim_gui.ui.launcher import LauncherWindow  # noqa: E402
from corgisim_gui.ui.sequence_window import SequenceWindow  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CPGS = os.path.join(os.path.dirname(ROOT), "corgisim", "test", "test_data", "cpgs_ref_pol_satspots.xml")
app = make_app([], restore=False)
out = os.path.join(ROOT, "docs", "screenshots")
os.makedirs(out, exist_ok=True)
themes = [a for a in sys.argv[1:] if not a.startswith("--")] or ["roman", "console", "neon", "homepage", "midnight"]
which = [a[2:] for a in sys.argv[1:] if a.startswith("--")] or ["launcher", "imagelab", "sequence", "console"]


def shot(w, name):
    app.processEvents()
    app.processEvents()
    w.grab().save(os.path.join(out, name))
    print("wrote", name)


for key in themes:
    theming.theme_manager().set_theme(key, persist=False)
    if "launcher" in which:
        w = LauncherWindow()
        w.show()
        w.wait_environment(120000)
        shot(w, f"{key}_launcher.png")
        w.close()
    if "imagelab" in which:
        w = ImageLabWindow()
        w.resize(1480, 900)
        w.show()
        w.load_example("image")
        w.log.appendPlainText("$ python -u -m corgisim_gui.runner ~/.corgisim_gui/imagelab/20261028_153000_simulate.json --n-jobs 2")
        w.log.appendPlainText('corgisim_gui job: name="hlc band 1" visits=1 frames=1 engine=stepwise n_jobs=2')
        shot(w, f"{key}_imagelab.png")
        w.close()
    if "sequence" in which:
        w = SequenceWindow()
        w.resize(1560, 940)
        w.show()
        if os.path.exists(CPGS):
            w.import_cpgs(CPGS, show_notes=False)
            w.table.selectRow(1)
        shot(w, f"{key}_sequence.png")
        w.close()
    if "console" in which:
        q = JobQueue(store_dir=tempfile.mkdtemp())
        q.paused = True
        w = ConsoleWindow(queue=q, restore=False)
        w.resize(1320, 860)
        w.show()
        job = model.roll_sequence_job()
        job.output.output_dir = "/data/cgi/sims/47uma"
        job.scene.point_sources.append(model.PointSource.from_polar(20.0, 300.0, 45.0, label="b"))
        for i, (st, msg) in enumerate((("done", "30 files written"), ("running", ""), ("waiting", ""), ("failed", "visit 2/3: ValueError: FPM cannot be used with ND filter 1"))):
            j = w.enqueue(job, "sequence")
            j.status = st
            j.message = msg
            if st in ("done", "running", "failed"):
                import time
                j.started = time.time() - 900
                if st != "running":
                    j.ended = time.time()
            if st == "running":
                for line in ['corgisim_gui job: name="roll sequence" visits=3 frames=30 engine=stepwise n_jobs=2',
                             'corgisim_gui visit: i=1 n=3 id=0200001001001001001 label="reference" frames=10 roll=0 dpam=None',
                             'corgisim_gui psf: i=1 n=1 label=science', 'corgisim_gui psf_done: i=1 label=science',
                             *(f'corgisim_gui frame: i={k} n=10 visit=1 kind=science index={k-1} seconds=1.5 max=2000' for k in range(1, 11)),
                             'corgisim_gui visit: i=2 n=3 id=0200001001001001002 label="target roll -13" frames=10 roll=-13 dpam=None',
                             'corgisim_gui psf: i=1 n=1 label=science', 'corgisim_gui psf_done: i=1 label=science',
                             *(f'corgisim_gui frame: i={k} n=10 visit=2 kind=science index={k-1} seconds=1.5 max=2000' for k in range(1, 5))]:
                    j.parser.feed(line)
                    j.append_log(line)
                    w.log_line(f"[{j.name}] {line}", j)
        w.model.refresh()
        w.table.selectRow(1)
        w._show_job(w.queue.jobs[1])
        w._update_all()
        shot(w, f"{key}_console.png")
        for j in q.jobs:               # the fake 'running' entry would make close() ask a question
            if j.status == "running":
                j.status = "aborted"
        w._timer.stop()
        w.close()
