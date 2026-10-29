"""The simulation queue: jobs and their persistence. No Qt, no processes.

The Sim Console owns a :class:`JobQueue`, asks it for the next runnable job,
starts a runner process for it and reports the result with :meth:`JobQueue.mark_finished`.
Each entry is one job file (the JSON of :class:`corgisim_gui.core.model.Job`)
written into the queue folder at enqueue time, so the runner reads exactly what
the console shows and the same command works from a terminal.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field

from .model import Job
from .progress import ProgressParser

__all__ = ["SimJob", "JobQueue", "STATUSES", "queue_dir", "gui_home"]

STATUSES = ("waiting", "running", "done", "failed", "aborted")


def gui_home() -> str:
    d = os.environ.get("CORGISIM_GUI_HOME") or os.path.join(os.path.expanduser("~"), ".corgisim_gui")
    os.makedirs(d, exist_ok=True)
    return d


def queue_dir() -> str:
    d = os.path.join(gui_home(), "queue")
    os.makedirs(d, exist_ok=True)
    return d


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name) or "job"


@dataclass
class SimJob:
    id: str
    job: Job
    job_path: str                      # JSON written at enqueue time; what the runner reads
    source: str = "imagelab"           # imagelab | sequence | file
    status: str = "waiting"
    created: float = field(default_factory=time.time)
    started: float | None = None
    ended: float | None = None
    returncode: int | None = None
    pid: int | None = None
    outputs: list[str] = field(default_factory=list)
    previews: list[str] = field(default_factory=list)
    message: str = ""
    parser: ProgressParser = field(default_factory=ProgressParser, repr=False)
    log: list[str] = field(default_factory=list, repr=False)
    max_log_lines: int = 5000

    @property
    def name(self) -> str:
        return self.job.name

    @property
    def outputdir(self) -> str:
        return self.job.output.output_dir

    @property
    def n_visits(self) -> int:
        return self.job.n_visits

    @property
    def n_frames(self) -> int:
        return self.job.total_frames

    @property
    def n_jobs(self) -> int:
        return self.job.run.n_jobs

    @property
    def elapsed(self) -> float | None:
        if self.started is None:
            return None
        return (self.ended or time.time()) - self.started

    @property
    def active(self) -> bool:
        return self.status in ("waiting", "running")

    def progress_text(self) -> str:
        p = self.parser
        if self.status == "waiting":
            return "—"
        if self.status == "done":
            return f"{self.n_frames}/{self.n_frames}"
        if self.status == "running":
            return p.status_text()
        return f"{p.frames_done}/{self.n_frames}"

    def fraction(self) -> float:
        if self.status == "done":
            return 1.0
        if self.status == "waiting":
            return 0.0
        return self.parser.fraction

    def append_log(self, line: str):
        self.log.append(line)
        if len(self.log) > self.max_log_lines:
            del self.log[: len(self.log) - self.max_log_lines]

    def to_record(self) -> dict:
        return {
            "id": self.id, "name": self.name, "job_path": self.job_path, "source": self.source, "status": self.status,
            "created": self.created, "started": self.started, "ended": self.ended, "returncode": self.returncode,
            "outputs": self.outputs, "previews": self.previews, "message": self.message,
        }


class JobQueue:
    """Ordered jobs plus the rules for which may run next."""

    def __init__(self, store_dir: str | None = None):
        self.store_dir = store_dir or queue_dir()
        os.makedirs(self.store_dir, exist_ok=True)
        self.jobs: list[SimJob] = []
        self.paused = False
        self.max_workers = 1
        self.listeners: list = []          # callables(event: str, job: SimJob | None)

    def _emit(self, event: str, job: SimJob | None = None):
        for cb in list(self.listeners):
            cb(event, job)

    # -- enqueue -------------------------------------------------------------
    def add(self, job: Job, source: str = "imagelab") -> SimJob:
        """Write the job file into the queue folder and append the entry."""
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        job_id = f"{stamp}_{uuid.uuid4().hex[:6]}"
        j = job.copy()
        path = os.path.join(self.store_dir, f"{job_id}_{_safe(j.name)}.json")
        j.save(path)
        entry = SimJob(id=job_id, job=j, job_path=path, source=source)
        self.jobs.append(entry)
        self._emit("added", entry)
        return entry

    def add_file(self, path: str, source: str = "file") -> SimJob:
        job = Job.load(path)
        entry = SimJob(id=f"{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}", job=job, job_path=path, source=source)
        self.jobs.append(entry)
        self._emit("added", entry)
        return entry

    # -- scheduling ------------------------------------------------------------
    def get(self, job_id: str) -> SimJob | None:
        return next((j for j in self.jobs if j.id == job_id), None)

    @property
    def running(self) -> list[SimJob]:
        return [j for j in self.jobs if j.status == "running"]

    @property
    def waiting(self) -> list[SimJob]:
        return [j for j in self.jobs if j.status == "waiting"]

    def counts(self) -> dict[str, int]:
        c = {s: 0 for s in STATUSES}
        for j in self.jobs:
            c[j.status] += 1
        return c

    def next_runnable(self) -> SimJob | None:
        if self.paused or len(self.running) >= self.max_workers:
            return None
        return next((j for j in self.jobs if j.status == "waiting"), None)

    def prepare_launch(self, job: SimJob) -> SimJob:
        job.status = "running"
        job.started = time.time()
        job.ended = None
        job.parser = ProgressParser()
        job.log = []
        job.outputs = []
        job.previews = []
        self._emit("started", job)
        return job

    def mark_finished(self, job: SimJob, returncode: int | None, aborted: bool = False):
        job.ended = time.time()
        job.returncode = returncode
        p = job.parser
        job.outputs = list(p.outputs)
        job.previews = list(p.previews)
        if aborted:
            job.status = "aborted"
            job.message = "aborted by user"
        elif returncode == 0 and p.finished is not False:
            job.status = "done"
            job.message = f"{len(job.outputs)} file{'s' if len(job.outputs) != 1 else ''} written"
        else:
            job.status = "failed"
            err = p.errors[-1] if p.errors else f"exit code {returncode}"
            where = f"visit {p.current_visit.index}/{p.current_visit.total}: " if p.current_visit else ""
            job.message = where + err
        self._emit("finished", job)

    # -- user actions ----------------------------------------------------------
    def requeue(self, job: SimJob) -> SimJob:
        if job.status == "running":
            return job
        job.status = "waiting"
        job.started = job.ended = None
        job.returncode = None
        job.outputs = []
        job.previews = []
        job.message = ""
        job.parser = ProgressParser()
        job.log = []
        self.jobs.remove(job)
        self.jobs.append(job)
        self._emit("added", job)
        return job

    def remove(self, job: SimJob):
        if job.status == "running":
            return
        self.jobs.remove(job)
        self._emit("removed", job)

    def clear_finished(self):
        for j in [j for j in self.jobs if not j.active]:
            self.jobs.remove(j)
        self._emit("cleared", None)

    def move(self, job: SimJob, delta: int):
        i = self.jobs.index(job)
        k = max(0, min(len(self.jobs) - 1, i + delta))
        if k != i and job.status == "waiting":
            self.jobs.insert(k, self.jobs.pop(i))
            self._emit("reordered", job)

    # -- persistence -----------------------------------------------------------
    def state_path(self) -> str:
        return os.path.join(self.store_dir, "queue_state.json")

    def save(self):
        data = {"saved": _dt.datetime.now().isoformat(timespec="seconds"), "max_workers": self.max_workers,
                "jobs": [j.to_record() for j in self.jobs][-300:]}
        tmp = self.state_path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.state_path())

    def load(self) -> int:
        """Restore waiting jobs (and recent history) from disk. Running jobs become 'aborted'."""
        p = self.state_path()
        if not os.path.exists(p):
            return 0
        try:
            with open(p) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return 0
        self.max_workers = int(data.get("max_workers", 1))
        n = 0
        for rec in data.get("jobs", []):
            if not os.path.exists(rec.get("job_path", "")):
                continue
            try:
                job = Job.load(rec["job_path"])
            except (OSError, ValueError, TypeError):
                continue
            entry = SimJob(id=rec["id"], job=job, job_path=rec["job_path"], source=rec.get("source", "file"),
                           status=rec.get("status", "waiting"), created=rec.get("created", time.time()),
                           started=rec.get("started"), ended=rec.get("ended"), returncode=rec.get("returncode"),
                           outputs=list(rec.get("outputs", [])), previews=list(rec.get("previews", [])), message=rec.get("message", ""))
            if entry.status == "running":
                entry.status = "aborted"
                entry.message = "GUI closed while running"
                entry.ended = entry.ended or time.time()
            self.jobs.append(entry)
            n += 1
        self._emit("cleared", None)
        return n


def machine_limits() -> dict:
    """Cores and memory of this machine, for capping parallel frames."""
    cpus = os.cpu_count() or 1
    mem_gb = None
    try:
        import psutil
        mem_gb = psutil.virtual_memory().total / 1e9
    except Exception:  # noqa: BLE001
        try:
            mem_gb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
        except (ValueError, OSError, AttributeError):
            mem_gb = None
    return {"cpus": cpus, "memory_gb": mem_gb}
