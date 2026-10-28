"""Offscreen screenshots of the Setup View, per theme and example (docs/screenshots)."""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from qtpy import QtCore  # noqa: E402

QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, tempfile.mkdtemp())
from corgisim_gui import theming  # noqa: E402
from corgisim_gui.app import make_app  # noqa: E402
from corgisim_gui.ui.setup_view import SetupWindow  # noqa: E402

app = make_app([], restore=False)
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "screenshots")
os.makedirs(out, exist_ok=True)
themes = [a for a in sys.argv[1:] if not a.startswith("--")] or ["roman", "console", "neon", "homepage", "midnight"]
examples = ["image", "pol", "spec"] if "--all" in sys.argv else ["image"]
for key in themes:
    theming.theme_manager().set_theme(key, persist=False)
    for ex in examples:
        w = SetupWindow()
        w.resize(1320, 840)
        w.show()
        w.load_example(ex)
        if ex == "pol":
            w.view.toggles["rings"].setChecked(True)
        app.processEvents()
        app.processEvents()
        name = f"{key}_setup_{ex}.png" if ex != "image" else f"{key}_setup.png"
        w.grab().save(os.path.join(out, name))
        print("wrote", name)
        w.close()
