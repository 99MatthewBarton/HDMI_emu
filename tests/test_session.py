import json

from hdmi_tester.patterns import PATTERNS
from hdmi_tester.session import Session


def test_navigation_wraps():
    s = Session(100, 50)
    s.prev()
    assert s.index == len(PATTERNS) - 1
    s.next()
    assert s.index == 0


def test_select():
    s = Session(100, 50)
    s.select("grid")
    assert s.pattern.key == "grid"


def test_flashing_pattern_blocked_until_confirmed():
    s = Session(100, 50)
    s.select("flash")
    assert s.blocked
    s.confirm()
    assert not s.blocked
    s.next(); s.prev()
    assert s.blocked  # re-arms after leaving


def test_cursor_clamped():
    s = Session(100, 50)
    assert s.cursor == (50, 25)
    s.move_cursor(-1000, 1000)
    assert s.cursor == (0, 49)


def test_mark_undo_and_report(tmp_path):
    s = Session(100, 50)
    s.select("white")
    s.move_cursor(3, -2)
    d = s.mark()
    assert (d.x, d.y, d.pattern) == (53, 23, "white")
    s.mark()
    s.undo_mark()
    path = tmp_path / "r.json"
    s.save_report(str(path), edid_summary="X")
    data = json.loads(path.read_text())
    assert data["defect_count"] == 1
    assert data["defects"][0] == {"x": 53, "y": 23, "pattern": "white", "note": ""}
    assert data["resolution"] == [100, 50]
