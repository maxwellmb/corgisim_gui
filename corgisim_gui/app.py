"""Application entry point: ``corgisim-gui``.

Until the launcher exists (phase 6) this opens the Setup View.
"""
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


def parse_args(argv: list[str] | None = None):
    import argparse

    from . import __version__
    ap = argparse.ArgumentParser(prog="corgisim-gui", description="Desktop GUI wrapper around corgisim.")
    ap.add_argument("--version", action="version", version=f"corgisim_gui {__version__}")
    ap.add_argument("--theme", metavar="NAME", help="start with this theme for this session only")
    ap.add_argument("path", nargs="?", help="a job JSON or CPGS XML file to open")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = make_app([], theme=args.theme)
    from .ui.setup_view import SetupWindow
    w = SetupWindow()
    if args.path:
        w.load_path(args.path)
    else:
        w.load_example("image")
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
