import numpy as np
import pytest

from hdmi_tester.patterns import BY_KEY, PATTERNS

SIZES = [(1920, 1080), (641, 479), (16, 9)]


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda p: p.key)
@pytest.mark.parametrize("size", SIZES)
def test_shape_and_dtype(pattern, size):
    w, h = size
    for frame in (0, 1, 1000):
        img = pattern.render(w, h, frame)
        assert img.shape == (h, w, 3)
        assert img.dtype == np.uint8


def test_keys_unique():
    assert len(BY_KEY) == len(PATTERNS)


def test_solids():
    assert (BY_KEY["black"].render(8, 8, 0) == 0).all()
    assert (BY_KEY["white"].render(8, 8, 0) == 255).all()
    red = BY_KEY["red"].render(8, 8, 0)
    assert (red[..., 0] == 255).all() and (red[..., 1:] == 0).all()


def test_checkerboard_neighbours_differ():
    img = BY_KEY["checker1"].render(64, 48, 0)[..., 0].astype(int)
    assert (np.abs(np.diff(img, axis=0)) == 255).all()
    assert (np.abs(np.diff(img, axis=1)) == 255).all()


def test_grid_has_full_border():
    img = BY_KEY["grid"].render(101, 57, 0)
    for edge in (img[0], img[-1], img[:, 0], img[:, -1]):
        assert (edge == 255).all()


def test_overscan_outer_rectangle_on_edge():
    img = BY_KEY["overscan"].render(200, 100, 0)
    assert (img[0, :] == 255).all()
    # 2.5% inset: 5px horizontally, round(2.5)=2px vertically.
    assert tuple(img[2, 50]) == (255, 0, 0)
    assert tuple(img[50, 5]) == (255, 0, 0)


def test_ramp_spans_full_range():
    img = BY_KEY["ramp"].render(256, 4, 0)
    assert img[0, 0, 0] == 0 and img[0, -1, 0] == 255
    assert (np.diff(img[0, :, 0].astype(int)) >= 0).all()


def test_steps_distinct_levels():
    img = BY_KEY["steps"].render(320, 2, 0)
    assert len(np.unique(img[0, :, 0])) == 32


def test_flasher_cycles_and_has_warning():
    p = BY_KEY["flash"]
    assert p.animated and p.warning
    colours = {tuple(p.render(4, 4, f)[0, 0]) for f in range(5)}
    assert len(colours) == 5


def test_moving_bar_moves():
    p = BY_KEY["motion"]
    a, b = p.render(480, 10, 50), p.render(480, 10, 60)
    assert a.any() and b.any() and not np.array_equal(a, b)
