"""The static tables must agree with the installed corgisim / cgisim (catches drift after an upgrade)."""
import os
import re

import pytest

from corgisim_gui.core import model, tables
from conftest import needs_corgisim

pytestmark = needs_corgisim


def _cgisim_info_dir():
    import cgisim
    return os.path.join(cgisim.lib_dir, "cgisim_info_dir")


def _read_mode_file(cor_type):
    with open(os.path.join(_cgisim_info_dir(), cor_type + ".txt")) as f:
        lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    owa = float(lines[lines.index("owa (lam0/D)") + 1].split()[0])
    bps = lines[lines.index("bandpasses") + 1:]
    return owa, bps


def test_cor_types_match_corgisim_lists():
    import inspect
    from corgisim import instrument
    src = inspect.getsource(instrument.CorgiOptics.__init__)
    valid = re.search(r"valid_cor_types\s*=\s*\[(.*?)\]", src, re.S).group(1)
    untested = re.search(r"untest_cor_types\s*=\s*\[(.*?)\]", src, re.S).group(1)
    valid = set(re.findall(r"'([^']+)'", valid))
    untested = set(re.findall(r"'([^']+)'", untested))
    assert {n for n, c in tables.CORONAGRAPHS.items() if c.tested} == valid
    assert {n for n, c in tables.CORONAGRAPHS.items() if not c.tested} == untested


def test_allowed_bandpasses_match_cgisim_mode_files():
    for name, c in tables.CORONAGRAPHS.items():
        owa, bps = _read_mode_file(name)
        if c.allowed_cgisim == "*":
            assert bps == ["*"], name
        else:
            assert set(c.allowed_cgisim) == set(bps) - {"lowfs", "none"}, name
        if c.owa_cgisim_lamD:
            assert abs(c.owa_cgisim_lamD - owa) < 1e-6, name


def test_filters_match_cgisim_bandpasses():
    with open(os.path.join(_cgisim_info_dir(), "cgisim_bandpasses.txt")) as f:
        text = f.read()
    for name, flt in tables.FILTERS.items():
        m = re.search(rf"^{re.escape(flt.cgisim)}\s*=\s*bandpass name\s*\n\s*([\d.]+)\s*=.*\n\s*(\d+)\s*=.*\n\s*([\d.]+)\s+([\d.]+)", text, re.M)
        assert m, name
        lam0, nlam, lmin, lmax = float(m.group(1)), int(m.group(2)), float(m.group(3)), float(m.group(4))
        assert abs(flt.lam0_um - lam0) < 1e-6, name
        assert flt.nlam == nlam, name
        assert abs(flt.lam_min_um - lmin) < 1e-5 and abs(flt.lam_max_um - lmax) < 1e-5, name


@pytest.mark.parametrize("cor_type,bandpass,kw", [
    ("hlc_band1", "1F", {}),
    ("hlc_band1", "1F", {"prism": "POL0"}),
    ("hlc_band1", "1B", {"use_fpm": False, "nd": 2}),
    ("hlc_band2", "2F", {}),
    ("hlc_band3", "3A", {}),
    ("hlc_band4", "4F", {}),
    ("spc-wide_band4", "4F", {}),
    ("spc-wide_band4", "4F", {"prism": "POL45"}),
    ("spc-wide_band1", "1F", {}),
    ("spc-spec_band2", "2F", {"prism": "PRISM2", "slit": "R6C5"}),
    ("spc-spec_band3", "3F", {"prism": "PRISM3", "slit": "R1C2"}),
    ("spc-spec_band3_rotated", "3F", {"prism": "PRISM3", "slit": "R2C2"}),
    ("spc-spec_band2_rotated", "2F", {"prism": "None", "slit": "None"}),
    ("hlc_band1", "1F", {"use_lyot_stop": False, "use_field_stop": False}),
    ("hlc_band1", "1F", {"use_pupil_lens": True}),
])
def test_header_mechanisms_match_corgisim_outputs(cor_type, bandpass, kw):
    from corgisim import outputs
    inst = model.InstrumentSpec(cor_type=cor_type, bandpass=bandpass, cgi_mode=tables.CORONAGRAPHS[cor_type].cgi_mode)
    for k, v in kw.items():
        setattr(inst, "dpam" if k == "prism" else k, v)
    m = inst.mechanisms()
    nd_name = {0: "0", 1: "2.25", 2: "4.75fpam", 3: "4.75fsam"}[inst.nd]
    pol_basis = {"POL0": "0/90 degrees", "POL45": "45/135 degrees"}.get(inst.dpam, "None")
    assert outputs.write_headers_SPAM(cor_type)[2] == m.spam
    assert outputs.write_headers_LSAM(cor_type, int(inst.use_lyot_stop))[2] == m.lsam
    assert outputs.write_headers_FPAM(cor_type, bandpass, int(inst.use_fpm), nd_name)[2] == m.fpam
    assert outputs.write_headers_FSAM(cor_type, bandpass, inst.slit, pol_basis, int(inst.use_field_stop))[2] == m.fsam
    assert outputs.write_headers_DPAM(inst.cgi_mode, pol_basis, inst.dpam, int(inst.use_pupil_lens))[2] == m.dpam


def test_dm_solutions_exist():
    from corgisim_gui.engine import stepwise
    present = set(stepwise.available_dm_rootnames())
    assert set(tables.DM_SOLUTIONS) <= present, set(tables.DM_SOLUTIONS) - present
    for name, c in tables.CORONAGRAPHS.items():
        for r in c.dm_rootnames:
            assert r in present, (name, r)


def test_cpgs_dm_rule_matches_corgisim():
    for fam, cases in tables.CPGS_DM_CASES.items():
        for contrast in (1e-9, 7e-8, 1e-8, 2.5e-9):
            chosen = str(min(cases, key=lambda x: abs(x - contrast)))
            expect = f"{fam}_ni_{chosen[:-2] + chosen[-1]}"
            assert tables.dm_rootname_for_contrast(fam, contrast) == expect


def test_emccd_defaults_match_corgisim():
    from corgisim import instrument
    det = instrument.CorgiDetector({"em_gain": 10, "fast_gain_mode": True, "gain_CIC_Q": 0})
    assert set(det.emccd_keywords_default) == set(tables.EMCCD_DEFAULTS)
    for k, v in tables.EMCCD_DEFAULTS.items():
        if k in ("em_gain", "fast_gain_mode", "gain_CIC_Q"):
            continue
        assert det.emccd_keywords_default[k] == v, k


def test_slits_match_corgisim_data():
    import json
    import corgisim
    with open(os.path.join(corgisim.lib_dir, "data", "FSAM_slit_params.json")) as f:
        d = json.load(f)
    for name, s in tables.SLITS.items():
        assert abs(d[name]["width"] - s.width_um) < 1e-6
        assert abs(d[name]["height"] - s.height_um) < 1e-6
        assert abs(d[name].get("rotation", 0.0) - s.rotation_deg) < 1e-6
    assert set(d) - {"_comment"} == set(tables.SLITS)


def test_constants_match_corgisim():
    from corgisim import constants, instrument
    assert abs(constants.PIXEL_SCALE_ARCSEC * 1000 - tables.PIXEL_SCALE_MAS) < 1e-9
    import inspect
    sig = inspect.signature(instrument.CorgiOptics.__init__)
    assert abs(sig.parameters["diam"].default / 100.0 - tables.TELESCOPE_DIAM_M) < 1e-9


def test_jitter_presets_match_corgisim():
    from corgisim import jitter
    import numpy as np
    for preset, n in (("mintest", 1), ("quicktest", 35), ("full", 124)):
        kw = jitter.load_predefined_jitter_and_stellar_diam_params(quicktest=(preset == "quicktest"), mintest=(preset == "mintest"))
        assert int(np.sum(kw["N_offsets_per_ring"])) == tables.JITTER_PRESETS[preset] == n
