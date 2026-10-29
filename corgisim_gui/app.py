"""Application entry point: ``corgisim-gui``."""
from __future__ import annotations

import sys

from qtpy import QtWidgets

from . import theming


def make_app(argv: list[str] | None = None, theme: str | None = None,
             restore: bool = True) -> QtWidgets.QApplication:
    """Create (or reuse) the QApplication and apply a theme.

    ``theme`` forces a theme without persisting it; otherwise the saved theme
    (QSettings key ``theme``, default ``roman``) is restored when ``restore`` is true.
    """
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(list(argv if argv is not None else sys.argv))
    app.setApplicationName("corgisim GUI")
    app.setOrganizationName(theming.SETTINGS_ORG)
    manager = theming.theme_manager()
    if theme is not None:
        manager.set_theme(theme, persist=False)
    elif restore:
        manager.restore()
    else:
        manager.set_theme(theming.DEFAULT_THEME, persist=False)
    return app


class ToolWindows:
    """Creates each tool window once, raises it on later requests, and wires the hand-offs."""

    def __init__(self, launcher):
        self.launcher = launcher
        self.windows: dict[str, QtWidgets.QMainWindow] = {}
        launcher.set_tool_handler("imagelab", self.open_imagelab)
        launcher.set_tool_handler("sequence", self.open_sequence)
        launcher.set_tool_handler("setup", self.open_setup)
        launcher.set_tool_handler("console", self.open_console)

    def _show(self, key, factory):
        win = self.windows.get(key)
        if win is None:
            win = factory()
            self.windows[key] = win
        win.show()
        win.raise_()
        win.activateWindow()
        return win

    def open_imagelab(self):
        from .ui.imagelab_window import ImageLabWindow

        def factory():
            w = ImageLabWindow()
            w.queue_handler = lambda job: self._queue(job, "imagelab")
            w.sequence_handler = lambda job: self.open_sequence().load_job(job)
            return w
        return self._show("imagelab", factory)

    def open_sequence(self):
        from .ui.sequence_window import SequenceWindow

        def factory():
            w = SequenceWindow()
            w.queue_handler = lambda job: self._queue(job, "sequence")
            w.imagelab_handler = lambda job: self.open_imagelab().load_job(job)
            return w
        return self._show("sequence", factory)

    def open_setup(self):
        from .ui.setup_view import SetupWindow

        def factory():
            w = SetupWindow()
            w.load_example("image")
            return w
        return self._show("setup", factory)

    def open_console(self):
        from .ui.console_window import ConsoleWindow

        def factory():
            w = ConsoleWindow()
            w.imagelab_handler = lambda job: self.open_imagelab().load_job(job)
            w.sequence_handler = lambda job: self.open_sequence().load_job(job)
            return w
        return self._show("console", factory)

    def _queue(self, job, source: str) -> bool:
        self.open_console().enqueue(job, source)
        return True


def parse_args(argv: list[str] | None = None):
    import argparse

    from . import __version__
    ap = argparse.ArgumentParser(prog="corgisim-gui", description="Desktop GUI wrapper around corgisim.")
    ap.add_argument("--version", action="version", version=f"corgisim_gui {__version__}")
    ap.add_argument("--theme", metavar="NAME", help="start with this theme for this session only (roman, console, neon, homepage, midnight, or a .toml path)")
    ap.add_argument("--tool", choices=["imagelab", "sequence", "setup", "console"], action="append",
                    help="open this tool at startup as well as the launcher (repeatable)")
    ap.add_argument("--job", metavar="JOB.json", help="open this job in the Image Lab (one visit) or the Sequence Builder")
    ap.add_argument("--cpgs", metavar="FILE.xml", help="import this CPGS file in the Sequence Builder")
    ap.add_argument("--queue", metavar="JOB.json", action="append", help="queue this job file in the Sim Console (repeatable)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = make_app([], theme=args.theme)
    from .core.model import Job
    from .ui.launcher import LauncherWindow
    launcher = LauncherWindow()
    tools = ToolWindows(launcher)
    launcher.show()
    for key in args.tool or []:
        launcher.tool_requested.emit(key)
    if args.job:
        job = Job.load(args.job)
        if job.n_visits > 1 or job.kind == "sequence":
            tools.open_sequence().load_job(job, args.job)
        else:
            tools.open_imagelab().load_job(job, args.job)
    if args.cpgs:
        tools.open_sequence().import_cpgs(args.cpgs)
    for path in args.queue or []:
        tools.open_console()._add_file(path)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
