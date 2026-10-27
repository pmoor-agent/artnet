#!/usr/bin/env python3
"""Demo 1: Composable animations across 4 RGBW PARs + Segmented LED Strobe."""


import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightshow import (
    Blackout,
    Chase,
    Color,
    DimmerLFO,
    Fade,
    Hold,
    Pulse,
    Rainbow,
    Sequence,
    Strobe,
    Wait,
    dim,
    inf,
)
from my_rig import PARS, STROBE_RGB, STROBE_W, run_show_cli


def build_demo_show():
    # -------------------------------------------------------------------------
    # Section 1 (5.0s): Warm-up intro + center-outward symmetric pulse
    # -------------------------------------------------------------------------
    pars_intro = Sequence([
        Fade(Color.BLACK, Color.WARM_WHITE, duration=2.0),
        Pulse(Color.AMBER, duration=1.5).mirror() * 2,
    ])
    w8_intro = Sequence([
        Blackout(duration=2.0),
        Chase(Color.WHITE, step_duration=0.1875, tail=1.5).mirror() * 4,
    ])
    rgb8_intro = Sequence([
        Fade(Color.BLACK, Color.AMBER, duration=2.0),
        Pulse(Color.ORANGE, duration=1.5).mirror().spread(0.6) * 2,
    ])

    # -------------------------------------------------------------------------
    # Section 2 (8.0s): Spatial rainbow wave across all fixtures
    # -------------------------------------------------------------------------
    pars_rainbow = (
        (Rainbow(period=4.0).spread() * 2)
        | DimmerLFO(period=2.0, low=0.3, high=1.0, duration=8.0)
    )
    w8_rainbow = Chase(Color.WHITE, step_duration=0.125, tail=0.8) * 16
    rgb8_rainbow = Rainbow(period=4.0).spread() * 2

    # -------------------------------------------------------------------------
    # Section 3 (5.76s): Ping-pong cyan/magenta chase with smooth tails
    # -------------------------------------------------------------------------
    pars_chase = Chase(
        Color.CYAN, step_duration=0.18, background=Color.PURPLE * 0.2, tail=1.2
    ).pingpong() * 4
    w8_chase = Chase(
        Color.WHITE, step_duration=0.18, background=Color.BLACK, tail=0.6
    ).pingpong() * 4
    rgb8_chase = (
        Chase(Color.CYAN, step_duration=0.18, background=None, tail=2.5).pingpong()
        + Chase(Color.MAGENTA, step_duration=0.18, background=None, tail=2.5).reverse_fixtures().pingpong()
    ) * 4

    # -------------------------------------------------------------------------
    # Section 4 (4.0s): Odd/Even Red-Blue Duel + Segmented White Strobe Hits
    # -------------------------------------------------------------------------
    duel_colors = (
        Pulse(Color.RED, duration=1.0).on(0, 2)
        | Pulse(Color.BLUE, duration=1.0).on(1, 3)
    ) * 4
    strobe_hit = Sequence([Wait(1.6), Strobe(rate=0.75, duration=0.4, color=Color.WHITE)]) * 2
    pars_duel = duel_colors | strobe_hit

    w8_rapid_flash = Sequence([
        Hold(Color.WHITE, duration=0.075).on(0, 2, 4, 6),
        Hold(Color.WHITE, duration=0.075).on(1, 3, 5, 7),
    ]) * 3
    w8_duel = Sequence([Blackout(duration=1.55), w8_rapid_flash]) * 2

    rgb8_duel = (
        Pulse(Color.RED, duration=1.0).on(0, 2, 4, 6)
        | Pulse(Color.BLUE, duration=1.0).on(1, 3, 5, 7)
    ) * 4

    pars_anim = Sequence([pars_intro, pars_rainbow, pars_chase, pars_duel]) * inf
    w8_anim = Sequence([w8_intro, w8_rainbow, w8_chase, w8_duel]) * inf
    rgb8_anim = Sequence([rgb8_intro, rgb8_rainbow, rgb8_chase, rgb8_duel]) * inf

    # Bind each clip to its FixtureGroup and compose them with `|`!
    return (
        PARS(pars_anim)
        | STROBE_W(dim(0.25, w8_anim))
        | STROBE_RGB(dim(0.35, rgb8_anim))
    )


if __name__ == "__main__":
    run_show_cli("Demo 1 (Classic Show)", build_demo_show())
