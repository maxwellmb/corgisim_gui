import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")



def _cpgs_dir() -> str | None:
    """corgisim's sample CPGS files: test/test_data next to the installed package (an editable checkout)."""
    try:
        import corgisim
        pkg = corgisim.lib_dir if hasattr(corgisim, "lib_dir") else list(corgisim.__path__)[0]
    except Exception:  # noqa: BLE001
        pkg = None
    candidates = []
    if pkg:
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(pkg)), "test", "test_data"))
    candidates.append(os.path.join(os.path.dirname(ROOT), "corgisim", "test", "test_data"))
    for c in candidates:
        if os.path.isdir(c):
            return c
    return None


CPGS_DIR = _cpgs_dir()


def corgisim_available() -> bool:
    try:
        import corgisim  # noqa: F401
        import cgisim  # noqa: F401
        import roman_preflight_proper  # noqa: F401
        return True
    except Exception:
        return False


needs_corgisim = pytest.mark.skipif(not corgisim_available(), reason="corgisim/cgisim/roman_preflight_proper not importable")


@pytest.fixture(scope="session")
def cpgs_files() -> list[str]:
    import glob
    files = sorted(glob.glob(os.path.join(CPGS_DIR, "cpgs_*.xml"))) if CPGS_DIR else []
    if not files:
        pytest.skip("corgisim sample CPGS files not found")
    return files


@pytest.fixture(scope="session")
def workdir(tmp_path_factory):
    """A folder with roman_preflight.py for PROPER (corgisim needs it in the cwd)."""
    d = tmp_path_factory.mktemp("work")
    if corgisim_available():
        from corgisim_gui.engine import stepwise
        stepwise.prepare_environment(str(d))
    return str(d)


@pytest.fixture(scope="session", autouse=True)
def _close_qt_windows_at_exit():
    yield
    try:
        from qtpy import QtWidgets
    except ImportError:  # pragma: no cover
        return
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        w.close()
        w.deleteLater()
    app.processEvents()
    app.processEvents()
