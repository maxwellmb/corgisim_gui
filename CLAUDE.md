# corgisim_gui — notes for coding agents

A PySide6 desktop wrapper around `corgisim` (the Roman Coronagraph simulator). Sibling of
`../corgidrp_gui`, same rules, separate code (the theme engine is a copy, on purpose: no
coordination between the two repos).

## Hard rules
- **Never modify `../corgisim`** (or cgisim, proper, roman_preflight_proper). This package only
  imports them. No monkeypatching: progress comes from the runner's own marker lines.
- Python for everything: `/opt/anaconda3/envs/corgisim_gui/bin/python` (corgisim, cgisim, proper via
  a `.pth` file pointing at `../proper`, roman_preflight_proper 2.0.2, emccd_detect 2.6.2, corgidrp
  5.1.1 editable, PySide6, qtpy, pytest). `corgi_env` is Max's older env and cannot run corgisim main.
- Qt code imports through `qtpy`. `corgisim_gui/core/` and `corgisim_gui/engine/` stay Qt-free.
  `core/` never imports corgisim (so the GUI draws and validates without it); `engine/` imports it
  inside functions.
- Windows never call `os`/`subprocess` directly; they go through `corgisim_gui.backend.default_backend()`.
- Simulations run as `python -u -m corgisim_gui.runner job.json` (spawn-safe, `__main__` guarded);
  `core.progress.ProgressParser` turns its stdout/stderr into events. PROPER needs
  `roman_preflight.py` in the cwd: `engine.stepwise.prepare_environment(workdir)` does that.
- Build against corgisim **main** today, but keep the upgrade path to PR 300 (parallel frame
  generation: `frame_runner`, `seed`, `zindex/zval_m_i`) in mind: the engine's own frame loop is
  the only place that would change.

## Layout
    corgisim_gui/core/      tables (modes, filters, mechanisms, DM solutions), model (Job dataclasses + JSON),
                            build (model -> corgisim kwargs), validate, cost, cpgs (XML -> Job), field (FOV preview),
                            progress (runner output -> events)
    corgisim_gui/engine/    stepwise.py: corgisim objects from a Job; PSF states, frames, spawn pool, L1 files
    corgisim_gui/runner.py  CLI entry point used by the console
    corgisim_gui/backend/   file-system and process access behind one interface
    corgisim_gui/ui/        setup_view.py (OpticalTrainStrip, FieldView, SetupView, SetupWindow), glyphs.py (QPainter
                            element glyphs), imaging.py (numpy -> QImage stretches/colour maps), base.ThemedWindow, widgets/
    corgisim_gui/app.py     make_app + CLI (opens the Setup View until the launcher exists)
    tools/render_setup_view.py   offscreen screenshots per theme (--all for the pol/spec examples)
    corgisim_gui/themes/ fonts/ theming.py   copied from corgidrp_gui; roles: QPushButton[role="primary"], QLabel[role="section"], ...
    tests/                  core tests run without corgisim; *_vs_corgisim / cpgs loader / engine tests need it

## Tests
    /opt/anaconda3/envs/corgisim_gui/bin/python -m pytest -q            # ~2 min, runs real PSFs in test_engine.py
    /opt/anaconda3/envs/corgisim_gui/bin/python -m pytest -q --deselect tests/test_engine.py   # seconds

`tests/test_tables_vs_corgisim.py` and `tests/test_cpgs.py::test_translation_matches_corgisim_loader`
compare the static tables and the CPGS translation with the installed corgisim/cgisim: after a
corgisim upgrade, run them first and fix `core/tables.py` / `core/cpgs.py` to match.

## Setup View conventions
- `SetupView.set_job(job)` validates, fills the strip for the selected visit (DPAM/roll/gain from the visit), renders
  the field with `core.field.render_field` and the facts panel. Windows embed `SetupView` and call `set_job` on edits.
- Glyph painters take a `colors` dict from `setup_view._colors(theme)`; field overlays use theme roles
  (action = dark hole, secondary = stops/slits, warn = pol beams, ok = sources).

## Windows
- Forms (`ui/forms.py`) have `load(spec)` / `apply(spec)` / `changed`; windows debounce `changed` and call
  `SetupView.set_job`. Hand-offs are plain callables set by `app.ToolWindows` (`queue_handler`, `sequence_handler`,
  `imagelab_handler`) plus Qt signals.
- Never call a modal `exec()` from code a test can reach (offscreen tests block forever); use `open()`.
- Slow things (importing corgisim, running) go in subprocesses: `RunnerProcess`, `corgisim_gui.envcheck`.
- Screenshots: `tools/render_all.py` (windows + Setup View, every theme).

## Phases
0 environment · 1 core + engine + runner · 2 Setup View · 3 Image Lab · 4 Sequence Builder · 5 Sim Console ·
6 launcher, CLI, docs — all done 2026-10-28. Next: real-use shakedown, the PR 300 upgrade, figure-panel glyphs.
