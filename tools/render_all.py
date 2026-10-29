"""Regenerate every screenshot in docs/screenshots (run after UI or theme changes)."""
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
themes = sys.argv[1:] or ["roman", "console", "neon", "homepage", "midnight"]
for script, extra in (("render_windows.py", []), ("render_setup_view.py", ["--all"])):
    print("==", script)
    subprocess.run([sys.executable, os.path.join(here, script), *themes, *extra], check=False)
