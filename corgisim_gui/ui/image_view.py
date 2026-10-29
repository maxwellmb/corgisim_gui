"""A FITS / array viewer for the noiseless scene and the detector frames.

Pan with drag, zoom with the wheel, pixel readout on hover, stretch and colour
map controls, and a file list of the frames a run produced. Used by the Image
Lab result tab and the Sim Console's live thumbnail.
"""
from __future__ import annotations

import os

import numpy as np
from qtpy import QtCore, QtGui, QtWidgets

from .. import theming
from . import imaging


def load_fits_image(path: str) -> tuple[np.ndarray, dict]:
    """The first 2D image in a FITS file (L1: extension 1) and a few header facts."""
    from astropy.io import fits
    with fits.open(path) as hdul:
        data = None
        info: dict = {}
        for h in hdul:
            if h.data is not None and getattr(h.data, "ndim", 0) >= 2:
                data = np.asarray(h.data, dtype=float)
                break
        pri = hdul[0].header
        ext = hdul[1].header if len(hdul) > 1 else {}
        for k in ("VISITID", "VISTYPE", "TARGET", "PA_APER", "FILENAME", "BUNIT", "ROLL"):
            if k in pri:
                info[k] = pri[k]
        for k in ("EXPTIME", "EMGAIN_C", "FTIMEUTC", "CFAMNAME", "FPAMNAME", "DPAMNAME", "SATSPOTS", "BUNIT"):
            if k in ext:
                info[k] = ext[k]
    if data is None:
        raise ValueError(f"{path}: no 2D image found")
    while data.ndim > 2:
        data = data[0]
    return np.nan_to_num(data), info


class ImageCanvas(QtWidgets.QWidget):
    """Draws one array with pan/zoom; emits the pixel under the cursor."""

    hovered = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: np.ndarray | None = None
        self._qimage: QtGui.QImage | None = None
        self._stretch = "asinh"
        self._cmap = "inferno"
        self._pmin, self._pmax = 0.5, 99.8
        self._zoom = 1.0
        self._pan = QtCore.QPointF(0, 0)
        self._drag_from: QtCore.QPointF | None = None
        self._crop: tuple[int, int, int, int] | None = None     # x0, x1, y0, y1 shown region (L1 image area)
        self.setMouseTracking(True)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)

    @property
    def data(self):
        return self._data

    def set_data(self, data: np.ndarray | None, crop_l1: bool = True) -> None:
        self._data = data
        self._crop = None
        if data is not None and crop_l1 and data.shape == (1200, 2200):
            from ..core import tables
            (r0, r1), (c0, c1) = tables.L1_IMAGE_SLICE
            self._crop = (c0, c1, r0, r1)
        self._zoom = 1.0
        self._pan = QtCore.QPointF(0, 0)
        self._rebuild()
        self.update()

    def set_display(self, stretch=None, cmap=None, pmin=None, pmax=None) -> None:
        if stretch:
            self._stretch = stretch
        if cmap:
            self._cmap = cmap
        if pmin is not None:
            self._pmin = pmin
        if pmax is not None:
            self._pmax = pmax
        self._rebuild()
        self.update()

    def shown(self) -> np.ndarray | None:
        if self._data is None:
            return None
        if self._crop:
            x0, x1, y0, y1 = self._crop
            return self._data[y0:y1, x0:x1]
        return self._data

    def _rebuild(self) -> None:
        arr = self.shown()
        if arr is None:
            self._qimage = None
            return
        table = imaging.theme_lut(theming.current_theme()) if self._cmap == "theme" else imaging.lut(self._cmap)
        self._qimage = imaging.render(arr, self._stretch, table, pmin=self._pmin, pmax=self._pmax)

    def _geom(self) -> tuple[float, float, float]:
        arr = self.shown()
        if arr is None:
            return (0, 0, 1)
        h, w = arr.shape
        s = min(self.width() / w, self.height() / h) * self._zoom
        ox = (self.width() - w * s) / 2 + self._pan.x()
        oy = (self.height() - h * s) / 2 + self._pan.y()
        return (ox, oy, s)

    def to_image(self, pos) -> tuple[float, float]:
        arr = self.shown()
        ox, oy, s = self._geom()
        h = arr.shape[0] if arr is not None else 1
        return ((pos.x() - ox) / s - 0.5, h - (pos.y() - oy) / s - 0.5)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        theme = theming.current_theme()
        p.fillRect(self.rect(), QtGui.QColor("#0b1020" if not theming.is_dark(theme.palette.bg) else theme.palette.bg))
        if self._qimage is None:
            p.setPen(QtGui.QColor("#9aa6b8"))
            p.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "no image")
            p.end()
            return
        arr = self.shown()
        h, w = arr.shape
        ox, oy, s = self._geom()
        p.drawImage(QtCore.QRectF(ox, oy, w * s, h * s), self._qimage)
        p.end()

    def wheelEvent(self, event):
        d = event.angleDelta().y()
        if d:
            self._zoom = max(0.2, min(50.0, self._zoom * (1.2 if d > 0 else 1 / 1.2)))
            self.update()

    def mousePressEvent(self, event):
        self._drag_from = event.position() if hasattr(event, "position") else QtCore.QPointF(event.pos())

    def mouseReleaseEvent(self, event):
        self._drag_from = None

    def mouseMoveEvent(self, event):
        pos = event.position() if hasattr(event, "position") else QtCore.QPointF(event.pos())
        if self._drag_from is not None and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self._pan += pos - self._drag_from
            self._drag_from = pos
            self.update()
            return
        arr = self.shown()
        if arr is None:
            return
        x, y = self.to_image(pos)
        xi, yi = int(round(x)), int(round(y))
        if 0 <= xi < arr.shape[1] and 0 <= yi < arr.shape[0]:
            off = (self._crop[0], self._crop[2]) if self._crop else (0, 0)
            self.hovered.emit(f"x={xi + off[0]}  y={yi + off[1]}  value={arr[yi, xi]:.4g}")
        else:
            self.hovered.emit("")

    def reset_view(self) -> None:
        self._zoom = 1.0
        self._pan = QtCore.QPointF(0, 0)
        self.update()


class ImageView(QtWidgets.QWidget):
    """Canvas + controls + a list of files to pick from."""

    def __init__(self, parent=None, with_list: bool = True):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        ctl = QtWidgets.QHBoxLayout()
        self.stretch = QtWidgets.QComboBox()
        self.stretch.addItems(list(imaging.STRETCHES))
        self.cmap = QtWidgets.QComboBox()
        self.cmap.addItems([*imaging.COLORMAPS, "theme"])
        self.pmax = QtWidgets.QDoubleSpinBox()
        self.pmax.setRange(50, 100)
        self.pmax.setDecimals(2)
        self.pmax.setValue(99.8)
        self.pmax.setSuffix(" %")
        self.pmax.setToolTip("upper percentile of the stretch")
        ctl.addWidget(QtWidgets.QLabel("Stretch"))
        ctl.addWidget(self.stretch)
        ctl.addWidget(QtWidgets.QLabel("Colours"))
        ctl.addWidget(self.cmap)
        ctl.addWidget(QtWidgets.QLabel("Clip"))
        ctl.addWidget(self.pmax)
        reset = QtWidgets.QPushButton("Fit")
        ctl.addWidget(reset)
        ctl.addStretch(1)
        self.readout = QtWidgets.QLabel("")
        self.readout.setProperty("role", "hint")
        ctl.addWidget(self.readout)
        lay.addLayout(ctl)
        body = QtWidgets.QSplitter()
        self.canvas = ImageCanvas()
        body.addWidget(self.canvas)
        self.files = QtWidgets.QListWidget()
        self.files.setMaximumWidth(320)
        self.files.currentItemChanged.connect(self._on_file)
        if with_list:
            body.addWidget(self.files)
            body.setSizes([700, 260])
        lay.addWidget(body, 1)
        self.info = QtWidgets.QLabel("")
        self.info.setWordWrap(True)
        self.info.setProperty("role", "hint")
        lay.addWidget(self.info)
        self.stretch.currentTextChanged.connect(lambda t: self.canvas.set_display(stretch=t))
        self.cmap.currentTextChanged.connect(lambda t: self.canvas.set_display(cmap=t))
        self.pmax.valueChanged.connect(lambda v: self.canvas.set_display(pmax=v))
        reset.clicked.connect(self.canvas.reset_view)
        self.canvas.hovered.connect(self.readout.setText)
        self._paths: list[str] = []

    # -- files
    def clear(self) -> None:
        self._paths = []
        self.files.clear()
        self.canvas.set_data(None)
        self.info.setText("")

    def add_file(self, path: str, label: str | None = None, select: bool = True) -> None:
        if path in self._paths:
            return
        self._paths.append(path)
        it = QtWidgets.QListWidgetItem(label or os.path.basename(path))
        it.setData(QtCore.Qt.ItemDataRole.UserRole, path)
        it.setToolTip(path)
        self.files.addItem(it)
        if select:
            self.files.setCurrentItem(it)

    def show_file(self, path: str) -> None:
        try:
            data, info = load_fits_image(path)
        except Exception as exc:  # noqa: BLE001
            self.canvas.set_data(None)
            self.info.setText(f"{os.path.basename(path)}: {type(exc).__name__}: {exc}")
            return
        self.canvas.set_data(data)
        facts = "  ".join(f"{k}={v}" for k, v in info.items())
        self.info.setText(f"{os.path.basename(path)}  {data.shape[1]}x{data.shape[0]}  min {data.min():.4g}  max {data.max():.4g}  {facts}")

    def show_array(self, data: np.ndarray, text: str = "") -> None:
        self.canvas.set_data(data, crop_l1=False)
        self.info.setText(text)

    def _on_file(self, cur, _prev) -> None:
        if cur is not None:
            self.show_file(cur.data(QtCore.Qt.ItemDataRole.UserRole))

    def current_path(self) -> str | None:
        it = self.files.currentItem()
        return it.data(QtCore.Qt.ItemDataRole.UserRole) if it else None

    def theme_changed(self) -> None:
        self.canvas.set_display()
