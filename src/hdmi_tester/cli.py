"""Command-line entry point: ``hdmi-tester <command>``."""

from __future__ import annotations

import argparse
import os
import struct
import sys
import zlib

import numpy as np

from . import edid as edid_mod
from .patterns import BY_KEY, PATTERNS


def _parse_size(text: str) -> tuple[int, int]:
    try:
        w, h = (int(v) for v in text.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected WIDTHxHEIGHT, got {text!r}")
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError("size must be positive")
    return w, h


def write_png(path: str, img: np.ndarray) -> None:
    """Minimal RGB PNG writer so ``render`` needs no imaging library."""
    h, w, _ = img.shape
    rows = np.hstack([np.zeros((h, 1), np.uint8), img.reshape(h, w * 3)])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(rows.tobytes(), 6)))
        f.write(chunk(b"IEND", b""))


def _load_edid(args) -> tuple[edid_mod.Edid | None, str | None, str]:
    """Returns (parsed EDID, connector name, status message)."""
    if getattr(args, "edid_file", None):
        with open(args.edid_file, "rb") as f:
            return edid_mod.parse_edid(f.read()), None, f"EDID from {args.edid_file}"
    connectors = edid_mod.find_connectors()
    if getattr(args, "connector", None):
        connectors = [c for c in connectors if c.name == args.connector]
    connected = [c for c in connectors if c.connected]
    if not connected:
        return None, None, "No connected HDMI display found in /sys/class/drm"
    conn = connected[0]
    raw = conn.read_edid()
    if not raw:
        return None, conn.name, f"{conn.name} is connected but returned no EDID"
    return edid_mod.parse_edid(raw), conn.name, f"EDID from {conn.name}"


def cmd_list(args) -> int:
    for p in PATTERNS:
        flag = " (animated)" if p.animated else ""
        print(f"{p.key:10s} {p.name}{flag}\n{'':10s} {p.purpose}")
    return 0


def cmd_edid(args) -> int:
    try:
        parsed, conn, status = _load_edid(args)
    except (OSError, edid_mod.EdidError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(status)
    if parsed is None:
        return 1
    if args.raw:
        for off in range(0, len(parsed.raw), 16):
            print(f"{off:04x}  {parsed.raw[off:off + 16].hex(' ')}")
    print(parsed.summary())
    pt = parsed.preferred_timing
    if pt:
        print("\nTo force the native mode on Raspberry Pi OS, append to "
              "/boot/firmware/cmdline.txt:")
        print(f"  {edid_mod.kernel_video_arg(conn or 'HDMI-A-1', pt)}")
    if args.save:
        with open(args.save, "wb") as f:
            f.write(parsed.raw)
        print(f"\nRaw EDID saved to {args.save}")
    return 0


def cmd_render(args) -> int:
    keys = args.pattern or [p.key for p in PATTERNS]
    os.makedirs(args.out, exist_ok=True)
    w, h = args.size
    for key in keys:
        if key not in BY_KEY:
            print(f"error: unknown pattern {key!r}", file=sys.stderr)
            return 2
        path = os.path.join(args.out, f"{key}.png")
        write_png(path, BY_KEY[key].render(w, h, args.frame))
        print(path)
    return 0


def cmd_run(args) -> int:
    from .display import Display
    from .session import Session

    summary = None
    if not args.no_edid:
        try:
            parsed, _, status = _load_edid(args)
        except (OSError, edid_mod.EdidError) as e:
            parsed, status = None, f"EDID unreadable: {e}"
        print(status, file=sys.stderr)
        if parsed:
            summary = parsed.summary()
            print(summary, file=sys.stderr)

    if args.pattern and args.pattern not in BY_KEY:
        print(f"error: unknown pattern {args.pattern!r}", file=sys.stderr)
        return 2

    def make_session(w: int, h: int) -> Session:
        s = Session(w, h)
        if args.pattern:
            s.select(args.pattern)
        return s

    display = Display(make_session, edid_summary=summary, report_path=args.report,
                      windowed=args.windowed, button_pin=args.button_pin)
    session = display.run()
    if session.defects:
        print(f"{len(session.defects)} defect(s) saved to {args.report}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hdmi-tester",
                                description="HDMI display test pattern generator")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="show test patterns fullscreen")
    run.add_argument("--pattern", help="pattern to start on (see 'list')")
    run.add_argument("--report", default="defects.json",
                     help="where marked defects are saved (default: %(default)s)")
    run.add_argument("--windowed", type=_parse_size, metavar="WxH",
                     help="run in a window instead of fullscreen (for development)")
    run.add_argument("--button-pin", type=int, metavar="GPIO",
                     help="GPIO pin of a push button for next/prev pattern")
    run.add_argument("--no-edid", action="store_true", help="skip reading EDID")
    run.add_argument("--connector", help="DRM connector name, e.g. HDMI-A-1")
    run.add_argument("--edid-file", help=argparse.SUPPRESS)
    run.set_defaults(func=cmd_run)

    ed = sub.add_parser("edid", help="read and decode the display's EDID")
    ed.add_argument("--connector", help="DRM connector name, e.g. HDMI-A-2")
    ed.add_argument("--edid-file", help="decode a saved EDID binary instead")
    ed.add_argument("--save", metavar="PATH", help="save raw EDID bytes")
    ed.add_argument("--raw", action="store_true", help="also print hex dump")
    ed.set_defaults(func=cmd_edid)

    ls = sub.add_parser("list", help="list available patterns")
    ls.set_defaults(func=cmd_list)

    rd = sub.add_parser("render", help="save patterns as PNG files")
    rd.add_argument("--size", type=_parse_size, default=(1920, 1080), metavar="WxH")
    rd.add_argument("--out", default="patterns", help="output directory")
    rd.add_argument("--frame", type=int, default=0, help="frame for animated patterns")
    rd.add_argument("pattern", nargs="*", help="pattern keys (default: all)")
    rd.set_defaults(func=cmd_render)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
