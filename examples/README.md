# Lightshow Examples & Demos

This directory contains standalone lighting shows and hardware diagnostic scripts built with `lightshow`. Each script includes an animated vector SVG preview rendered right beside it.

## Example Shows & Demos

| Script | Animated Preview | Target Rig | Description |
| :--- | :--- | :--- | :--- |
| [`demo_disco_16par.py`](./demo_disco_16par.py) | [Preview](./demo_disco_16par.svg) | 16x PARs (2x8) | 30-second 5-movement disco extravaganza show featuring counter-chases, checkerboards, mirror ripples, dual-helix rainbow wheels, and peak-time strobe stabs. |
| [`demo_show.py`](./demo_show.py) | [Preview](./demo_show.svg) | 4x PARs + BCL-40 Bar | 4-movement classic show: warm-up pulse intro, spatial rainbow wave, ping-pong cyan/magenta chase, and odd/even red-blue duel with white strobe bursts. |
| [`demo_sideways.py`](./demo_sideways.py) | [Preview](./demo_sideways.svg) | 4x PARs + BCL-40 Bar | Multi-color spatial sweeps, colliding comets across stage wings, and dynamic strobe sweeps. |
| [`demo_halloween.py`](./demo_halloween.py) | [Preview](./demo_halloween.svg) | 4x PARs + BCL-40 Bar | Atmospheric spooky show with organic flame flicker, deep ember wash, scanning red eye, and blinding white lightning strikes. |
| [`demo_red_spot.py`](./demo_red_spot.py) | [Preview](./demo_red_spot.svg) | 4x PARs | Minimalist bouncing spot that fades completely to black between fixtures while slowly shifting hue across the rainbow. |
| [`demo_refresh_rate.py`](./demo_refresh_rate.py) | [Preview](./demo_refresh_rate.svg) | 4x PARs | Transmitter refresh rate diagnostic testing 20 Hz, 10 Hz, 5 Hz, and 2.5 Hz toggles. |
| [`demo_24ch.py`](./demo_24ch.py) | [Preview](./demo_24ch.svg) | 4x PARs + BCL-40 Bar | 24-channel strobe bar demonstration testing Warm White (3200K) vs Cold White (6600K) solo sweeps, CCT blending, and Master Strobe channel. |
| [`demo_cct_focus.py`](./demo_cct_focus.py) | [Preview](./demo_cct_focus.svg) | 4x PARs + BCL-40 Bar | Focused CCT diagnostic: segment orientation, WW solo, CW solo, continuous CCT crossfade, and simultaneous WW+CW blast. |
| [`demo_strobe_ramp.py`](./demo_strobe_ramp.py) | [Preview](./demo_strobe_ramp.svg) | 4x PARs + BCL-40 Bar | Hardware Master Strobe ramp (0..100% speed) across simultaneous 100% WW + 100% CW diodes. |
| [`demo_strobe_colors.py`](./demo_strobe_colors.py) | [Preview](./demo_strobe_colors.svg) | 4x PARs + BCL-40 Bar | Multi-color strobe test exploring how the Master Strobe channel modulates RGB compartments and bi-color SMD diodes. |

---

## Running the Examples

### 1. Live Art-Net Streaming (Direct to Hardware)
Run any script directly from the project root or within `examples/`:

```bash
# Stream to default Art-Net node (192.168.1.158, Universe 1)
python3 examples/demo_show.py

# Specify custom target IP and universe
python3 examples/demo_halloween.py --host 192.168.1.50 --universe 1

# Dry-run mode (prints frame status without sending UDP packets)
python3 examples/demo_disco_16par.py --dry-run
```

### 2. Exporting Animated Previews
Export a fresh animated SVG or GIF at any time:

```python
from examples.demo_disco_16par import STAGE_16, DISCO_SHOW

# Export standalone animated SVG (SMIL, vector)
STAGE_16.save_animated_svg(DISCO_SHOW, "disco.svg", fps=10.0)

# Export animated GIF (requires inkscape and ffmpeg)
STAGE_16.save_animated_gif(DISCO_SHOW, "disco.gif", fps=10.0)
```
