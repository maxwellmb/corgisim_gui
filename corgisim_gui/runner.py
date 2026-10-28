"""Run one corgisim_gui job in a plain Python process.

    python -u -m corgisim_gui.runner JOB.json [--outputdir DIR] [--n-jobs N] [--engine stepwise|corgisim]
                                              [--preview] [--seed S] [--workdir DIR] [--validate-only] [--pdb]

Whatever the GUI runs can also be run, and debugged, from a terminal. The only
additions over the engine are marker lines on stdout, prefixed ``corgisim_gui ``,
which the Sim Console parses (see :mod:`corgisim_gui.core.progress`)::

    corgisim_gui job: name=<name> visits=<n> frames=<m> engine=<engine> n_jobs=<k>
    corgisim_gui visit: i=1 n=3 id=<visitid> label="<label>" frames=<f> roll=<deg> dpam=<element>
    corgisim_gui psf: i=1 n=3 label=science [part=host|companions|disk]
    corgisim_gui frame: i=2 n=10 visit=1 kind=science index=1 seconds=3.2 max=1234
    corgisim_gui output: <path>
    corgisim_gui preview: <path>
    corgisim_gui finished: status=ok|error elapsed=<seconds> outputs=<k> [error=<type>]

The spawn start method (macOS default) re-imports this module in every worker,
so everything runs under ``if __name__ == "__main__"``.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback

from .core.model import Job
from .core.validate import has_errors, validate_job


def _say(kind: str, text: str) -> None:
    sys.stdout.write(f"corgisim_gui {kind}: {text}\n")
    sys.stdout.flush()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="corgisim_gui.runner", description=__doc__.split("\n\n")[0])
    ap.add_argument("job", help="path to a job JSON file")
    ap.add_argument("--outputdir", help="override the job's output folder")
    ap.add_argument("--n-jobs", type=int, help="detector frames simulated in parallel")
    ap.add_argument("--engine", choices=("stepwise", "corgisim"), help="override the job's engine")
    ap.add_argument("--preview", action="store_true", help="noiseless PSF only, no detector frames")
    ap.add_argument("--seed", type=int, help="override the random seed")
    ap.add_argument("--workdir", help="where roman_preflight.py is copied and PROPER runs (default: output folder)")
    ap.add_argument("--validate-only", action="store_true", help="print validation issues and exit")
    ap.add_argument("--pdb", action="store_true", help="drop into pdb post-mortem on error")
    args = ap.parse_args(argv)

    job = Job.load(args.job)
    if args.outputdir:
        job.output.output_dir = args.outputdir
    if args.n_jobs:
        job.run.n_jobs = args.n_jobs
    if args.engine:
        job.run.engine = args.engine
    if args.preview:
        job.run.preview_only = True
    if args.seed is not None:
        job.run.seed = args.seed
    if args.workdir:
        job.run.workdir = args.workdir

    issues = validate_job(job)
    for issue in issues:
        _say("validation", f"level={issue.level} field={issue.field} msg=\"{issue.message}\"")
    if args.validate_only:
        return 1 if has_errors(issues) else 0
    if has_errors(issues):
        _say("finished", "status=error elapsed=0 error=ValidationError")
        return 2

    workdir = job.run.workdir or job.output.output_dir or os.getcwd()
    t0 = time.monotonic()
    _say("job", f'name="{job.name}" visits={job.n_visits} frames={job.total_frames} engine={job.run.engine} '
                f"n_jobs={job.run.n_jobs} outputdir={job.output.output_dir} workdir={workdir}")
    try:
        from .engine import stepwise                       # imports corgisim lazily inside
        stepwise.prepare_environment(workdir)
        if job.run.engine == "corgisim":
            outputs = stepwise.run_job_corgisim(job, _say)
        else:
            outputs = stepwise.run_job(job, _say, n_jobs=job.run.n_jobs)
    except BaseException as exc:          # noqa: BLE001 - KeyboardInterrupt is reported too
        traceback.print_exc()
        sys.stderr.flush()
        _say("finished", f"status=error elapsed={time.monotonic() - t0:.1f} error={type(exc).__name__}")
        if args.pdb:
            import pdb
            pdb.post_mortem(exc.__traceback__)
        return 1
    _say("finished", f"status=ok elapsed={time.monotonic() - t0:.1f} outputs={len(outputs)}")
    return 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
