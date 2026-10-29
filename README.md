# corgisim_gui

A desktop GUI wrapper around [corgisim](https://github.com/roman-corgi/corgisim), the Roman
Coronagraph Instrument simulator. It does not modify corgisim; it imports it.

Tools (the plan is in `docs/plan.md`):

- **Image Lab** - set up a scene (host star, companions, disk), the instrument (coronagraph, filter,
  DPAM element, slit, ND, DMs, satellite spots, jitter) and the detector, preview the noiseless
  scene, simulate one frame, save it as L1.
- **Sequence Builder** - a table of visits built by hand, from templates or from a CPGS XML file,
  with a cost estimate per visit; saved as a JSON job file the runner consumes.
- **Setup View** - an optical-train strip (SPAM, FPAM, LSAM, FSAM, CFAM, DPAM, EXCAM, with the element
  corgisim will record in the L1 header) and a field-of-view sketch (dark hole, field stop or slit,
  companions and disk after roll, polarimetry beams).
- **Sim Console** - a queue of jobs, one runner subprocess each, progress per PSF state and frame,
  parallel detector frames capped by RAM, abort and re-queue.
- **Themes** - the corgidrp_gui style systems (Roman, Console, Neon, Homepage '98, Midnight).

## Status

All six phases are built (2026-10-28): launcher, Image Lab, Sequence Builder, Setup View and Sim
Console, on top of the Qt-free core, the stepwise engine and the runner. See the
[user guide](docs/user_guide.md) and the [developer notes](docs/developing.md).

    conda activate corgisim_gui
    corgisim-gui                         # launcher; --tool imagelab|sequence|setup|console, --job, --cpgs, --queue
    python -m corgisim_gui.runner job.json --n-jobs 2 --seed 7     # the same run without the GUI

![Image Lab](docs/screenshots/roman_imagelab.png)

## Install

Start from a Python 3.12 environment in which corgisim imports, installed as corgisim's README
describes (PROPER, roman_preflight_proper, cgi-eetc, cgisim 4.1, emccd_detect >= 2.6.2, corgidrp,
then corgisim itself). Then, in that environment:

    git clone git@github.com:maxwellmb/corgisim_gui.git
    cd corgisim_gui
    pip install -e ".[dev]"
    corgisim-gui

The GUI needs PySide6, qtpy and jinja2 on top of corgisim's dependencies; pip installs them.
Tests:

    python -m pytest -q --deselect tests/test_engine.py --deselect tests/test_gui_runs.py   # seconds
    python -m pytest -q                                      # also simulates tiny jobs with real PSFs (a few minutes)

The tests that compare the GUI's tables and CPGS translation with corgisim, and the ones that
simulate, are skipped when corgisim is not importable. The CPGS tests use the sample files in
corgisim's own `test/test_data` folder, found through the installed package.

Simulations write to the output folder you choose; job files written by the GUI and the queue
state live in `~/.corgisim_gui` (override with the `CORGISIM_GUI_HOME` environment variable).

## Layout

    corgisim_gui/core/      Qt-free, corgisim-free: tables, model, build, validate, cost, cpgs, field, progress
    corgisim_gui/engine/    builds corgisim objects from a Job and runs it (stepwise loop or corgisim's own)
    corgisim_gui/runner.py  python -u -m corgisim_gui.runner job.json
    corgisim_gui/backend/   file-system and process access behind one interface
    corgisim_gui/ui/        launcher, imagelab_window, sequence_window, console_window, setup_view, forms, image_view,
                            runner_process, glyphs, imaging, dialogs, base.ThemedWindow, widgets/
    corgisim_gui/themes/    theme token files and the stylesheet template (copied from corgidrp_gui)
    tests/
