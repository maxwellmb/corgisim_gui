"""The parameter model: what the GUI edits, what a job file stores, what the runner executes.

A :class:`Job` is the unit of work. It holds a target :class:`SceneSpec` (and an
optional reference-star scene), one :class:`InstrumentSpec`, default
:class:`DetectorSpec` values, a list of :class:`Visit` and :class:`OutputSpec` /
:class:`RunSpec`. A single image is a job with one visit of one frame.

The model is plain dataclasses with a JSON round trip (``to_dict`` /
``from_dict``). Unknown keys are ignored on load so job files written by a newer
version still open. Nothing here imports corgisim; :mod:`corgisim_gui.core.build`
turns a job into corgisim keyword dictionaries.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any

from . import tables

JOB_FORMAT_VERSION = 1


# ----------------------------------------------------------------------------- helpers
def _from_dict(cls, data: dict | None):
    """Build dataclass ``cls`` from ``data``, recursing into nested dataclass fields."""
    if data is None:
        return None
    kwargs = {}
    hints = {f.name: f.type for f in fields(cls)}
    for f in fields(cls):
        if f.name not in data:
            continue
        v = data[f.name]
        nested = _NESTED.get((cls.__name__, f.name))
        if nested is not None and v is not None:
            if isinstance(v, list):
                v = [_from_dict(nested, x) for x in v]
            else:
                v = _from_dict(nested, v)
        kwargs[f.name] = v
    del hints
    return cls(**kwargs)


def _to_dict(obj) -> Any:
    if is_dataclass(obj):
        return {k: _to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, (list, tuple)):
        return [_to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    return obj


# ----------------------------------------------------------------------------- scene
@dataclass
class HostStar:
    vmag: float = 5.0
    spectral_type: str = "G2V"
    magtype: str = "vegamag"
    name: str = "UNKNOWN"
    ra_deg: float = 0.0
    dec_deg: float = 0.0
    stellar_diam_mas: float | None = None
    stokes: list[float] | None = None        # [I, Q, U, V]; None -> unpolarized

    def label(self) -> str:
        return f"{self.name} ({self.spectral_type}, V={self.vmag:g})"


@dataclass
class PointSource:
    """An off-axis point source. Positions are sky offsets (dRA, dDec) in mas."""
    vmag: float = 20.0
    dra_mas: float = 200.0
    ddec_mas: float = 0.0
    magtype: str = "vegamag"
    label: str = ""
    stokes: list[float] | None = None
    spectrum_path: str | None = None          # optional custom spectrum (CSV: wavelength, flux)
    rescale_spectrum: bool = False

    @property
    def separation_mas(self) -> float:
        return (self.dra_mas ** 2 + self.ddec_mas ** 2) ** 0.5

    @property
    def pa_deg(self) -> float:
        """Position angle east of north, degrees in [0, 360)."""
        import math
        return math.degrees(math.atan2(self.dra_mas, self.ddec_mas)) % 360.0

    @classmethod
    def from_polar(cls, vmag: float, separation_mas: float, pa_deg: float, **kw) -> "PointSource":
        import math
        pa = math.radians(pa_deg)
        return cls(vmag=vmag, dra_mas=separation_mas * math.sin(pa), ddec_mas=separation_mas * math.cos(pa), **kw)


DISK_UNITS = ("mJy/arcsec^2", "W.m^-2.pixel^-1", "contrast/pixel")


@dataclass
class DiskModel:
    """A 2D scene (disk) image, already sampled at 21.8 mas/pix and centred on the star."""
    path: str = ""
    unit: str = "mJy/arcsec^2"
    contrast: float | None = None             # only for 'contrast/pixel'
    prf_cube_path: str = ""                   # PRF cube for corgisim's field-dependent convolution
    interpolate_prfs: bool = False


@dataclass
class SceneSpec:
    host: HostStar = field(default_factory=HostStar)
    point_sources: list[PointSource] = field(default_factory=list)
    disk: DiskModel | None = None
    ref_flag: bool = False                    # True for the reference (PSF) star
    spmethod: str = "bpgs"                    # 'bpgs' or 'blackbody'

    @property
    def n_point_sources(self) -> int:
        return len(self.point_sources)


# ----------------------------------------------------------------------------- instrument
@dataclass
class SatSpotSpec:
    num_pairs: int = 2
    sep_lamD: float = 6.25
    angle_deg: list[float] = field(default_factory=lambda: [0.0, 90.0])
    contrast: float = 1e-7

    @classmethod
    def from_pair_id(cls, pair_id: int) -> "SatSpotSpec":
        sep, angles, contrast = tables.SATSPOT_PAIR_IDS[pair_id]
        return cls(2, sep, list(angles), contrast)


@dataclass
class JitterSpec:
    preset: str = "quicktest"                 # 'mintest', 'quicktest', 'full'
    jitter_sigma_x_mas: float = 0.0
    jitter_sigma_y_mas: float = 0.0
    use_finite_stellar_diam: bool = True
    add_jitter: bool = True

    @property
    def n_offsets(self) -> int:
        return tables.JITTER_PRESETS.get(self.preset, 0)


@dataclass
class InstrumentSpec:
    cgi_mode: str = "excam"
    cor_type: str = "hlc_band1"
    bandpass: str = "1F"
    dpam: str = "None"                        # corgisim 'prism': None | POL0 | POL45 | PRISM2 | PRISM3
    nd: int = 0
    slit: str = "None"
    slit_ra_offset_mas: float = 0.0
    slit_dec_offset_mas: float = 0.0
    slit_x_offset_mas: float | None = None
    slit_y_offset_mas: float | None = None
    roll_angle_deg: float = 0.0              # default roll; visits override it
    polaxis: int = 10
    use_fpm: bool = True
    use_lyot_stop: bool = True
    use_field_stop: bool = True
    use_pupil_lens: bool = False
    use_errors: bool = True
    dm_solution: str | None = "hlc_ni_3e-8"  # rootname in roman_preflight_proper/examples, or None for no DMs
    fsm_x_offset_mas: float = 0.0
    fsm_y_offset_mas: float = 0.0
    source_x_offset_mas: float = 0.0
    source_y_offset_mas: float = 0.0
    output_dim: int = 201
    oversampling_factor: int = 7
    return_oversample: bool = False
    satspots: SatSpotSpec | None = None       # satellite spots on the DM1 (used by visits with a satspot block)
    jitter: JitterSpec | None = None
    extra_optics_keywords: dict[str, Any] = field(default_factory=dict)   # passed through to PROPER

    @property
    def coronagraph(self) -> tables.Coronagraph | None:
        return tables.CORONAGRAPHS.get(self.cor_type)

    @property
    def filter(self) -> tables.Filter | None:
        return tables.FILTERS.get(self.bandpass)

    @property
    def is_polarimetry(self) -> bool:
        return self.dpam in ("POL0", "POL45")

    @property
    def is_spectroscopy(self) -> bool:
        return self.cgi_mode == "spec"

    @property
    def has_prism(self) -> bool:
        return self.dpam in ("PRISM2", "PRISM3")

    @property
    def lam_over_d_mas(self) -> float:
        f = self.filter
        return f.lam_over_d_mas if f else 0.0

    def mechanisms(self) -> tables.Mechanisms:
        return tables.header_mechanisms(self.cor_type, self.bandpass, use_fpm=self.use_fpm,
                                        use_lyot_stop=self.use_lyot_stop, use_field_stop=self.use_field_stop,
                                        use_pupil_lens=self.use_pupil_lens, nd=self.nd, prism=self.dpam, slit=self.slit)


# ----------------------------------------------------------------------------- detector
@dataclass
class DetectorSpec:
    em_gain: float = 1000.0
    photon_counting: bool = False
    cr_rate: float = 5.0
    fast_gain_mode: str | bool = "auto"
    gain_CIC_Q: str | float = "roman"
    full_frame: bool = True
    loc_x: int = 512
    loc_y: int = 512
    extra_emccd_keywords: dict[str, Any] = field(default_factory=dict)   # any other CorgiDetector keyword

    def emccd_keywords(self) -> dict[str, Any]:
        kw = {"em_gain": float(self.em_gain), "cr_rate": self.cr_rate,
              "fast_gain_mode": self.fast_gain_mode, "gain_CIC_Q": self.gain_CIC_Q}
        kw.update(self.extra_emccd_keywords)
        return kw


# ----------------------------------------------------------------------------- visits
@dataclass
class SatSpotBlock:
    """Satellite-spot frames taken in a visit: n frames each of background, positive and negative."""
    n_frames: int = 1
    exptime_s: float = 10.0
    em_gain: float = 1000.0


@dataclass
class Visit:
    label: str = ""
    vistype: str = "CGIVST_TDD_OBS"
    roll_angle_deg: float = 0.0
    n_frames: int = 1
    exptime_s: float = 10.0
    em_gain: float | None = None               # None -> job detector default
    photon_counting: bool | None = None
    dpam: str | None = None                    # None -> instrument default (POL visits alternate POL0/POL45)
    is_reference: bool = False
    satspots: SatSpotBlock | None = None
    visit_num: str = ""                        # 3-digit visit number used in VISITID; '' -> position in list
    zernike_index: list[int] | None = None     # per-visit wavefront drift (PR 300 / OS11 time series)
    zernike_value_m: list[float] | None = None

    @property
    def total_frames(self) -> int:
        return self.n_frames + (3 * self.satspots.n_frames if self.satspots else 0)

    @property
    def total_exposure_s(self) -> float:
        t = self.n_frames * self.exptime_s
        if self.satspots:
            t += 3 * self.satspots.n_frames * self.satspots.exptime_s
        return t


# ----------------------------------------------------------------------------- output / run
@dataclass
class OutputSpec:
    output_dir: str = ""
    save_fits: bool = True
    write_as_l1: bool = True                   # full-frame L1 with corgidrp headers
    save_noiseless: bool = True                # also write the noiseless PSF/scene (counts/s)
    visit_subfolders: bool = True              # output_dir/V<visitid>/ like corgisim's CPGS driver
    overwrite: bool = False
    visit_id_root: str = "0200001001001001"    # 16 digits; + 3-digit visit number = 19-digit VISITID


@dataclass
class RunSpec:
    engine: str = "stepwise"                   # 'stepwise' (GUI loop, progress per PSF/frame) | 'corgisim' (observation.generate_observation_sequence)
    n_jobs: int = 1                            # detector frames simulated in parallel (spawned processes)
    seed: int | None = None
    preview_only: bool = False                 # stop after the noiseless PSF (no detector)
    workdir: str = ""                          # where roman_preflight.py is copied; '' -> output_dir


# ----------------------------------------------------------------------------- job
@dataclass
class Job:
    name: str = "untitled"
    kind: str = "image"                        # 'image' | 'sequence' (UI hint only)
    scene: SceneSpec = field(default_factory=SceneSpec)
    reference_scene: SceneSpec | None = None
    instrument: InstrumentSpec = field(default_factory=InstrumentSpec)
    detector: DetectorSpec = field(default_factory=DetectorSpec)
    visits: list[Visit] = field(default_factory=lambda: [Visit(label="single image")])
    output: OutputSpec = field(default_factory=OutputSpec)
    run: RunSpec = field(default_factory=RunSpec)
    source_cpgs: str = ""                      # the CPGS file this job was built from, if any
    notes: list[str] = field(default_factory=list)
    format_version: int = JOB_FORMAT_VERSION

    # -- derived
    @property
    def n_visits(self) -> int:
        return len(self.visits)

    @property
    def total_frames(self) -> int:
        return sum(v.total_frames for v in self.visits)

    @property
    def total_exposure_s(self) -> float:
        return sum(v.total_exposure_s for v in self.visits)

    @property
    def has_reference(self) -> bool:
        return self.reference_scene is not None and any(v.is_reference for v in self.visits)

    def visit_id(self, index: int) -> str:
        v = self.visits[index]
        num = v.visit_num or f"{index + 1:03d}"
        return f"{self.output.visit_id_root}{num[-3:].zfill(3)}"

    def visit_dpam(self, v: Visit) -> str:
        return v.dpam if v.dpam is not None else self.instrument.dpam

    def visit_gain(self, v: Visit) -> float:
        return v.em_gain if v.em_gain is not None else self.detector.em_gain

    def visit_photon_counting(self, v: Visit) -> bool:
        return v.photon_counting if v.photon_counting is not None else self.detector.photon_counting

    # -- JSON
    def to_dict(self) -> dict:
        return _to_dict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        job = _from_dict(cls, data)
        if not job.visits:
            job.visits = [Visit(label="single image")]
        return job

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "Job":
        return cls.from_dict(json.loads(text))

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            f.write(self.to_json())
            f.write("\n")

    @classmethod
    def load(cls, path: str) -> "Job":
        with open(path) as f:
            return cls.from_json(f.read())

    def copy(self) -> "Job":
        return Job.from_dict(self.to_dict())


# nested dataclass fields, for _from_dict
_NESTED = {
    ("SceneSpec", "host"): HostStar,
    ("SceneSpec", "point_sources"): PointSource,
    ("SceneSpec", "disk"): DiskModel,
    ("InstrumentSpec", "satspots"): SatSpotSpec,
    ("InstrumentSpec", "jitter"): JitterSpec,
    ("Visit", "satspots"): SatSpotBlock,
    ("Job", "scene"): SceneSpec,
    ("Job", "reference_scene"): SceneSpec,
    ("Job", "instrument"): InstrumentSpec,
    ("Job", "detector"): DetectorSpec,
    ("Job", "visits"): Visit,
    ("Job", "output"): OutputSpec,
    ("Job", "run"): RunSpec,
}


# ----------------------------------------------------------------------------- factories
def single_image_job(name: str = "single image", **visit_kw) -> Job:
    job = Job(name=name, kind="image")
    job.visits = [Visit(label="single image", **visit_kw)]
    return job


def roll_sequence_job(name: str = "roll sequence", rolls=(-13.0, 13.0), n_frames: int = 10,
                      exptime_s: float = 100.0, with_reference: bool = True) -> Job:
    """Template: reference, then target at each roll angle (the classic RDI/ADI pattern)."""
    job = Job(name=name, kind="sequence")
    visits = []
    if with_reference:
        job.reference_scene = SceneSpec(host=HostStar(vmag=3.0, spectral_type="A0V", name="REFERENCE"), ref_flag=True)
        visits.append(Visit(label="reference", roll_angle_deg=0.0, n_frames=n_frames, exptime_s=exptime_s, is_reference=True))
    for r in rolls:
        visits.append(Visit(label=f"target roll {r:+g}", roll_angle_deg=float(r), n_frames=n_frames, exptime_s=exptime_s))
    job.visits = visits
    return job


def polarimetry_pair_job(name: str = "polarimetry pair", n_frames: int = 10, exptime_s: float = 100.0) -> Job:
    job = Job(name=name, kind="sequence")
    job.instrument.dpam = "POL0"
    job.visits = [
        Visit(label="POL0", vistype="CGIVST_TDD_POL_OBS", n_frames=n_frames, exptime_s=exptime_s, dpam="POL0"),
        Visit(label="POL45", vistype="CGIVST_TDD_POL_OBS", n_frames=n_frames, exptime_s=exptime_s, dpam="POL45"),
    ]
    return job
