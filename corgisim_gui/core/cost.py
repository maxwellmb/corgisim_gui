"""Cost estimate for a job: how many PROPER propagations and detector frames, and a rough wall-clock.

corgisim's cost is dominated by PROPER propagations. One *PSF state* (host star
with a given DM pattern and roll) costs::

    propagations = n_runs * nlam * (1 + n_offsets)

where ``n_runs`` is 4 for polarimetry (Wollaston) or ``polaxis=-10`` and 1
otherwise, ``nlam`` is the number of wavelengths of the bandpass (dense grid
with a prism) and ``n_offsets`` the jitter / stellar-diameter offsets. Each
off-axis point source adds one propagation set of its own. Satellite spots add
two more PSF states (positive and negative pattern). Detector frames are cheap
in comparison but a full-frame emccd_detect call with the gain-register CIC
model takes seconds and a lot of memory.

Per-propagation timings come from :data:`Calibration`; ``tools/calibrate_cost.py``
measures them on a machine and the console can update them from real runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import tables
from .model import Job, Visit


@dataclass
class Calibration:
    """Seconds per unit of work, measured on the development Mac (Apple silicon, 8 cores, 2026-10-28).

    A band-1 host PSF (7 wavelengths run in parallel by PROPER) took 90 s at
    oversampling 7 and 39 s at oversampling 3; each companion the same again;
    a full-frame emccd_detect frame 18.5 s with gain_CIC_Q='roman' and 1.5 s in
    fast mode. Times scale about linearly with the oversampling factor.
    """
    seconds_per_propagation: float = 90.0         # one PROPER run at one wavelength, oversampling 7, 201 px output
    optics_init_s: float = 3.0
    detector_subframe_s: float = 0.5
    detector_fullframe_s: float = 18.5            # emccd_detect full frame with gain_CIC_Q='roman'
    detector_fullframe_fast_s: float = 1.5        # fast_gain_mode=True or gain_CIC_Q=0
    fullframe_memory_gb: float = 13.0             # per concurrent full-frame detector task (corgisim PR 302 notes)
    proper_cores: int = 8                         # PROPER parallelises over wavelengths itself


DEFAULT_CALIBRATION = Calibration()


@dataclass
class CostEstimate:
    psf_states: int = 0                 # distinct (visit, DM pattern) PSF computations
    propagations: int = 0               # total PROPER runs (one wavelength each)
    frames: int = 0                     # detector frames
    satspot_frames: int = 0
    seconds_optics: float = 0.0
    seconds_detector: float = 0.0
    memory_gb: float = 0.0              # peak for the chosen n_jobs
    per_visit: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def seconds(self) -> float:
        return self.seconds_optics + self.seconds_detector

    @property
    def pretty_time(self) -> str:
        return pretty_seconds(self.seconds)


def pretty_seconds(s: float) -> str:
    if s < 90:
        return f"{s:.0f} s"
    if s < 5400:
        return f"{s / 60:.0f} min"
    if s < 2 * 86400:
        return f"{s / 3600:.1f} h"
    return f"{s / 86400:.1f} d"


def nlam_for(job: Job) -> int:
    inst = job.instrument
    f = inst.filter
    if f is None:
        return 7
    if inst.cgi_mode == "spec" and inst.has_prism:
        # dense dispersed grid: (lam_max - lam_min) / wav_step_um (default 1e-3 um)
        step = float(inst.extra_optics_keywords.get("wav_step_um", 1e-3))
        return max(f.nlam, int(round((f.lam_max_um - f.lam_min_um) / step)) + 1)
    return f.nlam


def runs_per_psf(job: Job, visit: Visit | None = None) -> int:
    inst = job.instrument
    dpam = job.visit_dpam(visit) if visit is not None else inst.dpam
    if dpam in ("POL0", "POL45") or inst.polaxis == -10:
        return 4
    return 1


def n_offsets(job: Job) -> int:
    j = job.instrument.jitter
    return j.n_offsets if j is not None else 0


def estimate(job: Job, calib: Calibration = DEFAULT_CALIBRATION) -> CostEstimate:
    est = CostEstimate()
    inst = job.instrument
    nlam = nlam_for(job)
    offsets = n_offsets(job)
    n_sources = job.scene.n_point_sources
    grid_scale = (inst.oversampling_factor / 7.0) * (max(inst.output_dim, 51) / 201.0) ** 0.3
    sec_prop = calib.seconds_per_propagation * max(grid_scale, 0.1)
    full = job.detector.full_frame
    fast = (job.detector.fast_gain_mode is True) or (job.detector.gain_CIC_Q == 0)
    sec_frame = (calib.detector_fullframe_fast_s if fast else calib.detector_fullframe_s) if full else calib.detector_subframe_s

    distinct_optics: set[tuple] = set()
    for i, v in enumerate(job.visits):
        runs = runs_per_psf(job, v)
        scene = job.reference_scene if v.is_reference and job.reference_scene else job.scene
        n_src = scene.n_point_sources if not v.is_reference else job.reference_scene.n_point_sources if job.reference_scene else 0
        states = 1 + (2 if v.satspots is not None else 0)
        # host star PSF: runs * nlam * (1 + offsets); each companion: runs * nlam; the disk: none (PRF cube)
        props = states * runs * nlam * ((1 + offsets) + n_src)
        frames = v.n_frames
        sat = 3 * v.satspots.n_frames if v.satspots else 0
        distinct_optics.add((job.visit_dpam(v), round(v.roll_angle_deg, 3)))
        # PROPER runs the nlam wavelengths of one propagation set in parallel on proper_cores cores
        secs_o = props * sec_prop / max(1, min(calib.proper_cores, nlam))
        secs_d = (frames + sat) * sec_frame / max(1, job.run.n_jobs)
        est.per_visit.append({"index": i, "label": v.label or f"visit {i + 1}", "psf_states": states, "propagations": props,
                              "frames": frames + sat, "seconds": secs_o + secs_d})
        est.psf_states += states
        est.propagations += props
        est.frames += frames
        est.satspot_frames += sat
        est.seconds_optics += secs_o
        est.seconds_detector += secs_d
    est.seconds_optics += calib.optics_init_s * max(1, len(distinct_optics))
    if full:
        est.memory_gb = calib.fullframe_memory_gb * max(1, job.run.n_jobs)
    else:
        est.memory_gb = 2.0 * max(1, job.run.n_jobs)
    if n_sources:
        est.notes.append(f"{n_sources} point source(s): each adds a propagation set per PSF state")
    if offsets:
        est.notes.append(f"jitter/stellar diameter preset '{inst.jitter.preset}': {offsets} extra offsets per host PSF")
    if runs_per_psf(job) == 4:
        est.notes.append("polarimetry or polaxis=-10: 4 propagations per wavelength")
    if inst.cgi_mode == "spec" and inst.has_prism:
        est.notes.append(f"prism: dense {nlam}-wavelength grid")
    return est


def max_parallel_jobs(memory_gb_available: float, cpu_count: int, full_frame: bool = True,
                      calib: Calibration = DEFAULT_CALIBRATION) -> int:
    """How many detector frames can be simulated at once on this machine."""
    per = calib.fullframe_memory_gb if full_frame else 2.0
    by_mem = max(1, int(memory_gb_available // per))
    return max(1, min(by_mem, cpu_count))
