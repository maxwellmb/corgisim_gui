"""Report the simulation environment as JSON (run in a subprocess by the launcher: importing corgisim is slow).

    python -m corgisim_gui.envcheck
"""
from __future__ import annotations

import json
import os
import platform
import sys


def environment_report() -> list[tuple[str, str, str]]:
    """(key, value, tooltip) rows about the simulation environment. Imports corgisim (slow)."""
    from .core import tables
    from .core.queue import gui_home, machine_limits
    rows: list[tuple[str, str, str]] = [("python", f"{platform.python_version()}  {sys.executable}", "")]
    try:
        import corgisim
        rows.append(("corgisim", f"{getattr(corgisim, '__version__', '?')}  {os.path.dirname(corgisim.__file__ if hasattr(corgisim, '__file__') and corgisim.__file__ else list(corgisim.__path__)[0])}", ""))
    except Exception as exc:  # noqa: BLE001
        rows.append(("corgisim", f"not importable: {type(exc).__name__}: {exc}", ""))
        return rows
    for name in ("cgisim", "proper", "roman_preflight_proper", "emccd_detect", "corgidrp", "synphot", "eetc"):
        try:
            mod = __import__(name)
            rows.append((name, f"{getattr(mod, '__version__', '?')}", getattr(mod, "__file__", "") or ""))
        except Exception as exc:  # noqa: BLE001
            rows.append((name, f"missing ({type(exc).__name__})", ""))
    try:
        from .engine import stepwise
        present = stepwise.available_dm_rootnames()
        missing = sorted(set(tables.DM_SOLUTIONS) - set(present))
        rows.append(("DM solutions", f"{len(present)} in roman_preflight_proper/examples" + (f"; missing from the tables: {missing}" if missing else ""), stepwise.dm_examples_dir()))
    except Exception as exc:  # noqa: BLE001
        rows.append(("DM solutions", f"? ({type(exc).__name__})", ""))
    lim = machine_limits()
    rows.append(("machine", f"{lim['cpus']} cores, {lim['memory_gb']:.0f} GB RAM" if lim.get("memory_gb") else f"{lim['cpus']} cores", ""))
    rows.append(("GUI home", gui_home(), "job files written by the Image Lab and the queue live here"))
    return rows




def main() -> int:
    rows = environment_report()
    sys.stdout.write(json.dumps({"rows": rows}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
