"""Static instrument tables: coronagraph modes, filters, mechanisms, DM solutions.

Everything here is plain data so the GUI can draw and validate a setup without
importing corgisim (which is slow and needs PROPER, cgisim and the DM files).
The values mirror what corgisim and cgisim 4.1 hard-code:

* coronagraph names and the bandpasses each accepts: ``cgisim_info_dir/<cor_type>.txt``
  and ``corgisim.instrument.CorgiOptics.__init__``
* bandpass wavelength grids: ``cgisim_info_dir/cgisim_bandpasses.txt``
* CFAM filter centres and widths: Riggs et al. 2025 (JATIS 11(2) 021403), Table 5
* mechanism names written to L1 headers: ``corgisim.outputs.write_headers_*``
* field stop and slit sizes: Riggs et al. 2025 Table 3 / ``corgisim/data/FSAM_slit_params.json``
* DM solutions shipped with roman_preflight_proper 2.0.2 (``examples/*_dm?_v.fits``)

``tests/test_tables_vs_corgisim.py`` compares these tables with the installed
corgisim/cgisim so that an upgrade which changes them is caught.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ----------------------------------------------------------------------------- constants
ARCSEC_PER_RAD = 206265.0
PIXEL_SCALE_MAS = 21.8            # EXCAM plate scale (corgisim.constants.PIXEL_SCALE_ARCSEC)
TELESCOPE_DIAM_M = 2.363114       # CorgiOptics default ``diam`` in cm / 100
EXCAM_IMAGE_PIX = 1024            # science area of the EMCCD
L1_FRAME_SHAPE = (1200, 2200)     # full L1 frame incl. prescan/overscan
L1_IMAGE_SLICE = ((13, 1037), (1088, 2112))   # where the 1024x1024 image sits in the L1 frame
POL_BEAM_OFFSET_PIX = {"POL0": (172, 0), "POL45": (122, 122)}   # +/- offsets of the two beams
POL_MAX_SUBIMAGE_PIX = 512

CGI_MODES = ("excam", "spec")     # 'lowfs' and 'excam_efield' exist in corgisim but are not implemented

VISIT_TYPES = (
    "CGIVST_TDD_OBS",
    "CGIVST_TDD_POL_OBS",
    "CGIVST_TDD_OBS_HOWFSC",
    "CGIVST_TDD_SETUP_HOWFSC",
)


# ----------------------------------------------------------------------------- filters
@dataclass(frozen=True)
class Filter:
    name: str            # GUI / header name, e.g. '1F', '3B'
    band: int
    cgisim: str          # cgisim bandpass name, e.g. '1', '3b'
    center_nm: float     # Riggs 2025 Table 5
    fwhm_nm: float
    lam0_um: float       # cgisim reference wavelength
    nlam: int            # cgisim number of wavelengths (PROPER runs per propagation)
    lam_min_um: float
    lam_max_um: float
    kind: str = "full"   # 'full' or 'engineering'

    @property
    def lam_over_d_mas(self) -> float:
        return (self.lam0_um * 1e-6) / TELESCOPE_DIAM_M * ARCSEC_PER_RAD * 1e3

    @property
    def lam_over_d_pix(self) -> float:
        return self.lam_over_d_mas / PIXEL_SCALE_MAS


FILTERS: dict[str, Filter] = {f.name: f for f in [
    Filter("1F", 1, "1",  575.0,  58.0, 0.575, 7,  0.54625, 0.60375),
    Filter("1A", 1, "1a", 555.8,  19.2, 0.575, 5,  0.54627, 0.56573, "engineering"),
    Filter("1B", 1, "1b", 575.0,  19.2, 0.575, 5,  0.565512, 0.584487, "engineering"),
    Filter("1C", 1, "1c", 594.2,  19.2, 0.575, 5,  0.584496, 0.603504, "engineering"),
    Filter("2F", 2, "2",  660.0, 112.0, 0.660, 11, 0.604, 0.716),
    Filter("2A", 2, "2a", 615.0,  22.0, 0.660, 5,  0.604, 0.626, "engineering"),
    Filter("2B", 2, "2b", 638.0,  18.0, 0.660, 5,  0.629, 0.647, "engineering"),
    Filter("2C", 2, "2c", 656.3,   6.6, 0.660, 5,  0.653, 0.659, "engineering"),
    Filter("3F", 3, "3",  730.0, 122.0, 0.730, 11, 0.669, 0.791),
    Filter("3A", 3, "3a", 681.0,  24.0, 0.730, 5,  0.669, 0.693, "engineering"),
    Filter("3B", 3, "3b", 704.0,  24.0, 0.730, 5,  0.692, 0.716, "engineering"),
    Filter("3C", 3, "3c", 727.0,  20.0, 0.730, 5,  0.717, 0.737, "engineering"),
    Filter("3D", 3, "3d", 754.0,   7.5, 0.730, 5,  0.750, 0.758, "engineering"),
    Filter("3E", 3, "3e", 777.5,  27.0, 0.730, 5,  0.764, 0.791, "engineering"),
    Filter("3G", 3, "3g", 752.0,  25.0, 0.730, 5,  0.740, 0.765, "engineering"),
    Filter("4F", 4, "4",  825.0,  94.0, 0.825, 7,  0.778, 0.872),
    Filter("4A", 4, "4a", 792.0,  28.0, 0.825, 5,  0.778, 0.806, "engineering"),
    Filter("4B", 4, "4b", 825.0,  30.0, 0.825, 5,  0.810, 0.840, "engineering"),
    Filter("4C", 4, "4c", 857.0,  30.0, 0.825, 5,  0.842, 0.872, "engineering"),
]}

FILTER_NAMES = tuple(FILTERS)


def filter_from_cgisim(name: str) -> Filter | None:
    for f in FILTERS.values():
        if f.cgisim == name.lower():
            return f
    return None


# ----------------------------------------------------------------------------- coronagraphs
@dataclass(frozen=True)
class Coronagraph:
    name: str                    # corgisim cor_type
    family: str                  # 'hlc' | 'spc-wide' | 'spc-spec' | 'spc-mswc' | 'zwfs'
    cgi_mode: str                # 'excam' | 'spec'
    label: str                   # human name (Riggs 2025 Table 1 configuration name)
    bands: tuple[int, ...]       # bands this design is intended for
    allowed_cgisim: tuple[str, ...] | str    # cgisim bandpass names, or '*' for any
    iwa_lamD: float              # corgisim's dark-hole check range (instrument.inject_point_sources)
    owa_lamD: float
    owa_cgisim_lamD: float       # OWA from the cgisim mode file
    azimuth_deg: float = 360.0   # azimuthal coverage (spectroscopy SPCs: 2 x 65 deg)
    rotated: bool = False
    tested: bool = True          # corgisim's valid_cor_types (False: untest_cor_types -> warning)
    support: str = "best effort" # Riggs 2025 class: required / best effort / unsupported
    dm_rootnames: tuple[str, ...] = ()

    @property
    def spam(self) -> str:
        if self.family == "hlc":
            return "OPEN"
        if self.family in ("spc-wide", "spc-mswc"):
            return "WFOV"
        return "SPECROT" if self.rotated else "SPEC"

    @property
    def lsam(self) -> str:
        if self.family == "hlc":
            return "NFOV"
        if self.family in ("spc-wide", "spc-mswc"):
            return "WFOV"
        return "SPECROT" if self.rotated else "SPEC"

    def allows_filter(self, name: str) -> bool:
        f = FILTERS.get(name)
        if f is None:
            return False
        if self.allowed_cgisim == "*":
            return True
        return f.cgisim in self.allowed_cgisim


_HLC_B1 = ("1", "1a", "1b", "1c", "1_all")
_HLC_B2 = ("2", "2a", "2b", "2c", "3a", "3b")
_HLC_B3 = ("3", "3a", "3b", "3c", "3d", "3e", "3g")
_HLC_B4 = ("4", "4a", "4b", "4c")
_SPEC_B3 = ("3", "3_spec", "3a", "3b", "3c", "3d", "3e", "3g")
_SPEC_B2 = ("2", "2_spec", "2a", "2b", "2c", "3a", "3b")

_HLC_DMS = ("hlc_ni_3e-8", "hlc_ni_5e-9", "hlc_ni_2e-9", "hlc_flat_wfe")
_WIDE_DMS = ("spc-wide_ni_2e-8", "spc-wide_ni_5e-9", "spc-wide_ni_3e-9", "spc-wide_flat_wfe")
_WIDE_B1_DMS = ("spc-wide_band1_ni_2e-8", "spc-wide_band1_ni_8e-9", "spc-wide_band1_ni_5e-9", "spc-wide_band1_flat_wfe")
_SPEC_DMS = ("spc-spec_ni_2e-8", "spc-spec_ni_4e-9", "spc-spec_ni_1e-9", "spc-spec_flat_wfe")

CORONAGRAPHS: dict[str, Coronagraph] = {c.name: c for c in [
    Coronagraph("hlc",       "hlc", "excam", "HLC narrow FOV (band 1)", (1,), _HLC_B1, 3.0, 9.7, 9.7, support="required", dm_rootnames=_HLC_DMS),
    Coronagraph("hlc_band1", "hlc", "excam", "HLC narrow FOV, band 1", (1,), _HLC_B1, 3.0, 9.7, 9.7, support="required", dm_rootnames=_HLC_DMS),
    Coronagraph("hlc_band2", "hlc", "excam", "HLC narrow FOV, band 2", (2,), _HLC_B2, 3.0, 9.7, 9.7, support="unsupported", dm_rootnames=_HLC_DMS),
    Coronagraph("hlc_band3", "hlc", "excam", "HLC narrow FOV, band 3", (3,), _HLC_B3, 3.0, 9.7, 9.7, support="unsupported", dm_rootnames=_HLC_DMS),
    Coronagraph("hlc_band4", "hlc", "excam", "HLC narrow FOV, band 4", (4,), _HLC_B4, 3.0, 9.7, 9.7, support="unsupported", dm_rootnames=_HLC_DMS),
    Coronagraph("spc-wide",       "spc-wide", "excam", "SPC wide FOV (band 4)", (4,), "*", 5.9, 20.1, 20.4, dm_rootnames=_WIDE_DMS),
    Coronagraph("spc-wide_band4", "spc-wide", "excam", "SPC wide FOV, band 4", (4,), "*", 5.9, 20.1, 20.4, dm_rootnames=()),
    Coronagraph("spc-wide_band1", "spc-wide", "excam", "SPC wide FOV, band 1", (1,), "*", 5.9, 20.1, 20.4, dm_rootnames=_WIDE_B1_DMS),
    Coronagraph("spc-spec",       "spc-spec", "spec", "SPC spectroscopy (band 3)", (3,), _SPEC_B3, 3.0, 9.1, 9.4, 130.0, dm_rootnames=_SPEC_DMS),
    Coronagraph("spc-spec_band2", "spc-spec", "spec", "SPC spectroscopy, band 2", (2,), _SPEC_B2, 3.0, 9.1, 9.4, 130.0, dm_rootnames=_SPEC_DMS),
    Coronagraph("spc-spec_band3", "spc-spec", "spec", "SPC spectroscopy, band 3", (3,), _SPEC_B3, 3.0, 9.1, 9.4, 130.0, dm_rootnames=_SPEC_DMS),
    Coronagraph("spc-spec_rotated",       "spc-spec", "spec", "SPC rotated spectroscopy (band 3)", (3,), _SPEC_B3, 3.0, 9.1, 9.4, 130.0, rotated=True, support="unsupported", dm_rootnames=()),
    Coronagraph("spc-spec_band2_rotated", "spc-spec", "spec", "SPC rotated spectroscopy, band 2", (2,), _SPEC_B2, 3.0, 9.1, 9.4, 130.0, rotated=True, support="unsupported", dm_rootnames=()),
    Coronagraph("spc-spec_band3_rotated", "spc-spec", "spec", "SPC rotated spectroscopy, band 3", (3,), _SPEC_B3, 3.0, 9.1, 9.4, 130.0, rotated=True, support="unsupported", dm_rootnames=()),
    Coronagraph("spc-mswc",       "spc-mswc", "excam", "SPC multi-star (band 4)", (4,), "*", 5.9, 20.1, 20.4, tested=False, support="unsupported"),
    Coronagraph("spc-mswc_band4", "spc-mswc", "excam", "SPC multi-star, band 4", (4,), "*", 5.9, 20.1, 20.4, tested=False, support="unsupported"),
    Coronagraph("spc-mswc_band1", "spc-mswc", "excam", "SPC multi-star, band 1", (1,), "*", 5.9, 20.1, 20.4, tested=False, support="unsupported"),
    Coronagraph("zwfs",           "zwfs",     "excam", "Zernike WFS (calibration)", (1,), _HLC_B1, 0.0, 0.0, 0.0, tested=False, support="unsupported"),
]}

# the ones a user should normally pick from, in menu order
PRIMARY_CORONAGRAPHS = (
    "hlc_band1", "hlc_band2", "hlc_band3", "hlc_band4",
    "spc-wide_band1", "spc-wide_band4",
    "spc-spec_band2", "spc-spec_band3",
    "spc-spec_band2_rotated", "spc-spec_band3_rotated",
)

CORONAGRAPH_NAMES = tuple(CORONAGRAPHS)


def allowed_filters(cor_type: str) -> list[str]:
    c = CORONAGRAPHS.get(cor_type)
    if c is None:
        return []
    return [n for n in FILTER_NAMES if c.allows_filter(n)]


def dark_hole_lamD(cor_type: str) -> tuple[float, float]:
    """corgisim's (inner, outer) dark-hole range used in its point-source warning."""
    c = CORONAGRAPHS.get(cor_type)
    if c is None:
        return (0.0, 0.0)
    return (c.iwa_lamD, c.owa_lamD)


# ----------------------------------------------------------------------------- DPAM / ND / slits
DPAM_EXCAM = ("None", "POL0", "POL45")
DPAM_SPEC = ("None", "PRISM2", "PRISM3")
DPAM_LABELS = {
    "None": "imaging lens", "POL0": "Wollaston 0/90", "POL45": "Wollaston 45/135",
    "PRISM2": "Amici prism, band 2 (R~50 at 660 nm)", "PRISM3": "Amici prism, band 3 (R~50 at 730 nm)",
    "PUPIL": "pupil imaging lens",
}

ND_FILTERS = {
    0: ("none", "no neutral density filter"),
    1: ("ND225", "OD 2.25 at FPAM (replaces the focal plane mask)"),
    2: ("ND475", "OD 4.75 at FPAM (replaces the focal plane mask)"),
    3: ("ND475", "OD 4.75 at FSAM (replaces the Lyot stop in corgisim)"),
}

POLAXIS_CHOICES = {
    10: "mean of all polarization channels (default)",
    -10: "corgisim full aberration model (4 propagations)",
    0: "unpolarized, as used by the CPGS loader",
    -2: "single channel -2 (throughput halved)",
    -1: "single channel -1 (throughput halved)",
    1: "single channel +1 (throughput halved)",
    2: "single channel +2 (throughput halved)",
    5: "X channel mean (throughput halved)",
    6: "Y channel mean (throughput halved)",
}


@dataclass(frozen=True)
class Slit:
    name: str
    label: str
    width_um: float
    height_um: float
    rotation_deg: float = 0.0
    band: int = 0

    @property
    def width_mas(self) -> float:
        return self.width_um * _UM_TO_MAS

    @property
    def height_mas(self) -> float:
        return self.height_um * _UM_TO_MAS


# 7000 um = 14700 mas at FSAM (Riggs 2025 Table 3): 2.1 mas per micron
_UM_TO_MAS = 14700.0 / 7000.0

SLITS: dict[str, Slit] = {s.name: s for s in [
    Slit("R6C5", "SPC major-FWHM vertical slit, band 2 (tall)", 55.0, 329.7, 0.0, 2),
    Slit("R3C1", "SPC first-null vertical slit (tall)", 115.7, 347.2, 0.0, 0),
    Slit("R4C3", "SPC minor-FWHM rotated slit, band 2 (tall)", 27.5, 467.0, 60.0, 2),
    Slit("R1C2", "SPC major-FWHM vertical slit, band 3 (tall)", 60.8, 364.8, 0.0, 3),
    Slit("R2C2", "SPC minor-FWHM rotated slit, band 3 (tall)", 30.4, 516.6, 60.0, 3),
]}

SLITS_BY_BAND = {2: ("None", "R6C5", "R3C1", "R4C3"), 3: ("None", "R1C2", "R3C1", "R2C2")}

# nominal circular field stops (Riggs 2025 Table 3), radius in mas
FIELD_STOP_RADIUS_MAS = {
    "R1C1": 974 / 2, "R1C3": 974 / 2, "R6C6": 974 / 2,       # HLC band 1
    "R3C3": 1118 / 2, "R3C4": 1236 / 2, "R3C5": 1397 / 2,    # HLC bands 2-4
    "R1C5": 7000 / 2, "R6C1": 3800 / 2,                      # polarimetry stops
    "OPEN": 14700 / 2,
}


# ----------------------------------------------------------------------------- DM solutions
@dataclass(frozen=True)
class DMSolution:
    rootname: str
    family: str
    contrast: float | None     # None for flat-wavefront solutions
    band: int | None = None

    @property
    def label(self) -> str:
        if self.contrast is None:
            return f"{self.rootname} (flat wavefront)"
        return f"{self.rootname} (NI {self.contrast:.0e})"

    def filenames(self) -> tuple[str, str]:
        return (f"{self.rootname}_dm1_v.fits", f"{self.rootname}_dm2_v.fits")


DM_SOLUTIONS: dict[str, DMSolution] = {d.rootname: d for d in [
    DMSolution("hlc_ni_2e-9", "hlc", 2e-9, 1), DMSolution("hlc_ni_3e-8", "hlc", 3e-8, 1),
    DMSolution("hlc_ni_5e-9", "hlc", 5e-9, 1), DMSolution("hlc_flat_wfe", "hlc", None, 1),
    DMSolution("spc-spec_ni_1e-9", "spc-spec", 1e-9), DMSolution("spc-spec_ni_2e-8", "spc-spec", 2e-8),
    DMSolution("spc-spec_ni_4e-9", "spc-spec", 4e-9), DMSolution("spc-spec_flat_wfe", "spc-spec", None),
    DMSolution("spc-wide_ni_2e-8", "spc-wide", 2e-8, 4), DMSolution("spc-wide_ni_3e-9", "spc-wide", 3e-9, 4),
    DMSolution("spc-wide_ni_5e-9", "spc-wide", 5e-9, 4), DMSolution("spc-wide_flat_wfe", "spc-wide", None, 4),
    DMSolution("spc-wide_band1_ni_2e-8", "spc-wide", 2e-8, 1), DMSolution("spc-wide_band1_ni_5e-9", "spc-wide", 5e-9, 1),
    DMSolution("spc-wide_band1_ni_8e-9", "spc-wide", 8e-9, 1), DMSolution("spc-wide_band1_flat_wfe", "spc-wide", None, 1),
]}

# the contrast cases corgisim's CPGS loader snaps 'initial_target_planet_star_flux_ratio' to
CPGS_DM_CASES = {
    "hlc": [2e-9, 3e-8, 5e-9],
    "spc-wide": [3e-9, 5e-9],
    "spc-spec": [1e-9, 2e-8, 4e-9],
}


def dm_rootname_for_contrast(family: str, contrast: float) -> str:
    """Replicates ``inputs.load_cpgs_data``'s choice of DM solution."""
    cases = CPGS_DM_CASES[family]
    chosen = min(cases, key=lambda x: abs(x - contrast))
    s = str(chosen)                     # e.g. '3e-08'
    return f"{family}_ni_{s[:-2] + s[-1]}"   # '3e-8'


def dm_solutions_for(cor_type: str) -> list[DMSolution]:
    c = CORONAGRAPHS.get(cor_type)
    if c is None:
        return []
    return [DM_SOLUTIONS[r] for r in c.dm_rootnames]


# ----------------------------------------------------------------------------- satellite spots
# CPGS 'satellite_spots_pair_id' -> (sep_lamD, angles, contrast); observation.py
SATSPOT_PAIR_IDS = {
    0: (6.25, [0, 90], 1e-7), 1: (13.0, [0, 90], 1e-7), 2: (6.25, [45, 135], 1e-7), 3: (13.0, [45, 135], 1e-7),
    4: (6.25, [0, 90], 1e-5), 5: (13.0, [0, 90], 1e-5), 6: (6.25, [45, 135], 1e-5), 7: (13.0, [45, 135], 1e-5),
}

# ----------------------------------------------------------------------------- jitter presets
# number of PSF offsets each preset propagates (corgisim.jitter.load_predefined_jitter_and_stellar_diam_params)
JITTER_PRESETS = {
    "none": 0,
    "mintest": 1,
    "quicktest": 3 + 5 + 7 + 9 + 11,            # 35
    "full": 6 + 8 + 12 + 14 + 12 + 10 + 14 + 10 + 14 + 10 + 14,   # 124
}


# ----------------------------------------------------------------------------- header mechanisms
@dataclass
class Mechanisms:
    """The element in each mechanism for a setup, as corgisim writes it to the L1 header."""
    spam: str
    fpam: str
    lsam: str
    fsam: str
    cfam: str
    dpam: str
    fsmprfl: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, str]:
        return {"SPAM": self.spam, "FPAM": self.fpam, "LSAM": self.lsam, "FSAM": self.fsam,
                "CFAM": self.cfam, "DPAM": self.dpam, "FSMPRFL": self.fsmprfl}


def header_mechanisms(cor_type: str, bandpass: str, *, use_fpm: bool = True, use_lyot_stop: bool = True,
                      use_field_stop: bool = True, use_pupil_lens: bool = False, nd: int = 0,
                      prism: str = "None", slit: str = "None") -> Mechanisms:
    """Replicates ``corgisim.outputs.write_headers_{SPAM,LSAM,FPAM,FSAM,DPAM}`` and the FSMPRFL rule."""
    c = CORONAGRAPHS.get(cor_type)
    band = bandpass[0] if bandpass else ""
    notes: list[str] = []
    fam = c.family if c else ""
    rotated = c.rotated if c else False
    mode = c.cgi_mode if c else "excam"

    # SPAM
    if fam == "hlc":
        spam = "OPEN"
    elif fam in ("spc-wide", "spc-mswc"):
        spam = "WFOV"
    elif fam == "spc-spec":
        spam = "SPECROT" if rotated else "SPEC"
    else:
        spam = "?"
        notes.append(f"corgisim has no SPAM position for {cor_type}")

    # LSAM
    if not use_lyot_stop:
        lsam = "OPEN"
    elif fam == "hlc":
        lsam = "NFOV"
    elif fam in ("spc-wide", "spc-mswc"):
        lsam = "WFOV"
    elif fam == "spc-spec":
        lsam = "SPECROT" if rotated else "SPEC"
    else:
        lsam = "?"

    # FPAM
    nd_name = {0: "0", 1: "2.25", 2: "4.75fpam", 3: "4.75fsam"}.get(nd, "0")
    if not use_fpm:
        if nd_name == "0":
            fpam = "OPEN_12" if band in ("1", "2") else "OPEN_34"
        elif nd_name == "2.25":
            fpam = "ND225"
        elif nd_name == "4.75fpam":
            fpam = "ND475"
        else:
            fpam = "OPEN_12" if band in ("1", "2") else "OPEN_34"
            notes.append("ND 4.75 at FSAM: corgisim leaves FPAM at the open position")
    else:
        table = {
            "hlc": {"1": "HLC12_C2R5", "2": "HLC34_R7C1", "3": "HLC34_R5C1", "4": "HLC34_R3C1"},
            "spc-wide": {"1": "SPC12_R2C1", "4": "SPC34_R5C1"},
            "spc-mswc": {"1": "SPC12_R2C1", "4": "SPC34_R5C1"},
            "spc-spec": ({"2": "SPC12_R3C1", "3": "SPC34_R2C3"} if rotated else {"2": "SPC12_R3C2", "3": "SPC34_R2C2"}),
        }.get(fam, {})
        fpam = table.get(band, "?")
        if fpam == "?":
            notes.append(f"corgisim has no FPAM position for {cor_type} in band {band}")

    # FSAM
    pol = prism in ("POL0", "POL45")
    if not use_field_stop:
        fsam = "OPEN"
    elif fam == "hlc":
        if band == "1":
            fsam = "R1C5" if pol else "R1C1"
        else:
            fsam = {"2": "R3C3", "3": "R3C4", "4": "R3C5"}.get(band, "?")
    elif fam in ("spc-wide", "spc-mswc"):
        fsam = "R1C5" if pol else "OPEN"
    elif fam == "spc-spec" and rotated:
        # corgisim writes the rotated slit of the band whatever 'slit' says (outputs.write_headers_FSAM)
        fsam = {"2": "R4C3", "3": "R2C2"}.get(band, "?")
        if slit and slit != "None" and slit != fsam:
            notes.append(f"corgisim records FSAM {fsam} for the rotated SPC in band {band}, not the selected slit {slit}")
    elif fam == "spc-spec":
        fsam = slit if slit and slit != "None" else "OPEN"
    else:
        fsam = "?"

    # CFAM
    cfam = bandpass if bandpass in FILTERS else "?"

    # DPAM
    if use_pupil_lens:
        dpam = "PUPIL"
    elif mode == "excam":
        dpam = {"None": "IMAGING", "POL0": "POL0", "POL45": "POL45"}.get(prism, "IMAGING")
    else:
        dpam = {"None": "IMAGING", "PRISM2": "PRISM2", "PRISM3": "PRISM3"}.get(prism, "IMAGING")

    # FSMPRFL (outputs.create_hdu_list)
    if fam == "hlc":
        fsmprfl = "NFOV"
    elif fam in ("spc-wide", "spc-mswc"):
        fsmprfl = "WFOV"
    elif cor_type == "spc-spec_band2":
        fsmprfl = "SPEC660"
    elif cor_type == "spc-spec_band3":
        fsmprfl = "SPEC730"
    else:
        fsmprfl = "FSM_PROFILE_UNKNOWN"

    return Mechanisms(spam, fpam, lsam, fsam, cfam, dpam, fsmprfl, notes)


# ----------------------------------------------------------------------------- EMCCD defaults
# CorgiDetector.emccd_keywords_default (corgisim.instrument), for display and diffing
EMCCD_DEFAULTS = {
    "full_well_serial": 105000.0, "full_well_image": 90000.0, "dark_rate": 0.001, "cic_noise": 0.0088,
    "read_noise": 165.0, "cr_rate": 5, "em_gain": 1000.0, "bias": 1500, "pixel_pitch": 13e-6,
    "apply_smear": True, "e_per_dn": 8.7, "nbits": 14, "numel_gain_register": 604, "use_traps": False,
    "date4traps": 2028.0, "row_read_time": 223.5e-6, "nonlin_path": None, "flat_path": None,
    "fast_gain_mode": "auto", "gain_CIC_Q": "roman",
}

EMCCD_DOC = {
    "full_well_serial": "serial register full well (e-)", "full_well_image": "image area full well (e-)",
    "dark_rate": "dark current (e-/pix/s)", "cic_noise": "clock-induced charge (e-/pix/frame)",
    "read_noise": "read noise (e-/pix/frame)", "cr_rate": "cosmic ray rate (hits/cm^2/s; 0 = none)",
    "em_gain": "EM gain", "bias": "bias offset (e-)", "pixel_pitch": "pixel pitch (m)",
    "apply_smear": "apply fast-readout smear", "e_per_dn": "electrons per DN after gain",
    "nbits": "ADC bits", "numel_gain_register": "gain register elements", "use_traps": "include CTI traps (not implemented)",
    "date4traps": "decimal year for trap model", "row_read_time": "row read time (s); 0 disables smear",
    "nonlin_path": "non-linearity table (FITS/txt) or none", "flat_path": "flat field map or none",
    "fast_gain_mode": "'auto', true or false: skip the slow EM-register model",
    "gain_CIC_Q": "'roman' or 0: CIC in the gain register (0 is much faster)",
}
