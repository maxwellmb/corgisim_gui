from corgisim_gui.core import cost, model, validate


def _job(**kw):
    job = model.single_image_job()
    job.output.output_dir = "/tmp/corgisim_gui_test"
    for k, v in kw.items():
        setattr(job.instrument, k, v)
    return job


def levels(issues, level):
    return [i.field for i in issues if i.level == level]


def test_clean_default_job():
    assert not validate.has_errors(validate.validate_job(_job()))


def test_filter_coronagraph_mismatch():
    issues = validate.validate_job(_job(bandpass="3F"))
    assert "instrument.bandpass" in levels(issues, "error")


def test_nd_conflicts():
    assert "instrument.nd" in levels(validate.validate_job(_job(nd=1)), "error")
    assert "instrument.nd" not in levels(validate.validate_job(_job(nd=1, use_fpm=False)), "error")
    assert "instrument.nd" in levels(validate.validate_job(_job(nd=3)), "error")


def test_spec_mode_rules():
    job = _job(cgi_mode="spec", cor_type="spc-spec_band3", bandpass="3F", dpam="PRISM3", slit="R6C5", dm_solution="spc-spec_ni_2e-8")
    issues = validate.validate_job(job)
    assert "instrument.slit" in levels(issues, "error")
    job.instrument.slit = "R1C2"
    issues = validate.validate_job(job)
    assert not validate.has_errors(issues)
    assert any("dispersed" in i.message for i in issues)
    job.instrument.dpam = "POL0"
    assert "instrument.dpam" in levels(validate.validate_job(job), "error")


def test_polarimetry_size_and_placement():
    job = _job(dpam="POL0", output_dim=601)
    assert "instrument.output_dim" in levels(validate.validate_job(job), "error")
    job = _job(dpam="POL0", output_dim=201)
    job.detector.loc_x = 100
    assert "detector.loc_x" in levels(validate.validate_job(job), "error")


def test_companion_outside_dark_hole_warns():
    job = _job()
    job.scene.point_sources.append(model.PointSource.from_polar(20, 2000.0, 0.0, label="far"))
    issues = validate.validate_job(job)
    assert any(i.level == "warn" and "dark hole" in i.message for i in issues)


def test_visit_rules():
    job = _job()
    job.visits[0].is_reference = True
    assert "visits[0].is_reference" in levels(validate.validate_job(job), "error")
    job = _job()
    job.visits[0].satspots = model.SatSpotBlock()
    assert "visits[0].satspots" in levels(validate.validate_job(job), "error")
    job.instrument.satspots = model.SatSpotSpec()
    assert not validate.has_errors(validate.validate_job(job))
    job.output.visit_id_root = "123"
    assert "visits[0].visit_num" in levels(validate.validate_job(job), "error")


def test_output_rules():
    job = _job()
    job.output.output_dir = ""
    assert "output.output_dir" in levels(validate.validate_job(job), "error")
    job = _job()
    job.detector.full_frame = False
    assert "output.write_as_l1" in levels(validate.validate_job(job), "error")
    job.output.write_as_l1 = False
    assert not validate.has_errors(validate.validate_job(job))


def test_cost_scaling():
    base = cost.estimate(_job())
    assert base.propagations == 7 and base.frames == 1
    pol = cost.estimate(_job(dpam="POL0"))
    assert pol.propagations == 28
    job = _job()
    job.scene.point_sources.append(model.PointSource())
    assert cost.estimate(job).propagations == 14
    job = _job()
    job.instrument.jitter = model.JitterSpec(preset="mintest")
    assert cost.estimate(job).propagations == 14
    job = _job()
    job.instrument.satspots = model.SatSpotSpec()
    job.visits[0].satspots = model.SatSpotBlock(n_frames=2)
    e = cost.estimate(job)
    assert e.psf_states == 3 and e.propagations == 21 and e.satspot_frames == 6
    seq = model.roll_sequence_job(n_frames=10)
    seq.output.output_dir = "/tmp/x"
    e2 = cost.estimate(seq)
    assert e2.frames == 30 and len(e2.per_visit) == 3
    seq.run.n_jobs = 3
    assert cost.estimate(seq).seconds_detector < e2.seconds_detector
    assert cost.max_parallel_jobs(26.0, 8) == 2
    assert cost.max_parallel_jobs(64.0, 2) == 2
    assert cost.pretty_seconds(30) == "30 s" and cost.pretty_seconds(7200) == "2.0 h"
