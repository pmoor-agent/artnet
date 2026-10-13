#!/usr/bin/env python3
"""Demo 2: Sideways multi-color waves, colliding comets, and color sweeps."""

from lightshow import (
    Blackout,
    Chase,
    Color,
    Gradient,
    Rainbow,
    Strobe,
    dim,
    inf,
)
from my_rig import PARS, STROBE_RGB, STROBE_W, run_show_cli


def build_sideways_show():
    palette = [
        Color.RED,
        Color.ORANGE,
        Color.YELLOW,
        Color.GREEN,
        Color.CYAN,
        Color.BLUE,
        Color.MAGENTA,
        Color.RED,
    ]

    # 1. Multi-color palette wave sweeping L->R (6.4s) then R->L (6.4s)
    pars_wave = (
        Gradient(palette, duration=3.2).spread(total_offset=2.4) * 2
        >> Gradient(palette, duration=3.2).spread(total_offset=2.4).reverse_fixtures() * 2
    )
    rgb8_wave = (
        Gradient(palette, duration=3.2).spread(total_offset=3.2) * 2
        >> Gradient(palette, duration=3.2).spread(total_offset=3.2).reverse_fixtures() * 2
    )
    w8_wave = (
        Chase(Color.WHITE, step_duration=0.4, tail=1.5) * 4
        >> Chase(Color.WHITE, step_duration=0.4, tail=1.5).reverse_fixtures() * 4
    )

    # 2. Colliding Comets (Cyan L->R + Magenta R->L)
    pars_comets = (
        Chase(Color.CYAN, step_duration=0.14, background=None, tail=1.3)
        + Chase(Color.MAGENTA, step_duration=0.14, background=None, tail=1.3).reverse_fixtures()
    ) * 8
    rgb8_comets = (
        Chase(Color.CYAN, step_duration=0.14, background=None, tail=3.0)
        + Chase(Color.MAGENTA, step_duration=0.14, background=None, tail=3.0).reverse_fixtures()
    ) * 8
    w8_comets = (
        Chase(Color.WHITE * 0.5, step_duration=0.14, background=None, tail=1.0)
        + Chase(Color.WHITE * 0.5, step_duration=0.14, background=None, tail=1.0).reverse_fixtures()
    ) * 8

    # 3. Color-changing Knight Rider scanner bouncing back & forth
    scanner_colors = [Color.RED, Color.AMBER, Color.GREEN, Color.CYAN, Color.PURPLE, Color.WARM_WHITE]

    def _build_scanner(tail: float):
        passes = [
            Chase(c, step_duration=0.12, background=Color.BLACK, tail=tail).pingpong()
            for c in scanner_colors
        ]
        seq = passes[0]
        for p in passes[1:]:
            seq = seq >> p
        return seq

    pars_scanner = _build_scanner(tail=0.9)
    rgb8_scanner = _build_scanner(tail=2.5)
    w8_scanner = (
        Chase(Color.WHITE, step_duration=0.12, background=Color.BLACK, tail=1.2).pingpong() * 6
    )

    # 4. High-speed Rainbow Ripple (6.4s) + Sideways Strobe Finale (2.4s)
    pars_ripple = (
        Rainbow(period=1.6).phase(0.35) * 4
        >> (Rainbow(period=1.2).phase(0.25) * 2 | Strobe(rate=0.7, duration=0.6).phase(0.15) * 4)
    )
    rgb8_ripple = (
        Rainbow(period=1.6).spread() * 4
        >> Rainbow(period=0.6).spread() * 4
    )
    w8_ripple = (
        Blackout(duration=6.4)
        >> Chase(Color.WHITE, step_duration=0.075, background=Color.BLACK, tail=0.5).pingpong() * 4
    )

    pars_anim = (pars_wave >> pars_comets >> pars_scanner >> pars_ripple) * inf
    w8_anim = (w8_wave >> w8_comets >> w8_scanner >> w8_ripple) * inf
    rgb8_anim = (rgb8_wave >> rgb8_comets >> rgb8_scanner >> rgb8_ripple) * inf

    return (
        PARS(pars_anim)
        | STROBE_W(dim(0.25, w8_anim))
        | STROBE_RGB(dim(0.35, rgb8_anim))
    )


if __name__ == "__main__":
    run_show_cli("Demo 2 (Sideways Show)", build_sideways_show())
