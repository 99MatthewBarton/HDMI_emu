"""Test pattern generators.

Every pattern renders to an ``(height, width, 3)`` ``uint8`` RGB array so it can
be unit-tested and previewed without any display hardware. Animated patterns
take a ``frame`` counter and return a different image per frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

RenderFn = Callable[[int, int, int], np.ndarray]


@dataclass(frozen=True)
class Pattern:
    key: str
    name: str
    purpose: str
    render: RenderFn
    animated: bool = False
    # Frames per second for animated patterns.
    fps: int = 0
    # Shown before the pattern starts; used for flashing content.
    warning: str | None = None


def _solid(rgb: tuple[int, int, int]) -> RenderFn:
    def render(w: int, h: int, frame: int = 0) -> np.ndarray:
        img = np.empty((h, w, 3), dtype=np.uint8)
        img[:] = rgb
        return img

    return render


def checkerboard(w: int, h: int, frame: int = 0, cell: int = 1) -> np.ndarray:
    """Alternating black/white cells. With ``cell=1`` every pixel differs from
    its neighbours, so any scaling or overscan shows up as moire or blur."""
    y, x = np.ogrid[:h, :w]
    on = ((x // cell) + (y // cell)) % 2 == 0
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[on] = 255
    return img


def pixel_grid(w: int, h: int, frame: int = 0, spacing: int = 16) -> np.ndarray:
    """1px white lines on black every ``spacing`` px, plus a 1px border on the
    outermost rows/columns. A missing border edge means the display is
    cropping (overscan) or not mapping pixels 1:1."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[::spacing, :] = 255
    img[:, ::spacing] = 255
    img[0, :] = img[-1, :] = 255
    img[:, 0] = img[:, -1] = 255
    return img


def overscan(w: int, h: int, frame: int = 0) -> np.ndarray:
    """Nested rectangles at 0%, 2.5%, 5% and 10% inset from each edge, each in
    a different colour. The outermost visible rectangle tells you how much the
    display is cropping."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = (40, 40, 40)
    # Centre crosshair for geometry/centring, drawn first so the rectangles
    # stay unbroken.
    img[h // 2, :] = (128, 128, 128)
    img[:, w // 2] = (128, 128, 128)
    insets = [(0.0, (255, 255, 255)), (0.025, (255, 0, 0)),
              (0.05, (0, 255, 0)), (0.10, (0, 0, 255))]
    for frac, colour in insets:
        dx, dy = int(round(w * frac)), int(round(h * frac))
        x0, x1, y0, y1 = dx, w - 1 - dx, dy, h - 1 - dy
        img[y0, x0:x1 + 1] = colour
        img[y1, x0:x1 + 1] = colour
        img[y0:y1 + 1, x0] = colour
        img[y0:y1 + 1, x1] = colour
    return img


def gray_ramp(w: int, h: int, frame: int = 0) -> np.ndarray:
    """Smooth black-to-white horizontal ramp. Visible steps indicate reduced
    bit depth, dithering problems or aggressive processing."""
    ramp = np.linspace(0, 255, w).round().astype(np.uint8)
    img = np.empty((h, w, 3), dtype=np.uint8)
    img[:] = ramp[None, :, None]
    return img


def rgb_ramps(w: int, h: int, frame: int = 0) -> np.ndarray:
    """Four horizontal bands: red, green, blue and gray ramps."""
    ramp = np.linspace(0, 255, w).round().astype(np.uint8)
    img = np.zeros((h, w, 3), dtype=np.uint8)
    bands = np.array_split(np.arange(h), 4)
    for ch, rows in enumerate(bands[:3]):
        img[rows, :, ch] = ramp
    img[bands[3], :, :] = ramp[None, :, None]
    return img


def gray_steps(w: int, h: int, frame: int = 0, steps: int = 32) -> np.ndarray:
    """Discrete gray steps. Each step should be distinguishable from its
    neighbours; merged steps near black/white indicate crushed or clipped
    shadows/highlights."""
    idx = (np.arange(w) * steps // w).astype(np.int32)
    levels = np.round(idx * 255 / (steps - 1)).astype(np.uint8)
    img = np.empty((h, w, 3), dtype=np.uint8)
    img[:] = levels[None, :, None]
    return img


def color_bars(w: int, h: int, frame: int = 0) -> np.ndarray:
    """75% colour bars (white, yellow, cyan, green, magenta, red, blue)."""
    v = 191
    bars = [(v, v, v), (v, v, 0), (0, v, v), (0, v, 0),
            (v, 0, v), (v, 0, 0), (0, 0, v)]
    idx = (np.arange(w) * len(bars) // w)
    palette = np.array(bars, dtype=np.uint8)
    img = np.empty((h, w, 3), dtype=np.uint8)
    img[:] = palette[idx][None, :, :]
    return img


def crosstalk(w: int, h: int, frame: int = 0) -> np.ndarray:
    """Black and white boxes on mid-gray. Shadows or streaks extending from
    the boxes indicate crosstalk; persisting after switching away suggests
    image retention."""
    img = np.empty((h, w, 3), dtype=np.uint8)
    img[:] = 128
    bw, bh = w // 5, h // 3
    y0 = (h - bh) // 2
    img[y0:y0 + bh, w // 5:w // 5 + bw] = 0
    img[y0:y0 + bh, 3 * w // 5:3 * w // 5 + bw] = 255
    return img


_FLASH_COLOURS = np.array([
    (255, 0, 0), (0, 255, 0), (0, 0, 255),
    (255, 255, 255), (0, 0, 0),
], dtype=np.uint8)


def stuck_pixel_flasher(w: int, h: int, frame: int = 0) -> np.ndarray:
    """Full-screen rapid colour cycling. Sometimes revives stuck (not dead)
    subpixels when left running for 10-30 minutes. Contains flashing light."""
    img = np.empty((h, w, 3), dtype=np.uint8)
    img[:] = _FLASH_COLOURS[frame % len(_FLASH_COLOURS)]
    return img


def moving_bar(w: int, h: int, frame: int = 0) -> np.ndarray:
    """A white vertical bar sweeping across black. Trailing smear shows slow
    pixel response / ghosting; judder or tearing shows frame pacing issues."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    bar = max(4, w // 64)
    speed = max(1, w // 240)  # crosses the screen in ~4s at 60fps
    x = (frame * speed) % (w + bar) - bar
    img[:, max(0, x):max(0, x + bar)] = 255
    return img


FLASH_WARNING = ("WARNING: this pattern flashes rapidly. "
                 "Do not view if you are sensitive to flashing light.")

PATTERNS: list[Pattern] = [
    Pattern("black", "Black", "Lit/stuck pixels, backlight bleed, clouding",
            _solid((0, 0, 0))),
    Pattern("white", "White", "Dead pixels, dirt, uniformity",
            _solid((255, 255, 255))),
    Pattern("red", "Red", "Dead/stuck red subpixels", _solid((255, 0, 0))),
    Pattern("green", "Green", "Dead/stuck green subpixels",
            _solid((0, 255, 0))),
    Pattern("blue", "Blue", "Dead/stuck blue subpixels", _solid((0, 0, 255))),
    Pattern("gray", "50% gray", "Uniformity, dirty-screen effect, banding",
            _solid((128, 128, 128))),
    Pattern("checker1", "1px checkerboard",
            "1:1 pixel mapping; moire/blur means scaling", checkerboard),
    Pattern("grid", "Pixel grid + border",
            "Overscan (missing border edge), geometry, convergence",
            pixel_grid),
    Pattern("overscan", "Overscan rectangles",
            "How much of the image the display crops", overscan),
    Pattern("ramp", "Gray ramp", "Banding, bit depth, dithering", gray_ramp),
    Pattern("rgbramp", "RGB ramps", "Per-channel banding and tint",
            rgb_ramps),
    Pattern("steps", "Gray steps", "Black crush / white clipping",
            gray_steps),
    Pattern("bars", "Colour bars", "Colour reproduction, channel swaps",
            color_bars),
    Pattern("crosstalk", "Crosstalk boxes", "Crosstalk, image retention",
            crosstalk),
    Pattern("motion", "Moving bar", "Ghosting, response time, tearing",
            moving_bar, animated=True, fps=60),
    Pattern("flash", "Stuck-pixel flasher",
            "Attempt to revive stuck subpixels", stuck_pixel_flasher,
            animated=True, fps=30, warning=FLASH_WARNING),
]

BY_KEY: dict[str, Pattern] = {p.key: p for p in PATTERNS}
