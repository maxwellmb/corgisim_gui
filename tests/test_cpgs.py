import os

import pytest

from corgisim_gui.core import cpgs, model, tables, validate
from conftest import needs_corgisim


def test_read_all_samples(cpgs_files):
    for f in cpgs_files:
        c = cpgs.read_cpgs(f)
        assert c.visits and c.inputs and c.targets
        s = cpgs.summarize(c)
        assert s["n_simulated_visits"] >= 1
        assert c.bandpass in tables.FILTERS
        assert c.cor_type in tables.CORONAGRAPHS


def test_not_cpgs(tmp_path):
    p = tmp_path / "x.xml"
    p.write_text("<root/>")
    with pytest.raises(cpgs.CpgsError):
        cpgs.read_cpgs(str(p))
    p.write_text("not xml")
    with pytest.raises(cpgs.CpgsError):
        cpgs.read_cpgs(str(p))
    with pytest.raises(FileNotFoundError):
        cpgs.read_cpgs(str(tmp_path / "missing.xml"))


def test_job_from_pol_satspots_file(cpgs_files):
    f = [x for x in cpgs_files if x.endswith("cpgs_ref_pol_satspots.xml")][0]
    c = cpgs.read_cpgs(f)
    job = cpgs.job_from_cpgs(c, output_dir="/tmp/cpgs_test")
    assert job.instrument.cor_type == "hlc_band1" and job.instrument.bandpass == "1F"
    assert job.instrument.dm_solution == "hlc_ni_3e-8"          # 7e-8 -> nearest of [2e-9, 3e-8, 5e-9]
    assert job.has_reference and job.reference_scene.host.name == "Zeta Pup"
    assert job.scene.host.spectral_type == "A6" and job.reference_scene.host.spectral_type == "O4"
    assert abs(job.scene.host.ra_deg - 86.82116667) < 1e-6
    assert [v.vistype for v in job.visits][0] == "CGIVST_TDD_SETUP_HOWFSC"
    assert [job.visit_dpam(v) for v in job.visits] == ["None", "POL0", "POL45", "POL0", "POL45", "POL0", "POL45"]
    assert [v.is_reference for v in job.visits] == [True, False, False, True, False, False, True]
    assert job.visits[1].n_frames == 14 and job.visits[1].exptime_s == 12.0
    assert job.visits[1].roll_angle_deg == 87.83
    assert job.detector.em_gain == 3500.0 and job.detector.photon_counting is True
    assert job.visit_gain(job.visits[0]) == 300.0 and job.visit_photon_counting(job.visits[0]) is False
    assert job.instrument.satspots.sep_lamD == 6.25 and job.instrument.satspots.contrast == 1e-7
    assert job.visits[1].satspots.n_frames == 4 and job.visits[1].satspots.em_gain == 500.0
    assert job.visits[0].satspots.n_frames == 1 and job.visits[0].satspots.em_gain == 200.0
    assert job.visit_id(1).endswith("002")
    assert not validate.has_errors(validate.validate_job(job))
    assert any("alternate DPAM" in n for n in job.notes)
    # round trip through JSON keeps everything
    back = model.Job.from_json(job.to_json())
    assert back.to_dict() == job.to_dict()


def test_job_from_wfov_and_short(cpgs_files):
    wf = cpgs.load_job_from_cpgs([x for x in cpgs_files if x.endswith("cpgs_ref_wfov_satspots.xml")][0], output_dir="/tmp/x")
    assert wf.instrument.cor_type == "spc-wide_band4" and wf.instrument.bandpass == "4F"
    assert wf.instrument.dm_solution == "spc-wide_ni_5e-9"
    short = cpgs.load_job_from_cpgs([x for x in cpgs_files if x.endswith("cpgs_short_sequence.xml")][0], output_dir="/tmp/x")
    assert short.instrument.cor_type == "hlc_band4" and short.n_visits == 2 and not short.has_reference
    assert short.visits[0].n_frames == 6 and short.visits[0].exptime_s == 100.0
    nopol = cpgs.load_job_from_cpgs([x for x in cpgs_files if x.endswith("cpgs_without_polarization.xml")][0], output_dir="/tmp/x")
    assert nopol.instrument.satspots is None and all(v.satspots is None for v in nopol.visits)
    auto = cpgs.load_job_from_cpgs([x for x in cpgs_files if x.endswith("cpgs_autogain.xml")][0], output_dir="/tmp/x")
    assert auto.detector.em_gain == 1000.0 and auto.detector.photon_counting is True


@needs_corgisim
def test_translation_matches_corgisim_loader(cpgs_files, workdir):
    """Compare with corgisim's own inputs.load_cpgs_data on every sample it can read."""
    from corgisim import inputs
    for f in cpgs_files:
        c = cpgs.read_cpgs(f)
        job = cpgs.job_from_cpgs(c, output_dir="/tmp/x")
        try:
            res = inputs.load_cpgs_data(f, output_dim=51)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"corgisim could not load {os.path.basename(f)}: {exc}")
        if len(res) == 8:
            scene_t, scene_r, optics, det_t, det_r, visit_list, sat_t, sat_r = res
        else:
            scene_t, optics, det_t, visit_list, sat_t = res
            scene_r = det_r = sat_r = None
        assert optics.cor_type == job.instrument.cor_type, f
        assert optics.bandpass_header == job.instrument.bandpass, f
        assert optics.cgi_mode == job.instrument.cgi_mode, f
        assert scene_t._host_star_Vmag == job.scene.host.vmag
        assert scene_t._host_star_sptype == job.scene.host.spectral_type
        assert (scene_r is not None) == (job.reference_scene is not None)
        if scene_r is not None:
            assert scene_r._host_star_Vmag == job.reference_scene.host.vmag
        assert det_t.emccd_keywords_default["em_gain"] == job.detector.em_gain
        assert det_t.photon_counting == job.detector.photon_counting
        assert len(visit_list) == job.n_visits
        for v_c, v_j in zip(visit_list, job.visits):
            assert v_c["number_of_frames"] == v_j.n_frames
            assert abs(v_c["exp_time"] - v_j.exptime_s) < 1e-9
            assert abs(v_c["roll_angle"] - v_j.roll_angle_deg) < 1e-9
            assert v_c["visit_num"] == v_j.visit_num
            assert v_c["isReference"] == v_j.is_reference
            assert v_c["vistype"] == v_j.vistype
        if sat_t is not None:
            assert job.instrument.satspots is not None
            exp = tables.SATSPOT_PAIR_IDS[sat_t["satellite_spot_conf"]]
            assert job.instrument.satspots.sep_lamD == exp[0]
            tv = [v for v in job.visits if not v.is_reference][0]
            assert tv.satspots.em_gain == sat_t["satellite_spots_gain"]
            assert tv.satspots.exptime_s == sat_t["satellite_spots_frame_time"]
            assert tv.satspots.n_frames == sat_t["satellite_spots_number_of_frames"]
        else:
            assert job.instrument.satspots is None
        # DM solution: corgisim loaded dm1_v from <rootname>_dm1_v.fits; compare arrays
        from corgisim_gui.engine import stepwise
        import numpy as np
        dm1 = stepwise.load_dm(tables.DM_SOLUTIONS[job.instrument.dm_solution].filenames()[0])
        assert np.allclose(dm1, optics.optics_keywords["dm1_v"]), (f, job.instrument.dm_solution)
