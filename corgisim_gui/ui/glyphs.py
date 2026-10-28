"""Schematic glyphs for the optical-train strip, drawn with QPainter.

Each painter draws one element into a square ``rect``. They are deliberately
diagrammatic (after Fig. 2 of Riggs et al. 2025): a pupil with its spider, a
shaped pupil, a focal plane mask, a Lyot stop, a field stop or slit, a colour
filter, a DPAM element and the detector. ``colors`` is a dict with ``line``,
``fill`` (the "light" of an open aperture), ``dark`` (opaque mask material),
``text`` and ``accent``.
"""
from __future__ import annotations

import math

from qtpy import QtCore, QtGui

from ..core import tables
from .imaging import wavelength_rgb


def _pen(color, width=1.2, style=QtCore.Qt.PenStyle.SolidLine) -> QtGui.QPen:
    pen = QtGui.QPen(QtGui.QColor(color), width)
    pen.setStyle(style)
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    return pen


def _square(rect: QtCore.QRectF, margin: float = 0.08) -> QtCore.QRectF:
    s = min(rect.width(), rect.height()) * (1 - 2 * margin)
    return QtCore.QRectF(rect.center().x() - s / 2, rect.center().y() - s / 2, s, s)


def _circle(c: QtCore.QPointF, r: float) -> QtCore.QRectF:
    return QtCore.QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)


def _wedge_path(c: QtCore.QPointF, r_in: float, r_out: float, a0: float, span: float) -> QtGui.QPainterPath:
    """Annular wedge from angle a0 spanning ``span`` degrees (Qt angles: counter-clockwise from +x)."""
    path = QtGui.QPainterPath()
    outer = _circle(c, r_out)
    inner = _circle(c, r_in)
    path.arcMoveTo(outer, a0)
    path.arcTo(outer, a0, span)
    if r_in > 0:
        path.arcTo(inner, a0 + span, -span)
    else:
        path.lineTo(c)
    path.closeSubpath()
    return path


# ----------------------------------------------------------------------------- pupils
def paint_pupil(p: QtGui.QPainter, rect: QtCore.QRectF, colors: dict, obscuration: float = 0.32, struts: int = 6, fill=None) -> None:
    """The Roman telescope pupil: disc, central obscuration, six struts."""
    sq = _square(rect)
    c, r = sq.center(), sq.width() / 2
    p.setPen(_pen(colors["line"]))
    p.setBrush(QtGui.QColor(fill or colors["fill"]))
    p.drawEllipse(_circle(c, r))
    p.setBrush(QtGui.QColor(colors["dark"]))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.drawEllipse(_circle(c, r * obscuration))
    p.setPen(_pen(colors["dark"], max(1.5, r * 0.07)))
    for k in range(struts):
        a = math.radians(90 + k * 360 / struts)
        p.drawLine(QtCore.QPointF(c.x() + r * obscuration * math.cos(a), c.y() - r * obscuration * math.sin(a)),
                   QtCore.QPointF(c.x() + r * math.cos(a), c.y() - r * math.sin(a)))


def paint_dm(p: QtGui.QPainter, rect: QtCore.QRectF, colors: dict, active: bool = True) -> None:
    """A deformable mirror: a 48x48 actuator grid, drawn as a coarse grid with a soft bump pattern."""
    sq = _square(rect)
    p.setPen(_pen(colors["line"]))
    p.setBrush(QtGui.QColor(colors["fill"] if active else colors["dark"]))
    p.drawRect(sq)
    n = 8
    pen = _pen(colors["line"], 0.6)
    pen.setColor(QtGui.QColor(colors["line"]).lighter(130) if active else QtGui.QColor(colors["line"]))
    p.setPen(pen)
    step = sq.width() / n
    for k in range(1, n):
        p.drawLine(QtCore.QPointF(sq.left() + k * step, sq.top()), QtCore.QPointF(sq.left() + k * step, sq.bottom()))
        p.drawLine(QtCore.QPointF(sq.left(), sq.top() + k * step), QtCore.QPointF(sq.right(), sq.top() + k * step))
    if active:
        # a few "poked" actuators
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        acc = QtGui.QColor(colors["accent"])
        acc.setAlpha(120)
        p.setBrush(acc)
        for (i, j) in ((2, 3), (5, 1), (6, 5), (3, 6), (1, 5)):
            p.drawRect(QtCore.QRectF(sq.left() + i * step, sq.top() + j * step, step, step))


def paint_spam(p: QtGui.QPainter, rect: QtCore.QRectF, name: str, colors: dict) -> None:
    """SPAM: OPEN = flat mirror (plain pupil); WFOV/SPEC/SPECROT = shaped pupil masks."""
    if name == "OPEN":
        paint_pupil(p, rect, colors)
        return
    sq = _square(rect)
    c, r = sq.center(), sq.width() / 2
    p.setPen(_pen(colors["line"]))
    p.setBrush(QtGui.QColor(colors["dark"]))
    p.drawEllipse(_circle(c, r))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(colors["fill"]))
    if name == "WFOV":
        # concentric open arcs (an annular shaped pupil), interrupted by the struts
        for r_in, r_out in ((0.40, 0.56), (0.64, 0.80), (0.86, 0.96)):
            for k in range(6):
                p.drawPath(_wedge_path(c, r * r_in, r * r_out, 90 + k * 60 + 6, 48))
    else:
        rot = 90 if name == "SPECROT" else 0
        for a0 in (-32 + rot, 148 + rot):
            path = _wedge_path(c, r * 0.36, r * 0.95, a0, 64)
            p.drawPath(path)
        # ripples in the wedges to suggest the apodised pattern
        p.setPen(_pen(colors["dark"], 1.0))
        for rr in (0.5, 0.64, 0.78):
            for a0 in (-30 + rot, 150 + rot):
                p.drawArc(_circle(c, r * rr), int((a0 + 4) * 16), int(52 * 16))


# ----------------------------------------------------------------------------- focal planes
def paint_fpam(p: QtGui.QPainter, rect: QtCore.QRectF, name: str, family: str, rotated: bool, colors: dict) -> None:
    sq = _square(rect)
    c, r = sq.center(), sq.width() / 2
    p.setPen(_pen(colors["line"]))
    if name.startswith("OPEN"):
        p.setBrush(QtGui.QColor(colors["fill"]))
        p.drawEllipse(_circle(c, r))
        return
    if name.startswith("ND"):
        p.setBrush(QtGui.QColor(colors["line"]).darker(110))
        p.drawEllipse(_circle(c, r))
        return
    if family == "hlc":
        p.setBrush(QtGui.QColor(colors["fill"]))
        p.drawEllipse(_circle(c, r))
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(colors["dark"]))
        p.drawEllipse(_circle(c, r * 0.14))
        # the dielectric pattern: a faint ring
        p.setPen(_pen(colors["line"], 0.8, QtCore.Qt.PenStyle.DotLine))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawEllipse(_circle(c, r * 0.3))
        return
    # SPC masks: opaque with an opening
    p.setBrush(QtGui.QColor(colors["dark"]))
    p.drawEllipse(_circle(c, r))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(colors["fill"]))
    if family in ("spc-wide", "spc-mswc"):
        p.drawPath(_wedge_path(c, r * 0.30, r * 0.92, 0, 360))
    else:
        rot = 90 if rotated else 0
        for a0 in (-32 + rot, 148 + rot):
            p.drawPath(_wedge_path(c, r * 0.30, r * 0.90, a0, 64))


def paint_lsam(p: QtGui.QPainter, rect: QtCore.QRectF, name: str, colors: dict) -> None:
    if name == "OPEN":
        paint_pupil(p, rect, colors)
        return
    sq = _square(rect)
    c, r = sq.center(), sq.width() / 2
    p.setPen(_pen(colors["line"]))
    p.setBrush(QtGui.QColor(colors["dark"]))
    p.drawEllipse(_circle(c, r))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(colors["fill"]))
    if name == "NFOV":
        r_in, r_out, gap = 0.42, 0.80, 10
    elif name == "WFOV":
        r_in, r_out, gap = 0.38, 0.88, 8
    else:
        r_in, r_out, gap = 0.40, 0.86, 12
    if name in ("SPEC", "SPECROT"):
        rot = 90 if name == "SPECROT" else 0
        for a0 in (-30 + rot, 150 + rot):
            p.drawPath(_wedge_path(c, r * r_in, r * r_out, a0, 60))
    else:
        for k in range(6):
            p.drawPath(_wedge_path(c, r * r_in, r * r_out, 90 + k * 60 + gap / 2, 60 - gap))


def paint_fsam(p: QtGui.QPainter, rect: QtCore.QRectF, name: str, colors: dict, radius_mas: float | None = None,
               slit: tables.Slit | None = None) -> None:
    """Field stop: an opaque square with a circular opening (radius to scale up to 1.9") or a slit."""
    sq = _square(rect)
    c, r = sq.center(), sq.width() / 2
    p.setPen(_pen(colors["line"]))
    if name == "OPEN" or (radius_mas is None and slit is None):
        p.setBrush(QtGui.QColor(colors["fill"]))
        p.drawRect(sq)
        return
    p.setBrush(QtGui.QColor(colors["dark"]))
    p.drawRect(sq)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(colors["fill"]))
    scale = r * 0.92 / 1900.0        # 1.9" radius fills the cell
    if slit is not None:
        w = max(2.0, slit.width_mas * scale * 2.5)      # slits are too thin to see at scale: widen
        h = min(2 * r * 0.92, slit.height_mas * scale * 2.5)
        p.save()
        p.translate(c)
        p.rotate(-slit.rotation_deg)
        p.drawRect(QtCore.QRectF(-w / 2, -h / 2, w, h))
        p.restore()
        return
    rr = max(3.0, min(r * 0.92, radius_mas * scale))
    p.drawEllipse(_circle(c, rr))


# ----------------------------------------------------------------------------- filters, DPAM, detector
def paint_cfam(p: QtGui.QPainter, rect: QtCore.QRectF, flt: tables.Filter | None, colors: dict) -> None:
    sq = _square(rect)
    p.setPen(_pen(colors["line"]))
    if flt is None:
        p.setBrush(QtGui.QColor(colors["dark"]))
        p.drawEllipse(sq)
        return
    rgb = wavelength_rgb(flt.center_nm)
    col = QtGui.QColor(*rgb)
    if flt.kind == "engineering":
        col.setAlpha(170)
    p.setBrush(col)
    p.drawEllipse(sq)
    # bandwidth bar
    frac = min(1.0, flt.fwhm_nm / 130.0)
    bar = QtCore.QRectF(sq.left() + sq.width() * (1 - frac) / 2, sq.bottom() - sq.height() * 0.16, sq.width() * frac, sq.height() * 0.07)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(colors["text"]))
    p.drawRect(bar)


def paint_dpam(p: QtGui.QPainter, rect: QtCore.QRectF, name: str, colors: dict) -> None:
    sq = _square(rect, 0.12)
    c, w, h = sq.center(), sq.width(), sq.height()
    p.setPen(_pen(colors["line"], 1.4))
    p.setBrush(QtGui.QColor(colors["fill"]))
    if name in ("IMAGING", "PUPIL", "None"):
        path = QtGui.QPainterPath()
        path.moveTo(c.x(), sq.top())
        path.quadTo(c.x() + w * 0.5, c.y(), c.x(), sq.bottom())
        path.quadTo(c.x() - w * 0.5, c.y(), c.x(), sq.top())
        p.drawPath(path)
        if name == "PUPIL":
            p.setPen(_pen(colors["accent"], 1.0, QtCore.Qt.PenStyle.DashLine))
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            p.drawEllipse(_circle(c, w * 0.18))
        return
    if name.startswith("POL"):
        # a Wollaston: two wedges, two outgoing beams
        p.drawRect(sq)
        p.drawLine(QtCore.QPointF(sq.left(), sq.top()), QtCore.QPointF(sq.right(), sq.bottom()))
        p.setPen(_pen(colors["accent"], 1.6))
        y1, y2 = c.y() - h * 0.18, c.y() + h * 0.18
        p.drawLine(QtCore.QPointF(sq.left() - w * 0.12, c.y()), QtCore.QPointF(c.x(), c.y()))
        p.drawLine(QtCore.QPointF(c.x(), c.y()), QtCore.QPointF(sq.right() + w * 0.12, y1))
        p.drawLine(QtCore.QPointF(c.x(), c.y()), QtCore.QPointF(sq.right() + w * 0.12, y2))
        return
    if name.startswith("PRISM"):
        # an Amici (direct-vision) prism: three wedges in a row
        path = QtGui.QPainterPath()
        path.moveTo(sq.left(), sq.bottom())
        path.lineTo(sq.left() + w * 0.33, sq.top())
        path.lineTo(sq.left() + w * 0.66, sq.bottom())
        path.lineTo(sq.right(), sq.top())
        path.lineTo(sq.right(), sq.bottom())
        path.closeSubpath()
        p.drawPath(path)
        # a little dispersed beam
        for k, col in enumerate(((60, 120, 255), (60, 220, 90), (255, 70, 60))):
            p.setPen(_pen(QtGui.QColor(*col), 1.4))
            p.drawLine(QtCore.QPointF(c.x(), c.y()), QtCore.QPointF(sq.right() + w * 0.14, c.y() + (k - 1) * h * 0.16))
        return
    p.drawRect(sq)


def paint_excam(p: QtGui.QPainter, rect: QtCore.QRectF, colors: dict, boxes: list[dict] | None = None, size: int = 1024) -> None:
    """The EXCAM science area with the simulated image box(es) at their positions."""
    sq = _square(rect)
    p.setPen(_pen(colors["line"]))
    p.setBrush(QtGui.QColor(colors["dark"]))
    p.drawRect(sq)
    pen = _pen(colors["line"], 0.6, QtCore.Qt.PenStyle.DotLine)
    p.setPen(pen)
    for f in (0.25, 0.5, 0.75):
        p.drawLine(QtCore.QPointF(sq.left() + f * sq.width(), sq.top()), QtCore.QPointF(sq.left() + f * sq.width(), sq.bottom()))
        p.drawLine(QtCore.QPointF(sq.left(), sq.top() + f * sq.height()), QtCore.QPointF(sq.right(), sq.top() + f * sq.height()))
    s = sq.width() / size
    acc = QtGui.QColor(colors["accent"])
    acc.setAlpha(190)
    p.setPen(_pen(colors["accent"], 1.2))
    p.setBrush(acc)
    for b in boxes or []:
        half = max(2.0, b["half"] * s)
        x = sq.left() + b["x"] * s
        y = sq.bottom() - b["y"] * s
        p.drawRect(QtCore.QRectF(x - half, y - half, 2 * half, 2 * half))


def paint_arrow(p: QtGui.QPainter, x0: float, x1: float, y: float, colors: dict) -> None:
    p.setPen(_pen(colors["line"], 1.2))
    p.drawLine(QtCore.QPointF(x0, y), QtCore.QPointF(x1 - 3, y))
    path = QtGui.QPainterPath()
    path.moveTo(x1, y)
    path.lineTo(x1 - 6, y - 3.5)
    path.lineTo(x1 - 6, y + 3.5)
    path.closeSubpath()
    p.setBrush(QtGui.QColor(colors["line"]))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.drawPath(path)
