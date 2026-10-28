"""Build corgisim objects from a :class:`Job` and run it, one PSF state and one frame at a time.

This is the GUI's own observation loop. It does what
``corgisim.observation.generate_observation_sequence`` does (host PSF, point
sources, satellite-spot states, one detector call per frame, L1 files per
visit) but also

* reports progress per PSF state and per frame through ``emit``,
* includes 2D scenes (disks) in every frame,
* writes the noiseless scene for the viewer,
* simulates detector frames in parallel with a spawn-based process pool and
  per-frame seeds (same scheme as corgisim PR 300: ``SeedSequence`` -> ints),
* gives every frame a synthetic, unique ``FTIMEUTC`` so file names never collide.

corgisim is imported inside the functions so this module can be imported (and
the task functions pickled by ``multiprocessing``) without corgisim being
importable in the parent.

Call :func:`prepare_environment` first: PROPER finds ``roman_preflight.py``
through the current working directory.
"""
from __future__ import annotations

import copy
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import numpy as np

from ..core import build
from ..core.model import Job, SceneSpec, Visit

Emit = Callable[[str, str], None]


def _noop(kind: str, text: str) -> None:
    pass


# ----------------------------------------------------------------------------- environment
def prepare_environment(workdir: str) -> str:
    """chdir into ``workdir`` and copy the roman_preflight prescription files there."""
    import roman_preflight_proper
    os.makedirs(workdir, exist_ok=True)
    os.chdir(workdir)
    for name in ("roman_preflight.py", "roman_preflight_compact.py"):
        if not os.path.exists(os.path.join(workdir, name)):
            roman_preflight_proper.copy_here()
            break
    return workdir


def dm_examples_dir() -> str:
    import roman_preflight_proper
    return os.path.join(roman_preflight_proper.lib_dir, "examples")


def load_dm(filename: str) -> np.ndarray:
    import proper
    path = filename if os.path.isabs(filename) else os.path.join(dm_examples_dir(), filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"DM solution not found: {path}")
    return proper.prop_fits_read(path)


def available_dm_rootnames() -> list[str]:
    """DM solutions actually present in the installed roman_preflight_proper."""
    d = dm_examples_dir()
    out = set()
    for f in os.listdir(d):
        if f.endswith("_dm1_v.fits") and os.path.exists(os.path.join(d, f.replace("_dm1_v", "_dm2_v"))):
            out.add(f[:-len("_dm1_v.fits")])
    return sorted(out)


# ----------------------------------------------------------------------------- objects
def make_scene(spec: SceneSpec):
    from corgisim import scene as cscene
    host = build.host_star_properties(spec)
    sources = build.point_source_info(spec)
    if sources:
        for s in sources:
            path = s.pop("Custom_Spectrum_path", None)
            if path:
                from synphot import SourceSpectrum
                s["Custom_Spectrum"] = SourceSpectrum.from_file(path)
    disk = build.twoD_scene_info(spec)
    return cscene.Scene(host, sources, disk, spmethod=spec.spmethod)


def make_jitter_keywords(args: dict[str, Any] | None) -> dict[str, Any] | None:
    if args is None:
        return None
    from corgisim import jitter
    preset = args["preset"]
    kw = jitter.load_predefined_jitter_and_stellar_diam_params(
        quicktest=(preset == "quicktest"), mintest=(preset == "mintest"), stellar_diam_mas=args.get("stellar_diam_mas", 0.0))
    kw.update(args.get("overrides", {}))
    return kw


def make_optics(job: Job, visit: Visit | None = None):
    """A CorgiOptics for ``visit`` (DPAM element and roll from the visit)."""
    from corgisim import instrument
    oa = build.optics_arguments(job, visit)
    kw = dict(oa.optics_keywords)
    for key in ("dm1_v", "dm2_v"):
        v = kw.get(key)
        if isinstance(v, str) and v.startswith(build.DM_KEY_PLACEHOLDER):
            kw[key] = load_dm(v[len(build.DM_KEY_PLACEHOLDER):])
    return instrument.CorgiOptics(oa.cgi_mode, oa.bandpass, optics_keywords=kw,
                                  satspot_keywords=oa.satspot_keywords,
                                  stellar_diam_and_jitter_keywords=make_jitter_keywords(oa.jitter_keywords),
                                  **oa.kwargs)


def make_detector(emccd_keywords: dict[str, Any], photon_counting: bool):
    from corgisim import instrument
    return instrument.CorgiDetector(emccd_keywords=dict(emccd_keywords), photon_counting=bool(photon_counting))


# ----------------------------------------------------------------------------- PSF states
def compute_psf(optics, scene_obj, spec: SceneSpec, emit: Emit = _noop, label: str = "host"):
    """Noiseless scene through the optics: host star, point sources, disk."""
    emit("psf", f"label={label} part=host")
    sim = optics.get_host_star_psf(scene_obj)
    if spec.point_sources:
        emit("psf", f"label={label} part=companions n={len(spec.point_sources)}")
        sim = optics.inject_point_sources(scene_obj, sim)
    if spec.disk is not None and spec.disk.path:
        emit("psf", f"label={label} part=disk")
        sim = optics.simulate_2d_scene(scene_obj, spec.disk.prf_cube_path, sim, interpolate_prfs=spec.disk.interpolate_prfs)
    return sim


def noiseless_image(sim) -> np.ndarray:
    """Sum of the noiseless components, as generate_detector_image adds them (counts/s)."""
    total = None
    for attr in ("host_star_image", "point_source_image", "twoD_image"):
        hdu = getattr(sim, attr, None)
        if hdu is None or getattr(hdu, "data", None) is None:
            continue
        d = np.asarray(hdu.data, dtype=float)
        total = d if total is None else total + d
    if total is None:
        raise ValueError("the simulated scene has no image components")
    return total


def save_noiseless(sim, path: str, extra_header: dict[str, Any] | None = None) -> str:
    from astropy.io import fits
    data = noiseless_image(sim)
    hdu = fits.PrimaryHDU(data)
    src = getattr(sim, "host_star_image", None)
    if src is not None:
        for card in src.header.cards:
            if card.keyword == "COMMENT":
                hdu.header.add_comment(card.value)
    hdu.header["BUNIT"] = "counts/s"
    for k, v in (extra_header or {}).items():
        hdu.header[k] = v
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    hdu.writeto(path, overwrite=True)
    return path


# ----------------------------------------------------------------------------- frames
def frame_seeds(seed: int | None, n: int) -> list[int | None]:
    if seed is None:
        return [None] * n
    ss = np.random.SeedSequence(int(seed))
    return [int(s) for s in ss.generate_state(n)]


def _seeded(seed: int | None):
    class _Ctx:
        def __enter__(self):
            self.state = np.random.get_state() if seed is not None else None
            if seed is not None:
                np.random.seed(seed)
            return self

        def __exit__(self, *exc):
            if self.state is not None:
                np.random.set_state(self.state)
    return _Ctx()


def frame_task(payload: dict[str, Any]) -> dict[str, Any]:
    """One detector frame. Runs in the parent or in a spawned worker; returns a small dict.

    payload keys: sim (SimulatedImage), emccd_keywords, photon_counting, exptime, full_frame,
    loc_x, loc_y, seed, save (bool), outdir, write_as_l1, overwrite, visit_id, ftimeutc,
    index, kind.
    """
    from corgisim import outputs
    t0 = time.monotonic()
    detector = make_detector(payload["emccd_keywords"], payload["photon_counting"])
    sim = copy.deepcopy(payload["sim"])
    with _seeded(payload.get("seed")):
        if payload["full_frame"]:
            sim = detector.generate_detector_image(sim, payload["exptime"], full_frame=True,
                                                   loc_x=payload["loc_x"], loc_y=payload["loc_y"])
        else:
            sim = detector.generate_detector_image(sim, payload["exptime"])
    out: dict[str, Any] = {"index": payload["index"], "kind": payload["kind"], "path": None,
                           "seconds": 0.0}
    img = sim.image_on_detector
    data = img[1].data if hasattr(img, "__len__") and len(img) > 1 else img.data
    out["max"] = float(np.max(data))
    out["mean"] = float(np.mean(data))
    if payload.get("save"):
        if payload["write_as_l1"]:
            prikw = {"VISITID": payload["visit_id"]} if payload.get("visit_id") else None
            extkw = {"FTIMEUTC": payload["ftimeutc"]} if payload.get("ftimeutc") else None
            outputs.save_hdu_to_fits(img, outdir=payload["outdir"], write_as_L1=True, overwrite=payload["overwrite"],
                                     overwrite_pri_keywords=prikw, overwrite_ext_keywords=extkw)
            fname = img[0].header["FILENAME"] if "FILENAME" in img[0].header else None
            if fname is None or not os.path.exists(os.path.join(payload["outdir"], fname)):
                # fall back to the newest file in outdir
                files = sorted((os.path.join(payload["outdir"], f) for f in os.listdir(payload["outdir"]) if f.endswith(".fits")),
                               key=os.path.getmtime)
                fname = os.path.basename(files[-1]) if files else fname
            out["path"] = os.path.join(payload["outdir"], fname) if fname else None
        else:
            fname = f"cgi_{payload.get('visit_id', 'sim')}_{payload['kind']}_{payload['index']:04d}"
            outputs.save_hdu_to_fits(img, outdir=payload["outdir"], write_as_L1=False, filename=fname, overwrite=payload["overwrite"])
            out["path"] = os.path.join(payload["outdir"], fname + ".fits")
    out["seconds"] = time.monotonic() - t0
    return out


def run_frames(payloads: list[dict[str, Any]], n_jobs: int = 1, on_result: Callable[[dict], None] | None = None) -> list[dict]:
    """Run frame tasks serially or in a spawn pool; results come back in completion order."""
    results = []
    if n_jobs <= 1 or len(payloads) <= 1:
        for p in payloads:
            r = frame_task(p)
            results.append(r)
            if on_result:
                on_result(r)
        return results
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    with ctx.Pool(min(n_jobs, len(payloads))) as pool:
        for r in pool.imap_unordered(frame_task, payloads):
            results.append(r)
            if on_result:
                on_result(r)
    return results


# ----------------------------------------------------------------------------- the job
class _Clock:
    """Synthetic exposure start times: t0 plus the cumulative exposure, at least 0.1 s apart."""

    def __init__(self, t0: datetime | None = None):
        self.t = t0 or datetime.now(timezone.utc)

    def next(self, exptime: float) -> str:
        """ISO string without a UTC offset: corgisim parses FTIMEUTC with astropy Time, which rejects '+00:00'."""
        stamp = self.t
        self.t = self.t + timedelta(seconds=max(float(exptime), 0.1))
        return stamp.replace(tzinfo=None).isoformat(timespec="microseconds")


def run_job(job: Job, emit: Emit = _noop, n_jobs: int | None = None) -> list[str]:
    """Simulate every visit of ``job``; returns the paths written."""
    n_jobs = int(n_jobs or job.run.n_jobs or 1)
    outputs_written: list[str] = []
    out = job.output
    scene_t = make_scene(job.scene)
    scene_r = make_scene(job.reference_scene) if job.reference_scene is not None else None
    optics_cache: dict[str, Any] = {}
    seeds = frame_seeds(job.run.seed, job.total_frames)
    seed_i = 0
    clock = _Clock()
    satkw = build.satspot_keywords(job.instrument)

    for vi, visit in enumerate(job.visits):
        visit_id = job.visit_id(vi)
        dpam = job.visit_dpam(visit)
        label = visit.label or f"visit {vi + 1}"
        emit("visit", f'i={vi + 1} n={job.n_visits} id={visit_id} label="{label}" frames={visit.total_frames} roll={visit.roll_angle_deg:g} dpam={dpam}')
        optics = optics_cache.get(dpam)
        if optics is None:
            optics = make_optics(job, visit)
            optics_cache[dpam] = optics
        optics.roll_angle = float(visit.roll_angle_deg)
        optics.visit_id = visit_id
        optics.visit_type = visit.vistype
        optics.SATSPOTS = 1 if visit.satspots is not None else 0
        spec = job.reference_scene if (visit.is_reference and job.reference_scene is not None) else job.scene
        scene_obj = scene_r if (visit.is_reference and scene_r is not None) else scene_t

        outdir = out.output_dir
        if out.visit_subfolders:
            outdir = os.path.join(out.output_dir, f"V{visit_id}")
        if out.save_fits or out.save_noiseless:
            os.makedirs(outdir, exist_ok=True)

        # PSF states: science, and with satellite spots also background (= science), positive, negative
        states: list[tuple[str, Any]] = []
        n_states = 1 + (2 if visit.satspots is not None else 0)
        emit("psf", f"i=1 n={n_states} label=science")
        sim_science = compute_psf(optics, scene_obj, spec, emit, "science")
        emit("psf_done", "i=1 label=science")
        states.append(("science", sim_science))
        if out.save_noiseless:
            p = save_noiseless(sim_science, os.path.join(outdir, f"noiseless_V{visit_id}_science.fits"),
                               {"VISITID": visit_id, "ROLL": float(visit.roll_angle_deg)})
            emit("preview", p)
        if visit.satspots is not None and satkw is not None:
            for k, sign in enumerate(("positive", "negative"), start=2):
                kw = dict(satkw)
                kw["sign"] = sign
                emit("psf", f"i={k} n={n_states} label=satspot_{sign}")
                optics.add_satspot(satspot_keywords=kw)
                try:
                    sim_s = compute_psf(optics, scene_obj, spec, emit, f"satspot_{sign}")
                finally:
                    optics.remove_satspot(satspot_keywords=kw)
                emit("psf_done", f"i={k} label=satspot_{sign}")
                states.append((f"satspot_{sign}", sim_s))
                if out.save_noiseless:
                    p = save_noiseless(sim_s, os.path.join(outdir, f"noiseless_V{visit_id}_satspot_{sign}.fits"),
                                       {"VISITID": visit_id, "ROLL": float(visit.roll_angle_deg), "SATSPOTS": 1})
                    emit("preview", p)
        if job.run.preview_only:
            continue

        # frames
        sci_kw, sci_pc = build.visit_detector_arguments(job, visit)
        payloads: list[dict[str, Any]] = []
        common = {"full_frame": job.detector.full_frame, "loc_x": job.detector.loc_x, "loc_y": job.detector.loc_y,
                  "save": out.save_fits, "outdir": outdir, "write_as_l1": out.write_as_l1 and job.detector.full_frame,
                  "overwrite": out.overwrite, "visit_id": visit_id}
        idx = 0
        if visit.satspots is not None:
            sat_kw, sat_pc = build.satspot_detector_arguments(job, visit)
            for kind, sim in (("satspot_background", sim_science), ("satspot_positive", states[1][1]), ("satspot_negative", states[2][1])):
                for _ in range(visit.satspots.n_frames):
                    payloads.append({**common, "sim": sim, "emccd_keywords": sat_kw, "photon_counting": sat_pc,
                                     "exptime": visit.satspots.exptime_s, "seed": seeds[seed_i] if seed_i < len(seeds) else None,
                                     "ftimeutc": clock.next(visit.satspots.exptime_s), "index": idx, "kind": kind})
                    idx += 1
                    seed_i += 1
        for _ in range(visit.n_frames):
            payloads.append({**common, "sim": sim_science, "emccd_keywords": sci_kw, "photon_counting": sci_pc,
                             "exptime": visit.exptime_s, "seed": seeds[seed_i] if seed_i < len(seeds) else None,
                             "ftimeutc": clock.next(visit.exptime_s), "index": idx, "kind": "science"})
            idx += 1
            seed_i += 1

        done = 0
        n = len(payloads)

        def on_result(r: dict, _n=n, _vi=vi):
            nonlocal done
            done += 1
            emit("frame", f"i={done} n={_n} visit={_vi + 1} kind={r['kind']} index={r['index']} seconds={r['seconds']:.1f} max={r['max']:.0f}")
            if r.get("path"):
                outputs_written.append(r["path"])
                emit("output", r["path"])

        run_frames(payloads, n_jobs=n_jobs, on_result=on_result)
    return outputs_written


# ----------------------------------------------------------------------------- corgisim's own loop
def run_job_corgisim(job: Job, emit: Emit = _noop) -> list[str]:
    """Run the visits through ``corgisim.observation.generate_observation_sequence`` (fidelity mode).

    Progress is per visit only; new files in the visit folder are reported after each visit.
    """
    from corgisim import observation
    written: list[str] = []
    scene_t = make_scene(job.scene)
    scene_r = make_scene(job.reference_scene) if job.reference_scene is not None else None
    optics_cache: dict[str, Any] = {}
    satkw = build.satspot_keywords(job.instrument)
    for vi, visit in enumerate(job.visits):
        visit_id = job.visit_id(vi)
        dpam = job.visit_dpam(visit)
        label = visit.label or f"visit {vi + 1}"
        emit("visit", f'i={vi + 1} n={job.n_visits} id={visit_id} label="{label}" frames={visit.total_frames} roll={visit.roll_angle_deg:g} dpam={dpam}')
        optics = optics_cache.get(dpam)
        if optics is None:
            optics = make_optics(job, visit)
            optics_cache[dpam] = optics
        optics.roll_angle = float(visit.roll_angle_deg)
        scene_obj = scene_r if (visit.is_reference and scene_r is not None) else scene_t
        sci_kw, sci_pc = build.visit_detector_arguments(job, visit)
        detector = make_detector(sci_kw, sci_pc)
        outdir = job.output.output_dir
        if job.output.visit_subfolders:
            outdir = os.path.join(outdir, f"V{visit_id}")
        os.makedirs(outdir, exist_ok=True)
        before = set(os.listdir(outdir))
        kwargs: dict[str, Any] = dict(vistype=visit.vistype, visit_id=visit_id, save_as_fits=job.output.save_fits,
                                      output_dir=outdir, full_frame=job.detector.full_frame,
                                      loc_x=job.detector.loc_x, loc_y=job.detector.loc_y)
        if visit.satspots is not None:
            sat_kw, sat_pc = build.satspot_detector_arguments(job, visit)
            kwargs.update(satspots_are_present=True, satspots_detector=make_detector(sat_kw, sat_pc),
                          satspots_exptime=visit.satspots.exptime_s, satspots_number_of_frames=visit.satspots.n_frames,
                          satspot_keywords=dict(satkw or {}))
        emit("psf", f"i=1 n=1 label=corgisim")
        observation.generate_observation_sequence(scene_obj, optics, detector, visit.exptime_s, visit.n_frames, **kwargs)
        new = sorted(set(os.listdir(outdir)) - before)
        for k, f in enumerate(new, start=1):
            p = os.path.join(outdir, f)
            written.append(p)
            emit("frame", f"i={k} n={len(new)} visit={vi + 1} kind=corgisim index={k - 1}")
            emit("output", p)
    return written
