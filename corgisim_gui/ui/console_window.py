"""Sim Console: the job queue, one runner process per job, progress per visit and frame, logs, a live frame view."""
from __future__ import annotations

import datetime as _dt
import os
import shlex
import shutil
import subprocess

from qtpy import QtCore, QtGui, QtWidgets

from .. import theming
from ..backend import default_backend
from ..core import cost
from ..core.model import Job
from ..core.queue import JobQueue, SimJob, machine_limits
from .base import ThemedWindow
from .dialogs import JobPreviewDialog, text_dialog
from .image_view import ImageView
from .runner_process import RunnerProcess
from .widgets.flow import FlowLayout
from .widgets.themed import Chip, ElidedLabel, Panel, SectionLabel, step_label

Qt = QtCore.Qt


def _fmt_elapsed(sec: float | None) -> str:
    if sec is None:
        return "—"
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


class JobTableModel(QtCore.QAbstractTableModel):
    HEADERS = ["#", "Job", "Visits", "Frames", "Parallel", "Status", "Progress", "Elapsed", "Message"]

    def __init__(self, queue: JobQueue, parent=None):
        super().__init__(parent)
        self.queue = queue

    def refresh(self):
        self.beginResetModel()
        self.endResetModel()

    def refresh_row(self, job: SimJob):
        if job in self.queue.jobs:
            r = self.queue.jobs.index(job)
            self.dataChanged.emit(self.index(r, 0), self.index(r, self.columnCount() - 1))

    def tick(self):
        for j in self.queue.running:
            self.refresh_row(j)

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.queue.jobs)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def job_at(self, row: int) -> SimJob | None:
        return self.queue.jobs[row] if 0 <= row < len(self.queue.jobs) else None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        j = self.queue.jobs[index.row()]
        c = index.column()
        pal = theming.current_theme().palette
        if role == Qt.ItemDataRole.DisplayRole:
            return [index.row() + 1, j.name, j.n_visits, j.n_frames, j.n_jobs, j.status, j.progress_text(),
                    _fmt_elapsed(j.elapsed), j.message][c]
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{j.job_path}\noutput: {j.outputdir}\n{j.message}"
        if role == Qt.ItemDataRole.ForegroundRole and c == 5:
            return QtGui.QColor({"done": pal.ok, "failed": pal.err, "running": pal.secondary if pal.secondary != pal.bg else pal.primary,
                                 "aborted": pal.warn, "waiting": pal.muted}[j.status])
        if role == Qt.ItemDataRole.FontRole and c == 5 and j.status in ("running", "failed"):
            f = QtGui.QFont()
            f.setBold(True)
            return f
        if role == Qt.ItemDataRole.TextAlignmentRole and c in (0, 2, 3, 4, 7):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None


class ConsoleWindow(ThemedWindow):
    """GPI Status Console equivalent for corgisim jobs."""

    open_in_imagelab = QtCore.Signal(object)
    open_in_sequence = QtCore.Signal(object)
    job_finished = QtCore.Signal(object)

    def __init__(self, parent=None, backend=None, queue: JobQueue | None = None, restore: bool = True):
        super().__init__(parent, title="Sim Console")
        self.setObjectName("ConsoleWindow")
        self.backend = backend or default_backend()
        self.settings = theming.theme_manager().settings()
        self.queue = queue or JobQueue()
        self.imagelab_handler = None
        self.sequence_handler = None
        self._runners: dict[str, RunnerProcess] = {}
        self._shown_job: SimJob | None = None
        self._all_log: list[str] = []
        self.limits = machine_limits()
        self.model = JobTableModel(self.queue)
        self._build_menus()
        self._build_body()
        self.resize(1320, 860)
        geo = self.settings.value("console/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        if restore:
            n = self.queue.load()
            if n:
                self.log_line(f"restored {n} queue entries from {self.queue.state_path()}")
        self.workers_spin.setValue(self.queue.max_workers)
        self.queue.listeners.append(self._on_queue_event)
        self.model.refresh()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._update_all()

    # ------------------------------------------------------------------ menus
    def _build_menus(self):
        q = self.add_menu("&Queue")
        self._act(q, "Add job file…", self.add_job_file_dialog, "Ctrl+O")
        q.addSeparator()
        self.pause_act = self._act(q, "Pause queue", self.toggle_pause, "Ctrl+P")
        self.pause_act.setCheckable(True)
        self._act(q, "Abort selected", self.abort_selected, "Ctrl+.")
        self._act(q, "Re-queue selected", self.requeue_selected, "Ctrl+R")
        self._act(q, "Remove selected", self.remove_selected, "Delete")
        self._act(q, "Clear finished", self.clear_finished)
        q.addSeparator()
        self._act(q, "Close", self.close, "Ctrl+W")
        v = self.add_menu("&View")
        self._act(v, "Job JSON", self.view_job)
        self._act(v, "Job log and traceback", self.show_details)
        self._act(v, "Open output folder", self.open_output_folder)
        self._act(v, "Copy runner command", self.copy_command)
        v.addSeparator()
        self._act(v, "Open in Image Lab", self.open_selected_in_imagelab)
        self._act(v, "Open in Sequence Builder", self.open_selected_in_sequence)
        self._act(v, "Reduce outputs with corgidrp_gui", self.reduce_with_corgidrp)
        self.add_theme_menu()
        self.add_help_menu()

    @staticmethod
    def _act(menu, text, slot, shortcut=None):
        a = menu.addAction(text)
        a.triggered.connect(lambda _=False: slot())
        if shortcut:
            a.setShortcut(QtGui.QKeySequence(shortcut))
        return a

    def _build_body(self):
        theme = theming.current_theme()
        gap = theme.density.gap
        central = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(gap, gap, gap, gap)
        outer.setSpacing(gap)
        self.setCentralWidget(central)

        # queue
        qpanel = Panel(layout="v")
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setMinimumSectionSize(36)
        for c in (0, 2, 3, 4, 5, 6, 7):
            hh.setSectionResizeMode(c, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Interactive)
        hh.resizeSection(1, 200)
        hh.setSectionResizeMode(8, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)
        self.table.doubleClicked.connect(lambda _i: self.show_details())
        qpanel.layout().addWidget(self.table, 1)
        brow = QtWidgets.QHBoxLayout()
        self.pause_btn = QtWidgets.QPushButton("Pause queue")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._on_pause_toggled)
        self.abort_btn = QtWidgets.QPushButton("Abort")
        self.abort_btn.clicked.connect(self.abort_selected)
        self.requeue_btn = QtWidgets.QPushButton("Re-queue")
        self.requeue_btn.clicked.connect(self.requeue_selected)
        self.remove_btn = QtWidgets.QPushButton("Remove")
        self.remove_btn.clicked.connect(self.remove_selected)
        self.up_btn = QtWidgets.QPushButton("▲")
        self.up_btn.clicked.connect(lambda: self.move_selected(-1))
        self.down_btn = QtWidgets.QPushButton("▼")
        self.down_btn.clicked.connect(lambda: self.move_selected(+1))
        self.clear_btn = QtWidgets.QPushButton("Clear finished")
        self.clear_btn.clicked.connect(self.clear_finished)
        for b in (self.pause_btn, self.abort_btn, self.requeue_btn, self.remove_btn, self.up_btn, self.down_btn, self.clear_btn):
            brow.addWidget(b)
        brow.addStretch(1)
        brow.addWidget(QtWidgets.QLabel("Jobs at once"))
        self.workers_spin = QtWidgets.QSpinBox()
        self.workers_spin.setRange(1, 8)
        mem = self.limits.get("memory_gb")
        self.workers_spin.setToolTip(f"How many jobs may run at the same time. Each job also runs its own parallel frames.\n"
                                     f"This machine: {self.limits['cpus']} cores, {mem:.0f} GB RAM" if mem else "How many jobs may run at the same time")
        self.workers_spin.valueChanged.connect(self._on_workers)
        brow.addWidget(self.workers_spin)
        qpanel.layout().addLayout(brow)
        self.queue_label = SectionLabel("Queue")
        qsection = self._section(self.queue_label, qpanel)

        # current job
        cpanel = Panel(layout="v")
        self.cur_title = QtWidgets.QLabel("No job selected")
        f = self.cur_title.font()
        f.setBold(True)
        self.cur_title.setFont(f)
        cpanel.layout().addWidget(self.cur_title)
        self.strip_host = QtWidgets.QWidget()
        self.strip = FlowLayout(self.strip_host, 0, 4, 4)
        cpanel.layout().addWidget(self.strip_host)
        self.cur_step_label = QtWidgets.QLabel("")
        cpanel.layout().addWidget(self.cur_step_label)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        cpanel.layout().addWidget(self.progress)
        kv = QtWidgets.QGridLayout()
        self.kv_labels: dict[str, ElidedLabel] = {}
        for r, key in enumerate(("setup", "output", "run", "process")):
            k = QtWidgets.QLabel(key)
            k.setProperty("role", "hint")
            v = ElidedLabel("—")
            kv.addWidget(k, r, 0)
            kv.addWidget(v, r, 1)
            self.kv_labels[key] = v
        kv.setColumnStretch(1, 1)
        cpanel.layout().addLayout(kv)
        crow = QtWidgets.QHBoxLayout()
        for text, slot in (("Job JSON", self.view_job), ("Log && traceback", self.show_details),
                           ("Open output folder", self.open_output_folder), ("Copy command", self.copy_command)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(lambda _=False, s=slot: s())
            crow.addWidget(b)
        crow.addStretch(1)
        cpanel.layout().addLayout(crow)
        hrow = QtWidgets.QHBoxLayout()
        self.lab_btn = QtWidgets.QPushButton("Open in Image Lab")
        self.lab_btn.clicked.connect(self.open_selected_in_imagelab)
        self.seq_btn = QtWidgets.QPushButton("Open in Sequence Builder")
        self.seq_btn.clicked.connect(self.open_selected_in_sequence)
        self.reduce_btn = QtWidgets.QPushButton("Reduce with corgidrp_gui")
        self.reduce_btn.clicked.connect(self.reduce_with_corgidrp)
        self.reduce_btn.setEnabled(shutil.which("corgidrp-gui") is not None)
        self.reduce_btn.setToolTip("Open the output folder in corgidrp_gui's Recipe Parser" if shutil.which("corgidrp-gui")
                                   else "corgidrp-gui is not on the PATH of this environment")
        for b in (self.lab_btn, self.seq_btn, self.reduce_btn):
            hrow.addWidget(b)
        hrow.addStretch(1)
        cpanel.layout().addLayout(hrow)
        self.frame_view = ImageView(with_list=False)
        self.frame_view.setMinimumHeight(220)
        cpanel.layout().addWidget(SectionLabel("Latest frame"))
        cpanel.layout().addWidget(self.frame_view, 1)
        self.cur_label = SectionLabel("Current job")
        csection = self._section(self.cur_label, cpanel)

        top = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(qsection)
        top.addWidget(csection)
        top.setSizes([760, 560])
        top.setChildrenCollapsible(False)

        lpanel = Panel(layout="v")
        lrow = QtWidgets.QHBoxLayout()
        self.follow_cb = QtWidgets.QCheckBox("Show only the selected job")
        self.follow_cb.toggled.connect(lambda _c: self._reload_log())
        lrow.addWidget(self.follow_cb)
        lrow.addStretch(1)
        clr = QtWidgets.QPushButton("Clear log view")
        clr.clicked.connect(self._clear_log_view)
        lrow.addWidget(clr)
        lpanel.layout().addLayout(lrow)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setProperty("role", "log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(20000)
        lpanel.layout().addWidget(self.log, 1)
        lsection = self._section(SectionLabel("Log"), lpanel)

        main = QtWidgets.QSplitter(Qt.Orientation.Vertical)
        main.addWidget(top)
        main.addWidget(lsection)
        main.setSizes([560, 260])
        main.setChildrenCollapsible(False)
        outer.addWidget(main, 1)
        self.status_chip = Chip("idle", "dim")
        self.statusBar().addPermanentWidget(self.status_chip)
        self.setAcceptDrops(True)

    @staticmethod
    def _section(label, body):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(label)
        lay.addWidget(body, 1)
        return w

    # ------------------------------------------------------------------ enqueue
    def enqueue(self, job: Job, source: str = "imagelab") -> SimJob:
        entry = self.queue.add(job, source)
        est = cost.estimate(job)
        self.log_line(f"queued {entry.name} from the {source}: {job.n_visits} visit(s), {job.total_frames} frame(s), about {est.pretty_time}")
        self.queue.save()
        self.model.refresh()
        self.pump()
        self._update_all()
        return entry

    def add_job_file_dialog(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Queue job files", self.backend.home(), "Job JSON (*.json)")
        for p in paths:
            self._add_file(p)

    def _add_file(self, p: str):
        try:
            entry = self.queue.add_file(p)
        except (OSError, ValueError, TypeError) as exc:
            self.log_line(f"skipped {p}: {exc}")
            return
        self.log_line(f"queued {entry.name} from {p}")
        self.queue.save()
        self.model.refresh()
        self.pump()
        self._update_all()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(u.toLocalFile().endswith(".json") for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for u in event.mimeData().urls():
            p = u.toLocalFile()
            if p.endswith(".json"):
                self._add_file(p)

    # ------------------------------------------------------------------ running
    def pump(self):
        while True:
            job = self.queue.next_runnable()
            if job is None:
                break
            self.launch(job)

    def runner_command(self, job: SimJob) -> list[str]:
        return self.backend.runner_command(job.job_path, None, None)

    def launch(self, job: SimJob):
        self.queue.prepare_launch(job)
        if job.job.output.save_fits and job.outputdir:
            self.backend.makedirs(job.outputdir)
        runner = RunnerProcess(self, self.backend)
        runner.line.connect(lambda ln, st, j=job: self._on_line(j, ln, st))
        runner.event.connect(lambda ev, j=job: self._on_event(j, ev))
        runner.finished.connect(lambda code, aborted, j=job: self._on_finished(j, code, aborted))
        self._runners[job.id] = runner
        cmd = runner.start(job.job_path, workdir=job.outputdir)
        job.parser = runner.parser
        job.pid = int(runner.proc.processId()) if runner.proc and runner.proc.processId() else None
        self.log_line(f"[{job.name}] $ {shlex.join(cmd)}", job)
        self.model.refresh_row(job)
        self._show_job(job)
        self._update_all()

    def _on_line(self, job: SimJob, line: str, stream: str):
        job.append_log(line)
        if line.startswith("corgisim_gui ") or stream == "stderr" or "Error" in line or "Warning" in line:
            self.log_line(f"[{job.name}] {line}", job)
        else:
            self._record(f"[{job.name}] {line}", job, raw=line)

    def _on_event(self, job: SimJob, ev):
        if ev.kind in ("visit", "frame", "finished", "error", "psf"):
            self.model.refresh_row(job)
        if ev.kind == "output" and job is self._shown_job:
            self._show_frame(ev.data["path"])
        elif ev.kind == "preview" and job is self._shown_job and not job.parser.outputs:
            self._show_frame(ev.data["path"])
        if job is self._shown_job:
            self._refresh_current()

    def _show_frame(self, path: str):
        if os.path.exists(path):
            self.frame_view.show_file(path)

    def _on_finished(self, job: SimJob, code: int, aborted: bool):
        runner = self._runners.pop(job.id, None)
        if runner is not None:
            job.parser = runner.parser
        self.queue.mark_finished(job, code, aborted=aborted)
        self.log_line(f"[{job.name}] {job.status}: {job.message} ({_fmt_elapsed(job.elapsed)})", job)
        self.queue.save()
        self.model.refresh()
        self.job_finished.emit(job)
        if job is self._shown_job:
            self._refresh_current()
        self.pump()
        self._update_all()

    def abort(self, job: SimJob):
        runner = self._runners.get(job.id)
        if runner is None or job.status != "running":
            return
        self.log_line(f"[{job.name}] aborting (SIGTERM)…", job)
        runner.abort()

    # ------------------------------------------------------------------ actions
    def selected_jobs(self) -> list[SimJob]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self.queue.jobs[r] for r in rows if r < len(self.queue.jobs)]

    def abort_selected(self):
        jobs = [j for j in self.selected_jobs() if j.status == "running"] or self.queue.running
        for j in jobs:
            self.abort(j)

    def requeue_selected(self):
        for j in self.selected_jobs():
            if j.status != "running":
                self.queue.requeue(j)
        self.queue.save()
        self.model.refresh()
        self.pump()
        self._update_all()

    def remove_selected(self):
        for j in self.selected_jobs():
            self.queue.remove(j)
        self.queue.save()
        self.model.refresh()
        self._update_all()

    def clear_finished(self):
        self.queue.clear_finished()
        self.queue.save()
        self.model.refresh()
        self._update_all()

    def move_selected(self, delta: int):
        jobs = self.selected_jobs()
        for j in (jobs if delta < 0 else reversed(jobs)):
            self.queue.move(j, delta)
        self.model.refresh()
        sm = self.table.selectionModel()
        sm.clearSelection()
        for j in jobs:
            r = self.queue.jobs.index(j)
            sm.select(self.model.index(r, 0), QtCore.QItemSelectionModel.SelectionFlag.Select | QtCore.QItemSelectionModel.SelectionFlag.Rows)

    def toggle_pause(self):
        self.pause_btn.toggle()

    def _on_pause_toggled(self, checked: bool):
        self.queue.paused = checked
        self.pause_btn.setText("Resume queue" if checked else "Pause queue")
        self.pause_act.setChecked(checked)
        self.log_line("queue paused; running jobs continue" if checked else "queue resumed")
        if not checked:
            self.pump()
        self._update_all()

    def _on_workers(self, n: int):
        self.queue.max_workers = n
        self.pump()

    def _target_job(self) -> SimJob | None:
        sel = self.selected_jobs()
        return sel[0] if sel else self._shown_job

    def open_selected_in_imagelab(self):
        job = self._target_job()
        if job is None:
            return
        if self.imagelab_handler is not None:
            self.imagelab_handler(job.job.copy())
        self.open_in_imagelab.emit(job.job.copy())

    def open_selected_in_sequence(self):
        job = self._target_job()
        if job is None:
            return
        if self.sequence_handler is not None:
            self.sequence_handler(job.job.copy())
        self.open_in_sequence.emit(job.job.copy())

    def reduce_with_corgidrp(self):
        job = self._target_job()
        exe = shutil.which("corgidrp-gui")
        if job is None or exe is None:
            return
        outdir = job.outputdir
        if not self.backend.isdir(outdir):
            return
        subprocess.Popen([exe, "--tool", "parser", "--files", outdir], start_new_session=True)
        self.log_line(f"[{job.name}] opened {outdir} in corgidrp_gui")

    def view_job(self):
        job = self._target_job()
        if job:
            JobPreviewDialog(job.job, self, title=f"{job.name} - job file").open()

    def show_details(self):
        job = self._target_job()
        if not job:
            return
        parts = [f"{job.name}  status: {job.status}  {job.message}", f"job: {job.job_path}",
                 f"command: {shlex.join(self.runner_command(job))}", ""]
        parts += job.log
        if job.parser.traceback and job.parser.traceback not in "\n".join(job.log):
            parts += ["", job.parser.traceback]
        text_dialog(self, f"{job.name} - log", "\n".join(parts))

    def open_output_folder(self):
        job = self._target_job()
        if job and self.backend.isdir(job.outputdir):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(job.outputdir))

    def copy_command(self):
        job = self._target_job()
        if job:
            QtWidgets.QApplication.clipboard().setText(shlex.join(self.runner_command(job)))
            self.statusBar().showMessage("Runner command copied; paste it in a terminal to reproduce this run", 6000)

    # ------------------------------------------------------------------ display
    def log_line(self, text: str, job: SimJob | None = None):
        stamp = _dt.datetime.now().strftime("%H:%M:%S")
        self._record(f"{stamp}  {text}", job)

    def _record(self, text: str, job: SimJob | None, raw: str | None = None):
        self._all_log.append(text)
        if len(self._all_log) > 20000:
            del self._all_log[:5000]
        if self.follow_cb.isChecked():
            if job is not None and job is self._shown_job:
                self.log.appendPlainText(raw if raw is not None else text)
        else:
            self.log.appendPlainText(text)

    def _clear_log_view(self):
        self.log.clear()
        if not self.follow_cb.isChecked():
            self._all_log.clear()

    def _on_queue_event(self, event: str, job: SimJob | None):
        if event in ("added", "removed", "cleared", "reordered"):
            self.model.refresh()
        elif job is not None:
            self.model.refresh_row(job)

    def _on_selection(self, *_):
        sel = self.selected_jobs()
        if sel:
            self._show_job(sel[0])
        self._reload_log()
        self._update_buttons()

    def _show_job(self, job: SimJob | None):
        if job is self._shown_job:
            self._refresh_current()
            return
        self._shown_job = job
        self._refresh_current()
        if job is not None:
            last = (job.parser.outputs or job.outputs or job.parser.previews or job.previews)
            if last:
                self._show_frame(last[-1])
            else:
                self.frame_view.clear()
        if self.follow_cb.isChecked():
            self._reload_log()

    def _reload_log(self):
        if self.follow_cb.isChecked():
            if self._shown_job is None:
                return
            self.log.setPlainText("\n".join(self._shown_job.log))
        else:
            self.log.setPlainText("\n".join(self._all_log))
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _refresh_current(self):
        job = self._shown_job
        self.strip.clear()
        if job is None:
            self.cur_title.setText("No job selected")
            self.cur_step_label.clear()
            self.progress.setValue(0)
            for v in self.kv_labels.values():
                v.setFullText("—")
            return
        self.cur_title.setText(f"{job.name}  —  {job.status}")
        p = job.parser
        done_ids = {v.index for v in p.visits if v.ended is not None}
        cur = p.current_visit.index if p.current_visit and p.current_visit.ended is None else None
        for i, v in enumerate(job.job.visits, start=1):
            state = "done" if (i in done_ids or job.status == "done") else ("running" if i == cur else "pending")
            text = v.label or f"visit {i}"
            vp = next((x for x in p.visits if x.index == i), None)
            if vp is not None and (state == "done" or vp.frames_done):
                text += f" {vp.frames_done}/{v.total_frames}"
            lab = step_label(text, state)
            if job.status in ("failed", "aborted") and i == cur:
                lab.setProperty("chip", "err")
            lab.setToolTip(f"roll {v.roll_angle_deg:g}°, {v.total_frames} frames, {job.job.visit_dpam(v)}")
            self.strip.addWidget(lab)
        theming.decorate_tree(self.strip_host)
        self.progress.setValue(int(100 * job.fraction()))
        self.cur_step_label.setText(p.status_text() if job.status == "running" else (job.message or ""))
        inst = job.job.instrument
        self.kv_labels["setup"].setFullText(f"{inst.cor_type} {inst.bandpass} {inst.dpam if inst.dpam != 'None' else 'imaging'} · {job.job.scene.host.label()}"
                                            + (f" · ref {job.job.reference_scene.host.name}" if job.job.reference_scene else ""))
        self.kv_labels["output"].setFullText(job.outputdir + (f" · {len(p.outputs or job.outputs)} files written" if (p.outputs or job.outputs) else ""))
        self.kv_labels["run"].setFullText(f"engine {job.job.run.engine} · {job.n_jobs} parallel frame(s) · seed {job.job.run.seed if job.job.run.seed is not None else 'random'}")
        proc = f"pid {job.pid}" if job.pid else "not started"
        if job.returncode is not None:
            proc = f"exit {job.returncode}"
        self.kv_labels["process"].setFullText(f"{proc} · {_fmt_elapsed(job.elapsed)}")

    def _tick(self):
        if self.queue.running:
            self.model.tick()
            if self._shown_job in self.queue.running:
                self._refresh_current()

    def _update_buttons(self):
        sel = self.selected_jobs()
        self.abort_btn.setEnabled(bool(self.queue.running))
        self.requeue_btn.setEnabled(any(j.status != "running" for j in sel))
        self.remove_btn.setEnabled(any(j.status != "running" for j in sel))
        self.up_btn.setEnabled(any(j.status == "waiting" for j in sel))
        self.down_btn.setEnabled(any(j.status == "waiting" for j in sel))
        self.clear_btn.setEnabled(any(not j.active for j in self.queue.jobs))
        has = bool(sel) or self._shown_job is not None
        self.lab_btn.setEnabled(has)
        self.seq_btn.setEnabled(has)

    def _update_all(self):
        c = self.queue.counts()
        running, waiting = c["running"], c["waiting"]
        self.setWindowTitle(f"Sim Console — running {running} · queued {waiting} · done {c['done']}" + (f" · failed {c['failed']}" if c["failed"] else ""))
        self.queue_label.setRawText(f"Queue · {len(self.queue.jobs)}")
        if running:
            self.status_chip.setText(f"running {running}")
            self.status_chip.set_kind("run")
        elif self.queue.paused:
            self.status_chip.setText("paused")
            self.status_chip.set_kind("warn")
        else:
            self.status_chip.setText("idle")
            self.status_chip.set_kind("dim")
        self._update_buttons()
        if self._shown_job is None and self.queue.running:
            self._show_job(self.queue.running[0])

    def theme_changed(self, theme):
        self.model.layoutChanged.emit()
        self.frame_view.theme_changed()
        self._refresh_current()

    def closeEvent(self, event):
        if self.queue.running:
            r = QtWidgets.QMessageBox.question(
                self, "Jobs are running", f"{len(self.queue.running)} job(s) are running. Abort them and close?",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
            if r != QtWidgets.QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            for j in list(self.queue.running):
                self.abort(j)
            for r_ in list(self._runners.values()):
                r_.wait(5000)
        self._timer.stop()
        self.queue.save()
        self.settings.setValue("console/geometry", self.saveGeometry())
        super().closeEvent(event)

    def wait_idle(self, timeout_ms: int = 600000) -> bool:
        """Spin the event loop until nothing runs and nothing is runnable (tests)."""
        deadline = QtCore.QDeadlineTimer(timeout_ms)
        app = QtWidgets.QApplication.instance()
        while (self.queue.running or self.queue.next_runnable()) and not deadline.hasExpired():
            app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
            QtCore.QThread.msleep(20)
        app.processEvents()
        return not self.queue.running
