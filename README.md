# HDMI display tester

A Raspberry Pi based **test pattern generator** for checking HDMI displays for
dead/stuck pixels, uniformity problems, banding, overscan, scaling and motion
artifacts. It also reads the display's **EDID** to report what the display says
about itself (native resolution, HDMI version, supported modes).

Plug a Pi into the display, boot it, step through the patterns with a keyboard
(or a single GPIO button), mark any defects you see, and get a JSON report.

> **Terminology:** this is an HDMI *source* (it sends a signal to the display).
> It does not emulate a display, and it does not measure the electrical HDMI
> signal. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#scope-and-non-goals).

## Hardware

- Raspberry Pi 4 or 5 (a Pi 3 works for displays up to 1080p)
- Micro-HDMI → HDMI cable (Pi 4/5) to the display under test
- USB keyboard, and/or a momentary push button between a GPIO pin and GND
- Raspberry Pi OS **Lite** (Bookworm or later). A desktop image works too, but
  Lite boots straight to the patterns with nothing else drawn on screen.

## Install (on the Pi)

```sh
git clone <this repo> hdmi_emu && cd hdmi_emu
./deploy/install.sh                       # CLI only
./deploy/install.sh --service             # also start automatically on boot
./deploy/install.sh --service --button-pin 17   # with a button on GPIO17
```

## Usage

```sh
hdmi-tester edid               # decode the connected display's EDID
hdmi-tester list               # list patterns and what each one finds
hdmi-tester run                # fullscreen patterns on HDMI
hdmi-tester run --pattern white --report ~/panel42.json
hdmi-tester render --size 3840x2160 --out patterns/   # save patterns as PNGs
```

On a development machine, `hdmi-tester run --windowed 1280x720` runs it in a
window.

### Controls

| Key | Action |
| --- | --- |
| Right / Space / N | next pattern |
| Left / P | previous pattern |
| I | toggle info overlay (pattern name, purpose, resolution) |
| H | toggle help |
| M | toggle defect-marking mode |
| Arrows (marking mode) | move cursor 1px (hold Shift for 10px) |
| Enter (marking mode) | record a defect at the cursor |
| Backspace (marking mode) | remove the last defect |
| Enter (on a flashing pattern) | start the flashing pattern |
| S | save report now |
| Q / Esc | quit (saves the report if any defects were marked) |

GPIO button: short press = next pattern, hold 2 s = previous pattern.

**Turn the info overlay off (I) before you inspect a pattern.** It covers the
top-left corner of the screen.

### Suggested test procedure

1. `hdmi-tester edid`: confirm the display reports the native resolution you
   expect. If the Pi isn't outputting that mode, force it (the command prints
   the `video=` line to add).
2. **checker1** and **grid**: the checkerboard should look like a flat even
   gray, and all four edges of the grid border should be visible. Moire or
   blur means the display is scaling. A missing edge means it is overscanning.
   Fix this first, otherwise one "pixel" in the other tests is not one panel
   pixel.
3. **black, white, red, green, blue, gray**: look for single wrong pixels up
   close. Mark each one (M, move, Enter).
4. **ramp, rgbramp, steps**: look for banding and crushed blacks.
5. **crosstalk, motion**: look for ghosting and smearing.
6. **flash** (optional): may revive *stuck* pixels if left running for 10–30
   minutes. It cannot fix dead pixels.

## Development

```sh
pip install -e '.[test]'
pytest
```

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the program works
and why it is built this way.
