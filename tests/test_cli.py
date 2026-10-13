import zlib

import numpy as np

from hdmi_tester.cli import main, write_png

from conftest import build_edid


def test_png_roundtrip(tmp_path):
    img = np.arange(4 * 3 * 3, dtype=np.uint8).reshape(3, 4, 3)
    path = tmp_path / "a.png"
    write_png(str(path), img)
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG")
    idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
    rows = np.frombuffer(zlib.decompress(idat), np.uint8).reshape(3, 13)
    assert (rows[:, 0] == 0).all()
    assert np.array_equal(rows[:, 1:].reshape(3, 4, 3), img)


def test_render_command(tmp_path, capsys):
    assert main(["render", "--size", "32x16", "--out", str(tmp_path), "grid", "ramp"]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["grid.png", "ramp.png"]


def test_render_unknown_pattern(tmp_path):
    assert main(["render", "--out", str(tmp_path), "nope"]) == 2


def test_edid_command(tmp_path, capsys):
    f = tmp_path / "edid.bin"
    f.write_bytes(build_edid())
    assert main(["edid", "--edid-file", str(f)]) == 0
    out = capsys.readouterr().out
    assert "TESTMON" in out
    assert "video=HDMI-A-1:1920x1080@60" in out


def test_list(capsys):
    assert main(["list"]) == 0
    assert "checker1" in capsys.readouterr().out
