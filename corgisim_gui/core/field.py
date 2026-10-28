"""Field-of-view preview: what the scene will look like on the detector, without corgisim.

:func:`render_field` returns a :class:`FieldPreview` with

* ``image``: a float array at the EXCAM plate scale (21.8 mas/pix) with the
  disk model (rotated by the roll angle, scaled by its unit) and each off-axis
  point source as a 2D Gaussian whose FWHM is the diffraction width of the
  selected filter; the host star is marked but not drawn (it is behind the mask);
* ``overlays``: geometry in pixels for the Setup View to draw: dark-hole
  annulus, field stop or slit, polarimetry beam footprints, the λ/D scale,
  sources with labels, the roll-rotated north/east arrows.

Coordinates follow corgisim: sky offsets (dRA, dDec) in mas map to EXCAM
pixels through ``skycoord_to_excamcoord``: x = -dRA, y = +dDec, rotated by
-roll. Images are ``[y, x]`` with (0, 0) at the bottom-left when displayed with
origin='lower'.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import tables
from .model import InstrumentSpec, Job, SceneSpec


@dataclass
class Overlay:
    kind: str                     # 'annulus' | 'circle' | 'rect' | 'point' | 'arrow' | 'text'
    data: dict[str, Any]
    label: str = ""
    role: str = ""                # 'dark_hole' | 'field_stop' | 'slit' | 'beam' | 'source' | 'host' | 'compass' | 'scale'


@dataclass
class FieldPreview:
    image: np.ndarray                  # [ny, nx], arbitrary flux units (counts/s-like)
    size_pix: int
    pixel_scale_mas: float
    lam_over_d_pix: float
    roll_deg: float
    overlays: list[Overlay] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def centre(self) -> tuple[float, float]:
        return ((self.size_pix - 1) / 2.0, (self.size_pix - 1) / 2.0)

    def extent_mas(self) -> tuple[float, float, float, float]:
        h = self.size_pix * self.pixel_scale_mas / 2.0
        return (-h, h, -h, h)


def skycoord_to_excam(dra_mas: float, ddec_mas: float, roll_deg: float) -> tuple[float, float]:
    """corgisim.instrument.skycoord_to_excamcoord: x = -dRA, y = dDec, rotated by -roll."""
    x, y = -dra_mas, ddec_mas
    th = math.radians(-roll_deg)
    return (x * math.cos(th) - y * math.sin(th), x * math.sin(th) + y * math.cos(th))


def gaussian_fwhm_pix(inst: InstrumentSpec) -> float:
    """FWHM of the Airy core, about 1.03 λ/D, in pixels."""
    f = inst.filter
    return 1.03 * (f.lam_over_d_pix if f else 1.2)


def _add_gaussian(img: np.ndarray, x0: float, y0: float, flux: float, fwhm_pix: float) -> None:
    sigma = fwhm_pix / 2.3548
    n = img.shape[0]
    r = int(math.ceil(4 * sigma)) + 1
    xi, yi = int(round(x0)), int(round(y0))
    x1, x2 = max(0, xi - r), min(n, xi + r + 1)
    y1, y2 = max(0, yi - r), min(n, yi + r + 1)
    if x1 >= x2 or y1 >= y2:
        return
    yy, xx = np.mgrid[y1:y2, x1:x2]
    g = np.exp(-((xx - x0) ** 2 + (yy - y0) ** 2) / (2 * sigma ** 2))
    g *= flux / (2 * math.pi * sigma ** 2)
    img[y1:y2, x1:x2] += g


def _vmag_flux(vmag: float, vmag_ref: float = 0.0) -> float:
    return 10 ** (-0.4 * (vmag - vmag_ref))


def load_disk_image(path: str) -> np.ndarray:
    from astropy.io import fits
    with fits.open(path) as hdul:
        data = None
        for h in hdul:
            if h.data is not None and getattr(h.data, "ndim", 0) >= 2:
                data = np.asarray(h.data, dtype=float)
                break
    if data is None:
        raise ValueError(f"{path}: no 2D image found")
    while data.ndim > 2:
        data = data[0]
    data = np.nan_to_num(data)
    return data


def _place_centered(dst: np.ndarray, src: np.ndarray) -> None:
    n = dst.shape[0]
    sy, sx = src.shape
    cy, cx = n // 2, n // 2
    y1, x1 = cy - sy // 2, cx - sx // 2
    dy1, dx1 = max(0, y1), max(0, x1)
    dy2, dx2 = min(n, y1 + sy), min(n, x1 + sx)
    if dy1 >= dy2 or dx1 >= dx2:
        return
    dst[dy1:dy2, dx1:dx2] += src[dy1 - y1:dy2 - y1, dx1 - x1:dx2 - x1]


def render_field(job: Job, size_pix: int | None = None, roll_deg: float | None = None,
                 scene: SceneSpec | None = None, disk_max_pix: int = 801) -> FieldPreview:
    inst = job.instrument
    scene = scene or job.scene
    roll = inst.roll_angle_deg if roll_deg is None else roll_deg
    n = int(size_pix or inst.output_dim)
    if n % 2 == 0:
        n += 1
    f = inst.filter
    lamd_pix = f.lam_over_d_pix if f else 1.2
    fwhm = gaussian_fwhm_pix(inst)
    img = np.zeros((n, n), dtype=float)
    cx = cy = (n - 1) / 2.0
    ov: list[Overlay] = []
    notes: list[str] = []
    host_flux = _vmag_flux(scene.host.vmag)

    # disk
    if scene.disk is not None and scene.disk.path:
        try:
            disk = load_disk_image(scene.disk.path)
            if disk.shape[0] > disk_max_pix:
                c0 = disk.shape[0] // 2
                h = disk_max_pix // 2
                disk = disk[c0 - h:c0 + h + 1, c0 - h:c0 + h + 1]
            if roll % 360:
                from scipy import ndimage
                disk = ndimage.rotate(disk, roll, reshape=False, order=1, mode="constant", cval=0.0)   # same sense as skycoord_to_excam
            scale = 1.0
            if scene.disk.unit == "contrast/pixel":
                scale = host_flux
            elif scene.disk.unit == "mJy/arcsec^2":
                # relative only: 1 mJy/arcsec^2 ~ V=13.5 per arcsec^2 -> per 21.8 mas pixel
                scale = _vmag_flux(13.5) * (tables.PIXEL_SCALE_MAS / 1000.0) ** 2
            else:
                scale = disk.max() and host_flux * 1e-6 / disk.max()
            _place_centered(img, disk * scale)
            notes.append(f"disk {scene.disk.path.split('/')[-1]} ({disk.shape[1]}x{disk.shape[0]} px, {scene.disk.unit}), rotated by roll {roll:g} deg")
        except Exception as exc:  # noqa: BLE001 - preview must not fail
            notes.append(f"disk not drawn: {type(exc).__name__}: {exc}")

    # host star marker
    ov.append(Overlay("point", {"x": cx, "y": cy, "r": 0.5 * lamd_pix}, scene.host.label(), "host"))

    # point sources as Gaussians
    for i, p in enumerate(scene.point_sources):
        ex, ey = skycoord_to_excam(p.dra_mas, p.ddec_mas, roll)
        x = cx + ex / tables.PIXEL_SCALE_MAS
        y = cy + ey / tables.PIXEL_SCALE_MAS
        _add_gaussian(img, x, y, _vmag_flux(p.vmag), fwhm)
        sep_lamd = p.separation_mas / (lamd_pix * tables.PIXEL_SCALE_MAS)
        ov.append(Overlay("point", {"x": x, "y": y, "r": fwhm, "vmag": p.vmag, "sep_mas": p.separation_mas,
                                    "sep_lamD": sep_lamd, "pa_deg": p.pa_deg},
                          p.label or f"source {i + 1}", "source"))

    # dark hole
    iwa, owa = tables.dark_hole_lamD(inst.cor_type)
    if owa > 0:
        c = inst.coronagraph
        ov.append(Overlay("annulus", {"x": cx, "y": cy, "r_in": iwa * lamd_pix, "r_out": owa * lamd_pix,
                                      "azimuth_deg": c.azimuth_deg if c else 360.0, "roll_deg": roll,
                                      "rotated": bool(c and c.rotated)},
                          f"dark hole {iwa:g}-{owa:g} λ/D", "dark_hole"))

    # field stop / slit
    mech = inst.mechanisms()
    if inst.cgi_mode == "spec":
        s = tables.SLITS.get(inst.slit)
        if s is not None and inst.use_field_stop:
            if inst.slit_x_offset_mas is not None and inst.slit_y_offset_mas is not None:
                sx, sy = inst.slit_x_offset_mas, inst.slit_y_offset_mas
            else:
                sx, sy = skycoord_to_excam(inst.slit_ra_offset_mas, inst.slit_dec_offset_mas, roll)
            ov.append(Overlay("rect", {"x": cx + sx / tables.PIXEL_SCALE_MAS, "y": cy + sy / tables.PIXEL_SCALE_MAS,
                                       "w": s.width_mas / tables.PIXEL_SCALE_MAS, "h": s.height_mas / tables.PIXEL_SCALE_MAS,
                                       "angle_deg": s.rotation_deg}, f"slit {s.name}", "slit"))
    else:
        r_mas = tables.FIELD_STOP_RADIUS_MAS.get(mech.fsam)
        if r_mas and inst.use_field_stop and mech.fsam != "OPEN":
            ov.append(Overlay("circle", {"x": cx, "y": cy, "r": r_mas / tables.PIXEL_SCALE_MAS}, f"field stop {mech.fsam}", "field_stop"))

    # polarimetry beams
    if inst.is_polarimetry:
        dx, dy = tables.POL_BEAM_OFFSET_PIX[inst.dpam]
        half = inst.output_dim / 2.0
        for sgn, name in ((+1, "beam A"), (-1, "beam B")):
            ov.append(Overlay("rect", {"x": cx + sgn * dx, "y": cy + sgn * dy, "w": 2 * half, "h": 2 * half, "angle_deg": 0.0},
                              f"{inst.dpam} {name}", "beam"))
        notes.append(f"{inst.dpam}: two beams offset by ±({dx}, {dy}) px on the detector; the preview shows one")

    # compass and scale
    ov.append(Overlay("arrow", {"x": cx, "y": cy, "north_deg": -roll, "east_deg": -roll + 90.0, "len": 5 * lamd_pix}, "N/E", "compass"))
    ov.append(Overlay("text", {"lam_over_d_pix": lamd_pix, "lam_over_d_mas": lamd_pix * tables.PIXEL_SCALE_MAS,
                               "pixel_scale_mas": tables.PIXEL_SCALE_MAS}, "scale", "scale"))

    return FieldPreview(img, n, tables.PIXEL_SCALE_MAS, lamd_pix, roll, ov, notes)


def detector_layout(job: Job) -> dict[str, Any]:
    """Where the simulated image lands on the 1024x1024 science area and in the L1 frame."""
    inst, det = job.instrument, job.detector
    half = inst.output_dim // 2
    boxes = []
    if inst.is_polarimetry:
        dx, dy = tables.POL_BEAM_OFFSET_PIX[inst.dpam]
        boxes.append({"x": det.loc_x + dx, "y": det.loc_y + dy, "half": half, "label": "beam A"})
        boxes.append({"x": det.loc_x - dx, "y": det.loc_y - dy, "half": half, "label": "beam B"})
    else:
        boxes.append({"x": det.loc_x, "y": det.loc_y, "half": half, "label": "image"})
    (r0, r1), (c0, c1) = tables.L1_IMAGE_SLICE
    return {"science_area": tables.EXCAM_IMAGE_PIX, "l1_shape": tables.L1_FRAME_SHAPE,
            "image_rows": (r0, r1), "image_cols": (c0, c1), "boxes": boxes, "full_frame": det.full_frame}
