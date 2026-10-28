"""Read CPGS observation-specification XML files and turn them into a :class:`Job`.

Two layers:

* :func:`read_cpgs` parses the XML into a :class:`CpgsFile` with *everything*
  the GUI may want to show (targets with coordinates, every visit with its
  mechanism positions, gains, frame counts, durations), with no corgisim import.
* :func:`job_from_cpgs` builds a :class:`Job` the same way corgisim's
  ``inputs.load_cpgs_data`` and ``observation.generate_observation_scenario_from_cpgs``
  do (same visit filter, same DM-solution snapping, same satellite-spot
  configuration, gain from ``cpgs_input`` rather than per visit) and records in
  ``job.notes`` where the file says something corgisim ignores.

``tests/test_cpgs.py`` checks the translation against corgisim's own loader on
the sample files, so a change in corgisim's parser after an upgrade is caught.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from . import tables
from .model import (DetectorSpec, HostStar, InstrumentSpec, Job, OutputSpec, SatSpotBlock,
                    SatSpotSpec, SceneSpec, Visit)

MAS_PER_PIX = tables.PIXEL_SCALE_MAS

# the visit types corgisim simulates (inputs.load_cpgs_data)
SIMULATED_VISIT_TYPES = ("CGIVST_TDD_OBS", "CGIVST_TDD_POL_OBS", "CGIVST_TDD_OBS_HOWFSC", "CGIVST_TDD_SETUP_HOWFSC")


class CpgsError(ValueError):
    pass


# ----------------------------------------------------------------------------- data
@dataclass
class CpgsTarget:
    target_id: int
    name: str
    ra: str = ""
    dec: str = ""
    ra_deg: float | None = None
    dec_deg: float | None = None
    parallax_mas: float | None = None


@dataclass
class CpgsVisit:
    number: int
    visit_type: str
    position_angle: float
    target_id: int | None
    is_reference: bool
    auto_gain: bool
    gain: float | None
    frame_time: float | None
    photon_counting: bool | None
    number_of_frames: int | None
    exposure_duration_s: float | None       # the planning tool's own total (s, or h for auto-gain visits)
    satspots: bool
    satspot_pair_id: int | None
    satspot_gain: float | None
    satspot_frame_time: float | None
    satspot_n_frames: int | None
    mechanisms: dict[str, str] = field(default_factory=dict)   # spampos, fpampos, fsampos, lsampos, cfampos, dpampos, ...
    howfsc: bool = False
    observation_type: str = ""
    science_duration_s: float | None = None
    initial_overhead_s: float | None = None
    comments: list[str] = field(default_factory=list)

    @property
    def simulated(self) -> bool:
        return self.visit_type in SIMULATED_VISIT_TYPES


@dataclass
class CpgsFile:
    path: str
    label: str
    observer: str
    cpgs_version: str
    targets: list[CpgsTarget]
    visits: list[CpgsVisit]
    inputs: dict[str, str]                 # the flat <cpgs_input> block, as strings

    # -- convenience accessors over the <cpgs_input> block
    def get(self, key: str, default: str | None = None) -> str | None:
        return self.inputs.get(key, default)

    def getf(self, key: str, default: float | None = None) -> float | None:
        v = self.inputs.get(key)
        try:
            return float(v) if v is not None else default
        except ValueError:
            return default

    def geti(self, key: str, default: int | None = None) -> int | None:
        v = self.inputs.get(key)
        try:
            return int(float(v)) if v is not None else default
        except ValueError:
            return default

    @property
    def has_reference(self) -> bool:
        return "reference_name" in self.inputs

    @property
    def is_spectroscopy(self) -> bool:
        return self.get("is_spectroscopy") == "1"

    @property
    def bandpass(self) -> str:
        bp = self.get("howfsc_cfam_pos") or "NONE"
        if bp == "NONE":
            bp = (self.get("filter") or "1") + "F"
        return bp

    @property
    def cor_type(self) -> str:
        bp = self.bandpass
        if self.is_spectroscopy:
            ct = "spc-spec_band" + bp[0]
            if self.get("howfsc_spam_pos") == "SPECROT":
                ct += "_rotated"
            return ct
        mask = self.get("coronagraph_mask")
        if mask == "1":
            return "hlc_band" + bp[0]
        if mask == "2":
            return "spc-wide_band" + bp[0]
        raise CpgsError(f"coronagraph_mask={mask!r}: corgisim only handles 1 (HLC) and 2 (SPC wide)")

    @property
    def simulated_visits(self) -> list[CpgsVisit]:
        return [v for v in self.visits if v.simulated]


# ----------------------------------------------------------------------------- parsing
def _text(el, tag: str, default: str | None = None) -> str | None:
    if el is None:
        return default
    x = el.find(tag)
    return x.text.strip() if x is not None and x.text is not None else default


def _f(el, tag: str) -> float | None:
    t = _text(el, tag)
    try:
        return float(t) if t is not None else None
    except ValueError:
        return None


def _i(el, tag: str) -> int | None:
    t = _text(el, tag)
    try:
        return int(float(t)) if t is not None else None
    except ValueError:
        return None


def _yn(el, tag: str) -> bool | None:
    t = _text(el, tag)
    if t is None:
        return None
    return t.upper() in ("Y", "1", "TRUE")


def read_cpgs(path: str) -> CpgsFile:
    """Parse a CPGS XML file. Raises :class:`CpgsError` for non-CPGS input."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise CpgsError(f"{path} is not an XML file: {exc}") from exc
    root = tree.getroot()
    if root.tag != "obs_specification":
        raise CpgsError(f"{path}: root element is <{root.tag}>, not <obs_specification>")
    cpgs_input = root.find("cpgs_input")
    if cpgs_input is None:
        raise CpgsError(f"{path}: no <cpgs_input> block")

    version = ""
    for node in root.iter():
        if isinstance(node.tag, str):
            continue
    # the version is in a comment right under the root; ElementTree drops comments by default
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(2000)
        import re
        m = re.search(r"CPGS version ([\w.]+)", head)
        if m:
            version = m.group(1)
    except OSError:
        pass

    info = root.find("observation_information")
    label = _text(info, "label", "") or ""
    observer = " ".join(x for x in (_text(info, "observer_firstname"), _text(info, "observer_lastname")) if x)

    targets = []
    tl = root.find("target_list")
    if tl is not None:
        for t in tl.findall("target"):
            targets.append(CpgsTarget(_i(t, "target_id") or 0, _text(t, "target_name", "") or "",
                                      _text(t, "ra", "") or "", _text(t, "dec", "") or "",
                                      _f(t, "ra_computed"), _f(t, "dec_computed"), _f(t, "parallax")))

    inputs = {child.tag: (child.text or "").strip() for child in cpgs_input}

    visits = []
    vl = root.find("visit_list")
    if vl is not None:
        for v in vl.iter("cgi_visit"):
            excam = v.find("cgi_excam")
            fixed = v.find("fixed_target")
            mech = v.find("cgi_mechanisms")
            howfsc = v.find("cgi_howfsc")
            mechanisms = {c.tag: (c.text or "").strip() for c in mech} if mech is not None else {}
            visits.append(CpgsVisit(
                number=int(v.attrib.get("number", len(visits) + 1)),
                visit_type=_text(v, "cgi_visit_type", "") or "",
                position_angle=_f(v, "position_angle") or 0.0,
                target_id=_i(fixed, "target_id"),
                is_reference=bool(_yn(fixed, "reference_target")),
                auto_gain=bool(_yn(excam, "auto_gain")),
                gain=_f(excam, "gain"),
                frame_time=_f(excam, "frame_time"),
                photon_counting=_yn(excam, "photon_counting"),
                number_of_frames=_i(excam, "number_of_frames"),
                exposure_duration_s=_f(excam, "exposure_duration"),
                satspots=bool(_yn(excam, "observe_satellite_spots")),
                satspot_pair_id=_i(excam, "satellite_spots_pair_id"),
                satspot_gain=_f(excam, "satellite_spots_gain"),
                satspot_frame_time=_f(excam, "satellite_spots_frame_time"),
                satspot_n_frames=_i(excam, "satellite_spots_number_of_frames"),
                mechanisms=mechanisms,
                howfsc=bool(_yn(howfsc, "is_howfsc_visit")),
                observation_type=_text(v, "observation_type", "") or "",
                science_duration_s=_f(v, "science_duration"),
                initial_overhead_s=_f(v, "initial_overhead_duration"),
            ))
    return CpgsFile(path, label, observer, version, targets, visits, inputs)


# ----------------------------------------------------------------------------- job
def _sptype(spec: str | None, sub: str | None) -> str:
    """corgisim: spec_type + first character of sub_type, e.g. 'G' + '1.0' -> 'G1'."""
    return (spec or "G") + ((sub or "2")[:1])


def job_from_cpgs(cpgs: CpgsFile, *, output_dim: int = 201, polaxis: int = 0, fast_gain_mode="auto",
                  gain_CIC_Q="roman", output_dir: str = "") -> Job:
    """Build a Job the way corgisim's CPGS loader and scenario driver would run this file."""
    notes: list[str] = []
    job = Job(name=cpgs.label or os.path.basename(cpgs.path), kind="sequence", source_cpgs=cpgs.path)

    # -- scenes
    tname = cpgs.get("target_name", "UNKNOWN") or "UNKNOWN"
    job.scene = SceneSpec(host=HostStar(vmag=cpgs.getf("target_v_mag", 5.0), spectral_type=_sptype(cpgs.get("target_spec_type"), cpgs.get("target_sub_type")),
                                        name=tname), ref_flag=False)
    for t in cpgs.targets:
        if t.name == tname and t.ra_deg is not None:
            job.scene.host.ra_deg, job.scene.host.dec_deg = t.ra_deg, t.dec_deg or 0.0
    if cpgs.has_reference:
        rname = cpgs.get("reference_name", "REFERENCE") or "REFERENCE"
        job.reference_scene = SceneSpec(host=HostStar(vmag=cpgs.getf("reference_v_mag", 3.0),
                                                      spectral_type=_sptype(cpgs.get("reference_spec_type"), cpgs.get("reference_sub_type")),
                                                      name=rname), ref_flag=True)
        for t in cpgs.targets:
            if t.name == rname and t.ra_deg is not None:
                job.reference_scene.host.ra_deg, job.reference_scene.host.dec_deg = t.ra_deg, t.dec_deg or 0.0
    notes.append("RA/Dec are taken from the CPGS target list (corgisim's loader leaves them at 0)")

    # -- instrument
    bp = cpgs.bandpass
    cor_type = cpgs.cor_type
    c = tables.CORONAGRAPHS[cor_type]
    contrast = cpgs.getf("initial_target_planet_star_flux_ratio")
    if contrast is None:
        contrast = 0.0
        notes.append("no initial_target_planet_star_flux_ratio in the file; corgisim would fail, the GUI assumes 0")
    dm = tables.dm_rootname_for_contrast(c.family, contrast)
    inst = InstrumentSpec(cgi_mode=c.cgi_mode, cor_type=cor_type, bandpass=bp, polaxis=polaxis, output_dim=output_dim,
                          dm_solution=dm, use_errors=True)
    inst.extra_optics_keywords = {}
    if cpgs.is_spectroscopy:
        inst.slit = cpgs.get("fsam_pos_spec", "None") or "None"
        if inst.slit.upper() == "NONE":
            inst.slit = "None"
        inst.slit_x_offset_mas = (cpgs.getf("fsam_dx_pix_a", 0.0) or 0.0) * MAS_PER_PIX
        inst.slit_y_offset_mas = (cpgs.getf("fsam_dy_pix_a", 0.0) or 0.0) * MAS_PER_PIX
        if cpgs.getf("fsam_dx_pix_b") or cpgs.getf("fsam_dy_pix_b"):
            notes.append("slit orientation B offsets (fsam_dx/dy_pix_b) are ignored; corgisim uses orientation A only")
    if dm not in tables.DM_SOLUTIONS:
        notes.append(f"DM solution {dm} chosen for flux ratio {contrast:g} is not shipped with roman_preflight_proper 2.0.2")
    else:
        notes.append(f"DM solution {dm}: nearest case to the requested flux ratio {contrast:g} (corgisim's rule)")
    # corgisim's loader does not read use_errors; CorgiOptics defaults use_errors from the prescription (1)
    job.instrument = inst

    # -- detector (gain and photon counting come from cpgs_input, not from the visits)
    det = DetectorSpec(full_frame=True, fast_gain_mode=fast_gain_mode, gain_CIC_Q=gain_CIC_Q)
    if cpgs.get("target_autogain") == "1":
        det.em_gain, det.photon_counting = 1000.0, True
        notes.append("target_autogain=1: corgisim uses gain 1000 and photon counting (no eetc autogain yet, issue 80)")
    else:
        det.em_gain = cpgs.getf("target_gain", 1000.0)
        det.photon_counting = cpgs.get("target_pcounting") == "1"
    job.detector = det
    ref_gain, ref_pc = None, None
    if cpgs.has_reference:
        if cpgs.get("reference_autogain") == "1":
            ref_gain, ref_pc = 1000.0, True
            notes.append("reference_autogain=1: corgisim's loader assigns the reference detector to the target by mistake (inputs.py); the GUI gives the reference gain 1000 / photon counting")
        else:
            ref_gain = cpgs.getf("reference_gain", det.em_gain)
            ref_pc = cpgs.get("reference_pcounting") == "1"

    # -- satellite spots
    satspots_on = cpgs.get("obtain_satspot_image_every_visit") == "1"
    sat_target = sat_ref = None
    if satspots_on:
        pair_id = cpgs.geti("satellite_spots_pair_id", 0) or 0
        inst.satspots = SatSpotSpec.from_pair_id(pair_id)
        sat_target = SatSpotBlock(n_frames=cpgs.geti("satellite_spots_nframes_targ", 1),
                                  exptime_s=cpgs.getf("satellite_spots_exptime_targ", 1.0),
                                  em_gain=cpgs.getf("satellite_spots_gain_targ", 1000.0))
        if cpgs.has_reference:
            sat_ref = SatSpotBlock(n_frames=cpgs.geti("satellite_spots_nframes", 1),
                                   exptime_s=cpgs.getf("satellite_spots_exptime", 1.0),
                                   em_gain=cpgs.getf("satellite_spots_gain", 1000.0))
        notes.append(f"satellite spots pair_id {pair_id}: {inst.satspots.sep_lamD} λ/D at {inst.satspots.angle_deg} deg, contrast {inst.satspots.contrast:g}; "
                     "satellite-spot gain/exptime/frames come from cpgs_input, the per-visit values are ignored by corgisim")
    else:
        notes.append("obtain_satspot_image_every_visit=0: corgisim's own CPGS driver fails on such files (observation.py indexes a None satellite dict); the stepwise engine runs them")

    # -- visits
    visits: list[Visit] = []
    last_prism = "None"
    for cv in cpgs.visits:
        if not cv.simulated:
            notes.append(f"visit {cv.number} ({cv.visit_type}) is not simulated by corgisim and is skipped")
            continue
        if cv.visit_type == "CGIVST_TDD_POL_OBS":
            prism = cv.mechanisms.get("dpampos", "None") or "None"
        elif cpgs.is_spectroscopy:
            prism = cv.mechanisms.get("dpampos_spec", "None") or "None"
        else:
            prism = "None"
        if prism.upper() in ("IMAGING", "NONE", ""):
            prism = "None"
        last_prism = prism
        is_ref = cv.is_reference if cpgs.has_reference else False
        if cv.auto_gain:
            n_frames, exptime = 1, (cv.exposure_duration_s or 0.0) * 3600.0
            notes.append(f"visit {cv.number}: auto_gain=Y, corgisim takes one frame of exposure_duration x 3600 s")
        else:
            n_frames, exptime = cv.number_of_frames or 0, cv.frame_time or 0.0
        v = Visit(label=f"V{cv.number:03d} {cv.visit_type.replace('CGIVST_TDD_', '')}" + (" ref" if is_ref else ""),
                  vistype=cv.visit_type, roll_angle_deg=cv.position_angle, n_frames=n_frames, exptime_s=exptime,
                  dpam=prism, is_reference=is_ref, visit_num=f"{cv.number:03d}",
                  em_gain=ref_gain if is_ref else None, photon_counting=ref_pc if is_ref else None)
        if satspots_on:
            v.satspots = SatSpotBlock(**vars(sat_ref if is_ref and sat_ref else sat_target))
        if cv.gain is not None and not cv.auto_gain:
            used = (ref_gain if is_ref and ref_gain is not None else det.em_gain)
            if abs(cv.gain - used) > 1e-6:
                notes.append(f"visit {cv.number}: the visit's gain {cv.gain:g} is ignored by corgisim, which uses {used:g} from cpgs_input")
        visits.append(v)
    if not visits:
        notes.append("no simulated visits in this file")
    job.visits = visits
    if len({job.visit_dpam(v) for v in visits}) > 1:
        notes.append(f"visits alternate DPAM elements; corgisim's loader builds one optics with the last visit's ({last_prism}). "
                     "The stepwise engine builds one optics per element")
    # roll angle = position_angle: corgisim uses the absolute PA as roll_angle
    job.instrument.dpam = last_prism
    job.instrument.roll_angle_deg = visits[0].roll_angle_deg if visits else 0.0
    job.output = OutputSpec(output_dir=output_dir, save_fits=True, write_as_l1=True, visit_subfolders=True)
    job.notes = notes
    return job


def load_job_from_cpgs(path: str, **kw) -> Job:
    return job_from_cpgs(read_cpgs(path), **kw)


def summarize(cpgs: CpgsFile) -> dict:
    """Short facts for a file chooser preview."""
    try:
        cor = cpgs.cor_type
    except CpgsError as exc:
        cor = f"? ({exc})"
    sim = cpgs.simulated_visits
    return {
        "label": cpgs.label, "observer": cpgs.observer, "cpgs_version": cpgs.cpgs_version,
        "target": cpgs.get("target_name"), "reference": cpgs.get("reference_name"),
        "coronagraph": cor, "filter": cpgs.bandpass, "spectroscopy": cpgs.is_spectroscopy,
        "polarimetry": cpgs.get("with_polarization") == "1",
        "satellite_spots": cpgs.get("obtain_satspot_image_every_visit") == "1",
        "n_visits": len(cpgs.visits), "n_simulated_visits": len(sim),
        "n_frames": sum((v.number_of_frames or 0) for v in sim),
        "total_science_s": sum((v.science_duration_s or 0.0) for v in cpgs.visits),
    }
