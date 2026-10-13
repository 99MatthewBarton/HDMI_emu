# Architecture and design decisions

This document explains how the HDMI tester works, what each part is for, and
why it was built this way. It is meant to be read top to bottom by someone
learning the codebase.

- [What the program does](#what-the-program-does)
- [Scope and non-goals](#scope-and-non-goals)
- [How a frame reaches the display](#how-a-frame-reaches-the-display)
- [Module tour](#module-tour)
- [The test patterns, and what each one reveals](#the-test-patterns-and-what-each-one-reveals)
- [EDID primer](#edid-primer)
- [Defect marking and the report](#defect-marking-and-the-report)
- [Running on the Pi: install, boot service, GPIO](#running-on-the-pi-install-boot-service-gpio)
- [Design decisions](#design-decisions)
- [Testing strategy](#testing-strategy)
- [Known limitations and ideas for extension](#known-limitations-and-ideas-for-extension)

---

## What the program does

```
            HDMI cable (video →, EDID ←)
 ┌──────────────┐ ─────────────────────────────▶ ┌─────────────────┐
 │ Raspberry Pi │                                │ Display under   │
 │ hdmi-tester  │ ◀───────────────────────────── │ test            │
 └──────┬───────┘   DDC/I²C: EDID (what the      └─────────────────┘
        │           display says it supports)
   keyboard / GPIO button
        │
   defects.json (where you saw problems)
```

1. **Reads EDID**: the display's self-description, sent back to the Pi over
   the HDMI cable's DDC (I²C) wires. Tells you the panel's native resolution,
   whether it is really HDMI or DVI, and which modes it accepts.
2. **Shows test patterns** fullscreen, pixel-for-pixel, at the display's
   current mode.
3. **Records defects**: you move a crosshair to a bad pixel and press Enter;
   the coordinates go into a JSON report along with the EDID summary, so the
   report identifies which display it belongs to.

## Scope and non-goals

The project was originally described as an "HDMI emulator". It is really an
**HDMI pattern generator** (a *source*). The distinction matters when you go
looking for related tools:

| Term | What it is | This project? |
| --- | --- | --- |
| Pattern generator | Sends known images to a display so a human (or camera) can spot defects | **Yes** |
| EDID emulator | Pretends to be a display so a *source* (PC, console) sees a fixed EDID | No |
| HDMI analyzer | Measures the electrical/protocol signal (TMDS eye, jitter, HDCP, InfoFrames) | No |

Non-goals, with the reason for each:

- **Automatic defect detection.** The Pi can't see the screen. Automatic
  detection needs a camera and calibration, which would be a separate
  project (see [extensions](#known-limitations-and-ideas-for-extension)).
- **Signal-integrity testing.** The Pi's HDMI hardware gives software no
  access to the TMDS link. That needs an FPGA or a protocol analyzer.
- **HDR / 10-bit output.** Everything is 8-bit RGB. Dead-pixel and
  uniformity testing doesn't need more, and HDR output on the Pi isn't
  exposed in a usable way through SDL.

## How a frame reaches the display

```
patterns.py             display.py                     Linux kernel          Pi HDMI hardware
render(w, h, frame) ──▶ numpy array ──▶ pygame Surface ──▶ SDL "kmsdrm" ──▶ DRM/KMS (vc4 driver) ──▶ HDMI out
  (pure numpy)          frombuffer()   blit + overlay      page flip        scanout at current mode
```

- **DRM/KMS** (Direct Rendering Manager / Kernel Mode Setting) is how modern
  Linux drives display hardware. The Pi's `vc4` driver implements it. KMS owns
  the *mode* (resolution, refresh rate, timings) and scans a framebuffer out
  to the HDMI port.
- **SDL's `kmsdrm` backend** lets pygame draw into a KMS framebuffer
  directly, with no X11 or Wayland desktop. That is why Raspberry Pi OS Lite
  works. On a desktop session SDL uses the windowing system instead.
  `display.py` picks `kmsdrm` automatically when no `DISPLAY` or
  `WAYLAND_DISPLAY` is set.
- `set_mode((0, 0), FULLSCREEN)` tells SDL to **keep the current mode**, so
  the window size equals the mode and no scaling happens. This is essential:
  any scaling between the pattern and the panel blurs single-pixel patterns
  and makes dead-pixel coordinates meaningless.

The mode itself is chosen by the kernel at boot, normally the display's
EDID-preferred mode. To force a different one, add a `video=` argument to the
kernel command line. `hdmi-tester edid` prints the correct line for the
native timing.

## Module tour

All source lives in `src/hdmi_tester/`.

| Module | Responsibility | Depends on |
| --- | --- | --- |
| `patterns.py` | Pattern definitions and generators | numpy only |
| `edid.py` | EDID parsing, connector discovery via sysfs | stdlib only |
| `session.py` | Test state: current pattern, cursor, defects, report | patterns |
| `display.py` | pygame window, drawing, keyboard/GPIO input | pygame, session |
| `cli.py` | `hdmi-tester` command and subcommands | everything |

The dependencies point one way: `cli → display → session → patterns`, plus
`cli → edid`. Only `display.py` touches pygame, and it imports pygame inside
`Display.__init__`. So `edid`, `list` and `render`, and every test except
the display smoke test, work without SDL.

### `patterns.py`

Each pattern is a frozen `Pattern` dataclass:

```python
Pattern(key, name, purpose, render, animated=False, fps=0, warning=None)
```

`render(width, height, frame) -> np.ndarray` returns a `(height, width, 3)`
`uint8` RGB image. The contract is deliberately tiny: a pattern is a **pure
function** of size and frame number. That makes patterns trivially testable,
lets the `render` command save them as PNGs, and keeps them free of display
code.

Generators use numpy broadcasting (`np.ogrid`, slicing) instead of Python
loops, so even 4K frames take milliseconds. `PATTERNS` is the ordered list
the UI cycles through, and `BY_KEY` is the lookup used by `--pattern`.

To **add a pattern**, write a function with the `render` signature and
append a `Pattern` to `PATTERNS`. The parametrized test in
`tests/test_patterns.py` checks its shape and dtype at several sizes
automatically.

### `edid.py`

- `parse_edid(raw) -> Edid` decodes the 128-byte base block and any CTA-861
  extension blocks. It raises `EdidError` for data that isn't EDID, and
  records (rather than rejects) checksum errors, because a display with a
  corrupt EDID is exactly the kind of fault you want to report.
- `find_connectors()` lists `/sys/class/drm/card*-HDMI-*`. On a Pi with the
  KMS driver, each HDMI port appears there with a `status` file
  (`connected`/`disconnected`) and an `edid` file holding the raw bytes the
  kernel read over DDC. No I²C code or root access is needed.
- `kernel_video_arg()` turns a timing into a `video=HDMI-A-1:1920x1080@60`
  kernel argument.

See the [EDID primer](#edid-primer) for what the fields mean.

### `session.py`

`Session` holds all mutable test state and has **no pygame dependency**:

- current pattern index and animation frame
- info overlay on/off
- marking mode, cursor position (clamped to the screen)
- the list of `Defect(x, y, pattern, note)`
- `confirmed` / `blocked`: a pattern with a `warning` (the flasher) renders
  black until the user explicitly confirms. Leaving the pattern re-arms the
  gate.

It also builds the JSON report. Keeping this out of `display.py` means the
behaviour that matters (navigation, clamping, safety gate, report contents)
is covered by fast unit tests.

### `display.py`

`Display` is a thin shell around `Session`:

- **Setup**: chooses the SDL driver, opens a fullscreen (or `--windowed`)
  surface, reads the real size, and then creates the `Session` through a
  factory, because the resolution isn't known until the mode is open.
- **Drawing**: static patterns are rendered once and cached as Surfaces.
  Animated ones are re-rendered every frame. Then the overlays are drawn: info
  box, help, the marking crosshair, transient messages.
- **Crosshair**: drawn with a 3px gap around the target so the pixel being
  marked stays visible. Its colour is black or white, whichever contrasts with
  the pixel underneath.
- **Input**: `handle_key` maps keys to `Session` calls. In marking mode the
  arrow keys move the cursor instead of changing pattern.
- **Loop**: `run()` polls events, draws, and ticks the clock at the
  pattern's fps (or 30 fps for static patterns, which keeps input responsive
  without wasting CPU). On exit it saves the report if any defects were
  marked, so a quit never loses work.

### `cli.py`

`argparse` subcommands: `run`, `edid`, `list`, `render`. It also contains a
~15-line PNG writer (zlib + struct) so `render` needs no imaging library.

## The test patterns, and what each one reveals

Some vocabulary first:

- **Dead pixel**: never lights. Shows as a black dot on white and coloured
  screens.
- **Stuck pixel / subpixel**: always on in one colour. Shows as a coloured
  dot on black. Sometimes recoverable.
- **Hot pixel**: always fully lit. Shows as a white dot on black.
- **Subpixel**: each pixel is a red, green and blue element. Testing each
  primary on its own isolates a single bad subpixel that a white screen can
  hide.

| Key | Pattern | Look for |
| --- | --- | --- |
| `black` | Solid black | Stuck/hot pixels; backlight bleed and clouding at the edges (best in a dark room) |
| `white` | Solid white | Dead pixels; dust under the panel surface; brightness uniformity |
| `red` / `green` / `blue` | Primaries | Dead or stuck single subpixels |
| `gray` | 50% gray | Uniformity, "dirty screen effect", vignetting |
| `checker1` | 1px black/white checkerboard | Should look flat gray. Moire, blur or patches mean the display is **scaling** (not 1:1) |
| `grid` | 1px grid every 16px + 1px border | All four border edges visible = no overscan; straight lines = good geometry |
| `overscan` | Rectangles at 0 / 2.5 / 5 / 10% inset (white/red/green/blue) | The outermost fully visible rectangle tells you how much the display crops |
| `ramp` | Smooth black→white gradient | Banding (visible steps) from low bit depth or heavy processing |
| `rgbramp` | Red, green, blue and gray gradients | Per-channel banding, colour tint in the grays |
| `steps` | 32 discrete gray levels | Neighbouring dark steps merging = crushed blacks; bright ones = clipped whites |
| `bars` | 75% colour bars | Swapped or missing channels (wrong cable/colour-space negotiation) |
| `crosstalk` | Black and white boxes on gray | Shadows or streaks next to the boxes (crosstalk); boxes lingering after you switch away (image retention) |
| `motion` | White bar sweeping across black | Trailing smear (slow response/ghosting), tearing or judder |
| `flash` | Full-screen R/G/B/white/black cycling at 30 fps | Exercising stuck subpixels. **Photosensitivity warning**: gated behind Enter |

Why there is a **scaling/overscan check before the pixel checks**: if the
display scales the image, one source pixel no longer maps to one panel
pixel. A single dead pixel can then be hidden by interpolation, and the
coordinates you mark won't match the panel. Many TVs overscan by default.
Look for a "Just Scan", "Screen Fit" or "1:1" picture-size setting.

## EDID primer

**EDID** (Extended Display Identification Data) is a small binary blob, made
of 128-byte blocks, that every display provides over the HDMI cable's DDC
(I²C) lines. Sources use it to choose an output mode.

**Base block (block 0)**, as parsed by `parse_edid`:

| Bytes | Field |
| --- | --- |
| 0–7 | Fixed header `00 FF FF FF FF FF FF 00` |
| 8–9 | Manufacturer ID: three 5-bit letters (e.g. `DEL`, `SAM`) |
| 10–15 | Product code, serial number |
| 16–17 | Week/year of manufacture |
| 18–19 | EDID version (1.3 / 1.4) |
| 20 | Input type (bit 7 = digital) |
| 21–22 | Physical size in cm |
| 54–125 | Four 18-byte descriptors |
| 126 | Number of extension blocks |
| 127 | Checksum: all 128 bytes must sum to 0 mod 256 |

Each 18-byte descriptor is either:

- a **Detailed Timing Descriptor (DTD)**: pixel clock, active/blanking
  pixels, sync positions, image size in mm. **The first DTD is the preferred
  (native) mode**, and it is what the tester uses as "native".
- a **display descriptor** (first two bytes zero) whose tag says what it is:
  `0xFC` monitor name, `0xFF` serial string, `0xFD` range limits.

Refresh rate is not stored directly. It is computed as
`pixel_clock / (h_total × v_total)`, where total = active + blanking.

**CTA-861 extension (tag `0x02`)**. This is what makes a display "HDMI":

- Byte 3 flags: underscan of IT formats, basic audio, YCbCr 4:4:4 / 4:2:2.
- A **data block collection** follows. The tester decodes:
  - *Video Data Block*: a list of **VICs** (Video Identification Codes), the
    standard numbered modes (16 = 1080p60, 97 = 2160p60). On VICs 1–64, bit 7
    marks a "native" mode.
  - *Vendor-Specific Data Block* with HDMI's IEEE OUI `00-0C-03`. Its
    presence is what tells a source the sink is **HDMI rather than DVI**
    (without it there's no audio and only RGB). It optionally carries the max
    TMDS clock.
  - *HDMI Forum VSDB* (OUI `C4-5D-D8`): an HDMI 2.x sink. It carries the
    higher max TMDS rate (up to 600 MHz).
- More DTDs can follow the data blocks.

Things that are useful to notice in `hdmi-tester edid` output:

- **Checksum warnings**: a corrupt EDID causes "no signal" or wrong-mode
  problems that look like display faults.
- **Native mode ≠ what you expected**: wrong panel, wrong firmware, or a
  switch/extender that substitutes its own EDID.
- **"DVI (no HDMI VSDB)"** on an HDMI TV: often an adapter or a switch in the
  path.

For a complete decode, `edid-decode` (`apt install edid-decode`) handles every
block type. Save the bytes with `hdmi-tester edid --save display.bin` and run
`edid-decode display.bin`.

## Defect marking and the report

Press `M` to enter marking mode. Arrows move the crosshair (Shift = 10px),
Enter records the cursor position and the current pattern, and Backspace
undoes the last mark. The report (`--report`, default `defects.json`) looks
like this:

```json
{
  "generated": "2026-10-13T14:02:11",
  "resolution": [1920, 1080],
  "edid": "Monitor name:   DELL U2720Q\n...",
  "defect_count": 1,
  "defects": [{"x": 812, "y": 455, "pattern": "white", "note": ""}]
}
```

Coordinates are **panel pixels**, as long as the scaling/overscan check
passed. Recording the pattern tells you the defect type afterwards:
a mark made on `white` is a dead pixel, a mark on `black` is a stuck or hot
pixel. Including the EDID ties the report to a specific unit (model and
serial).

## Running on the Pi: install, boot service, GPIO

**`deploy/install.sh`**

- Installs numpy, pygame and gpiozero from **apt**, not pip. The Debian
  pygame build includes the `kmsdrm` SDL backend, and prebuilt packages avoid
  long or failing wheel builds on ARM.
- Creates a venv with `--system-site-packages` at `/opt/hdmi-tester/venv`.
  Bookworm marks the system Python as externally managed (PEP 668), so a
  venv is the supported way to install a package. Seeing the apt packages
  avoids duplicating them.
- Adds the user to `video` (DRM devices), `input` (keyboard via evdev without
  a desktop) and `gpio`.

**`deploy/hdmi-tester.service`** (with `--service`): a systemd unit that
takes over `tty1` (`Conflicts=getty@tty1.service`) and starts the tester at
boot. That turns the Pi into a dedicated appliance: power it on, patterns
appear. `Restart=on-failure` restarts it after a crash, but a deliberate quit
(Q) leaves it stopped. Run `sudo systemctl start hdmi-tester` or reboot to
bring it back.

**GPIO button** (`--button-pin N`, BCM numbering): one momentary button
between that pin and GND (gpiozero enables the internal pull-up). A short
press shows the next pattern, a 2 s hold the previous one. This lets you
test a display at a bench or in the field without a keyboard. Marking defects
and starting the flasher still need a keyboard.

**Forcing a mode**: append the printed `video=HDMI-A-1:WxH@Hz` to the single
line in `/boot/firmware/cmdline.txt` and reboot. Port names: on a Pi 4/5,
`HDMI-A-1` is the port nearest the USB-C power input. A Pi 4 additionally
needs `hdmi_enable_4kp60=1` in `config.txt` for 4K at 60 Hz.

## Design decisions

Each entry gives the decision, the alternatives considered, and why.

**1. Raspberry Pi + Linux, not FPGA, microcontroller or "any PC".**
An FPGA gives full control of HDMI timing and signal, but it is board-specific
HDL and far more work for the core goal of finding dead pixels. An
RP2040/RP2350 can bit-bang DVI, but only at about 640×480–720p, which is
useless for finding single dead pixels on a 4K panel. A generic PC works, but
gives less control over modes and can't be a cheap dedicated bench appliance.
The Pi hits 4K60 (Pi 4/5), exposes EDID through sysfs, has GPIO for a
button, and costs little.

**2. Python + numpy + pygame/SDL.**
Patterns are image arithmetic, which numpy expresses in a few lines and runs
fast. SDL's `kmsdrm` backend means no desktop is needed, and the same code
runs in a window on a laptop for development. Writing raw DRM/KMS ioctls (or
`/dev/fb0`) directly would remove one dependency but add a lot of fragile
low-level code. The fbdev path is also deprecated on current Pi kernels.

**3. Use the display's current mode; don't mode-set from the app.**
SDL's mode switching under kmsdrm is limited and varies between versions.
The kernel already picks the EDID-preferred (native) mode, and the `video=`
kernel argument is the documented, reliable override. The app tells you that
line instead of trying to change modes itself.

**4. Patterns are pure functions returning numpy arrays.**
They are testable without a display, can be exported to PNG (`render`), are
easy to add, and work at any resolution. The trade-off is that 4K animated
patterns are regenerated each frame on the CPU. That is fine at 30–60 fps
for these simple images, and static patterns are cached.

**5. Session state separated from pygame.**
All logic that can be wrong (navigation, clamping, safety gating, report
format) is in `Session` and unit-tested without SDL. `Display` only maps
events to calls and draws.

**6. EDID read from sysfs and parsed in-house, not via `edid-decode`.**
sysfs gives the raw bytes with no root or I²C code. A small parser keeps the
tester self-contained and lets it pull out exactly what it needs (native
timing, HDMI/DVI, VICs) for the summary and report. `edid-decode` is
recommended for full detail rather than reimplemented.

**7. Bad checksums are reported, not rejected.**
The parser's job here is diagnosis. A corrupt EDID is a finding about the
display, so it is surfaced as a warning and parsing continues.

**8. Flashing content is opt-in per visit.**
Full-screen colour cycling at 30 Hz is in the frequency range that can
trigger photosensitive seizures. The flasher renders black with a warning
until Enter is pressed, and re-arms whenever you leave it. A GPIO-only setup
can't start it, by design.

**9. Manual defect marking instead of camera-based detection.**
Manual marking is simple, reliable and needs no extra hardware, and a human
with a loupe is still the reference method for dead pixels. Automated
detection is listed as an extension below.

**10. Reports save automatically on quit.**
Losing marks to a stray Esc would be the most frustrating failure, so `run()`
saves in a `finally` block whenever defects exist.

## Testing strategy

`pytest` from the repo root (80 tests, about 1 s):

- `test_patterns.py`: every pattern at several sizes, including odd ones like
  641×479, has the right shape and dtype. Plus property checks: the
  checkerboard's neighbours all differ, the grid border is complete, the
  overscan rectangle sits at the right inset, the ramp spans 0–255, and so on.
- `test_edid.py`: parses a synthetic EDID built in `tests/conftest.py` from
  **real-world DTD byte sequences** (the standard CTA 1080p60 and 720p60
  timings) with a CTA extension that has VDB, HDMI VSDB and HF-VSDB. Also
  covers checksum detection, rejecting garbage, and connector discovery
  against a fake sysfs tree.
- `test_session.py`: navigation, the flasher gate, cursor clamping, and the
  report's contents.
- `test_cli.py`: PNG writer round-trip, and the `render`, `edid` and `list`
  commands.
- `test_display.py`: drives the real pygame loop with SDL's `dummy`
  (offscreen) driver. It steps through every pattern, marks a defect and
  checks that the report is saved.

What the tests **cannot** cover: actual kmsdrm output, keyboard input on a
bare console, and GPIO. Check those on a real Pi.

## Known limitations and ideas for extension

Limitations:

- Not yet validated on Raspberry Pi hardware. The kmsdrm, console-keyboard
  and systemd paths follow documented behaviour but need a hardware check.
- 8-bit RGB only: no 10/12-bit, HDR or YCbCr output selection.
- No in-app mode switching (see decision 3).
- The info overlay covers part of the screen. Toggle it off (I) before
  inspecting.
- The EDID parser covers common blocks only (no DisplayID, HDR static
  metadata, colorimetry or audio descriptors).

Possible extensions:

- **Camera-assisted detection**: photograph `black`/`white`/primaries with
  a Pi camera, and flag outlier pixels after aligning the image with the
  `grid` pattern.
- **Defect notes**: let the user type a note per mark (the `note` field
  already exists in the report).
- **HDMI-CEC** control (`cec-ctl`) to power on the TV and switch it to the
  Pi's input automatically.
- **Pixel-walk pattern**: a single lit pixel scanning the panel, for
  inspecting very small regions.
- **Report viewer**: render `defects.json` as an image of the panel with the
  marks drawn on it.
