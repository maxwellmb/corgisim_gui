"""The copied theme engine renders every bundled theme (offscreen)."""
import pytest


def test_every_theme_renders():
    qtpy = pytest.importorskip("qtpy")
    from corgisim_gui import theming
    themes = theming.available_themes()
    assert {t.key for t in themes} >= {"roman", "console", "neon", "homepage", "midnight"}
    for t in themes:
        qss = theming.render_qss(t)
        assert "QPushButton" in qss and t.palette.action in qss


def test_apply_theme_to_app():
    qtpy = pytest.importorskip("qtpy")
    from qtpy import QtWidgets
    from corgisim_gui import theming
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theming.apply_theme(app, theming.load_theme("roman"))
    from corgisim_gui.ui.base import ThemedWindow
    w = ThemedWindow(title="t")
    w.add_theme_menu()
    w.show()
    app.processEvents()
    w.close()
