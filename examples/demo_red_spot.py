#!/usr/bin/env python3
"""Minimalist bouncing spot that fades all the way to black and slowly shifts rainbow hue over ~8 bounces."""


import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightshow import Pulse, Rainbow, inf
from my_rig import PARS, run_show_cli


def build_rainbow_spot_show():
    # 1. Spatial 0.0 -> 1.0 -> 0.0 envelope: 0.6s pulse (0.3s in, 0.3s out) staggered by 0.3s
    #    so each PAR fades all the way down to black (0) as the next PAR peaks.
    #    One full bounce (0 -> 1 -> 2 -> 3 -> 2 -> 1) takes 6 * 0.3s = 1.8s.
    spot_envelope = Pulse(1.0, duration=0.6).stagger(0.3, fixtures=4, bounce=True) * inf

    # 2. Slow rainbow carrier: cycles through the full spectrum once every 8 bounces (8 * 1.8s = 14.4s)
    slow_rainbow = Rainbow(period=14.4) * inf

    # 3. Multiply (`&`) the slow rainbow color by the bouncing spatial envelope!
    return PARS(slow_rainbow & spot_envelope)


if __name__ == "__main__":
    run_show_cli("Slow-Shifting Rainbow Bouncing Spot", build_rainbow_spot_show())
