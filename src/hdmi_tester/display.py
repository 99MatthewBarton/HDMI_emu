"""Fullscreen output via pygame/SDL.

On Raspberry Pi OS Lite (no desktop) SDL's ``kmsdrm`` driver draws straight to
the HDMI output through the kernel's DRM/KMS interface. On a desktop it uses
the normal windowing system. Either way the display's *current* mode is used,
so the pattern is rendered 1:1 at the resolution the display was set to.
"""

from __future__ import annotations

import os
import time

import numpy as np

from .session import Session

HELP = [
    "Right/Space next   Left prev   I info   H help",
    "M mark mode: arrows move (Shift x10), Enter mark, Backspace undo",
    "S save report   Q/Esc quit (saves report)",
]


def _to_surface(pygame, img: np.ndarray):
    h, w, _ = img.shape
    return pygame.image.frombuffer(np.ascontiguousarray(img).tobytes(), (w, h), "RGB")


def _contrast(rgb) -> tuple[int, int, int]:
    r, g, b = rgb[:3]
    return (0, 0, 0) if 0.299 * r + 0.587 * g + 0.114 * b > 128 else (255, 255, 255)


class Display:
    def __init__(self, session_factory, edid_summary: str | None = None,
                 report_path: str = "defects.json", windowed: tuple[int, int] | None = None,
                 button_pin: int | None = None):
        import pygame  # imported lazily so pattern/EDID code needs no SDL

        self.pygame = pygame
        if "SDL_VIDEODRIVER" not in os.environ and not os.environ.get("DISPLAY") \
                and not os.environ.get("WAYLAND_DISPLAY"):
            os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
        pygame.display.init()
        pygame.font.init()
        if windowed:
            self.screen = pygame.display.set_mode(windowed)
        else:
            # (0, 0) = keep the display's current mode; no scaling.
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
        pygame.display.set_caption("HDMI tester")
        w, h = self.screen.get_size()
        self.session: Session = session_factory(w, h)
        self.edid_summary = edid_summary
        self.report_path = report_path
        self.font = pygame.font.Font(None, max(20, h // 40))
        self.clock = pygame.time.Clock()
        self.show_help = False
        self.message: tuple[str, float] | None = None
        self._cache: dict[str, object] = {}
        self._button_events: list[str] = []
        self._button = self._setup_button(button_pin) if button_pin is not None else None

    # -- GPIO ---------------------------------------------------------------

    def _setup_button(self, pin: int):
        """Optional push button on a GPIO pin: short press = next pattern,
        hold 2s = previous. Lets the tester run without a keyboard."""
        try:
            from gpiozero import Button
        except ImportError:
            self.flash("gpiozero not installed; button disabled")
            return None
        btn = Button(pin, hold_time=2)
        held = {"v": False}

        def on_held():
            held["v"] = True
            self._button_events.append("prev")

        def on_released():
            if not held["v"]:
                self._button_events.append("next")
            held["v"] = False

        btn.when_held = on_held
        btn.when_released = on_released
        return btn

    # -- drawing ------------------------------------------------------------

    def flash(self, text: str, seconds: float = 2.0) -> None:
        self.message = (text, time.monotonic() + seconds)

    def _pattern_surface(self):
        s = self.session
        p = s.pattern
        w, h = s.width, s.height
        if s.blocked:
            return None
        if p.animated:
            return _to_surface(self.pygame, p.render(w, h, s.frame))
        if p.key not in self._cache:
            self._cache[p.key] = _to_surface(self.pygame, p.render(w, h, 0))
        return self._cache[p.key]

    def _text_box(self, lines: list[str], pos: tuple[int, int]) -> None:
        pygame = self.pygame
        rendered = [self.font.render(t, True, (255, 255, 255)) for t in lines]
        pad = 6
        bw = max(r.get_width() for r in rendered) + 2 * pad
        bh = sum(r.get_height() for r in rendered) + 2 * pad
        box = pygame.Surface((bw, bh))
        box.set_alpha(200)
        box.fill((0, 0, 0))
        self.screen.blit(box, pos)
        y = pos[1] + pad
        for r in rendered:
            self.screen.blit(r, (pos[0] + pad, y))
            y += r.get_height()

    def _draw_cursor(self) -> None:
        """Crosshair with a gap so the marked pixel itself stays visible."""
        x, y = self.session.cursor
        colour = _contrast(self.screen.get_at((x, y)))
        gap, arm = 3, 15
        line = self.pygame.draw.line
        line(self.screen, colour, (x - gap - arm, y), (x - gap, y))
        line(self.screen, colour, (x + gap, y), (x + gap + arm, y))
        line(self.screen, colour, (x, y - gap - arm), (x, y - gap))
        line(self.screen, colour, (x, y + gap), (x, y + gap + arm))

    def draw(self) -> None:
        s = self.session
        surface = self._pattern_surface()
        if surface is None:
            self.screen.fill((0, 0, 0))
            self._text_box([s.pattern.name, s.pattern.warning,
                            "Press Enter to start, Right/Space to skip."],
                           (10, s.height // 3))
            self.pygame.display.flip()
            return
        self.screen.blit(surface, (0, 0))
        if s.marking:
            self._draw_cursor()
            self._text_box([f"MARK ({s.cursor[0]}, {s.cursor[1]})  "
                            f"defects: {len(s.defects)}"],
                           (10, s.height - self.font.get_linesize() - 22))
        if s.show_info:
            p = s.pattern
            self._text_box([f"[{s.index + 1}/{len(s.patterns)}] {p.name}",
                            p.purpose, f"{s.width}x{s.height}"], (10, 10))
        if self.show_help:
            self._text_box(HELP, (10, s.height // 2))
        if self.message:
            text, until = self.message
            if time.monotonic() < until:
                self._text_box([text], (s.width // 2 - 200, s.height // 2))
            else:
                self.message = None
        self.pygame.display.flip()

    # -- input --------------------------------------------------------------

    def _change_pattern(self, step: int) -> None:
        if step > 0:
            self.session.next()
        else:
            self.session.prev()

    def save(self) -> None:
        self.session.save_report(self.report_path, self.edid_summary)
        self.flash(f"Saved {len(self.session.defects)} defect(s) to {self.report_path}")

    def handle_key(self, event) -> bool:
        """Returns False when the app should exit."""
        pg = self.pygame
        s = self.session
        k = event.key
        step = 10 if event.mod & pg.KMOD_SHIFT else 1
        if k in (pg.K_q, pg.K_ESCAPE):
            return False
        if s.marking and k in (pg.K_LEFT, pg.K_RIGHT, pg.K_UP, pg.K_DOWN):
            dx = {pg.K_LEFT: -step, pg.K_RIGHT: step}.get(k, 0)
            dy = {pg.K_UP: -step, pg.K_DOWN: step}.get(k, 0)
            s.move_cursor(dx, dy)
        elif k in (pg.K_RIGHT, pg.K_SPACE, pg.K_n):
            self._change_pattern(1)
        elif k in (pg.K_LEFT, pg.K_p):
            self._change_pattern(-1)
        elif k == pg.K_TAB:
            self._change_pattern(-1 if event.mod & pg.KMOD_SHIFT else 1)
        elif k == pg.K_i:
            s.toggle_info()
        elif k == pg.K_h:
            self.show_help = not self.show_help
        elif k == pg.K_m:
            s.toggle_marking()
        elif k in (pg.K_RETURN, pg.K_KP_ENTER) and s.blocked:
            s.confirm()
        elif k in (pg.K_RETURN, pg.K_KP_ENTER) and s.marking:
            d = s.mark()
            self.flash(f"Marked ({d.x}, {d.y}) on {d.pattern}")
        elif k == pg.K_BACKSPACE and s.marking:
            d = s.undo_mark()
            self.flash(f"Removed ({d.x}, {d.y})" if d else "No marks to remove")
        elif k == pg.K_s:
            self.save()
        return True

    def run(self, max_frames: int | None = None) -> Session:
        pg = self.pygame
        running = True
        frames = 0
        try:
            while running:
                for event in pg.event.get():
                    if event.type == pg.QUIT:
                        running = False
                    elif event.type == pg.KEYDOWN:
                        running = self.handle_key(event) and running
                while self._button_events:
                    self._change_pattern(1 if self._button_events.pop(0) == "next" else -1)
                self.draw()
                p = self.session.pattern
                self.clock.tick(p.fps if p.animated and not self.session.blocked else 30)
                self.session.frame += 1
                frames += 1
                if max_frames is not None and frames >= max_frames:
                    running = False
        finally:
            if self.session.defects:
                self.session.save_report(self.report_path, self.edid_summary)
            pg.quit()
        return self.session
