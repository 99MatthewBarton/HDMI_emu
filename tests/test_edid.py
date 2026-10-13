import pytest

from hdmi_tester.edid import EdidError, find_connectors, kernel_video_arg, parse_edid

from conftest import build_edid


def test_identity(edid_bytes):
    e = parse_edid(edid_bytes)
    assert e.manufacturer == "TST"
    assert e.product_code == 0x1234
    assert e.serial_number == 987654
    assert e.serial_string == "SN0001"
    assert e.name == "TESTMON"
    assert e.manufacture_year == 2023
    assert e.version == "1.3"
    assert e.digital
    assert e.checksum_errors == []


def test_native_timing(edid_bytes):
    t = parse_edid(edid_bytes).preferred_timing
    assert (t.h_active, t.v_active) == (1920, 1080)
    assert (t.h_blank, t.v_blank) == (280, 45)
    assert (t.h_sync_offset, t.h_sync_width) == (88, 44)
    assert (t.v_sync_offset, t.v_sync_width) == (4, 5)
    assert (t.width_mm, t.height_mm) == (598, 336)
    assert t.pixel_clock_khz == 148500
    assert t.refresh_hz == pytest.approx(60.0)
    assert not t.interlaced


def test_range_limits(edid_bytes):
    e = parse_edid(edid_bytes)
    assert e.v_rate_range == (56, 76)
    assert e.h_rate_range_khz == (30, 83)
    assert e.max_pixel_clock_mhz == 170


def test_cta_extension(edid_bytes):
    e = parse_edid(edid_bytes)
    assert e.has_cta and e.is_hdmi and e.hdmi_forum
    assert e.max_tmds_mhz == 600
    assert e.underscan and e.basic_audio and e.ycbcr444 and e.ycbcr422
    assert [(m.vic, m.native) for m in e.video_modes] == [
        (16, True), (4, False), (31, False), (97, False)]
    assert e.video_modes[3].description == "VIC 97: 3840x2160p60"
    # Second DTD comes from the extension block.
    assert (e.timings[1].h_active, e.timings[1].v_active) == (1280, 720)


def test_no_extension_is_dvi():
    e = parse_edid(build_edid(with_cta=False))
    assert not e.has_cta and not e.is_hdmi
    assert "no CTA extension" in e.summary()


def test_checksum_error_reported(edid_bytes):
    bad = bytearray(edid_bytes)
    bad[20] ^= 0x01
    assert parse_edid(bytes(bad)).checksum_errors == [0]


@pytest.mark.parametrize("raw", [b"", b"\x00" * 128, b"\x00\xff" * 30])
def test_rejects_garbage(raw):
    with pytest.raises(EdidError):
        parse_edid(raw)


def test_summary_mentions_key_facts(edid_bytes):
    s = parse_edid(edid_bytes).summary()
    assert "TESTMON" in s
    assert "1920x1080p @ 60.00 Hz" in s
    assert "HDMI 2.x" in s
    assert "(native)" in s


def test_kernel_video_arg(edid_bytes):
    t = parse_edid(edid_bytes).preferred_timing
    assert kernel_video_arg("HDMI-A-1", t) == "video=HDMI-A-1:1920x1080@60"


def test_find_connectors(tmp_path, edid_bytes):
    for name, status in [("card1-HDMI-A-1", "connected"),
                         ("card1-HDMI-A-2", "disconnected"),
                         ("card1-Composite-1", "connected")]:
        d = tmp_path / name
        d.mkdir()
        (d / "status").write_text(status + "\n")
        (d / "edid").write_bytes(edid_bytes if status == "connected" else b"")
    conns = find_connectors(str(tmp_path))
    assert [(c.name, c.connected) for c in conns] == [
        ("HDMI-A-1", True), ("HDMI-A-2", False)]
    assert parse_edid(conns[0].read_edid()).name == "TESTMON"
