# Changelog

## Unreleased

- Phase 0: conda environment `corgisim_gui` (corgisim main, emccd_detect 2.6.2, PySide6).
- Phase 1: Qt-free core (instrument tables checked against corgisim/cgisim, Job model with JSON
  round trip, corgisim keyword builder, validation, cost estimate, CPGS reader and translation
  checked against corgisim's loader, field-of-view preview with disk and Gaussian sources, progress
  parser), the stepwise engine (PSF states, satellite spots, parallel seeded detector frames, unique
  L1 timestamps, noiseless previews) and the `corgisim_gui.runner` CLI.
