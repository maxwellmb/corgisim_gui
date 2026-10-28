"""Turn the runner's console output into progress events.

``corgisim_gui.runner`` prints marker lines, all prefixed with ``corgisim_gui ``::

    corgisim_gui job: name=<name> visits=<n> frames=<m> engine=stepwise
    corgisim_gui visit: i=1 n=3 id=0200001001001001001 label=<label> frames=<f> roll=<deg>
    corgisim_gui psf: i=1 n=3 label=host|companions|satspot_positive|satspot_negative|disk
    corgisim_gui frame: i=2 n=10 visit=1 kind=science|satspot_background|satspot_positive|satspot_negative
    corgisim_gui output: <path>
    corgisim_gui preview: <path>           (noiseless PSF/scene written for the viewer)
    corgisim_gui finished: status=ok|error elapsed=<s> outputs=<k> [error=<type>]

Everything else is passed through as log text. Python tracebacks and warnings
are recognised too. The console keeps one :class:`ProgressParser` per runner.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Event", "ProgressParser", "VisitProgress", "RUNNER_PREFIX"]

RUNNER_PREFIX = "corgisim_gui "

_RE = {
    "runner": re.compile(r"^corgisim_gui (?P<kind>[a-z_]+):\s*(?P<rest>.*)$"),
    "traceback": re.compile(r"^Traceback \(most recent call last\):"),
    "exception": re.compile(r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Warning|Interrupt|Exit))\s*:\s*(?P<msg>.*)$"),
    "warning": re.compile(r"^.*?:\d+:\s*(?P<type>\w*Warning):\s*(?P<msg>.*)$"),
    "proper": re.compile(r"^\s*(Propagating|Computing|Reading|Using)\b.*", re.IGNORECASE),
}
_KV = re.compile(r"(\w+)=(\"[^\"]*\"|\S+)")


def parse_kv(rest: str) -> dict[str, str]:
    out = {}
    for k, v in _KV.findall(rest):
        out[k] = v.strip('"')
    return out


@dataclass
class Event:
    kind: str                      # job, visit, psf, frame, output, preview, finished, log, warning, error
    text: str
    data: dict[str, Any] = field(default_factory=dict)
    stream: str = "stdout"
    time: float = 0.0


@dataclass
class VisitProgress:
    index: int
    total: int
    visit_id: str
    label: str
    n_frames: int
    roll: float | None
    started: float
    ended: float | None = None
    frames_done: int = 0
    psf_done: int = 0
    psf_total: int = 0
    current_psf: str = ""

    @property
    def elapsed(self) -> float:
        return (self.ended or time.monotonic()) - self.started


class ProgressParser:
    """Feed lines in; get :class:`Event` objects and running state out."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self.job_name: str | None = None
        self.n_visits: int | None = None
        self.n_frames: int | None = None
        self.engine: str | None = None
        self.visits: list[VisitProgress] = []
        self.current_visit: VisitProgress | None = None
        self.frames_done = 0
        self.outputs: list[str] = []
        self.previews: list[str] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.finished: bool | None = None
        self.elapsed: float | None = None
        self._in_traceback = False
        self._traceback_lines: list[str] = []
        self.traceback: str | None = None

    # ---------------------------------------------------------------- state
    @property
    def fraction(self) -> float:
        """0..1 progress by frames, with PSF work counted as a share of each visit."""
        if self.finished is not None:
            return 1.0
        if not self.n_frames:
            return 0.0
        done = float(self.frames_done)
        v = self.current_visit
        if v is not None and v.psf_total and v.frames_done == 0:
            done += 0.5 * v.n_frames * (v.psf_done / v.psf_total)
        return max(0.0, min(1.0, done / self.n_frames))

    def status_text(self) -> str:
        if self.finished is True:
            return "finished"
        if self.finished is False:
            return "failed"
        v = self.current_visit
        if v is None:
            return "starting" if self.job_name else "waiting"
        if v.frames_done == 0 and v.psf_total and v.psf_done < v.psf_total:
            return f"visit {v.index}/{v.total}: PSF {v.psf_done + 1}/{v.psf_total} {v.current_psf}".rstrip()
        return f"visit {v.index}/{v.total}: frame {v.frames_done}/{v.n_frames}"

    # ---------------------------------------------------------------- feed
    def feed(self, line: str, stream: str = "stdout") -> list[Event]:
        now = self._clock()
        line = line.rstrip("\r\n")
        events: list[Event] = []

        if self._in_traceback:
            self._traceback_lines.append(line)
            m = _RE["exception"].match(line)
            if m and not line.startswith(" "):
                self._in_traceback = False
                self.traceback = "\n".join(self._traceback_lines)
                self.errors.append(f"{m.group('type')}: {m.group('msg')}")
                events.append(Event("error", line, {"type": m.group("type"), "msg": m.group("msg"), "traceback": self.traceback}, stream, now))
            elif line == "":
                pass
            return events or [Event("log", line, {}, stream, now)]

        if _RE["traceback"].match(line):
            self._in_traceback = True
            self._traceback_lines = [line]
            return [Event("log", line, {}, stream, now)]

        m = _RE["runner"].match(line)
        if m:
            kind, rest = m.group("kind"), m.group("rest")
            if kind == "job":
                kv = parse_kv(rest)
                self.job_name = kv.get("name")
                self.n_visits = int(kv.get("visits", 0) or 0)
                self.n_frames = int(kv.get("frames", 0) or 0)
                self.engine = kv.get("engine")
                return [Event("job", line, kv, stream, now)]
            if kind == "visit":
                kv = parse_kv(rest)
                if self.current_visit is not None and self.current_visit.ended is None:
                    self.current_visit.ended = now
                v = VisitProgress(int(kv.get("i", 0)), int(kv.get("n", 0)), kv.get("id", ""), kv.get("label", ""),
                                  int(kv.get("frames", 0) or 0), float(kv["roll"]) if "roll" in kv else None, now)
                self.visits.append(v)
                self.current_visit = v
                return [Event("visit", line, kv, stream, now)]
            if kind == "psf":
                kv = parse_kv(rest)
                v = self.current_visit
                if v is not None:
                    v.psf_total = int(kv.get("n", 0) or 0)
                    v.psf_done = max(0, int(kv.get("i", 1) or 1) - 1)
                    v.current_psf = kv.get("label", "")
                return [Event("psf", line, kv, stream, now)]
            if kind == "psf_done":
                kv = parse_kv(rest)
                v = self.current_visit
                if v is not None:
                    v.psf_done = int(kv.get("i", v.psf_done + 1) or 0)
                return [Event("psf_done", line, kv, stream, now)]
            if kind == "frame":
                kv = parse_kv(rest)
                v = self.current_visit
                if v is not None:
                    v.frames_done = int(kv.get("i", v.frames_done) or 0)
                    v.n_frames = int(kv.get("n", v.n_frames) or v.n_frames)
                self.frames_done += 1
                return [Event("frame", line, kv, stream, now)]
            if kind == "output":
                self.outputs.append(rest.strip())
                return [Event("output", line, {"path": rest.strip()}, stream, now)]
            if kind == "preview":
                self.previews.append(rest.strip())
                return [Event("preview", line, {"path": rest.strip()}, stream, now)]
            if kind == "finished":
                kv = parse_kv(rest)
                self.finished = kv.get("status") == "ok"
                self.elapsed = float(kv.get("elapsed", 0) or 0)
                if self.current_visit is not None and self.current_visit.ended is None:
                    self.current_visit.ended = now
                if not self.finished and kv.get("error") and not any(e.startswith(kv["error"]) for e in self.errors):
                    self.errors.append(kv["error"])
                return [Event("finished", line, kv, stream, now)]
            return [Event("runner", line, {"kind": kind, "rest": rest}, stream, now)]

        m = _RE["warning"].match(line)
        if m:
            self.warnings.append(f"{m.group('type')}: {m.group('msg')}")
            return [Event("warning", line, {"type": m.group("type"), "msg": m.group("msg")}, stream, now)]
        return [Event("log", line, {}, stream, now)]
