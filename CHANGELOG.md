# Changelog

## 0.1.0 — 2026-10-28

- Phases 3-6: Image Lab (forms for scene, instrument, detector, exposure and output; live Setup
  View; Preview and Simulate through the runner subprocess; Result viewer), Sequence Builder
  (editable visits table, templates, CPGS import with notes, per-visit Setup View and cost),
  Sim Console (persistent queue, one runner per job, progress per visit and frame, latest-frame
  view, log and traceback, hand-offs, corgidrp_gui hook), Launcher (tiles, environment check in a
  subprocess, theme), `corgisim-gui` CLI, user guide and developer notes, screenshots per theme.

- Phase 2: Setup View. An optical-train strip (DMs, SPAM, FPAM, LSAM, FSAM, CFAM, DPAM, EXCAM with
  schematic glyphs, the header element names and validation status per cell), a field-of-view
  widget (disk and Gaussian sources on the detector grid, dark hole, field stop or slit, polarimetry
  beams, compass, λ/D scale and rings, auto/zoom fit, hover readout), a facts panel (mechanisms,
  sources, cost, checks), a visit selector, and a standalone window with examples and job/CPGS
  loading. `tools/render_setup_view.py` renders the screenshots.

- Phase 0: conda environment `corgisim_gui` (corgisim main, emccd_detect 2.6.2, PySide6).
- Phase 1: Qt-free core (instrument tables checked against corgisim/cgisim, Job model with JSON
  round trip, corgisim keyword builder, validation, cost estimate, CPGS reader and translation
  checked against corgisim's loader, field-of-view preview with disk and Gaussian sources, progress
  parser), the stepwise engine (PSF states, satellite spots, parallel seeded detector frames, unique
  L1 timestamps, noiseless previews) and the `corgisim_gui.runner` CLI.
