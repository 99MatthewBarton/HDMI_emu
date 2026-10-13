"""Smoke test of the pygame loop using SDL's offscreen dummy driver."""

import os

import pytest

pygame = pytest.importorskip("pygame")

from hdmi_tester.display import Display  # noqa: E402
from hdmi_tester.session import Session  # noqa: E402


@pytest.fixture(autouse=True)
def dummy_video(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")


def _key(key, mod=0):
    return pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod)


def test_cycles_every_pattern_and_marks(tmp_path):
    report = tmp_path / "defects.json"
    d = Display(Session, report_path=str(report), windowed=(160, 90))
    s = d.session
    for _ in range(len(s.patterns)):
        if s.blocked:
            d.handle_key(_key(pygame.K_RETURN))
        d.draw()
        s.frame += 1
        d.handle_key(_key(pygame.K_RIGHT))
    d.handle_key(_key(pygame.K_m))
    d.handle_key(_key(pygame.K_RIGHT, pygame.KMOD_SHIFT))
    d.draw()
    d.handle_key(_key(pygame.K_RETURN))
    assert s.defects[0].x == 90
    assert d.handle_key(_key(pygame.K_q)) is False
    d.run(max_frames=1)
    assert report.exists()
