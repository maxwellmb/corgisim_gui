from corgisim_gui.core.progress import ProgressParser, parse_kv


def test_parse_kv_quotes():
    assert parse_kv('name="a b" n=3') == {"name": "a b", "n": "3"}


def test_full_run():
    p = ProgressParser()
    lines = [
        'corgisim_gui job: name="x" visits=2 frames=4 engine=stepwise n_jobs=1',
        'corgisim_gui visit: i=1 n=2 id=0200001001001001001 label="first" frames=2 roll=-13 dpam=None',
        'corgisim_gui psf: i=1 n=1 label=science',
        'Propagating wavelength 1',
        'corgisim_gui psf_done: i=1 label=science',
        'corgisim_gui preview: /out/noiseless.fits',
        'corgisim_gui frame: i=1 n=2 visit=1 kind=science index=0 seconds=1.0 max=3',
        'corgisim_gui output: /out/a.fits',
        'corgisim_gui frame: i=2 n=2 visit=1 kind=science index=1 seconds=1.0 max=3',
        'corgisim_gui output: /out/b.fits',
        'corgisim_gui visit: i=2 n=2 id=0200001001001001002 label="second" frames=2 roll=13 dpam=None',
        '/x/y.py:12: UserWarning: careful',
        'corgisim_gui psf: i=1 n=1 label=science',
    ]
    for line in lines:
        p.feed(line)
    assert p.job_name == "x" and p.n_visits == 2 and p.n_frames == 4
    assert p.frames_done == 2 and 0.5 <= p.fraction < 1.0
    assert p.outputs == ["/out/a.fits", "/out/b.fits"] and p.previews == ["/out/noiseless.fits"]
    assert p.warnings == ["UserWarning: careful"]
    assert p.visits[0].ended is not None and p.visits[0].frames_done == 2
    assert p.status_text().startswith("visit 2/2: PSF 1/1")
    p.feed("corgisim_gui frame: i=1 n=2 visit=2 kind=science index=0 seconds=1 max=1")
    assert p.status_text() == "visit 2/2: frame 1/2"
    p.feed("corgisim_gui finished: status=ok elapsed=12.5 outputs=2")
    assert p.finished is True and p.elapsed == 12.5 and p.fraction == 1.0


def test_traceback_and_error():
    p = ProgressParser()
    for line in ["corgisim_gui job: name=x visits=1 frames=1 engine=stepwise",
                 "Traceback (most recent call last):", '  File "a.py", line 1, in <module>', "    boom()",
                 "ValueError: bad value", "corgisim_gui finished: status=error elapsed=1 error=ValueError"]:
        events = p.feed(line)
    assert p.finished is False
    assert p.errors[0] == "ValueError: bad value"
    assert "boom()" in p.traceback
    assert events[-1].kind == "finished"
    assert p.status_text() == "failed"
