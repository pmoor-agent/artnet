# lightshow: Algebraic Art-Net / DMX Lighting DSL

`lightshow` is a composable, algebraic Python framework for designing and sequencing DMX and Art-Net lighting shows.

Traditional lighting control often suffers from imperative spaghetti code: manual byte arrays, hardware tick loops, and scattered timing logic. `lightshow` replaces this with a **declarative, functional timeline**:

- **Continuous Functional Time**: Animations and cues are mathematical functions $f(t) \to \text{State}$, evaluated cleanly at any frame rate (30 Hz, 40 Hz, 60 Hz).
- **Musical Timing & Dynamic Tempo**: Mix fixed wall-clock seconds (`duration=0.1` for strobes/physics) with musical subdivisions (`Tempo(128).sixteenth`, `beats(1)`, `bars(4)`). Dynamically change BPM or tap-tempo at runtime with zero phase glitches.
- **Algebraic Composition**: Combine lighting patterns using standard Python idioms and operators:
  - `[A, B, C]` / `Sequence([A, B, C])` for chronological time sequencing
  - `|` for concurrent layering (Last-Takes-Precedence / LTP override)
  - `^` for additive optical blending
  - `* n` for repetition and infinite looping (`* inf` or `.loop()`)
  - `[start:stop]` for time cutting and sub-range extraction (`clip[0.3:1.2]`)
  - `@ dur` for time scaling and stretching
  - `~` for time reversal (`.pingpong()`)
- **Spatial Distribution & Transforms**: Distribute phase waves across fixtures with `.spread()`, create marquee sweeps with `.pingpong()`, and symmetrically mirror across the stage with `.mirror()`.
- **Physical Fixture Profiles & Visualizer**: Zero-dependency 2D SVG stage visualizer (`EurolitePartySpot`, `EuroliteBCL40Bar`) with authentic concentric LED rings, bi-color SMD diode tracks, and Nyquist-safe strobe rendering.
- **Organic Noise & Flame Flicker**: Continuous 1D fractal Brownian motion (`fbm_noise1d`, `Noise`, `Flicker`) with per-fixture decorrelation for organic candle and torch flicker without discrete frame pops.
- **Relative HSV Color Modulation**: Keep base colors/gradients intact while smoothly rotating hue or shifting saturation and brightness with `HueShift`, `.jitter_hue()`, and `.shift_hsv()`.
- **Jupyter & Live Streaming**: Built-in interactive Jupyter scrubber widget and non-blocking background 40 Hz Art-Net streaming with live hot-reloading (`from lightshow.jupyter import *`).

---

## Visualizer Previews

### Halloween Torch Flicker & Relative Hue Jitter
Deep ember/blood-red gradient wash with independent per-fixture flame flicker, smooth organic hue jitter, and a cold lightning strike:

![Halloween Torch Flicker](./docs/images/06_halloween_flicker.svg)

### Multi-Layer Composition
An ambient moving gradient wave, rhythmic dimmer pulse, and synchronized strobe hits:

![Multi-Layer Composition](./docs/images/05_composition_show.svg)

### Symmetric Ping-Pong Marquee Chase
Boundary-aware linear chase with trailing decay and background ambient wash:

![Symmetric Ping-Pong Chase](./docs/images/04_chase_pingpong.svg)

---

## Quickstart

```python
from lightshow import Color, Fade, Gradient, Hold, Pulse, Rainbow, Sequence, Strobe, Wait
from lightshow.profiles import EurolitePartySpot, Stage

# 1. Define your physical fixtures (e.g. 8 RGBW PARs)
PARS = EurolitePartySpot.group("PARS", start_channels=[1 + i * 6 for i in range(8)])

# 2. Compose a show using algebraic operators
show = PARS(
    # Layer 1: Ambient moving color wave across all 8 PARs
    Gradient([Color.PURPLE, Color.BLUE, Color.CYAN, Color.PURPLE], duration=3.0).spread()
    
    # Layer 2: Rhythmic master pulse modulating dimmer from 25% to 100%
    | (Pulse(1.0, low=0.25, high=1.0, duration=0.6, channel="dimmer") * 5)
    
    # Layer 3: Strobe burst on bookends and center at 2.4s
    | Sequence([
        Wait(2.4),
        (
            Hold(Color.RED, strobe=0.9, duration=0.6).on(0, 7)
            | Hold(Color.WHITE, strobe=0.9, duration=0.6).on(3, 4)
        ),
    ])
)

# 3. Render 2D SVG visualizer or inspect in Jupyter
STAGE = Stage(
    width=840,
    height=150,
    fixtures=[
        EurolitePartySpot(PARS[i], x=63 + i * 102, y=65, radius=26, label=f"PAR {i+1}")
        for i in range(8)
    ],
)

# In Jupyter:
# STAGE.inspect(show, duration=3.0, fps=15)
```

---

## Documentation & Examples

- 📖 **[Lightshow DSL Guide & Language Reference](docs/language_guide.md)**: Comprehensive walkthrough of the DSL syntax, operator algebra, modulation LFOs, and hardware channel rules.
- 💡 **[Example Shows & Previews](examples/README.md)**: Complete runnable shows with accompanying animated SVG previews in the [`examples/`](examples/) directory.

---

## Running Unit Tests

The test suite runs with standard Python `unittest`:

```bash
python3 -m unittest discover -s tests -v
```

---

## License

MIT License.
