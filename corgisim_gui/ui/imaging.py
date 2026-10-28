"""numpy image -> QImage: stretches and colour maps for the field preview and frame viewers."""
from __future__ import annotations

import numpy as np
from qtpy import QtGui

STRETCHES = ("asinh", "log", "sqrt", "linear")

# anchor colours (0..1 positions) for small, dependency-free colour maps
_ANCHORS = {
    "inferno": [(0.0, (0, 0, 4)), (0.2, (60, 15, 110)), (0.4, (150, 40, 100)), (0.6, (225, 100, 40)),
                (0.8, (250, 180, 30)), (1.0, (252, 255, 164))],
    "viridis": [(0.0, (68, 1, 84)), (0.25, (59, 82, 139)), (0.5, (33, 145, 140)), (0.75, (94, 201, 98)), (1.0, (253, 231, 37))],
    "grey": [(0.0, (0, 0, 0)), (1.0, (255, 255, 255))],
    "ink": [(0.0, (255, 255, 255)), (0.55, (112, 203, 255)), (1.0, (0, 39, 107))],     # Roman: white -> sky -> navy
}
COLORMAPS = tuple(_ANCHORS)


def lut(name: str, invert: bool = False) -> np.ndarray:
    """A (256, 3) uint8 table."""
    anchors = _ANCHORS.get(name, _ANCHORS["grey"])
    xs = np.array([a[0] for a in anchors])
    cols = np.array([a[1] for a in anchors], dtype=float)
    t = np.linspace(0, 1, 256)
    out = np.stack([np.interp(t, xs, cols[:, i]) for i in range(3)], axis=1)
    if invert:
        out = out[::-1]
    return np.clip(out, 0, 255).astype(np.uint8)


def theme_lut(theme) -> np.ndarray:
    """A two-colour map from the theme's background to its primary colour (for light themes) or text."""
    from .. import theming
    p = theme.palette
    dark = theming.is_dark(p.bg)
    c0 = np.array(theming._rgb(p.bg)) * 255
    c1 = np.array(theming._rgb(p.text if dark else p.primary)) * 255
    t = np.linspace(0, 1, 256)[:, None]
    return np.clip(c0 * (1 - t) + c1 * t, 0, 255).astype(np.uint8)


def normalise(img: np.ndarray, stretch: str = "asinh", pmin: float = 0.5, pmax: float = 99.8,
              vmin: float | None = None, vmax: float | None = None) -> np.ndarray:
    """Map ``img`` to 0..1 with a percentile cut and a stretch."""
    a = np.asarray(img, dtype=float)
    a = np.nan_to_num(a, nan=0.0, posinf=0.0, neginf=0.0)
    if a.size == 0:
        return np.zeros((1, 1))
    finite = a[np.isfinite(a)]
    lo = np.percentile(finite, pmin) if vmin is None else vmin
    hi = np.percentile(finite, pmax) if vmax is None else vmax
    if hi <= lo:
        hi = lo + (abs(lo) if lo else 1.0)
    x = np.clip((a - lo) / (hi - lo), 0.0, 1.0)
    if stretch == "asinh":
        k = 30.0
        x = np.arcsinh(k * x) / np.arcsinh(k)
    elif stretch == "log":
        k = 1000.0
        x = np.log1p(k * x) / np.log1p(k)
    elif stretch == "sqrt":
        x = np.sqrt(x)
    return x


def to_qimage(norm01: np.ndarray, table: np.ndarray) -> QtGui.QImage:
    """Colour a 0..1 array with a (256, 3) table. The returned QImage owns a copy of the bytes."""
    idx = np.clip((norm01 * 255).astype(int), 0, 255)
    rgb = np.ascontiguousarray(table[idx], dtype=np.uint8)      # (ny, nx, 3)
    h, w = rgb.shape[:2]
    img = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888)
    return img.copy()


def render(img: np.ndarray, stretch: str = "asinh", cmap: str | np.ndarray = "inferno", flip_y: bool = True, **kw) -> QtGui.QImage:
    """Array (origin lower) to a QImage (origin upper), stretched and coloured."""
    table = cmap if isinstance(cmap, np.ndarray) else lut(cmap)
    n = normalise(img, stretch, **kw)
    if flip_y:
        n = n[::-1]
    return to_qimage(n, table)


def wavelength_rgb(nm: float) -> tuple[int, int, int]:
    """A pleasant approximation of the colour of monochromatic light (visible, fading into the NIR)."""
    w = float(nm)
    if w < 440:
        r, g, b = -(w - 440) / 60, 0.0, 1.0
    elif w < 490:
        r, g, b = 0.0, (w - 440) / 50, 1.0
    elif w < 510:
        r, g, b = 0.0, 1.0, -(w - 510) / 20
    elif w < 580:
        r, g, b = (w - 510) / 70, 1.0, 0.0
    elif w < 645:
        r, g, b = 1.0, -(w - 645) / 65, 0.0
    else:
        r, g, b = 1.0, 0.0, 0.0
    if w > 700:        # fade toward a dark red / maroon for the near infrared
        f = max(0.35, 1.0 - (w - 700) / 250)
        r, g, b = r * f, g * f, b * f + (1 - f) * 0.25
    return (int(255 * min(1, max(0, r))), int(255 * min(1, max(0, g))), int(255 * min(1, max(0, b))))
