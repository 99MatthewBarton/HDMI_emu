"""EDID reading and parsing.

Covers the base EDID block (identity, preferred/native timing, monitor name,
range limits) and the CTA-861 extension (HDMI vs DVI, supported VICs,
colour formats). Not a full EDID decoder; for exhaustive output use
``edid-decode``.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field

EDID_HEADER = bytes([0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00])
HDMI_OUI = 0x000C03       # HDMI Licensing, LLC (HDMI 1.x VSDB)
HDMI_FORUM_OUI = 0xC45DD8  # HDMI Forum (HDMI 2.x HF-VSDB)

# Common CTA-861 Video Identification Codes -> (width, height, refresh, interlaced)
VICS: dict[int, tuple[int, int, float, bool]] = {
    1: (640, 480, 60, False),
    2: (720, 480, 60, False), 3: (720, 480, 60, False),
    4: (1280, 720, 60, False),
    5: (1920, 1080, 60, True),
    16: (1920, 1080, 60, False),
    17: (720, 576, 50, False), 18: (720, 576, 50, False),
    19: (1280, 720, 50, False),
    20: (1920, 1080, 50, True),
    31: (1920, 1080, 50, False),
    32: (1920, 1080, 24, False),
    33: (1920, 1080, 25, False),
    34: (1920, 1080, 30, False),
    47: (1280, 720, 120, False),
    63: (1920, 1080, 120, False),
    64: (1920, 1080, 100, False),
    93: (3840, 2160, 24, False),
    94: (3840, 2160, 25, False),
    95: (3840, 2160, 30, False),
    96: (3840, 2160, 50, False),
    97: (3840, 2160, 60, False),
    98: (4096, 2160, 24, False),
    99: (4096, 2160, 25, False),
    100: (4096, 2160, 30, False),
    101: (4096, 2160, 50, False),
    102: (4096, 2160, 60, False),
    117: (3840, 2160, 100, False),
    118: (3840, 2160, 120, False),
}


class EdidError(ValueError):
    pass


@dataclass
class Timing:
    pixel_clock_khz: int
    h_active: int
    h_blank: int
    v_active: int
    v_blank: int
    h_sync_offset: int
    h_sync_width: int
    v_sync_offset: int
    v_sync_width: int
    interlaced: bool
    width_mm: int
    height_mm: int

    @property
    def refresh_hz(self) -> float:
        total = (self.h_active + self.h_blank) * (self.v_active + self.v_blank)
        if total == 0:
            return 0.0
        hz = self.pixel_clock_khz * 1000 / total
        return hz * 2 if self.interlaced else hz

    def __str__(self) -> str:
        scan = "i" if self.interlaced else "p"
        return (f"{self.h_active}x{self.v_active}{scan} @ "
                f"{self.refresh_hz:.2f} Hz ({self.pixel_clock_khz / 1000:.2f} MHz)")


@dataclass
class VideoMode:
    vic: int
    native: bool

    @property
    def description(self) -> str:
        info = VICS.get(self.vic)
        if info is None:
            return f"VIC {self.vic}"
        w, h, hz, inter = info
        return f"VIC {self.vic}: {w}x{h}{'i' if inter else 'p'}{hz:g}"


@dataclass
class Edid:
    raw: bytes
    manufacturer: str
    product_code: int
    serial_number: int
    manufacture_week: int
    manufacture_year: int
    version: str
    digital: bool
    screen_width_cm: int
    screen_height_cm: int
    name: str | None = None
    serial_string: str | None = None
    timings: list[Timing] = field(default_factory=list)
    v_rate_range: tuple[int, int] | None = None
    h_rate_range_khz: tuple[int, int] | None = None
    max_pixel_clock_mhz: int | None = None
    extension_count: int = 0
    checksum_errors: list[int] = field(default_factory=list)
    # CTA-861 extension
    has_cta: bool = False
    is_hdmi: bool = False
    hdmi_forum: bool = False
    max_tmds_mhz: int | None = None
    underscan: bool | None = None
    basic_audio: bool | None = None
    ycbcr444: bool | None = None
    ycbcr422: bool | None = None
    video_modes: list[VideoMode] = field(default_factory=list)

    @property
    def preferred_timing(self) -> Timing | None:
        """The first detailed timing; by spec this is the native mode."""
        return self.timings[0] if self.timings else None

    def summary(self) -> str:
        lines = [
            f"Monitor name:   {self.name or '(not provided)'}",
            f"Manufacturer:   {self.manufacturer}  product 0x{self.product_code:04X}",
            f"Serial:         {self.serial_string or self.serial_number or '(none)'}",
            f"Made:           week {self.manufacture_week}, {self.manufacture_year}",
            f"EDID version:   {self.version}",
            f"Input:          {'digital' if self.digital else 'analog'}",
        ]
        if self.screen_width_cm and self.screen_height_cm:
            diag_in = (self.screen_width_cm ** 2 + self.screen_height_cm ** 2) ** 0.5 / 2.54
            lines.append(f"Screen size:    {self.screen_width_cm} x "
                         f"{self.screen_height_cm} cm (~{diag_in:.0f}\")")
        pt = self.preferred_timing
        lines.append(f"Native mode:    {pt if pt else '(none)'}")
        for t in self.timings[1:]:
            lines.append(f"Other timing:   {t}")
        if self.v_rate_range:
            lines.append(f"V rate range:   {self.v_rate_range[0]}-{self.v_rate_range[1]} Hz")
        if self.h_rate_range_khz:
            lines.append(f"H rate range:   {self.h_rate_range_khz[0]}-"
                         f"{self.h_rate_range_khz[1]} kHz")
        if self.max_pixel_clock_mhz:
            lines.append(f"Max pixclk:     {self.max_pixel_clock_mhz} MHz")
        if self.has_cta:
            iface = "HDMI" if self.is_hdmi else "DVI (no HDMI VSDB)"
            if self.hdmi_forum:
                iface += " 2.x (HF-VSDB)"
            lines.append(f"Interface:      {iface}")
            if self.max_tmds_mhz:
                lines.append(f"Max TMDS:       {self.max_tmds_mhz} MHz")
            fmts = ["RGB"]
            if self.ycbcr444:
                fmts.append("YCbCr 4:4:4")
            if self.ycbcr422:
                fmts.append("YCbCr 4:2:2")
            lines.append(f"Colour formats: {', '.join(fmts)}")
            lines.append(f"Basic audio:    {'yes' if self.basic_audio else 'no'}")
            lines.append(f"Underscans IT:  {'yes' if self.underscan else 'no'}")
            if self.video_modes:
                lines.append("Video modes:")
                for m in self.video_modes:
                    lines.append(f"  {m.description}{'  (native)' if m.native else ''}")
        else:
            lines.append("Interface:      DVI/DisplayPort-style (no CTA extension)")
        if self.checksum_errors:
            blocks = ", ".join(str(b) for b in self.checksum_errors)
            lines.append(f"WARNING: bad checksum in block(s) {blocks}")
        return "\n".join(lines)


def _parse_dtd(d: bytes) -> Timing:
    return Timing(
        pixel_clock_khz=int.from_bytes(d[0:2], "little") * 10,
        h_active=d[2] | (d[4] >> 4) << 8,
        h_blank=d[3] | (d[4] & 0x0F) << 8,
        v_active=d[5] | (d[7] >> 4) << 8,
        v_blank=d[6] | (d[7] & 0x0F) << 8,
        h_sync_offset=d[8] | ((d[11] >> 6) & 0x3) << 8,
        h_sync_width=d[9] | ((d[11] >> 4) & 0x3) << 8,
        v_sync_offset=(d[10] >> 4) | ((d[11] >> 2) & 0x3) << 4,
        v_sync_width=(d[10] & 0x0F) | (d[11] & 0x3) << 4,
        width_mm=d[12] | (d[14] >> 4) << 8,
        height_mm=d[13] | (d[14] & 0x0F) << 8,
        interlaced=bool(d[17] & 0x80),
    )


def _descriptor_text(d: bytes) -> str:
    return d[5:18].split(b"\x0a")[0].decode("ascii", errors="replace").strip()


def _parse_cta(block: bytes, edid: Edid) -> None:
    edid.has_cta = True
    dtd_offset = block[2]
    flags = block[3]
    edid.underscan = bool(flags & 0x80)
    edid.basic_audio = bool(flags & 0x40)
    edid.ycbcr444 = bool(flags & 0x20)
    edid.ycbcr422 = bool(flags & 0x10)

    # Data block collection sits between byte 4 and the DTD offset.
    end = dtd_offset if 4 <= dtd_offset <= 127 else 4
    i = 4
    while i < end:
        tag, length = block[i] >> 5, block[i] & 0x1F
        payload = block[i + 1:i + 1 + length]
        if tag == 2:  # Video data block: Short Video Descriptors
            for b in payload:
                if 1 <= b <= 127:
                    edid.video_modes.append(VideoMode(b, native=False))
                elif 129 <= b <= 192:
                    edid.video_modes.append(VideoMode(b & 0x7F, native=True))
                elif 193 <= b <= 253:
                    edid.video_modes.append(VideoMode(b, native=False))
        elif tag == 3 and length >= 3:  # Vendor-specific data block
            oui = int.from_bytes(payload[0:3], "little")
            if oui == HDMI_OUI:
                edid.is_hdmi = True
                if length >= 7 and payload[6]:
                    edid.max_tmds_mhz = max(edid.max_tmds_mhz or 0, payload[6] * 5)
            elif oui == HDMI_FORUM_OUI:
                edid.hdmi_forum = True
                if length >= 5 and payload[4]:
                    edid.max_tmds_mhz = max(edid.max_tmds_mhz or 0, payload[4] * 5)
        i += 1 + length

    # Additional detailed timings follow the data blocks.
    if dtd_offset >= 4:
        j = dtd_offset
        while j + 18 <= 127 and block[j] | block[j + 1]:
            edid.timings.append(_parse_dtd(block[j:j + 18]))
            j += 18


def parse_edid(raw: bytes) -> Edid:
    if len(raw) < 128:
        raise EdidError(f"EDID too short: {len(raw)} bytes")
    if raw[:8] != EDID_HEADER:
        raise EdidError("EDID header missing")

    mfg = int.from_bytes(raw[8:10], "big")
    manufacturer = "".join(
        chr(((mfg >> shift) & 0x1F) + ord("A") - 1) for shift in (10, 5, 0)
    )
    edid = Edid(
        raw=bytes(raw),
        manufacturer=manufacturer,
        product_code=int.from_bytes(raw[10:12], "little"),
        serial_number=int.from_bytes(raw[12:16], "little"),
        manufacture_week=raw[16],
        manufacture_year=raw[17] + 1990,
        version=f"{raw[18]}.{raw[19]}",
        digital=bool(raw[20] & 0x80),
        screen_width_cm=raw[21],
        screen_height_cm=raw[22],
        extension_count=raw[126],
    )

    for off in range(54, 126, 18):
        d = raw[off:off + 18]
        if d[0] | d[1]:
            edid.timings.append(_parse_dtd(d))
            continue
        tag = d[3]
        if tag == 0xFC:
            edid.name = _descriptor_text(d)
        elif tag == 0xFF:
            edid.serial_string = _descriptor_text(d)
        elif tag == 0xFD:
            edid.v_rate_range = (d[5], d[6])
            edid.h_rate_range_khz = (d[7], d[8])
            edid.max_pixel_clock_mhz = d[9] * 10

    n_blocks = min(1 + edid.extension_count, len(raw) // 128)
    for b in range(n_blocks):
        block = raw[b * 128:(b + 1) * 128]
        if sum(block) % 256 != 0:
            edid.checksum_errors.append(b)
        if b > 0 and block[0] == 0x02:
            _parse_cta(block, edid)

    return edid


@dataclass
class Connector:
    name: str        # e.g. "HDMI-A-1"
    path: str        # sysfs directory
    connected: bool

    def read_edid(self) -> bytes:
        with open(os.path.join(self.path, "edid"), "rb") as f:
            return f.read()


def find_connectors(sysfs_root: str = "/sys/class/drm") -> list[Connector]:
    """List HDMI connectors exposed by the kernel DRM driver (vc4-kms-v3d on
    a Raspberry Pi)."""
    connectors = []
    for path in sorted(glob.glob(os.path.join(sysfs_root, "card*-HDMI-*"))):
        name = os.path.basename(path).split("-", 1)[1]
        try:
            with open(os.path.join(path, "status")) as f:
                connected = f.read().strip() == "connected"
        except OSError:
            connected = False
        connectors.append(Connector(name, path, connected))
    return connectors


def kernel_video_arg(connector: str, timing: Timing) -> str:
    """The ``video=`` kernel command-line argument that forces ``timing``.
    Append it to /boot/firmware/cmdline.txt on Raspberry Pi OS."""
    hz = round(timing.refresh_hz)
    scan = "i" if timing.interlaced else ""
    return f"video={connector}:{timing.h_active}x{timing.v_active}@{hz}{scan}"
