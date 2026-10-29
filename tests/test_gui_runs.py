"""The windows drive the real runner: a preview from the Image Lab and a tiny job through the Sim Console."""
import os
import tempfile

import pytest
from qtpy import QtCore

from corgisim_gui.core import model
from corgisim_gui.core.queue import JobQueue
from conftest import needs_corgisim
from test_engine import tiny_job

pytestmark = needs_corgisim


@pytest.fixture(scope="module")
def app():
    os.environ["CORGISIM_GUI_HOME"] = tempfile.mkdtemp()
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
    QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, tempfile.mkdtemp())
    from corgisim_gui.app import make_app
    return make_app([], restore=False)


def test_imagelab_preview_run(app, tmp_path):
    from corgisim_gui.ui.imagelab_window import ImageLabWindow
    w = ImageLabWindow()
    w.show()
    job = tiny_job(str(tmp_path / "out"), n_frames=1, n_jobs=1, full_frame=False)
    job.scene.point_sources = []
    w.load_job(job)
    w.preview()
    assert w.runner.running
    assert w.runner.wait(600000)
    app.processEvents()
    assert w.status_chip.text() == "done", "\n".join(w.runner.log[-30:])
    assert w.result.files.count() == 1 and w.result.canvas.data is not None
    assert w.result.canvas.data.shape == (51, 51)
    w.close()


def test_console_runs_job(app, tmp_path):
    from corgisim_gui.ui.console_window import ConsoleWindow
    q = JobQueue(store_dir=str(tmp_path / "queue"))
    w = ConsoleWindow(queue=q, restore=False)
    w.show()
    job = tiny_job(str(tmp_path / "out"), n_frames=2, n_jobs=2, seed=3, full_frame=True)
    job.scene.point_sources = []
    entry = w.enqueue(job, "sequence")
    assert entry.status == "running"
    assert w.wait_idle(900000)
    app.processEvents()
    assert entry.status == "done", "\n".join(entry.log[-30:])
    assert len(entry.outputs) == 2 and all(os.path.exists(p) for p in entry.outputs)
    assert w.frame_view.canvas.data is not None and w.frame_view.canvas.shown().shape == (1024, 1024)
    assert w.model.data(w.model.index(0, 6)) == "2/2"
    w._timer.stop()
    w.close()
