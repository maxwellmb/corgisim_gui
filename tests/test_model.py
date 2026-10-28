import json

from corgisim_gui.core import model, tables


def test_default_job_round_trip():
    job = model.single_image_job()
    job.scene.point_sources.append(model.PointSource.from_polar(20.0, 300.0, 45.0, label="b"))
    job.scene.disk = model.DiskModel(path="/x/disk.fits", unit="contrast/pixel", contrast=1e-6, prf_cube_path="/x/prf.fits")
    job.instrument.satspots = model.SatSpotSpec.from_pair_id(3)
    job.instrument.jitter = model.JitterSpec(preset="mintest")
    job.visits[0].satspots = model.SatSpotBlock(n_frames=2, exptime_s=1.0, em_gain=200.0)
    job.reference_scene = model.SceneSpec(host=model.HostStar(vmag=3.0, spectral_type="A0V"), ref_flag=True)
    d = job.to_dict()
    back = model.Job.from_dict(json.loads(json.dumps(d)))
    assert back.to_dict() == d
    assert back.scene.point_sources[0].label == "b"
    assert back.scene.disk.unit == "contrast/pixel"
    assert back.instrument.satspots.sep_lamD == 13.0
    assert back.instrument.jitter.n_offsets == 1
    assert back.visits[0].satspots.em_gain == 200.0
    assert back.reference_scene.ref_flag is True


def test_unknown_keys_ignored_and_versions():
    d = model.single_image_job().to_dict()
    d["future_field"] = 1
    d["instrument"]["future_knob"] = 2
    job = model.Job.from_dict(d)
    assert job.format_version == model.JOB_FORMAT_VERSION


def test_visit_ids_and_totals():
    job = model.roll_sequence_job(rolls=(-13, 13), n_frames=5, exptime_s=10.0)
    assert job.n_visits == 3
    assert job.visits[0].is_reference
    assert job.visit_id(0).endswith("001") and len(job.visit_id(0)) == 19
    job.visits[2].visit_num = "007"
    assert job.visit_id(2).endswith("007")
    assert job.total_frames == 15
    assert job.total_exposure_s == 150.0
    job.visits[1].satspots = model.SatSpotBlock(n_frames=2, exptime_s=1.0)
    assert job.visits[1].total_frames == 11
    assert job.total_frames == 21


def test_point_source_polar():
    p = model.PointSource.from_polar(20.0, 100.0, 90.0)
    assert abs(p.dra_mas - 100.0) < 1e-9 and abs(p.ddec_mas) < 1e-9
    assert abs(p.pa_deg - 90.0) < 1e-9
    assert abs(p.separation_mas - 100.0) < 1e-9


def test_visit_overrides():
    job = model.polarimetry_pair_job()
    assert [job.visit_dpam(v) for v in job.visits] == ["POL0", "POL45"]
    job.visits[0].em_gain = 50.0
    assert job.visit_gain(job.visits[0]) == 50.0
    assert job.visit_gain(job.visits[1]) == job.detector.em_gain


def test_mechanisms_from_model():
    inst = model.InstrumentSpec(cor_type="spc-spec_band3", cgi_mode="spec", bandpass="3F", dpam="PRISM3", slit="R1C2")
    m = inst.mechanisms()
    assert m.as_dict() == {"SPAM": "SPEC", "FPAM": "SPC34_R2C2", "LSAM": "SPEC", "FSAM": "R1C2", "CFAM": "3F",
                           "DPAM": "PRISM3", "FSMPRFL": "SPEC730"}
    inst = model.InstrumentSpec(cor_type="hlc_band1", bandpass="1F", dpam="POL45")
    assert inst.mechanisms().fsam == "R1C5"
    assert inst.mechanisms().dpam == "POL45"
    inst = model.InstrumentSpec(cor_type="hlc_band1", bandpass="1B", use_fpm=False, nd=2)
    assert inst.mechanisms().fpam == "ND475"
    assert abs(inst.lam_over_d_mas - 50.2) < 0.5
    assert tables.FILTERS["1F"].lam_over_d_pix > 2
