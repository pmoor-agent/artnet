#!/usr/bin/env python3
"""Refresh rate test demo.

At a 40 Hz DMX refresh rate (1 frame = 25 ms):
- PAR 1 (index 0): 20 Hz square wave / 40 Hz toggle (1 frame ON, 1 frame OFF = 0.025s on / 0.025s off, 20 cycles/sec)
- PAR 2 (index 1): 10 Hz square wave (2 frames ON, 2 frames OFF = 0.050s on / 0.050s off, 10 cycles/sec)
- PAR 3 (index 2): 5 Hz square wave (4 frames ON, 4 frames OFF = 0.100s on / 0.100s off, 5 cycles/sec)
- PAR 4 (index 3): 2.5 Hz square wave (8 frames ON, 8 frames OFF = 0.200s on / 0.200s off, 2.5 cycles/sec)

We also support the alternate interpretation where "flicker at 40 Hz" means a full 40 Hz cycle (every 0.0125s on / 0.0125s off),
which would require an 80 Hz DMX rate; via CLI --fps you can test higher transmitter rates.
"""


import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightshow import Blackout, Color, Hold, Sequence, inf
from my_rig import PARS, run_show_cli


def make_square_wave(freq_hz: float, color: Color = Color.WHITE, w: float = 1.0):
    """Square wave on/off toggle at freq_hz with full RGB + W."""
    half_period = 0.5 / freq_hz
    return Sequence([Hold(color, w=w, duration=half_period), Blackout(duration=half_period)]) * inf


def build_refresh_test_show():
    # Nyquist limit for 40 Hz DMX is 20 Hz on/off toggle (1 frame on, 1 frame off).
    # If interpreting "40/20/10/5 Hz flicker" as toggle rate:
    # PAR 1: toggle every 1 frame (0.025s ON, 0.025s OFF) -> 20 Hz square cycle (40 state changes/sec)
    # PAR 2: toggle every 2 frames (0.050s ON, 0.050s OFF) -> 10 Hz square cycle (20 state changes/sec)
    # PAR 3: toggle every 4 frames (0.100s ON, 0.100s OFF) -> 5 Hz square cycle (10 state changes/sec)
    # PAR 4: toggle every 8 frames (0.200s ON, 0.200s OFF) -> 2.5 Hz square cycle (5 state changes/sec)
    par1 = make_square_wave(20.0).on(0)
    par2 = make_square_wave(10.0).on(1)
    par3 = make_square_wave(5.0).on(2)
    par4 = make_square_wave(2.5).on(3)

    return PARS(par1 | par2 | par3 | par4)


if __name__ == "__main__":
    run_show_cli("Refresh Rate Test (40/20/10/5 toggles/sec)", build_refresh_test_show())
