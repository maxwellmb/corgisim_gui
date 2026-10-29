# corgisim GUI — developer notes

## Principles

- **Never modify corgisim** (nor cgisim, proper, roman_preflight_proper). Import, read, call.
- `core/` is Qt-free and corgisim-free; `engine/` is Qt-free and imports corgisim inside functions;
  `ui/` is layout and plumbing. Tests exercise `core/` without corgisim and the engine / tables /
  CPGS translation against the real install.
- Simulations run in a subprocess (`corgisim_gui.runner`), never in the GUI process: PROPER
  spawns its own pool, corgisim objects are not thread-safe, and the user can abort.
- Python for everything: `/opt/anaconda3/envs/corgisim_gui/bin/python` on the development Mac.

## Layout

    corgisim_gui/
      core/
        tables.py       coronagraphs, filters, mechanisms, slits, ND, DM solutions, satellite-spot pair ids, jitter presets,
                        header_mechanisms() replicating corgisim.outputs.write_headers_*
        model.py        Job / SceneSpec / InstrumentSpec / DetectorSpec / Visit / OutputSpec / RunSpec (+ JSON) and templates
        build.py        model -> corgisim keyword dicts (optics_keywords with DM file placeholders, emccd keywords, scene dicts)
        validate.py     Issue list: corgisim's construction-time checks and documented pitfalls
        cost.py         propagations, frames, wall-clock and memory estimate; Calibration measured on this machine
        cpgs.py         read_cpgs (XML -> CpgsFile), job_from_cpgs (mirrors inputs.load_cpgs_data), summarize
        field.py        FieldPreview: image + overlays at the EXCAM plate scale
        progress.py     ProgressParser: runner marker lines -> events and state
        queue.py        SimJob / JobQueue (persisted in ~/.corgisim_gui/queue), machine_limits
      engine/stepwise.py  prepare_environment, make_scene/optics/detector, compute_psf, frame_task (spawn-safe), run_job, run_job_corgisim
      runner.py         CLI; marker lines "corgisim_gui <kind>: ..."
      envcheck.py       environment report as JSON (the launcher runs it in a subprocess)
      ui/
        setup_view.py   OpticalTrainStrip, FieldView, SetupView, SetupWindow
        glyphs.py       QPainter glyphs per element; imaging.py stretches/colour maps; image_view.py FITS viewer
        forms.py        SceneForm, InstrumentForm, DetectorForm, VisitForm, OutputRunForm (load/apply/changed)
        imagelab_window.py, sequence_window.py, console_window.py, launcher.py
        runner_process.py RunnerProcess (QProcess + ProgressParser)
      app.py            make_app, ToolWindows (hand-offs), CLI
      theming.py, themes/, fonts/   copied from corgidrp_gui
    tools/render_all.py  screenshots for docs

## How the pieces talk

- Forms emit `changed`; the windows debounce (200 ms), `apply_forms()` into the Job and call
  `SetupView.set_job(job)`, which validates, renders the field and fills the facts.
- Image Lab → Console: `queue_handler(job) -> bool`; Image Lab → Sequence: `sequence_handler(job)`;
  Sequence → Image Lab: `imagelab_handler(job)` (one visit, DPAM/roll/gain folded into the setup);
  Console → either. `app.ToolWindows` sets the handlers; each window also emits a Qt signal.
- The runner prints `corgisim_gui job|visit|psf|psf_done|frame|output|preview|finished:` lines.
  `ProgressParser.fraction` counts frames (PSF work counts as half a visit until its first frame).

## Upgrading corgisim

Run `tests/test_tables_vs_corgisim.py` and `tests/test_cpgs.py` first: they compare the static
tables and the CPGS translation with the installed corgisim/cgisim and fail on drift. The engine's
own loop in `engine/stepwise.py` is the only place that would change for PR 300 (parallel frame
generation: swap `run_frames` for `frame_runner`, pass `seed`, add `zindex/zval_m_i`).

## Tests and screenshots

    python -m pytest -q --deselect tests/test_engine.py --deselect tests/test_gui_runs.py   # seconds
    python -m pytest -q                                                                        # ~4 min, real PSFs
    python tools/render_all.py                                                                 # all themes, all windows

GUI tests run offscreen (`QT_QPA_PLATFORM=offscreen`) with QSettings and `CORGISIM_GUI_HOME`
redirected to temp folders. Never call a modal `exec()` from code a test reaches; use `open()`.

## Adding a window

Subclass `ui.base.ThemedWindow`, build menus with `add_menu`, `add_theme_menu`, `add_help_menu`,
use `Panel` + `SectionLabel`, run anything slow in a subprocess (`RunnerProcess` or a QProcess),
register it in `app.ToolWindows`, add an offscreen test and a `tools/render_windows.py` entry.
