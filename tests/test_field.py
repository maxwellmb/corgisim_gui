import numpy as np
from astropy.io import fits

from corgisim_gui.core import field, model, tables


def test_skycoord_matches_corgisim_convention():
    x, y = field.skycoord_to_excam(100.0, 0.0, 0.0)
    assert abs(x + 100.0) < 1e-9 and abs(y) < 1e-9
    x, y = field.skycoord_to_excam(0.0, 100.0, 90.0)
    assert abs(x - 100.0) < 1e-9 and abs(y) < 1e-6


def test_render_sources_and_overlays():
    job = model.single_image_job()
    job.scene.point_sources.append(model.PointSource(vmag=15, dra_mas=0.0, ddec_mas=218.0, label="north"))
    fp = field.render_field(job, size_pix=101)
    assert fp.image.shape == (101, 101)
    cy, cx = np.unravel_index(np.argmax(fp.image), fp.image.shape)
    assert (cx, cy) == (50, 60)            # +dDec -> +y, 10 pixels up
    roles = [o.role for o in fp.overlays]
    assert roles.count("source") == 1 and "dark_hole" in roles and "field_stop" in roles and "compass" in roles
    src = [o for o in fp.overlays if o.role == "source"][0]
    assert abs(src.data["sep_mas"] - 218.0) < 1e-9 and abs(src.data["pa_deg"]) < 1e-9
    fp2 = field.render_field(job, size_pix=101, roll_deg=90.0)
    cy, cx = np.unravel_index(np.argmax(fp2.image), fp2.image.shape)
    assert (cx, cy) == (60, 50)            # rotated by -roll: now along +x


def test_render_disk_and_pol(tmp_path):
    disk = np.zeros((61, 61))
    disk[30, 40] = 1.0                      # a blob 10 px east... in image x
    p = tmp_path / "disk.fits"
    fits.PrimaryHDU(disk).writeto(p)
    job = model.single_image_job()
    job.instrument.dpam = "POL0"
    job.scene.disk = model.DiskModel(path=str(p), unit="contrast/pixel", contrast=1e-5, prf_cube_path="")
    fp = field.render_field(job, size_pix=101)
    assert fp.image.max() > 0
    cy, cx = np.unravel_index(np.argmax(fp.image), fp.image.shape)
    assert (cx, cy) == (60, 50)
    assert [o.role for o in fp.overlays].count("beam") == 2
    assert any("disk" in n for n in fp.notes)
    fp = field.render_field(job, size_pix=101, roll_deg=90.0)
    cy, cx = np.unravel_index(np.argmax(fp.image), fp.image.shape)
    assert abs(cx - 50) <= 1 and abs(cy - 40) <= 1   # rotated by -90: +x -> -y


def test_spec_slit_overlay_and_layout():
    job = model.single_image_job()
    job.instrument = model.InstrumentSpec(cgi_mode="spec", cor_type="spc-spec_band3", bandpass="3F", dpam="PRISM3", slit="R2C2")
    fp = field.render_field(job)
    slit = [o for o in fp.overlays if o.role == "slit"][0]
    assert abs(slit.data["angle_deg"] - 60.0) < 1e-9
    assert abs(slit.data["w"] * tables.PIXEL_SCALE_MAS - tables.SLITS["R2C2"].width_mas) < 1e-6
    lay = field.detector_layout(job)
    assert lay["boxes"][0]["x"] == 512 and lay["l1_shape"] == (1200, 2200)
    job.instrument = model.InstrumentSpec(dpam="POL45")
    assert len(field.detector_layout(job)["boxes"]) == 2
