# corgisim_gui plan (agreed 2026-10-28)

## Decisions
- A fresh conda environment for corgisim main plus the GUI dependencies.
- Own copy of the theme engine, widgets and fonts (no shared package with corgidrp_gui).
- Build against corgisim **main**; keep the upgrade to PR 300 (parallel frame generation) in mind.
- Separate `corgisim-gui` launcher; cross-links to corgidrp_gui later.
- Read CPGS, do not write it.
- Field preview draws the disk image and 2D Gaussians for off-axis sources.
- Schematic glyphs for the optical-train strip (figure panels from Riggs et al. 2025 later, with permission).
- Themes: not a focus for now.

## Upstream facts that shaped the design
- corgisim PR 300 adds `frame_runner(func, args_list)` and `seed` to `generate_observation_sequence`
  with a spawn-based pool (`parallel_executor.run_parallel`), per-frame detector tasks within a visit,
  bit-identical results for the same seed. PRs 300, 273 and 307 all rewrite the same function.
- PR 296 renames DM solution files for roman_preflight_proper v3; PR 304 drops the cgisim runtime import.
- A full-frame detector task needs about 13 GB; the console caps `n_jobs` by RAM.
- Measured 2026-10-28 (8-core Apple silicon): band-1 host PSF 90 s at oversampling 7, 39 s at 3;
  each companion the same again; full-frame emccd frame 18.5 s (gain-register CIC) or 1.5 s (fast).

## Phases
0. Environment (done).
1. Core + engine + runner (done): tables, model, build, validate, cost, cpgs, field, progress;
   stepwise engine with spawn pool and seeds; runner CLI with marker lines; 57 tests.
2. Setup View widget: optical-train strip + field-of-view sketch from `core.field`.
3. Image Lab window + result viewer.
4. Sequence Builder window (CPGS import, templates, cost per visit).
5. Sim Console + queue (runner subprocesses, progress, RAM-capped parallelism, "then reduce" hook).
6. Docs, screenshots, launcher, packaging.

## Reference
Riggs et al. 2025, JATIS 11(2) 021403, "Flight masks of the Roman Space Telescope Coronagraph
Instrument": Fig. 1 optical layout; Fig. 2-3 per-configuration optical train (the model for the
Setup View); Tables 1-3 mask configurations, PAM positions and field stops; Table 5 CFAM filters.
