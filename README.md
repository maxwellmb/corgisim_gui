# corgisim_gui

A desktop GUI wrapper around [corgisim](https://github.com/roman-corgi/corgisim), the Roman
Coronagraph Instrument simulator. It does not modify corgisim; it imports it.

Planned tools (see the plan in `docs/plan.md`):

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

Phase 0 (environment) and phase 1 (the Qt-free core, the engine and the runner) are done. There is
no window yet. What works today:

    conda activate corgisim_gui
    python -m corgisim_gui.runner job.json --validate-only
    python -m corgisim_gui.runner job.json --n-jobs 2 --seed 7
    python -m corgisim_gui.runner job.json --preview        # noiseless scene only

A job file is the JSON of `corgisim_gui.core.model.Job` (`Job().save(path)` writes a template).
`corgisim_gui.core.cpgs.load_job_from_cpgs(xml)` builds one from a CPGS file the way corgisim's own
loader would, and records in `job.notes` where the file says something corgisim ignores.

## Install

The environment needs corgisim and its dependencies (PROPER, cgisim, roman_preflight_proper,
cgi-eetc, emccd_detect >= 2.6.2, corgidrp) plus PySide6, qtpy, jinja2. On the development Mac that is
the conda env `corgisim_gui`. Then:

    pip install -e ".[dev]"
    python -m pytest -q --deselect tests/test_engine.py     # fast tests
    python -m pytest -q                                      # also simulates a tiny job (about 2 min)

## Layout

    corgisim_gui/core/      Qt-free, corgisim-free: tables, model, build, validate, cost, cpgs, field, progress
    corgisim_gui/engine/    builds corgisim objects from a Job and runs it (stepwise loop or corgisim's own)
    corgisim_gui/runner.py  python -u -m corgisim_gui.runner job.json
    corgisim_gui/backend/   file-system and process access behind one interface
    corgisim_gui/ui/        windows and widgets (phase 2+)
    corgisim_gui/themes/    theme token files and the stylesheet template (copied from corgidrp_gui)
    tests/
