"""The Setup View: what a job will simulate, drawn from the model alone (no corgisim import).

* :class:`OpticalTrainStrip` - DMs, SPAM, FPAM, LSAM, FSAM, CFAM, DPAM, EXCAM in a row (after
  Fig. 2 of Riggs et al. 2025), each cell showing the element corgisim records in the L1 header,
  a one-line detail, and a status colour when validation found something about it.
* :class:`FieldView` - the field of view from :func:`corgisim_gui.core.field.render_field`:
  disk and companions on the detector grid with the dark hole, field stop or slit, polarimetry
  beams, compass and λ/D scale drawn over it.
* :class:`SetupView` - both, plus a visit selector, display controls and a facts panel
  (mechanisms, sources, cost, validation issues).
* :class:`SetupWindow` - a standalone window (``python -m corgisim_gui.ui.setup_view job.json``).
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field as dc_field

import numpy as np
from qtpy import QtCore, QtGui, QtWidgets

from .. import theming
from ..core import build, cost, field as fieldmod, tables, validate
from ..core.model import Job
from . import glyphs, imaging
from .base import ThemedWindow
from .widgets.themed import Chip, Panel, SectionLabel

# which validation fields light up which cell
_CELL_FIELDS = {
    "DM": ("instrument.dm_solution", "instrument.satspots"),
    "SPAM": ("instrument.cor_type", "instrument.cgi_mode"),
    "FPAM": ("instrument.cor_type", "instrument.nd", "instrument.use_fpm"),
    "LSAM": ("instrument.cor_type", "instrument.use_lyot_stop"),
    "FSAM": ("instrument.slit", "instrument.use_field_stop"),
    "CFAM": ("instrument.bandpass",),
    "DPAM": ("instrument.dpam", "instrument.polaxis", "instrument.use_pupil_lens"),
    "EXCAM": ("detector.loc_x", "detector.loc_y", "instrument.output_dim", "detector.em_gain"),
}


@dataclass
class TrainCell:
    key: str
    title: str
    name: str
    detail: str
    status: str = "ok"            # ok | warn | err | off
    tooltip: str = ""
    extra: dict = dc_field(default_factory=dict)


def _colors(theme) -> dict:
    p = theme.palette
    dark = theming.is_dark(p.bg)
    return {
        "line": p.text if not dark else p.muted,
        "fill": theming.mix(p.surface, p.secondary, 0.35) if not dark else theming.mix(p.surface, p.secondary, 0.45),
        "dark": p.primary if not dark else theming.mix(p.bg, "#000000", 0.5),
        "text": p.text,
        "muted": p.muted,
        "accent": p.action,
        "ok": p.ok, "warn": p.warn, "err": p.err,
        "surface": p.surface, "bg": p.bg, "line_soft": p.line,
        "secondary": p.secondary,
    }


def train_cells(job: Job, issues: list[validate.Issue] | None = None) -> list[TrainCell]:
    """The eight cells for ``job`` (per visit, pass a job whose instrument.dpam is the visit's)."""
    inst = job.instrument
    c = inst.coronagraph
    f = inst.filter
    mech = inst.mechanisms()
    issues = issues or []
    status: dict[str, str] = {}
    tips: dict[str, list[str]] = {}
    for iss in issues:
        for cell, fields in _CELL_FIELDS.items():
            if any(iss.field.startswith(fl) for fl in fields):
                lvl = {"error": "err", "warn": "warn", "info": "ok"}[iss.level]
                if lvl == "err" or (lvl == "warn" and status.get(cell) != "err"):
                    status[cell] = lvl
                tips.setdefault(cell, []).append(f"[{iss.level}] {iss.message}")
    for n in mech.notes:
        tips.setdefault("FSAM" if "FSAM" in n else "FPAM", []).append(n)

    dm = tables.DM_SOLUTIONS.get(inst.dm_solution or "")
    dm_name = "off" if not inst.dm_solution else (dm.label if dm else inst.dm_solution)
    dm_detail = "no dark hole" if not inst.dm_solution else (f"NI {dm.contrast:.0e}" if dm and dm.contrast else "flat wavefront")
    if inst.satspots:
        dm_detail += f" + spots {inst.satspots.sep_lamD:g} λ/D"
    fs_r = tables.FIELD_STOP_RADIUS_MAS.get(mech.fsam)
    slit = tables.SLITS.get(inst.slit) if inst.cgi_mode == "spec" else None
    if mech.fsam == "OPEN" or not inst.use_field_stop:
        fs_detail = "open"
    elif slit is not None and mech.fsam == slit.name:
        fs_detail = f"slit {slit.width_mas:.0f}x{slit.height_mas:.0f} mas" + (f"\n{slit.rotation_deg:g}° rotated" if slit.rotation_deg else "")
    elif fs_r:
        fs_detail = f"r = {fs_r:.0f} mas\n{fs_r / max(inst.lam_over_d_mas, 1e-9):.1f} λ/D"
    else:
        fs_detail = ""
    iwa, owa = tables.dark_hole_lamD(inst.cor_type)
    cells = [
        TrainCell("DM", "DM1 / DM2", inst.dm_solution or "off", dm_detail,
                  status.get("DM", "ok" if inst.dm_solution else "off"), "\n".join(tips.get("DM", [])), {"active": bool(inst.dm_solution)}),
        TrainCell("SPAM", "SPAM", mech.spam, "shaped pupil" if mech.spam != "OPEN" else "flat mirror",
                  status.get("SPAM", "ok"), "\n".join(tips.get("SPAM", []))),
        TrainCell("FPAM", "FPAM", mech.fpam,
                  ("no mask" if not inst.use_fpm else (c.label.split(",")[0] if c else inst.cor_type)) + (f"\n{iwa:g}-{owa:g} λ/D" if inst.use_fpm and owa else ""),
                  status.get("FPAM", "ok" if inst.use_fpm or inst.nd else "off"), "\n".join(tips.get("FPAM", [])),
                  {"family": c.family if c else "", "rotated": bool(c and c.rotated)}),
        TrainCell("LSAM", "LSAM", mech.lsam, "Lyot stop" if inst.use_lyot_stop else "open",
                  status.get("LSAM", "ok" if inst.use_lyot_stop else "off"), "\n".join(tips.get("LSAM", []))),
        TrainCell("FSAM", "FSAM", mech.fsam, fs_detail, status.get("FSAM", "ok" if inst.use_field_stop else "off"),
                  "\n".join(tips.get("FSAM", [])), {"radius_mas": fs_r, "slit": slit if mech.fsam == (slit.name if slit else None) else None}),
        TrainCell("CFAM", "CFAM", mech.cfam, f"{f.center_nm:g} ± {f.fwhm_nm / 2:g} nm\n{f.nlam} wavelengths" if f else "?",
                  status.get("CFAM", "ok"), "\n".join(tips.get("CFAM", [])), {"filter": f}),
        TrainCell("DPAM", "DPAM", mech.dpam, tables.DPAM_LABELS.get(inst.dpam if not inst.use_pupil_lens else "PUPIL", "").replace(" (", "\n(").replace(", band", "\nband"),
                  status.get("DPAM", "ok"), "\n".join(tips.get("DPAM", []))),
        TrainCell("EXCAM", "EXCAM", f"{inst.output_dim} px" + (" x2" if inst.is_polarimetry else ""),
                  (f"full frame at {job.detector.loc_x}, {job.detector.loc_y}" if job.detector.full_frame else "sub-frame")
                  + f"\ngain {job.detector.em_gain:g}" + (", photon counting" if job.detector.photon_counting else ""),
                  status.get("EXCAM", "ok"), "\n".join(tips.get("EXCAM", [])), {"layout": fieldmod.detector_layout(job)}),
    ]
    return cells


class OpticalTrainStrip(QtWidgets.QWidget):
    """The row of mechanism cells. ``set_job`` recomputes; hovering a cell shows its notes."""

    cell_clicked = QtCore.Signal(str)

    CELL_W, CELL_H, GAP = 124, 160, 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cells: list[TrainCell] = []
        self._rects: list[QtCore.QRectF] = []
        self._hover = -1
        self.setMouseTracking(True)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(self.CELL_H + 8)

    def sizeHint(self):
        return QtCore.QSize(8 * self.CELL_W + 7 * self.GAP + 16, self.CELL_H + 8)

    @property
    def cells(self) -> list[TrainCell]:
        return list(self._cells)

    def set_job(self, job: Job, issues: list[validate.Issue] | None = None) -> None:
        self._cells = train_cells(job, issues)
        self.update()

    def cell_at(self, pos) -> TrainCell | None:
        for cell, r in zip(self._cells, self._rects):
            if r.contains(QtCore.QPointF(pos)):
                return cell
        return None

    def mouseMoveEvent(self, event):
        pos = event.position() if hasattr(event, "position") else event.pos()
        idx = -1
        for i, r in enumerate(self._rects):
            if r.contains(QtCore.QPointF(pos)):
                idx = i
        if idx != self._hover:
            self._hover = idx
            cell = self._cells[idx] if idx >= 0 else None
            self.setToolTip((f"{cell.title}: {cell.name}\n{cell.detail}" + (f"\n\n{cell.tooltip}" if cell.tooltip else "")) if cell else "")
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()

    def mousePressEvent(self, event):
        cell = self.cell_at(event.position() if hasattr(event, "position") else event.pos())
        if cell:
            self.cell_clicked.emit(cell.key)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        theme = theming.current_theme()
        col = _colors(theme)
        fonts = theming.theme_fonts(theme)
        n = len(self._cells)
        self._rects = []
        if not n:
            return
        avail = self.width() - 16
        cw = min(self.CELL_W, max(70, (avail - (n - 1) * self.GAP) // n))
        total = n * cw + (n - 1) * self.GAP
        x = (self.width() - total) / 2
        y = 4
        glyph_h = cw * 0.72
        title_font = QtGui.QFont(fonts["ui"], max(8, theme.type.size - 2))
        title_font.setWeight(QtGui.QFont.Weight.DemiBold)
        name_font = QtGui.QFont(fonts["data"], max(8, theme.type.size - 1))
        name_font.setWeight(QtGui.QFont.Weight.Bold)
        detail_font = QtGui.QFont(fonts["ui"], max(7, theme.type.size - 3))
        for i, cell in enumerate(self._cells):
            rect = QtCore.QRectF(x, y, cw, self.CELL_H)
            self._rects.append(rect)
            # background
            bg = QtGui.QColor(col["surface"])
            if cell.status in ("warn", "err"):
                bg = QtGui.QColor(theming.mix(col["surface"], col[cell.status], 0.18))
            elif i == self._hover:
                bg = QtGui.QColor(theming.mix(col["surface"], col["secondary"], 0.15))
            p.setPen(QtGui.QPen(QtGui.QColor(col[cell.status] if cell.status in ("warn", "err") else col["line_soft"]), 1.5 if cell.status in ("warn", "err") else 1))
            p.setBrush(bg)
            p.drawRoundedRect(rect, theme.shape.radius, theme.shape.radius)
            # title
            p.setPen(QtGui.QColor(col["muted"]))
            p.setFont(title_font)
            p.drawText(QtCore.QRectF(rect.left(), rect.top() + 4, cw, 16), QtCore.Qt.AlignmentFlag.AlignCenter, theming.label_text(cell.title, theme) if theme.type.label_case != "upper" else cell.title.upper())
            # glyph
            grect = QtCore.QRectF(rect.left() + (cw - glyph_h) / 2, rect.top() + 22, glyph_h, glyph_h)
            gcol = dict(col)
            if cell.status == "off":
                gcol["fill"] = theming.mix(col["surface"], col["line_soft"], 0.5)
                gcol["accent"] = col["muted"]
            self._paint_glyph(p, grect, cell, gcol)
            # name
            p.setPen(QtGui.QColor(col["text"]))
            nf = QtGui.QFont(name_font)
            while nf.pointSize() > 7 and QtGui.QFontMetrics(nf).horizontalAdvance(cell.name) > cw - 8:
                nf.setPointSize(nf.pointSize() - 1)
            p.setFont(nf)
            fm = QtGui.QFontMetrics(nf)
            name = fm.elidedText(cell.name, QtCore.Qt.TextElideMode.ElideMiddle, int(cw - 6))
            p.drawText(QtCore.QRectF(rect.left(), rect.top() + 24 + glyph_h, cw, 18), QtCore.Qt.AlignmentFlag.AlignCenter, name)
            # detail (up to two lines)
            p.setPen(QtGui.QColor(col["muted"]))
            p.setFont(detail_font)
            fm = QtGui.QFontMetrics(detail_font)
            for li, line in enumerate(cell.detail.split("\n")[:2]):
                detail = fm.elidedText(line, QtCore.Qt.TextElideMode.ElideRight, int(cw - 6))
                p.drawText(QtCore.QRectF(rect.left(), rect.top() + 42 + glyph_h + li * 13, cw, 14), QtCore.Qt.AlignmentFlag.AlignCenter, detail)
            # status dot
            if cell.status in ("warn", "err"):
                p.setPen(QtCore.Qt.PenStyle.NoPen)
                p.setBrush(QtGui.QColor(col[cell.status]))
                p.drawEllipse(QtCore.QRectF(rect.right() - 12, rect.top() + 6, 7, 7))
            if i < n - 1:
                glyphs.paint_arrow(p, rect.right() + 4, rect.right() + self.GAP - 4, rect.top() + 22 + glyph_h / 2, col)
            x += cw + self.GAP
        p.end()

    @staticmethod
    def _paint_glyph(p, rect, cell: TrainCell, col: dict) -> None:
        k = cell.key
        if k == "DM":
            glyphs.paint_dm(p, rect, col, active=cell.extra.get("active", True))
        elif k == "SPAM":
            glyphs.paint_spam(p, rect, cell.name, col)
        elif k == "FPAM":
            glyphs.paint_fpam(p, rect, cell.name, cell.extra.get("family", ""), cell.extra.get("rotated", False), col)
        elif k == "LSAM":
            glyphs.paint_lsam(p, rect, cell.name, col)
        elif k == "FSAM":
            glyphs.paint_fsam(p, rect, cell.name, col, cell.extra.get("radius_mas"), cell.extra.get("slit"))
        elif k == "CFAM":
            glyphs.paint_cfam(p, rect, cell.extra.get("filter"), col)
        elif k == "DPAM":
            glyphs.paint_dpam(p, rect, cell.name, col)
        elif k == "EXCAM":
            lay = cell.extra.get("layout", {})
            glyphs.paint_excam(p, rect, col, lay.get("boxes"), lay.get("science_area", 1024))


# ----------------------------------------------------------------------------- field of view
class FieldView(QtWidgets.QWidget):
    """Paints a :class:`FieldPreview` with its overlays; hover reports the source under the cursor."""

    hovered = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._preview: fieldmod.FieldPreview | None = None
        self._qimage: QtGui.QImage | None = None
        self._stretch = "asinh"
        self._cmap = "inferno"
        self._show = {"dark_hole": True, "field_stop": True, "slit": True, "beam": True, "source": True,
                      "host": True, "compass": True, "scale": True, "rings": False, "labels": True}
        self._geom = (0.0, 0.0, 1.0)     # ox, oy, scale (widget px per image px)
        self._fit = "auto"               # auto | image | dark_hole | field_stop | sources, or a radius in pixels
        self._zoom = 1.0                 # extra user zoom (mouse wheel)
        self.setMouseTracking(True)
        self.setMinimumSize(240, 240)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)

    # -- API
    @property
    def preview(self):
        return self._preview

    def set_preview(self, preview: fieldmod.FieldPreview | None) -> None:
        self._preview = preview
        self._rebuild_image()
        self.update()

    def set_display(self, stretch: str | None = None, cmap: str | None = None) -> None:
        if stretch:
            self._stretch = stretch
        if cmap:
            self._cmap = cmap
        self._rebuild_image()
        self.update()

    def set_overlay(self, role: str, on: bool) -> None:
        self._show[role] = bool(on)
        self.update()

    def set_fit(self, mode: str) -> None:
        """What fills the view: 'auto', 'image', 'dark_hole', 'field_stop' or 'sources'."""
        self._fit = mode
        self._zoom = 1.0
        self.update()

    def fit_radius_pix(self) -> float | None:
        """Half-width of the region shown, in image pixels (None = whole image)."""
        pv = self._preview
        if pv is None:
            return None
        n = pv.size_pix
        full = n / 2.0
        radii = {}
        for o in pv.overlays:
            if o.role == "dark_hole":
                radii["dark_hole"] = o.data["r_out"]
            elif o.role == "field_stop":
                radii["field_stop"] = o.data["r"]
            elif o.role == "slit":
                cx, cy = pv.centre
                radii["slit"] = max(radii.get("slit", 0.0), math.hypot(o.data["x"] - cx, o.data["y"] - cy) + max(o.data["w"], o.data["h"]) / 2)
            elif o.role == "source":
                cx, cy = pv.centre
                radii["sources"] = max(radii.get("sources", 0.0), math.hypot(o.data["x"] - cx, o.data["y"] - cy) + o.data.get("r", 2))
        mode = self._fit
        if mode == "image":
            r = full
        elif mode in radii:
            r = radii[mode] * 1.25
        elif mode == "auto":
            cands = [radii[k] for k in ("dark_hole", "sources", "slit") if k in radii]
            if "field_stop" in radii and radii["field_stop"] < full:
                cands.append(radii["field_stop"])
            r = (max(cands) * 1.25) if cands else full
        else:
            r = full
        r = max(5.0, min(full * 1.0, r)) / self._zoom
        return r

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta:
            self._zoom = max(0.25, min(20.0, self._zoom * (1.15 if delta > 0 else 1 / 1.15)))
            self.update()

    def overlays_shown(self) -> dict[str, bool]:
        return dict(self._show)

    def _rebuild_image(self) -> None:
        if self._preview is None:
            self._qimage = None
            return
        img = self._preview.image
        if self._cmap == "theme":
            table = imaging.theme_lut(theming.current_theme())
        else:
            table = imaging.lut(self._cmap)
        if not np.any(img):
            self._qimage = imaging.to_qimage(np.zeros_like(img), table)
        else:
            self._qimage = imaging.render(img, self._stretch, table)

    # -- geometry
    def _layout(self) -> tuple[float, float, float]:
        if self._preview is None:
            return (0.0, 0.0, 1.0)
        n = self._preview.size_pix
        r = self.fit_radius_pix() or n / 2.0
        s = min(self.width(), self.height()) / (2.0 * r)
        ox = self.width() / 2 - (n / 2.0) * s
        oy = self.height() / 2 - (n / 2.0) * s
        self._geom = (ox, oy, s)
        return self._geom

    def to_widget(self, x: float, y: float) -> QtCore.QPointF:
        """Image pixel coordinates (origin lower) to widget coordinates."""
        ox, oy, s = self._geom
        n = self._preview.size_pix if self._preview else 1
        return QtCore.QPointF(ox + (x + 0.5) * s, oy + (n - (y + 0.5)) * s)

    def to_image(self, pos) -> tuple[float, float]:
        ox, oy, s = self._geom
        n = self._preview.size_pix if self._preview else 1
        return ((pos.x() - ox) / s - 0.5, n - (pos.y() - oy) / s - 0.5)

    def overlay_at(self, pos) -> fieldmod.Overlay | None:
        """The source (or host) overlay under a widget position, if any."""
        if self._preview is None:
            return None
        ox, oy, s = self._geom
        best, best_d = None, 1e9
        for o in self._preview.overlays:
            if o.role not in ("source", "host"):
                continue
            w = self.to_widget(o.data["x"], o.data["y"])
            d = math.hypot(w.x() - pos.x(), w.y() - pos.y())
            if d < max(10.0, o.data.get("r", 2) * s) and d < best_d:
                best, best_d = o, d
        return best

    def mouseMoveEvent(self, event):
        pos = event.position() if hasattr(event, "position") else QtCore.QPointF(event.pos())
        o = self.overlay_at(pos)
        if o is not None:
            if o.role == "source":
                d = o.data
                text = f"{o.label}: V={d['vmag']:g}, {d['sep_mas']:.0f} mas = {d['sep_lamD']:.1f} λ/D, PA {d['pa_deg']:.0f}°"
            else:
                text = f"host star: {o.label}"
        elif self._preview is not None:
            x, y = self.to_image(pos)
            pv = self._preview
            cx, cy = pv.centre
            dx, dy = (x - cx) * pv.pixel_scale_mas, (y - cy) * pv.pixel_scale_mas
            r = math.hypot(dx, dy)
            text = f"({x:.0f}, {y:.0f}) px   {r:.0f} mas = {r / (pv.lam_over_d_pix * pv.pixel_scale_mas):.1f} λ/D"
        else:
            text = ""
        self.setToolTip(text)
        self.hovered.emit(text)

    # -- painting
    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        theme = theming.current_theme()
        col = _colors(theme)
        p.fillRect(self.rect(), QtGui.QColor(col["dark"] if theming.is_dark(theme.palette.bg) else "#0b1020"))
        if self._preview is None or self._qimage is None:
            p.setPen(QtGui.QColor("#9aa6b8"))
            p.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "no setup")
            p.end()
            return
        ox, oy, s = self._layout()
        n = self._preview.size_pix
        target = QtCore.QRectF(ox, oy, n * s, n * s)
        p.drawImage(target, self._qimage)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 50), 1))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawRect(target)
        self._paint_overlays(p, theme, col)
        p.end()

    def _paint_overlays(self, p: QtGui.QPainter, theme, col: dict) -> None:
        pv = self._preview
        ox, oy, s = self._geom
        fonts = theming.theme_fonts(theme)
        small = QtGui.QFont(fonts["ui"], max(7, theme.type.size - 3))
        p.setFont(small)
        c_hole = QtGui.QColor(col["accent"])
        c_stop = QtGui.QColor(col["secondary"])
        c_beam = QtGui.QColor(col["warn"])
        c_src = QtGui.QColor(col["ok"])
        white = QtGui.QColor("#f2f4f8")
        if self._show["rings"]:
            pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 60), 1, QtCore.Qt.PenStyle.DotLine)
            p.setPen(pen)
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            cx, cy = pv.centre
            c = self.to_widget(cx, cy)
            step = max(1, int(math.ceil(28.0 / max(pv.lam_over_d_pix * s, 1e-6))))
            step = step if step <= 2 else int(math.ceil(step / 5.0) * 5)
            k = step
            limit = pv.size_pix / 2 * s
            while k * pv.lam_over_d_pix * s < min(limit, max(self.width(), self.height())):
                r = k * pv.lam_over_d_pix * s
                p.drawEllipse(c, r, r)
                p.drawText(QtCore.QPointF(c.x() + r * 0.707 + 2, c.y() - r * 0.707 - 2), f"{k} λ/D")
                k += step
        for o in pv.overlays:
            if not self._show.get(o.role, True):
                continue
            d = o.data
            if o.kind == "annulus":
                c = self.to_widget(d["x"], d["y"])
                pen = QtGui.QPen(c_hole, 1.5, QtCore.Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                az = d.get("azimuth_deg", 360.0)
                if az >= 360:
                    for r in (d["r_in"] * s, d["r_out"] * s):
                        p.drawEllipse(c, r, r)
                else:
                    rot = 90 if d.get("rotated") else 0
                    for a0 in (-az / 4 + rot, 180 - az / 4 + rot):
                        path = glyphs._wedge_path(c, d["r_in"] * s, d["r_out"] * s, a0, az / 2)
                        p.drawPath(path)
                if self._show["labels"]:
                    p.setPen(c_hole)
                    p.drawText(QtCore.QPointF(c.x() + d["r_out"] * s * 0.707 + 3, c.y() + d["r_out"] * s * 0.707 + 10), o.label)
            elif o.kind == "circle":
                c = self.to_widget(d["x"], d["y"])
                p.setPen(QtGui.QPen(c_stop, 1.5))
                p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, d["r"] * s, d["r"] * s)
                if self._show["labels"]:
                    p.drawText(QtCore.QPointF(c.x() - d["r"] * s * 0.707 - 2, c.y() + d["r"] * s * 0.707 + 12), o.label)
            elif o.kind == "rect":
                c = self.to_widget(d["x"], d["y"])
                p.save()
                p.translate(c)
                p.rotate(-d.get("angle_deg", 0.0))
                p.setPen(QtGui.QPen(c_beam if o.role == "beam" else c_stop, 1.5, QtCore.Qt.PenStyle.DashLine if o.role == "beam" else QtCore.Qt.PenStyle.SolidLine))
                p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                p.drawRect(QtCore.QRectF(-d["w"] * s / 2, -d["h"] * s / 2, d["w"] * s, d["h"] * s))
                if self._show["labels"]:
                    p.drawText(QtCore.QPointF(-d["w"] * s / 2, -d["h"] * s / 2 - 3), o.label)
                p.restore()
            elif o.kind == "point":
                c = self.to_widget(d["x"], d["y"])
                if o.role == "host":
                    p.setPen(QtGui.QPen(white, 1.2))
                    r = max(4.0, d.get("r", 1) * s)
                    p.drawLine(QtCore.QPointF(c.x() - r, c.y()), QtCore.QPointF(c.x() + r, c.y()))
                    p.drawLine(QtCore.QPointF(c.x(), c.y() - r), QtCore.QPointF(c.x(), c.y() + r))
                else:
                    r = max(6.0, d.get("r", 2) * s)
                    p.setPen(QtGui.QPen(c_src, 1.5))
                    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                    p.drawEllipse(c, r, r)
                    if self._show["labels"]:
                        p.drawText(QtCore.QPointF(c.x() + r + 2, c.y() - r), o.label)
            elif o.kind == "arrow":
                self._paint_compass(p, d, white, theme)
            elif o.kind == "text" and o.role == "scale":
                self._paint_scale(p, d, white)

    def _paint_compass(self, p, d, color, theme) -> None:
        pv = self._preview
        ox, oy, s = self._geom
        L = 28.0
        base = QtCore.QPointF(14 + L, self.height() - 14 - L)
        p.setPen(QtGui.QPen(color, 1.3))
        for dra, ddec, label in ((0.0, 1.0, "N"), (1.0, 0.0, "E")):
            ex, ey = fieldmod.skycoord_to_excam(dra, ddec, pv.roll_deg)
            tip = QtCore.QPointF(base.x() + ex * L, base.y() - ey * L)
            p.drawLine(base, tip)
            p.drawText(QtCore.QPointF(tip.x() + (ex * 8) - 4, tip.y() - (ey * 8) + 4), label)

    def _paint_scale(self, p, d, color) -> None:
        pv = self._preview
        ox, oy, s = self._geom
        k = 5
        L = d["lam_over_d_pix"] * s * k
        while L > self.width() * 0.4 and k > 1:
            k -= 1 if k <= 2 else 1
            L = d["lam_over_d_pix"] * s * k
        while L < 30 and k < 50:
            k += 5
            L = d["lam_over_d_pix"] * s * k
        x1 = self.width() - 14
        y = self.height() - 14
        p.setPen(QtGui.QPen(color, 1.5))
        p.drawLine(QtCore.QPointF(x1 - L, y), QtCore.QPointF(x1, y))
        p.drawText(QtCore.QRectF(x1 - 260, y - 17, 260, 14), QtCore.Qt.AlignmentFlag.AlignRight, f"{k} λ/D = {k * d['lam_over_d_mas']:.0f} mas")


# ----------------------------------------------------------------------------- composite
class SetupView(QtWidgets.QWidget):
    """Strip + field + facts for one job. Call :meth:`set_job`; ``visit_changed`` reports the selected visit."""

    visit_changed = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._job: Job | None = None
        self._issues: list[validate.Issue] = []
        self._visit = 0
        self._build()

    # -- construction
    def _build(self) -> None:
        theme = theming.current_theme()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.density.gap)

        self.strip = OpticalTrainStrip()
        strip_panel = Panel()
        strip_panel.layout().addWidget(self.strip)
        lay.addWidget(_section("Optical train", strip_panel))

        bottom = QtWidgets.QHBoxLayout()
        bottom.setSpacing(theme.density.gap)
        lay.addLayout(bottom, 1)

        # field with its control row
        field_panel = Panel()
        ctl = QtWidgets.QHBoxLayout()
        ctl.setSpacing(6)
        self.visit_combo = QtWidgets.QComboBox()
        self.visit_combo.currentIndexChanged.connect(self._on_visit)
        self.stretch_combo = QtWidgets.QComboBox()
        self.stretch_combo.addItems(list(imaging.STRETCHES))
        self.stretch_combo.currentTextChanged.connect(lambda t: self.field.set_display(stretch=t))
        self.cmap_combo = QtWidgets.QComboBox()
        self.cmap_combo.addItems([*imaging.COLORMAPS, "theme"])
        self.cmap_combo.currentTextChanged.connect(lambda t: self.field.set_display(cmap=t))
        ctl.addWidget(QtWidgets.QLabel("Visit"))
        ctl.addWidget(self.visit_combo, 1)
        ctl.addWidget(QtWidgets.QLabel("Stretch"))
        ctl.addWidget(self.stretch_combo)
        ctl.addWidget(QtWidgets.QLabel("Colours"))
        ctl.addWidget(self.cmap_combo)
        self.fit_combo = QtWidgets.QComboBox()
        for key, label in (("auto", "auto"), ("dark_hole", "dark hole"), ("field_stop", "field stop"), ("sources", "sources"), ("image", "whole image")):
            self.fit_combo.addItem(label, key)
        self.fit_combo.currentIndexChanged.connect(lambda i: self.field.set_fit(self.fit_combo.itemData(i)))
        ctl.addWidget(QtWidgets.QLabel("Fit"))
        ctl.addWidget(self.fit_combo)
        field_panel.layout().addLayout(ctl)
        self.field = FieldView()
        field_panel.layout().addWidget(self.field, 1)
        toggles = QtWidgets.QHBoxLayout()
        toggles.setSpacing(8)
        self.toggles: dict[str, QtWidgets.QCheckBox] = {}
        for role, label in (("dark_hole", "dark hole"), ("field_stop", "field stop"), ("slit", "slit"), ("beam", "pol. beams"),
                            ("source", "sources"), ("compass", "compass"), ("rings", "λ/D rings"), ("labels", "labels")):
            cb = QtWidgets.QCheckBox(label)
            cb.setChecked(self.field.overlays_shown().get(role, True))
            cb.toggled.connect(lambda on, r=role: self.field.set_overlay(r, on))
            self.toggles[role] = cb
            toggles.addWidget(cb)
        toggles.addStretch(1)
        field_panel.layout().addLayout(toggles)
        self.hover_label = QtWidgets.QLabel("")
        self.hover_label.setProperty("role", "hint")
        self.field.hovered.connect(self.hover_label.setText)
        field_panel.layout().addWidget(self.hover_label)
        bottom.addWidget(_section("Field of view", field_panel), 3)

        # facts
        facts_panel = Panel()
        self.facts = QtWidgets.QFormLayout()
        self.facts.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.facts.setHorizontalSpacing(10)
        self.facts.setVerticalSpacing(3)
        facts_panel.layout().addLayout(self.facts)
        self.sources_table = QtWidgets.QTableWidget(0, 5)
        self.sources_table.setHorizontalHeaderLabels(["source", "V", "sep (mas)", "λ/D", "PA (°)"])
        self.sources_table.horizontalHeader().setStretchLastSection(True)
        self.sources_table.verticalHeader().setVisible(False)
        self.sources_table.setEditTriggers(QtWidgets.QTableWidget.EditTrigger.NoEditTriggers)
        self.sources_table.setMaximumHeight(140)
        facts_panel.layout().addWidget(SectionLabel("Off-axis sources"))
        facts_panel.layout().addWidget(self.sources_table)
        facts_panel.layout().addWidget(SectionLabel("Cost"))
        self.cost_label = QtWidgets.QLabel("")
        self.cost_label.setWordWrap(True)
        facts_panel.layout().addWidget(self.cost_label)
        facts_panel.layout().addWidget(SectionLabel("Checks"))
        self.issues_box = QtWidgets.QVBoxLayout()
        self.issues_box.setSpacing(3)
        facts_panel.layout().addLayout(self.issues_box)
        facts_panel.layout().addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(facts_panel)
        scroll.setMinimumWidth(300)
        bottom.addWidget(_section("Setup", scroll), 2)

    # -- API
    @property
    def job(self) -> Job | None:
        return self._job

    @property
    def issues(self) -> list[validate.Issue]:
        return list(self._issues)

    @property
    def visit_index(self) -> int:
        return self._visit

    def set_job(self, job: Job | None, visit: int | None = None) -> None:
        self._job = job
        self._issues = validate.validate_job(job) if job is not None else []
        self.visit_combo.blockSignals(True)
        self.visit_combo.clear()
        if job is not None:
            for i, v in enumerate(job.visits):
                dp = job.visit_dpam(v)
                self.visit_combo.addItem(f"{i + 1}: {v.label or 'visit'}  roll {v.roll_angle_deg:g}°  {'imaging' if dp == 'None' else dp}" + ("  ref" if v.is_reference else ""))
            self._visit = min(visit if visit is not None else self._visit, max(0, len(job.visits) - 1))
            self.visit_combo.setCurrentIndex(self._visit)
        self.visit_combo.blockSignals(False)
        self.refresh()

    def refresh(self) -> None:
        job = self._job
        if job is None:
            self.strip.set_job(Job(), [])
            self.field.set_preview(None)
            return
        v = job.visits[self._visit] if job.visits else None
        # per-visit instrument view: DPAM and roll from the visit
        view = job.copy()
        if v is not None:
            view.instrument.dpam = job.visit_dpam(v)
            view.instrument.roll_angle_deg = v.roll_angle_deg
            view.detector.em_gain = job.visit_gain(v)
            view.detector.photon_counting = job.visit_photon_counting(v)
        self.strip.set_job(view, self._issues)
        scene = job.reference_scene if (v is not None and v.is_reference and job.reference_scene is not None) else job.scene
        preview = fieldmod.render_field(view, roll_deg=v.roll_angle_deg if v else None, scene=scene)
        self.field.set_preview(preview)
        self._fill_facts(view, scene, preview)

    def _on_visit(self, index: int) -> None:
        if index < 0:
            return
        self._visit = index
        self.refresh()
        self.visit_changed.emit(index)

    def _fill_facts(self, job: Job, scene, preview) -> None:
        while self.facts.rowCount():
            self.facts.removeRow(0)
        inst = job.instrument
        d = build.describe(job)
        mech = inst.mechanisms()
        rows = [
            ("mode", f"{inst.cgi_mode}, {d['coronagraph_label']}"),
            ("filter", f"{inst.bandpass}: {d['filter_center_nm']:g} nm, FWHM {d['filter_fwhm_nm']:g} nm, {d['nlam']} wavelengths" if d["nlam"] else inst.bandpass),
            ("λ/D", f"{d['lam_over_d_mas']:g} mas = {preview.lam_over_d_pix:.2f} px"),
            ("dark hole", f"{tables.dark_hole_lamD(inst.cor_type)[0]:g}-{tables.dark_hole_lamD(inst.cor_type)[1]:g} λ/D"),
            ("mechanisms", "  ".join(f"{k} {v}" for k, v in mech.as_dict().items())),
            ("DM", inst.dm_solution or "off"),
            ("roll", f"{inst.roll_angle_deg:g}°"),
            ("host", scene.host.label() + (" (reference)" if scene.ref_flag else "")),
            ("disk", os.path.basename(scene.disk.path) if scene.disk and scene.disk.path else "none"),
            ("detector", f"gain {job.detector.em_gain:g}" + (", photon counting" if job.detector.photon_counting else "")
                         + (f", full frame at ({job.detector.loc_x}, {job.detector.loc_y})" if job.detector.full_frame else ", sub-frame")),
            ("visits", f"{d['n_visits']} visits, {d['total_frames']} frames, {cost.pretty_seconds(d['total_exposure_s'])} exposure"),
        ]
        for k, v in rows:
            lab = QtWidgets.QLabel(v)
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            self.facts.addRow(k, lab)
        # sources
        self.sources_table.setRowCount(len(scene.point_sources))
        lamd = inst.lam_over_d_mas or 1.0
        for i, s in enumerate(scene.point_sources):
            vals = [s.label or f"source {i + 1}", f"{s.vmag:g}", f"{s.separation_mas:.0f}", f"{s.separation_mas / lamd:.1f}", f"{s.pa_deg:.1f}"]
            for j, t in enumerate(vals):
                self.sources_table.setItem(i, j, QtWidgets.QTableWidgetItem(t))
        self.sources_table.resizeColumnsToContents()
        # cost
        est = cost.estimate(self._job)
        self.cost_label.setText(f"{est.psf_states} PSF states, {est.propagations} propagations, {est.frames + est.satspot_frames} frames; "
                                f"about {est.pretty_time} on this machine, {est.memory_gb:.0f} GB with {self._job.run.n_jobs} parallel frame(s)."
                                + ("\n" + "\n".join(est.notes) if est.notes else ""))
        # issues
        while self.issues_box.count():
            item = self.issues_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._issues:
            self.issues_box.addWidget(Chip("no problems found", "ok"))
        for iss in self._issues[:12]:
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(Chip(iss.level, {"error": "err", "warn": "warn", "info": "dim"}[iss.level]))
            lab = QtWidgets.QLabel(f"{iss.field}: {iss.message}")
            lab.setWordWrap(True)
            row.addWidget(lab, 1)
            self.issues_box.addLayout(row)
        if len(self._issues) > 12:
            self.issues_box.addWidget(QtWidgets.QLabel(f"... and {len(self._issues) - 12} more"))

    def theme_changed(self, theme=None) -> None:
        self.field.set_display()
        self.strip.update()


def _section(title: str, body: QtWidgets.QWidget) -> QtWidgets.QWidget:
    w = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(SectionLabel(title))
    lay.addWidget(body, 1)
    return w


# ----------------------------------------------------------------------------- window
class SetupWindow(ThemedWindow):
    """Standalone Setup View: open a job JSON or a CPGS XML and look at it."""

    def __init__(self, parent=None):
        super().__init__(parent, title="corgisim GUI - Setup View")
        self.view = SetupView()
        self.setCentralWidget(self.view)
        self._build_menus()
        self.resize(1280, 820)

    def _build_menus(self) -> None:
        m = self.add_menu("&File")
        m.addAction("Open job or CPGS file...", self.open_file_dialog, QtGui.QKeySequence.StandardKey.Open)
        m.addAction("Example: single image", lambda: self.load_example("image"))
        m.addAction("Example: roll sequence", lambda: self.load_example("rolls"))
        m.addAction("Example: polarimetry pair", lambda: self.load_example("pol"))
        m.addAction("Example: spectroscopy", lambda: self.load_example("spec"))
        m.addSeparator()
        m.addAction("Quit", self.close, QtGui.QKeySequence.StandardKey.Quit)
        self.add_theme_menu()
        self.add_help_menu()

    def open_file_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open job or CPGS file", "", "Jobs and CPGS (*.json *.xml);;All files (*)")
        if path:
            self.load_path(path)

    def load_path(self, path: str) -> None:
        if path.lower().endswith(".xml"):
            from ..core.cpgs import load_job_from_cpgs
            job = load_job_from_cpgs(path)
        else:
            job = Job.load(path)
        self.view.set_job(job)
        self.setWindowTitle(f"corgisim GUI - Setup View - {os.path.basename(path)}")

    def load_example(self, kind: str) -> None:
        from ..core import model
        if kind == "rolls":
            job = model.roll_sequence_job()
            job.scene.point_sources.append(model.PointSource.from_polar(22.0, 350.0, 60.0, label="b"))
        elif kind == "pol":
            job = model.polarimetry_pair_job()
            job.scene.point_sources.append(model.PointSource.from_polar(21.0, 300.0, 200.0, label="b"))
        elif kind == "spec":
            job = model.single_image_job("spec")
            job.instrument = model.InstrumentSpec(cgi_mode="spec", cor_type="spc-spec_band3", bandpass="3F", dpam="PRISM3",
                                                  slit="R1C2", dm_solution="spc-spec_ni_2e-8")
            job.scene.point_sources.append(model.PointSource.from_polar(18.0, 270.0, 90.0, label="b"))
        else:
            job = model.single_image_job()
            job.scene.point_sources.append(model.PointSource.from_polar(20.0, 300.0, 45.0, label="b"))
            job.scene.point_sources.append(model.PointSource.from_polar(22.5, 480.0, 200.0, label="c"))
        job.output.output_dir = os.path.expanduser("~/corgisim_out")
        self.view.set_job(job)

    def theme_changed(self, theme) -> None:
        self.view.theme_changed(theme)


def main(argv=None) -> int:
    from ..app import make_app
    argv = sys.argv[1:] if argv is None else argv
    app = make_app([])
    w = SetupWindow()
    if argv:
        w.load_path(argv[0])
    else:
        w.load_example("image")
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
