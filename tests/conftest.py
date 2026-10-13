import pytest

# Standard CTA-861 1920x1080p60 detailed timing descriptor (148.5 MHz),
# as found in real monitor EDIDs, with a 598x336 mm image size.
DTD_1080P60 = bytes.fromhex("023a801871382d40582c4500 565021 00001e".replace(" ", ""))
# 1280x720p60 (74.25 MHz)
DTD_720P60 = bytes.fromhex("011d007251d01e206e285500 565021 00001e".replace(" ", ""))


def _text_descriptor(tag: int, text: str) -> bytes:
    body = text.encode("ascii")[:13]
    if len(body) < 13:
        body += b"\x0a" + b"\x20" * (12 - len(body))
    return bytes([0, 0, 0, tag, 0]) + body


def _finish(block: bytearray) -> bytes:
    block[127] = (-sum(block[:127])) % 256
    return bytes(block)


def build_edid(with_cta: bool = True, name: str = "TESTMON") -> bytes:
    b = bytearray(128)
    b[0:8] = bytes([0, 255, 255, 255, 255, 255, 255, 0])
    b[8:10] = (0x5274).to_bytes(2, "big")         # "TST"
    b[10:12] = (0x1234).to_bytes(2, "little")
    b[12:16] = (987654).to_bytes(4, "little")
    b[16], b[17] = 12, 2023 - 1990
    b[18], b[19] = 1, 3
    b[20] = 0x80                                  # digital input
    b[21], b[22] = 60, 34
    b[54:72] = DTD_1080P60
    b[72:90] = _text_descriptor(0xFC, name)
    b[90:108] = _text_descriptor(0xFF, "SN0001")
    # Range limits: 56-76 Hz V, 30-83 kHz H, 170 MHz max pixel clock.
    b[108:126] = bytes([0, 0, 0, 0xFD, 0, 56, 76, 30, 83, 17]) + b"\x00\x0a" + b"\x20" * 6
    b[126] = 1 if with_cta else 0
    base = _finish(b)
    if not with_cta:
        return base

    e = bytearray(128)
    e[0], e[1] = 0x02, 0x03
    e[3] = 0x80 | 0x40 | 0x20 | 0x10              # underscan, audio, 444, 422
    vdb = bytes([(2 << 5) | 4, 0x80 | 16, 4, 31, 97])  # 1080p60 native, 720p60, 1080p50, 2160p60
    hdmi_vsdb = bytes([(3 << 5) | 7, 0x03, 0x0C, 0x00, 0x10, 0x00, 0x00, 60])  # 300 MHz
    hf_vsdb = bytes([(3 << 5) | 5, 0xD8, 0x5D, 0xC4, 0x01, 120])               # 600 MHz
    blocks = vdb + hdmi_vsdb + hf_vsdb
    e[4:4 + len(blocks)] = blocks
    e[2] = 4 + len(blocks)
    e[e[2]:e[2] + 18] = DTD_720P60
    return base + _finish(e)


@pytest.fixture
def edid_bytes():
    return build_edid()
