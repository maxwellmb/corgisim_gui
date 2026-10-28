"""Validation of a :class:`Job` before it is run.

Returns a list of :class:`Issue` (level ``error`` stops a run; ``warn`` and
``info`` are shown). The rules replicate the checks corgisim makes at
construction time (so the user sees them before a long run) plus the pitfalls
documented in the corgisim code and issues.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

from . import tables
from .model import Job, SceneSpec, Visit

LEVELS = ("error", "warn", "info")


@dataclass(frozen=True)
class Issue:
    level: str
    field: str          # dotted path into the model, e.g. 'instrument.bandpass' or 'visits[2].exptime_s'
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.field}: {self.message}"


def _err(field: str, msg: str) -> Issue:
    return Issue("error", field, msg)


def _warn(field: str, msg: str) -> Issue:
    return Issue("warn", field, msg)


def _info(field: str, msg: str) -> Issue:
    return Issue("info", field, msg)


# ----------------------------------------------------------------------------- scene
_SPTYPE_RE = None


def _sptype_ok(s: str) -> bool:
    global _SPTYPE_RE
    import re
    if _SPTYPE_RE is None:
        # corgisim.scene: ^[OBAFGKM][0-9](\.\d)?(I|II|III|IV|V|VI|VII)?$
        _SPTYPE_RE = re.compile(r"^[OBAFGKM][0-9](\.\d)?(I|II|III|IV|V|VI|VII)?$")
    return bool(_SPTYPE_RE.match(s or ""))


def validate_scene(scene: SceneSpec, job: Job, prefix: str = "scene") -> list[Issue]:
    out: list[Issue] = []
    h = scene.host
    if not _sptype_ok(h.spectral_type):
        out.append(_err(f"{prefix}.host.spectral_type",
                        f"'{h.spectral_type}' is not a spectral type corgisim accepts (e.g. G2V, A0, K5III)"))
    if h.magtype != "vegamag":
        out.append(_err(f"{prefix}.host.magtype", "corgisim only implements 'vegamag' (ABmag raises NotImplementedError)"))
    if h.stokes is not None:
        if len(h.stokes) != 4 or h.stokes[0] <= 0 or math.hypot(h.stokes[1], math.hypot(h.stokes[2], h.stokes[3])) > h.stokes[0] + 1e-9:
            out.append(_err(f"{prefix}.host.stokes", "Stokes vector must be [I,Q,U,V] with I>0 and sqrt(Q²+U²+V²) <= I"))
    if h.stellar_diam_mas is not None and h.stellar_diam_mas < 0:
        out.append(_err(f"{prefix}.host.stellar_diam_mas", "stellar diameter must be >= 0"))

    inst = job.instrument
    lamd = inst.lam_over_d_mas
    iwa, owa = tables.dark_hole_lamD(inst.cor_type)
    for i, p in enumerate(scene.point_sources):
        f = f"{prefix}.point_sources[{i}]"
        if p.magtype != "vegamag":
            out.append(_err(f"{f}.magtype", "corgisim only implements 'vegamag'"))
        if lamd > 0 and owa > 0:
            r = p.separation_mas / lamd
            if not (iwa <= r <= owa):
                out.append(_warn(f, f"{p.label or 'source ' + str(i + 1)} at {r:.1f} λ/D ({p.separation_mas:.0f} mas) is outside "
                                    f"the {iwa:g}-{owa:g} λ/D dark hole of {inst.cor_type} (corgisim warns, still simulates)"))
        if p.spectrum_path and not os.path.exists(p.spectrum_path):
            out.append(_err(f"{f}.spectrum_path", f"spectrum file not found: {p.spectrum_path}"))
    if scene.disk is not None and scene.disk.path:
        d = scene.disk
        if not os.path.exists(d.path):
            out.append(_err(f"{prefix}.disk.path", f"disk model not found: {d.path}"))
        if d.unit not in ("mJy/arcsec^2", "W.m^-2.pixel^-1", "contrast/pixel"):
            out.append(_err(f"{prefix}.disk.unit", f"unknown surface brightness unit '{d.unit}'"))
        if d.unit == "contrast/pixel" and d.contrast is None:
            out.append(_warn(f"{prefix}.disk.contrast", "contrast/pixel images usually need 'contrast' to scale the spectrum"))
        if not d.prf_cube_path:
            out.append(_err(f"{prefix}.disk.prf_cube_path", "a PRF cube is required for the 2D-scene convolution (see corgisim examples/prf_build_demo.ipynb)"))
        elif not os.path.exists(d.prf_cube_path):
            out.append(_err(f"{prefix}.disk.prf_cube_path", f"PRF cube not found: {d.prf_cube_path}"))
        if job.run.engine == "corgisim":
            out.append(_warn(f"{prefix}.disk", "corgisim's generate_observation_sequence ignores 2D scenes; use the stepwise engine to include the disk"))
        if any(v.roll_angle_deg % 360 != 0 for v in job.visits):
            out.append(_warn(f"{prefix}.disk", "corgisim main raises NotImplementedError for 2D scenes at roll angle != 0 (PR 287 adds it)"))
    return out


# ----------------------------------------------------------------------------- instrument
def validate_instrument(job: Job) -> list[Issue]:
    out: list[Issue] = []
    inst = job.instrument
    c = inst.coronagraph
    f = inst.filter
    if inst.cgi_mode not in tables.CGI_MODES:
        out.append(_err("instrument.cgi_mode", f"'{inst.cgi_mode}': only {tables.CGI_MODES} are implemented in corgisim"))
    if c is None:
        out.append(_err("instrument.cor_type", f"unknown coronagraph '{inst.cor_type}'"))
        return out
    if not c.tested:
        out.append(_warn("instrument.cor_type", f"{inst.cor_type} is available in cgisim but untested in corgisim"))
    if c.cgi_mode != inst.cgi_mode:
        out.append(_err("instrument.cgi_mode", f"{inst.cor_type} needs cgi_mode '{c.cgi_mode}', not '{inst.cgi_mode}'"))
    if f is None:
        out.append(_err("instrument.bandpass", f"unknown filter '{inst.bandpass}'"))
    elif not c.allows_filter(inst.bandpass):
        out.append(_err("instrument.bandpass", f"cgisim does not allow filter {inst.bandpass} with {inst.cor_type}; "
                                               f"allowed: {', '.join(tables.allowed_filters(inst.cor_type))}"))
    elif f.band not in c.bands:
        out.append(_warn("instrument.bandpass", f"{inst.bandpass} is band {f.band}; {inst.cor_type} was designed for band {c.bands}"))

    # DPAM
    if inst.cgi_mode == "excam" and inst.dpam not in tables.DPAM_EXCAM:
        out.append(_err("instrument.dpam", f"'{inst.dpam}' is not valid in excam mode; use one of {tables.DPAM_EXCAM}"))
    if inst.cgi_mode == "spec" and inst.dpam not in tables.DPAM_SPEC:
        out.append(_err("instrument.dpam", f"'{inst.dpam}' is not valid in spec mode; use one of {tables.DPAM_SPEC}"))
    if inst.cgi_mode == "spec" and f is not None:
        if inst.dpam == "PRISM2" and f.band == 3 and not c.rotated:
            out.append(_warn("instrument.dpam", "PRISM2 with a band 3 filter is off-nominal (corgisim warns)"))
        if inst.dpam == "PRISM3" and f.band == 2:
            out.append(_warn("instrument.dpam", "PRISM3 with a band 2 filter is off-nominal (corgisim warns)"))
    if inst.is_polarimetry and inst.output_dim >= tables.POL_MAX_SUBIMAGE_PIX:
        out.append(_err("instrument.output_dim", f"polarimetry places two beams; the image must be smaller than {tables.POL_MAX_SUBIMAGE_PIX} pixels"))
    if inst.is_polarimetry and inst.polaxis not in (10, -10, 0):
        out.append(_warn("instrument.polaxis", "a Wollaston already splits the beams; polaxis other than 10 halves the throughput again"))

    # slit
    if inst.cgi_mode == "spec":
        band = f.band if f else 0
        allowed = tables.SLITS_BY_BAND.get(band)
        if allowed is None:
            out.append(_err("instrument.bandpass", "spectroscopy needs a band 2 or band 3 filter"))
        elif inst.slit not in allowed:
            out.append(_err("instrument.slit", f"slit '{inst.slit}' not available for band {band}; use one of {allowed}"))
        if inst.has_prism:
            out.append(_info("instrument.dpam", "with a prism corgisim propagates the dense dispersed wavelength grid "
                                                "(about 120 wavelengths): expect a much slower PSF"))

    # ND filters
    if inst.nd not in tables.ND_FILTERS:
        out.append(_err("instrument.nd", "nd must be 0, 1, 2 or 3"))
    if inst.nd in (1, 2) and inst.use_fpm:
        out.append(_err("instrument.nd", "ND filters 1 and 2 sit at FPAM: turn the focal plane mask off (use_fpm) to use them"))
    if inst.nd == 3 and inst.use_lyot_stop:
        out.append(_err("instrument.nd", "ND filter 3 (4.75 at FSAM) cannot be used with the Lyot stop in corgisim"))

    # pupil imaging
    if inst.use_pupil_lens and (inst.use_fpm or inst.use_lyot_stop or inst.use_field_stop):
        out.append(_warn("instrument.use_pupil_lens", "pupil imaging with the FPM, Lyot stop or field stop still in (corgisim warns)"))

    # polaxis
    if inst.polaxis not in tables.POLAXIS_CHOICES:
        out.append(_err("instrument.polaxis", f"polaxis must be one of {list(tables.POLAXIS_CHOICES)}"))
    elif inst.polaxis not in (10, -10, 0):
        out.append(_info("instrument.polaxis", "single-channel polaxis halves the throughput (polarizer transmission 0.48)"))
    if inst.polaxis == -10:
        out.append(_info("instrument.polaxis", "polaxis -10 runs corgisim's full aberration model: 4 propagations per PSF"))

    # DM solution
    if inst.dm_solution:
        dm = tables.DM_SOLUTIONS.get(inst.dm_solution)
        if dm is None:
            out.append(_warn("instrument.dm_solution", f"'{inst.dm_solution}' is not one of the DM solutions shipped with roman_preflight_proper 2.0.2; "
                                                       "the engine will look for <rootname>_dm1_v.fits in its examples folder"))
        elif dm.family != c.family:
            out.append(_warn("instrument.dm_solution", f"{inst.dm_solution} was made for {dm.family}, not {c.family}"))
        elif dm.band is not None and f is not None and dm.band != f.band:
            out.append(_warn("instrument.dm_solution", f"{inst.dm_solution} was made for band {dm.band}; you selected band {f.band}"))
    else:
        if inst.use_errors:
            out.append(_warn("instrument.dm_solution", "no DM solution with use_errors on: no dark hole will be dug (speckles everywhere)"))
    if not c.dm_rootnames and inst.dm_solution:
        out.append(_warn("instrument.dm_solution", f"roman_preflight_proper 2.0.2 ships no DM solution for {inst.cor_type}; "
                                                   "corgisim's notebooks turn DMs and errors off for it"))

    # satellite spots
    if inst.satspots is not None:
        s = inst.satspots
        if not inst.dm_solution:
            out.append(_err("instrument.satspots", "satellite spots are added to DM1: a DM solution (use_dm1=1) is required"))
        if s.num_pairs not in (1, 2):
            out.append(_err("instrument.satspots.num_pairs", "num_pairs must be 1 or 2"))
        if len(s.angle_deg) != s.num_pairs:
            out.append(_err("instrument.satspots.angle_deg", f"give one angle per pair ({s.num_pairs})"))
        if s.sep_lamD <= 0 or s.contrast <= 0:
            out.append(_err("instrument.satspots", "separation and contrast must be positive"))
    for i, v in enumerate(job.visits):
        if v.satspots is not None and inst.satspots is None:
            out.append(_err(f"visits[{i}].satspots", "the visit takes satellite-spot frames but no satellite-spot pattern is defined on the instrument"))

    # jitter
    if inst.jitter is not None and inst.jitter.preset not in tables.JITTER_PRESETS:
        out.append(_err("instrument.jitter.preset", f"preset must be one of {list(tables.JITTER_PRESETS)}"))
    if inst.jitter is not None and inst.jitter.preset != "none" and inst.jitter.use_finite_stellar_diam and not job.scene.host.stellar_diam_mas:
        out.append(_warn("scene.host.stellar_diam_mas", "finite stellar diameter is on but the host star has no diameter"))

    # sizes
    if inst.output_dim < 3 or inst.output_dim % 2 == 0:
        out.append(_warn("instrument.output_dim", "use an odd output_dim so the star sits on a pixel centre"))
    if inst.oversampling_factor < 1:
        out.append(_err("instrument.oversampling_factor", "oversampling_factor must be >= 1"))
    return out


# ----------------------------------------------------------------------------- detector / visits
def validate_visits(job: Job) -> list[Issue]:
    out: list[Issue] = []
    det = job.detector
    inst = job.instrument
    if det.em_gain < 1:
        out.append(_err("detector.em_gain", "EM gain must be >= 1"))
    if det.full_frame:
        half = inst.output_dim // 2
        for name, v in (("loc_x", det.loc_x), ("loc_y", det.loc_y)):
            if v - half < 0 or v + half >= tables.EXCAM_IMAGE_PIX:
                out.append(_err(f"detector.{name}", f"the {inst.output_dim}-pixel image centred at {v} does not fit in the 1024-pixel science area"))
        if inst.is_polarimetry:
            dx, dy = tables.POL_BEAM_OFFSET_PIX[inst.dpam]
            if det.loc_x - dx - half < 0 or det.loc_x + dx + half >= tables.EXCAM_IMAGE_PIX or \
               det.loc_y - dy - half < 0 or det.loc_y + dy + half >= tables.EXCAM_IMAGE_PIX:
                out.append(_err("detector.loc_x", "the two polarimetry beams do not fit on the detector at this position"))
    else:
        if job.output.write_as_l1:
            out.append(_err("output.write_as_l1", "L1 files need full-frame detector images (detector.full_frame)"))
    if "qe" in det.extra_emccd_keywords:
        out.append(_err("detector.extra_emccd_keywords", "corgisim forbids 'qe' (it is already in the bandpass)"))
    if det.extra_emccd_keywords.get("use_traps"):
        out.append(_err("detector.extra_emccd_keywords", "use_traps=True raises NotImplementedError in corgisim"))
    unknown = set(det.extra_emccd_keywords) - set(tables.EMCCD_DEFAULTS)
    if unknown:
        out.append(_warn("detector.extra_emccd_keywords", f"corgisim silently ignores unknown EMCCD keywords: {sorted(unknown)}"))

    if not job.visits:
        out.append(_err("visits", "at least one visit is needed"))
    seen_nums: dict[str, int] = {}
    for i, v in enumerate(job.visits):
        f = f"visits[{i}]"
        if v.vistype not in tables.VISIT_TYPES:
            out.append(_err(f"{f}.vistype", f"'{v.vistype}' is not one of {tables.VISIT_TYPES}"))
        if v.n_frames < 0:
            out.append(_err(f"{f}.n_frames", "n_frames must be >= 0"))
        if v.n_frames == 0 and v.satspots is None:
            out.append(_warn(f, "this visit produces no frames"))
        if v.exptime_s <= 0:
            out.append(_err(f"{f}.exptime_s", "exposure time must be positive"))
        if v.is_reference and job.reference_scene is None:
            out.append(_err(f"{f}.is_reference", "a reference visit needs a reference scene"))
        if v.dpam is not None:
            ok = tables.DPAM_EXCAM if inst.cgi_mode == "excam" else tables.DPAM_SPEC
            if v.dpam not in ok:
                out.append(_err(f"{f}.dpam", f"'{v.dpam}' is not valid in {inst.cgi_mode} mode"))
        if v.vistype == "CGIVST_TDD_POL_OBS" and job.visit_dpam(v) not in ("POL0", "POL45"):
            out.append(_warn(f"{f}.dpam", "a polarimetry visit without a Wollaston in DPAM"))
        if v.satspots is not None:
            if v.satspots.n_frames <= 0 or v.satspots.exptime_s <= 0:
                out.append(_err(f"{f}.satspots", "satellite-spot frames need n_frames > 0 and a positive exposure time"))
        vid = job.visit_id(i)
        if len(vid) != 19 or not vid.isdigit():
            out.append(_err(f"{f}.visit_num", f"VISITID '{vid}' must be 19 digits (visit_id_root 16 digits + 3-digit visit number)"))
        if vid in seen_nums:
            out.append(_warn(f"{f}.visit_num", f"VISITID {vid} is also used by visit {seen_nums[vid] + 1}; their files share a folder"))
        seen_nums.setdefault(vid, i)
        if v.zernike_index is not None:
            out.append(_info(f"{f}.zernike_index", "per-visit Zernike drift needs corgisim PR 300 (ignored on main)"))
    return out


def validate_output(job: Job) -> list[Issue]:
    out: list[Issue] = []
    o = job.output
    if o.save_fits and not o.output_dir:
        out.append(_err("output.output_dir", "choose an output folder"))
    if o.save_fits and o.output_dir and os.path.exists(o.output_dir) and not os.path.isdir(o.output_dir):
        out.append(_err("output.output_dir", f"{o.output_dir} is not a folder"))
    if o.write_as_l1 and not o.save_fits:
        out.append(_info("output.write_as_l1", "L1 headers are only written when saving FITS"))
    if job.run.engine not in ("stepwise", "corgisim"):
        out.append(_err("run.engine", "engine must be 'stepwise' or 'corgisim'"))
    if job.run.n_jobs < 1:
        out.append(_err("run.n_jobs", "n_jobs must be >= 1"))
    if job.run.engine == "corgisim":
        if job.run.n_jobs > 1:
            out.append(_info("run.n_jobs", "corgisim main simulates frames serially; n_jobs applies to the stepwise engine (or corgisim PR 300)"))
        if job.run.preview_only:
            out.append(_err("run.preview_only", "preview (noiseless PSF only) needs the stepwise engine"))
        if any(v.satspots is not None for v in job.visits) and job.detector.full_frame:
            out.append(_warn("run.engine", "corgisim main calls remove_satspot inside the full-frame satellite-spot loop (bug, fixed by PR 310): "
                                          "with more than one spot frame per sign the DM pattern flips repeatedly"))
    return out


def validate_job(job: Job) -> list[Issue]:
    issues = validate_instrument(job)
    issues += validate_scene(job.scene, job, "scene")
    if job.reference_scene is not None:
        issues += validate_scene(job.reference_scene, job, "reference_scene")
        if not job.reference_scene.ref_flag:
            issues.append(_warn("reference_scene.ref_flag", "the reference scene's ref_flag is off; PSFREF will read 0 in its headers"))
    issues += validate_visits(job)
    issues += validate_output(job)
    order = {"error": 0, "warn": 1, "info": 2}
    issues.sort(key=lambda i: order[i.level])
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(i.level == "error" for i in issues)
