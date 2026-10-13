"""Test-session state, independent of any display backend.

The display loop translates key presses into calls on :class:`Session`, which
keeps track of the current pattern, the defect-marking cursor and the defects
recorded so far. Keeping this free of pygame makes it unit-testable.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import asdict, dataclass, field

from .patterns import PATTERNS, Pattern


@dataclass
class Defect:
    x: int
    y: int
    pattern: str
    note: str = ""


@dataclass
class Session:
    width: int
    height: int
    patterns: list[Pattern] = field(default_factory=lambda: list(PATTERNS))
    index: int = 0
    frame: int = 0
    show_info: bool = True
    marking: bool = False
    # Patterns with a warning (flashing) stay blank until confirmed.
    confirmed: bool = False
    cursor: tuple[int, int] = (0, 0)
    defects: list[Defect] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cursor = (self.width // 2, self.height // 2)

    @property
    def pattern(self) -> Pattern:
        return self.patterns[self.index]

    def _go(self, index: int) -> None:
        self.index = index % len(self.patterns)
        self.frame = 0
        self.confirmed = False

    @property
    def blocked(self) -> bool:
        """True while a pattern's warning is awaiting confirmation."""
        return self.pattern.warning is not None and not self.confirmed

    def confirm(self) -> None:
        self.confirmed = True
        self.frame = 0

    def next(self) -> None:
        self._go(self.index + 1)

    def prev(self) -> None:
        self._go(self.index - 1)

    def select(self, key: str) -> None:
        for i, p in enumerate(self.patterns):
            if p.key == key:
                self._go(i)
                return
        raise KeyError(key)

    def toggle_info(self) -> None:
        self.show_info = not self.show_info

    def toggle_marking(self) -> None:
        self.marking = not self.marking

    def move_cursor(self, dx: int, dy: int) -> None:
        x = min(max(self.cursor[0] + dx, 0), self.width - 1)
        y = min(max(self.cursor[1] + dy, 0), self.height - 1)
        self.cursor = (x, y)

    def mark(self, note: str = "") -> Defect:
        d = Defect(self.cursor[0], self.cursor[1], self.pattern.key, note)
        self.defects.append(d)
        return d

    def undo_mark(self) -> Defect | None:
        return self.defects.pop() if self.defects else None

    def report(self, edid_summary: str | None = None) -> dict:
        return {
            "generated": _dt.datetime.now().isoformat(timespec="seconds"),
            "resolution": [self.width, self.height],
            "edid": edid_summary,
            "defect_count": len(self.defects),
            "defects": [asdict(d) for d in self.defects],
        }

    def save_report(self, path: str, edid_summary: str | None = None) -> None:
        with open(path, "w") as f:
            json.dump(self.report(edid_summary), f, indent=2)
            f.write("\n")
