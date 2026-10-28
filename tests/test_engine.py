"""End-to-end: the runner subprocess simulates a tiny job with the real corgisim."""
import glob
import json
import os
import subprocess
import sys

import numpy as np
import pytest
from astropy.io import fits

from corgisim_gui.core import model
from corgisim_gui.core.progress import ProgressParser
from conftest import ROOT, needs_corgisim

pytestmark = needs_corgisim


def tiny_job(outdir: str, n_frames: int = 2, n_jobs: int = 2, seed: int | None = 1, full_frame: bool = True) -> model.Job:
    job = model.single_image_job("tiny")
    job.instrument.oversampling_factor = 1
    job.instrument.output_dim = 51
    job.scene.point_sources.append(model.PointSource(vmag=12.0, dra_mas=300.0, ddec_mas=100.0, label="b"))
    job.detector = model.DetectorSpec(em_gain=500.0, fast_gain_mode=True, gain_CIC_Q=0, full_frame=full_frame, cr_rate=0)
    job.visits = [model.Visit(label="v1", roll_angle_deg=13.0, n_frames=n_frames, exptime_s=5.0, visit_num="042")]
    job.output = model.OutputSpec(output_dir=outdir, save_fits=True, write_as_l1=full_frame, save_noiseless=True)
    job.run = model.RunSpec(engine="stepwise", n_jobs=n_jobs, seed=seed)
    return job


def run_runner(job: model.Job, path: str, *extra: str) -> tuple[int, ProgressParser, str]:
    job.save(path)
    cmd = [sys.executable, "-u", "-m", "corgisim_gui.runner", path, *extra]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=900)
    p = ProgressParser()
    for line in proc.stdout.splitlines():
        p.feed(line)
    for line in proc.stderr.splitlines():
        p.feed(line, "stderr")
    return proc.returncode, p, proc.stdout + "\n" + proc.stderr


def test_validate_only(tmp_path):
    job = tiny_job(str(tmp_path / "out"))
    job.instrument.bandpass = "4F"
    code, p, text = run_runner(job, str(tmp_path / "bad.json"), "--validate-only")
    assert code == 1 and "instrument.bandpass" in text


def test_runner_parallel_and_reproducible(tmp_path):
    out1 = str(tmp_path / "run1")
    job = tiny_job(out1, n_frames=2, n_jobs=2, seed=7)
    code, p, text = run_runner(job, str(tmp_path / "job1.json"))
    assert code == 0, text
    assert p.finished is True and p.frames_done == 2 and p.n_visits == 1
    assert p.visits[0].visit_id == "0200001001001001042"
    assert len(p.outputs) == 2 and all(os.path.exists(o) for o in p.outputs)
    assert len(set(os.path.basename(o) for o in p.outputs)) == 2        # unique L1 names
    assert p.previews and os.path.exists(p.previews[0])
    vdir = os.path.join(out1, "V0200001001001001042")
    assert os.path.isdir(vdir)
    with fits.open(p.outputs[0]) as h:
        assert h[1].data.shape == (1200, 2200)
        assert h[0].header["VISITID"] == "0200001001001001042"
        assert h[0].header["VISNUM"] == "042"
        assert abs(h[0].header["PA_APER"] - 13.0) < 1e-6
        assert h[1].header["EMGAIN_C"] == 500.0 or h[1].header.get("EMGAIN_C") is not None
    with fits.open(p.previews[0]) as h:
        assert h[0].data.shape == (51, 51) and h[0].data.max() > 0 and h[0].header["BUNIT"] == "counts/s"

    # same seed, serial: bit-identical frames
    out2 = str(tmp_path / "run2")
    job2 = tiny_job(out2, n_frames=2, n_jobs=1, seed=7)
    code, p2, text2 = run_runner(job2, str(tmp_path / "job2.json"))
    assert code == 0, text2
    a = sorted(p.outputs)
    b = sorted(p2.outputs)
    for fa, fb in zip(a, b):
        with fits.open(fa) as ha, fits.open(fb) as hb:
            assert np.array_equal(ha[1].data, hb[1].data)
    # the two frames of one run differ from each other
    with fits.open(a[0]) as h0, fits.open(a[1]) as h1:
        assert not np.array_equal(h0[1].data, h1[1].data)


def test_preview_only_subframe(tmp_path):
    out = str(tmp_path / "prev")
    job = tiny_job(out, n_frames=1, n_jobs=1, full_frame=False)
    job.scene.point_sources = []
    code, p, text = run_runner(job, str(tmp_path / "job.json"), "--preview")
    assert code == 0, text
    assert p.frames_done == 0 and p.previews and not p.outputs
    assert glob.glob(os.path.join(out, "V*", "noiseless_*science.fits"))


def test_corgisim_engine_subframe(tmp_path):
    out = str(tmp_path / "cs")
    job = tiny_job(out, n_frames=1, n_jobs=1, full_frame=True)
    job.scene.point_sources = []
    job.run.engine = "corgisim"
    code, p, text = run_runner(job, str(tmp_path / "job.json"))
    assert code == 0, text
    assert p.finished and len(p.outputs) == 1 and os.path.exists(p.outputs[0])
    with fits.open(p.outputs[0]) as h:
        assert h[0].header["VISITID"] == "0200001001001001042"
