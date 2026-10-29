"""One runner subprocess wrapped in a QObject: lines in, progress events out.

Used by the Image Lab (one run at a time, inline) and the Sim Console (the queue).
"""
from __future__ import annotations

import os
import shlex

from qtpy import QtCore

import corgisim_gui

from ..backend import default_backend
from ..core.progress import Event, ProgressParser


class RunnerProcess(QtCore.QObject):
    """Starts ``python -u -m corgisim_gui.runner job.json`` and parses its output."""

    line = QtCore.Signal(str, str)              # raw line, stream
    event = QtCore.Signal(object)               # core.progress.Event
    finished = QtCore.Signal(int, bool)         # return code, aborted

    def __init__(self, parent=None, backend=None):
        super().__init__(parent)
        self.backend = backend or default_backend()
        self.parser = ProgressParser()
        self.proc: QtCore.QProcess | None = None
        self._buf = {"stdout": "", "stderr": ""}
        self._aborting = False
        self.command: list[str] = []
        self.log: list[str] = []

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.state() != QtCore.QProcess.ProcessState.NotRunning

    def start(self, job_path: str, n_jobs: int | None = None, outputdir: str | None = None,
              extra_args: list[str] | None = None, workdir: str | None = None) -> list[str]:
        if self.running:
            raise RuntimeError("a run is already in progress")
        self.parser = ProgressParser()
        self.log = []
        self._aborting = False
        cmd = self.backend.runner_command(job_path, n_jobs, outputdir) + list(extra_args or [])
        self.command = cmd
        proc = QtCore.QProcess(self)
        env = QtCore.QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(corgisim_gui.__file__)))
        pp = env.value("PYTHONPATH", "")
        if pkg_root not in pp.split(os.pathsep):
            env.insert("PYTHONPATH", pkg_root + (os.pathsep + pp if pp else ""))
        proc.setProcessEnvironment(env)
        proc.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        proc.setProgram(cmd[0])
        proc.setArguments(cmd[1:])
        wd = workdir or (outputdir if outputdir and self.backend.isdir(outputdir) else None)
        proc.setWorkingDirectory(wd if wd and self.backend.isdir(wd) else self.backend.home())
        self._buf = {"stdout": "", "stderr": ""}
        proc.readyReadStandardOutput.connect(lambda: self._read("stdout"))
        proc.readyReadStandardError.connect(lambda: self._read("stderr"))
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        self.proc = proc
        self.log.append("$ " + shlex.join(cmd))
        proc.start()
        return cmd

    def abort(self) -> None:
        if not self.running:
            return
        self._aborting = True
        self.proc.terminate()
        proc = self.proc
        QtCore.QTimer.singleShot(4000, lambda: proc.kill() if proc.state() != QtCore.QProcess.ProcessState.NotRunning else None)

    def _read(self, stream: str) -> None:
        if self.proc is None:
            return
        data = self.proc.readAllStandardOutput() if stream == "stdout" else self.proc.readAllStandardError()
        text = bytes(data).decode("utf-8", errors="replace")
        self._buf[stream] += text
        lines = self._buf[stream].split("\n")
        self._buf[stream] = lines.pop()
        for ln in lines:
            self._handle(ln, stream)

    def _handle(self, ln: str, stream: str) -> None:
        self.log.append(ln)
        self.line.emit(ln, stream)
        for ev in self.parser.feed(ln, stream):
            self.event.emit(ev)

    def _on_error(self, err) -> None:
        if err == QtCore.QProcess.ProcessError.FailedToStart:
            msg = f"failed to start: {self.proc.program() if self.proc else '?'}"
            self.log.append(msg)
            self.parser.errors.append(msg)
            self.event.emit(Event("error", msg, {"type": "FailedToStart", "msg": msg}, "stderr"))
            self.finished.emit(-1, False)
            self.proc = None

    def _on_finished(self, code: int, status) -> None:
        proc = self.proc
        if proc is not None:
            for stream in ("stdout", "stderr"):
                self._read(stream)
                rest = self._buf.get(stream, "")
                if rest.strip():
                    self._handle(rest, stream)
                self._buf[stream] = ""
            proc.deleteLater()
        self.proc = None
        crashed = status == QtCore.QProcess.ExitStatus.CrashExit
        self.finished.emit(code if not crashed else -9, self._aborting)

    def wait(self, timeout_ms: int = 600000) -> bool:
        """Spin the event loop until the process ends (tests)."""
        from qtpy import QtWidgets
        deadline = QtCore.QDeadlineTimer(timeout_ms)
        app = QtWidgets.QApplication.instance()
        while self.running and not deadline.hasExpired():
            app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
            QtCore.QThread.msleep(20)
        app.processEvents()
        return not self.running
