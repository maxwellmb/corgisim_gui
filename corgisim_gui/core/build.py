"""Translate the model into the dictionaries corgisim's constructors take.

Everything returned here is plain Python (no corgisim import). DM solutions are
returned as file names; the engine loads them with ``proper.prop_fits_read`` and
replaces them with arrays right before constructing ``CorgiOptics``.

The functions mirror, one to one, what corgisim's tutorials and
``inputs.load_cpgs_data`` build by hand:

* :func:`host_star_properties`, :func:`point_source_info`, :func:`twoD_scene_info` -> ``scene.Scene(...)``
* :func:`optics_arguments` -> ``instrument.CorgiOptics(cgi_mode, bandpass, optics_keywords=..., ...)``
* :func:`emccd_keywords` -> ``instrument.CorgiDetector(emccd_keywords, photon_counting)``
* :func:`satspot_keywords`, :func:`jitter_keywords`
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import tables
from .model import DetectorSpec, InstrumentSpec, Job, SceneSpec, Visit

DM_KEY_PLACEHOLDER = "__dm_file__"   # value prefix for dm1_v / dm2_v before the engine loads the FITS


# ----------------------------------------------------------------------------- scene
def host_star_properties(scene: SceneSpec) -> dict[str, Any]:
    h = scene.host
    d: dict[str, Any] = {
        "Vmag": float(h.vmag), "spectral_type": h.spectral_type, "magtype": h.magtype,
        "ref_flag": bool(scene.ref_flag), "target_name": h.name, "RA": float(h.ra_deg), "DEC": float(h.dec_deg),
    }
    if h.stellar_diam_mas is not None:
        d["stellar_diam_mas"] = float(h.stellar_diam_mas)
    if h.stokes is not None:
        d["stokes_vector"] = list(h.stokes)
    return d


def point_source_info(scene: SceneSpec) -> list[dict[str, Any]] | None:
    """corgisim reads ``position_x``/``position_y`` as dRA/dDec in mas (scene.py)."""
    if not scene.point_sources:
        return None
    out = []
    for p in scene.point_sources:
        d: dict[str, Any] = {"Vmag": float(p.vmag), "magtype": p.magtype,
                             "position_x": float(p.dra_mas), "position_y": float(p.ddec_mas)}
        if p.stokes is not None:
            d["stokes_vector"] = list(p.stokes)
        if p.spectrum_path:
            d["Custom_Spectrum_path"] = p.spectrum_path     # the engine turns this into a synphot spectrum
            d["Rescale_Custom_Spectrum"] = bool(p.rescale_spectrum)
        out.append(d)
    return out


def twoD_scene_info(scene: SceneSpec) -> dict[str, Any] | None:
    if scene.disk is None or not scene.disk.path:
        return None
    d: dict[str, Any] = {"disk_model_path": scene.disk.path, "surface_brightness_unit": scene.disk.unit}
    if scene.disk.contrast is not None:
        d["contrast"] = float(scene.disk.contrast)
    return d


# ----------------------------------------------------------------------------- optics
@dataclass
class OpticsArguments:
    cgi_mode: str
    bandpass: str
    optics_keywords: dict[str, Any]
    kwargs: dict[str, Any] = field(default_factory=dict)     # roll_angle, oversampling_factor, ... and if_quiet
    dm_files: tuple[str, str] | None = None                  # (dm1, dm2) file names inside roman_preflight_proper/examples
    satspot_keywords: dict[str, Any] | None = None
    jitter_keywords: dict[str, Any] | None = None


def optics_keywords(inst: InstrumentSpec, dpam: str | None = None) -> dict[str, Any]:
    """The ``optics_keywords`` dict for CorgiOptics. ``dpam`` overrides the instrument's element."""
    prism = dpam if dpam is not None else inst.dpam
    kw: dict[str, Any] = {
        "cor_type": inst.cor_type,
        "polaxis": int(inst.polaxis),
        "output_dim": int(inst.output_dim),
        "use_errors": int(bool(inst.use_errors)),
        "use_fpm": int(bool(inst.use_fpm)),
        "use_lyot_stop": int(bool(inst.use_lyot_stop)),
        "use_field_stop": int(bool(inst.use_field_stop)),
        "use_pupil_lens": int(bool(inst.use_pupil_lens)),
        "prism": prism,
    }
    if inst.nd:
        kw["nd"] = int(inst.nd)
    if inst.dm_solution:
        dm = tables.DM_SOLUTIONS.get(inst.dm_solution)
        f1, f2 = dm.filenames() if dm else (f"{inst.dm_solution}_dm1_v.fits", f"{inst.dm_solution}_dm2_v.fits")
        kw["use_dm1"] = 1
        kw["dm1_v"] = DM_KEY_PLACEHOLDER + f1
        kw["use_dm2"] = 1
        kw["dm2_v"] = DM_KEY_PLACEHOLDER + f2
    else:
        kw["use_dm1"] = 0
        kw["use_dm2"] = 0
    if inst.fsm_x_offset_mas or inst.fsm_y_offset_mas:
        kw["fsm_x_offset_mas"] = float(inst.fsm_x_offset_mas)
        kw["fsm_y_offset_mas"] = float(inst.fsm_y_offset_mas)
    if inst.source_x_offset_mas or inst.source_y_offset_mas:
        kw["source_x_offset_mas"] = float(inst.source_x_offset_mas)
        kw["source_y_offset_mas"] = float(inst.source_y_offset_mas)
    if inst.cgi_mode == "spec":
        kw["slit"] = inst.slit or "None"
        kw["slit_ra_offset_mas"] = float(inst.slit_ra_offset_mas)
        kw["slit_dec_offset_mas"] = float(inst.slit_dec_offset_mas)
        if inst.slit_x_offset_mas is not None:
            kw["slit_x_offset_mas"] = float(inst.slit_x_offset_mas)
        if inst.slit_y_offset_mas is not None:
            kw["slit_y_offset_mas"] = float(inst.slit_y_offset_mas)
    kw.update(inst.extra_optics_keywords)
    return kw


def satspot_keywords(inst: InstrumentSpec) -> dict[str, Any] | None:
    s = inst.satspots
    if s is None:
        return None
    return {"num_pairs": int(s.num_pairs), "sep_lamD": float(s.sep_lamD),
            "angle_deg": [float(a) for a in s.angle_deg], "contrast": float(s.contrast)}


def jitter_keywords(inst: InstrumentSpec, stellar_diam_mas: float | None) -> dict[str, Any] | None:
    """Keywords for ``jitter.load_predefined_jitter_and_stellar_diam_params`` plus the overrides.

    The engine calls that corgisim function with ``quicktest``/``mintest`` from
    ``preset`` and then updates the result with ``overrides``.
    """
    j = inst.jitter
    if j is None or j.preset == "none":
        return None
    return {
        "preset": j.preset,
        "stellar_diam_mas": float(stellar_diam_mas or 0.0),
        "overrides": {
            "use_finite_stellar_diam": int(bool(j.use_finite_stellar_diam)),
            "add_jitter": int(bool(j.add_jitter)),
            "jitter_sigmax": float(j.jitter_sigma_x_mas),
            "jitter_sigmay": float(j.jitter_sigma_y_mas),
        },
    }


def optics_arguments(job: Job, visit: Visit | None = None) -> OpticsArguments:
    inst = job.instrument
    dpam = job.visit_dpam(visit) if visit is not None else inst.dpam
    roll = visit.roll_angle_deg if visit is not None else inst.roll_angle_deg
    kw = optics_keywords(inst, dpam)
    dm_files = None
    if inst.dm_solution:
        dm_files = (kw["dm1_v"][len(DM_KEY_PLACEHOLDER):], kw["dm2_v"][len(DM_KEY_PLACEHOLDER):])
    kwargs = {"roll_angle": float(roll), "oversampling_factor": int(inst.oversampling_factor),
              "return_oversample": bool(inst.return_oversample), "if_quiet": True}
    stellar_diam = job.scene.host.stellar_diam_mas
    return OpticsArguments(inst.cgi_mode, inst.bandpass, kw, kwargs, dm_files,
                           satspot_keywords(inst), jitter_keywords(inst, stellar_diam))


# ----------------------------------------------------------------------------- detector
def emccd_keywords(det: DetectorSpec, em_gain: float | None = None) -> dict[str, Any]:
    kw = det.emccd_keywords()
    if em_gain is not None:
        kw["em_gain"] = float(em_gain)
    return kw


def visit_detector_arguments(job: Job, visit: Visit) -> tuple[dict[str, Any], bool]:
    """``(emccd_keywords, photon_counting)`` for the science frames of ``visit``."""
    return emccd_keywords(job.detector, job.visit_gain(visit)), job.visit_photon_counting(visit)


def satspot_detector_arguments(job: Job, visit: Visit) -> tuple[dict[str, Any], bool] | None:
    if visit.satspots is None:
        return None
    return emccd_keywords(job.detector, visit.satspots.em_gain), False


# ----------------------------------------------------------------------------- summary
def describe(job: Job) -> dict[str, Any]:
    """A flat, human-readable summary of what will be simulated (for the Setup View and logs)."""
    inst = job.instrument
    mech = inst.mechanisms()
    f = inst.filter
    return {
        "name": job.name,
        "mode": inst.cgi_mode,
        "coronagraph": inst.cor_type,
        "coronagraph_label": inst.coronagraph.label if inst.coronagraph else "?",
        "filter": inst.bandpass,
        "filter_center_nm": f.center_nm if f else None,
        "filter_fwhm_nm": f.fwhm_nm if f else None,
        "nlam": f.nlam if f else None,
        "lam_over_d_mas": round(inst.lam_over_d_mas, 2),
        "mechanisms": mech.as_dict(),
        "dm_solution": inst.dm_solution,
        "host": job.scene.host.label(),
        "n_point_sources": job.scene.n_point_sources,
        "disk": bool(job.scene.disk and job.scene.disk.path),
        "reference": job.reference_scene.host.label() if job.reference_scene else None,
        "n_visits": job.n_visits,
        "total_frames": job.total_frames,
        "total_exposure_s": job.total_exposure_s,
        "engine": job.run.engine,
        "n_jobs": job.run.n_jobs,
    }
