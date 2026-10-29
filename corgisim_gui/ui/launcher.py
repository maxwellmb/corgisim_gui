"""Launcher: four tool tiles, the environment panel and theme controls."""
from __future__ import annotations

import os
import platform
import sys

from qtpy import QtCore, QtGui, QtWidgets

from .. import __version__, theming
from ..core import tables
from ..core.queue import gui_home, machine_limits
from .base import ThemedWindow
from .widgets.themed import Panel, SectionLabel, TileButton
from .runner_process import RunnerProcess  # noqa: F401  (same env as the runner)

TOOLS = [
    ("imagelab", "Image Lab", "one scene, one setup: preview and simulate"),
    ("sequence", "Sequence Builder", "visits by hand, from templates or a CPGS file"),
    ("setup", "Setup View", "what a job file or CPGS file will simulate"),
    ("console", "Sim Console", "the queue: runs, progress, logs, frames"),
]


class LauncherWindow(ThemedWindow):
    tool_requested = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, title="corgisim GUI")
        self.setObjectName("LauncherWindow")
        self._handlers: dict[str, object] = {}
        self._env_proc: QtCore.QProcess | None = None
        self.env_rows: list[tuple[str, str, str]] = []
        self._build_menus()
        self._build_body()
        self.tool_requested.connect(self._default_tool_handler)
        self.resize(600, 560)

    def _build_menus(self) -> None:
        f = self.add_menu("&File")
        q = f.addAction("Quit")
        q.setShortcut(QtGui.QKeySequence.StandardKey.Quit)
        q.triggered.connect(self.close)
        t = self.add_menu("&Tools")
        for key, title, _sub in TOOLS:
            a = t.addAction(title)
            a.triggered.connect(lambda _=False, k=key: self.tool_requested.emit(k))
        self.add_theme_menu()
        self.add_help_menu()

    def _build_body(self) -> None:
        theme = theming.current_theme()
        central = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        band = QtWidgets.QFrame()
        band.setProperty("role", "titlebar")
        bl = QtWidgets.QHBoxLayout(band)
        title = QtWidgets.QLabel("corgisim GUI")
        title.setProperty("role", "title")
        sub = QtWidgets.QLabel("Roman Coronagraph simulations")
        sub.setProperty("role", "subtitle")
        bl.addWidget(title)
        bl.addStretch(1)
        bl.addWidget(sub, 0, QtCore.Qt.AlignmentFlag.AlignBottom)
        self._band_layout = bl
        outer.addWidget(band)
        body = QtWidgets.QWidget()
        self._body_layout = QtWidgets.QVBoxLayout(body)
        outer.addWidget(body, 1)
        grid = QtWidgets.QGridLayout()
        self._grid = grid
        self.tiles: dict[str, TileButton] = {}
        for i, (key, title_text, subtitle) in enumerate(TOOLS):
            tile = TileButton(title_text, subtitle, primary=(key == "imagelab"))
            tile.setObjectName(f"tile_{key}")
            tile.clicked.connect(lambda _=False, k=key: self.tool_requested.emit(k))
            grid.addWidget(tile, i // 2, i % 2)
            self.tiles[key] = tile
        self._body_layout.addLayout(grid, 1)
        self._body_layout.addSpacing(4)
        self._body_layout.addWidget(SectionLabel("Environment"))
        self.env_panel = Panel(layout="grid")
        self.env_panel.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)
        self._body_layout.addWidget(self.env_panel)
        self.env_status = QtWidgets.QLabel("checking the simulation environment…")
        self.env_status.setProperty("role", "hint")
        self.env_panel.layout().addWidget(self.env_status, 0, 0, 1, 2)
        row = QtWidgets.QHBoxLayout()
        lab = QtWidgets.QLabel("Theme")
        lab.setProperty("role", "muted")
        row.addWidget(lab)
        self.theme_combo = QtWidgets.QComboBox()
        for t in theming.available_themes():
            self.theme_combo.addItem(t.name, t.key)
        self._sync_combo(theme)
        self.theme_combo.currentIndexChanged.connect(self._combo_changed)
        row.addWidget(self.theme_combo)
        row.addStretch(1)
        ver = QtWidgets.QLabel(f"corgisim_gui {__version__}")
        ver.setProperty("role", "hint")
        row.addWidget(ver)
        self._body_layout.addLayout(row)
        self.statusBar()
        self.setCentralWidget(central)
        self._apply_density(theme)
        QtCore.QTimer.singleShot(0, self.refresh_environment)

    def _apply_density(self, theme) -> None:
        pad, gap = theme.density.padding, theme.density.gap
        m = max(pad + 4, 12)
        self._body_layout.setContentsMargins(m, m, m, m)
        self._body_layout.setSpacing(gap)
        self._grid.setSpacing(gap)
        self._band_layout.setContentsMargins(m, max(4, pad - 2), m, max(4, pad - 2))
        lay = self.env_panel.layout()
        lay.setContentsMargins(pad, max(4, pad - 3), pad, max(4, pad - 3))
        lay.setHorizontalSpacing(gap + 6)
        lay.setVerticalSpacing(2)

    def refresh_environment(self) -> None:
        """Run ``python -m corgisim_gui.envcheck`` (imports corgisim, slow) in a subprocess and show its rows."""
        if self._env_proc is not None:
            return
        from ..backend import default_backend
        import corgisim_gui
        proc = QtCore.QProcess(self)
        env = QtCore.QProcessEnvironment.systemEnvironment()
        pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(corgisim_gui.__file__)))
        pp = env.value("PYTHONPATH", "")
        if pkg_root not in pp.split(os.pathsep):
            env.insert("PYTHONPATH", pkg_root + (os.pathsep + pp if pp else ""))
        proc.setProcessEnvironment(env)
        proc.setProgram(default_backend().python_executable())
        proc.setArguments(["-m", "corgisim_gui.envcheck"])
        proc.finished.connect(self._env_finished)
        self._env_proc = proc
        proc.start()

    def _env_finished(self, code, status) -> None:
        proc = self._env_proc
        self._env_proc = None
        if proc is None:
            return
        import json
        text = bytes(proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        err = bytes(proc.readAllStandardError()).decode("utf-8", errors="replace")
        proc.deleteLater()
        rows = None
        for line in reversed(text.splitlines()):
            if line.startswith("{"):
                try:
                    rows = [tuple(r) for r in json.loads(line)["rows"]]
                except (ValueError, KeyError, TypeError):
                    rows = None
                break
        if rows is None:
            rows = [("environment", f"check failed (exit {code}): {err.strip().splitlines()[-1] if err.strip() else text.strip()[-200:]}", "")]
        self._show_environment(rows)

    def wait_environment(self, timeout_ms: int = 120000) -> bool:
        """Spin until the environment check finished (tests, screenshots)."""
        deadline = QtCore.QDeadlineTimer(timeout_ms)
        app = QtWidgets.QApplication.instance()
        app.processEvents()
        if self._env_proc is None and not self.env_rows:
            self.refresh_environment()
        while self._env_proc is not None and not deadline.hasExpired():
            app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
            QtCore.QThread.msleep(20)
        return self._env_proc is None

    def _show_environment(self, rows) -> None:
        lay: QtWidgets.QGridLayout = self.env_panel.layout()
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for r, (key, value, tip) in enumerate(rows):
            k = QtWidgets.QLabel(key)
            k.setProperty("role", "hint")
            v = QtWidgets.QLabel(value)
            v.setWordWrap(True)
            v.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            if tip:
                v.setToolTip(tip)
            if "not importable" in value or "missing" in value:
                v.setProperty("role", "error")
            lay.addWidget(k, r, 0, QtCore.Qt.AlignmentFlag.AlignTop)
            lay.addWidget(v, r, 1)
        lay.setColumnStretch(1, 1)
        self.env_rows = rows

    def _sync_combo(self, theme) -> None:
        for i in range(self.theme_combo.count()):
            if self.theme_combo.itemData(i) == theme.key:
                self.theme_combo.blockSignals(True)
                self.theme_combo.setCurrentIndex(i)
                self.theme_combo.blockSignals(False)
                return

    def _combo_changed(self, index: int) -> None:
        key = self.theme_combo.itemData(index)
        if key and key != theming.current_theme().key:
            self._manager.set_theme(key)

    def theme_changed(self, theme) -> None:
        self._sync_combo(theme)
        self._apply_density(theme)

    def set_tool_handler(self, key: str, handler) -> None:
        self._handlers[key] = handler

    def _default_tool_handler(self, key: str) -> None:
        h = self._handlers.get(key)
        if h is not None:
            h()
        else:
            self.statusBar().showMessage(f"{key}: no window registered", 3000)

    def closeEvent(self, event):
        if self._env_proc is not None:
            self._env_proc.kill()
            self._env_proc = None
        super().closeEvent(event)
