#!/usr/bin/env python3
"""Demo showcasing the 24-channel Strobe Bar features:
- Independent Warm White (WW) and Cold White (CW)
- Simultaneous WW + CW blending (color temperature sweep)
- Layered RGB background with Warm/Cold White chases
- Hardware Strobe on Channel 21 (DMX Ch 52)
"""


import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightshow import (
    Blackout,
    Chase,
    Color,
    Fade,
    Hold,
    Pulse,
    Rainbow,
    Wait,
    dim,
    inf,
)
from my_rig import (
    PARS,
    STROBE_CW,
    STROBE_MASTER,
    STROBE_RGB,
    STROBE_WW,
    run_show_cli,
)


def build_24ch_demo():
    # -------------------------------------------------------------------------
    # Part 1: Warm White vs Cold White solo sweeps (8.0s)
    # -------------------------------------------------------------------------
    # 4s Warm White chase (golden candlelight)
    ww_part1 = (Chase(1.0, step_duration=0.25, tail=1.5) * 4) >> Blackout(duration=4.0)
    # 4s Cold White chase (crisp daylight)
    cw_part1 = Blackout(duration=4.0) >> (Chase(1.0, step_duration=0.25, tail=1.5) * 4)
    # PARs provide a gentle deep blue backdrop
    pars_part1 = Hold(Color.BLUE * 0.15, duration=8.0)
    rgb_part1 = Blackout(duration=8.0)
    strobe_part1 = Blackout(duration=8.0)

    # -------------------------------------------------------------------------
    # Part 2: Simultaneous WW + CW CCT Blending (8.0s)
    # Smooth crossfade from 100% Warm White to 100% Cold White to BOTH on together!
    # -------------------------------------------------------------------------
    ww_part2 = (
        Fade(1.0, 0.0, duration=3.0)
        >> Fade(0.0, 1.0, duration=2.0)
        >> (Pulse(1.0, duration=0.75).spread() * 4)
    )
    cw_part2 = (
        Fade(0.0, 1.0, duration=3.0)
        >> Hold(1.0, duration=2.0)
        >> (Pulse(1.0, duration=0.75).reverse_fixtures().spread() * 4)
    )
    pars_part2 = (
        Fade(Color.AMBER * 0.4, Color.CYAN * 0.4, duration=3.0)
        >> Hold(Color.WHITE * 0.4, duration=5.0)
    )
    rgb_part2 = Blackout(duration=8.0)
    strobe_part2 = Blackout(duration=8.0)

    # -------------------------------------------------------------------------
    # Part 3: Layered RGB Color + White Accents (8.0s)
    # Vibrant RGB rainbow on the strobe segments + PARs, with WW/CW rhythmic hits
    # -------------------------------------------------------------------------
    pars_part3 = Rainbow(period=4.0).spread() * 2
    rgb_part3 = Rainbow(period=4.0).spread() * 2
    # WW hits on outer segments (0, 3), CW hits on inner segments (1, 2)
    ww_part3 = (Hold(1.0, duration=0.25).on(0, 3) >> Blackout(duration=0.75)) * 8
    cw_part3 = (Wait(0.5) >> Hold(1.0, duration=0.25).on(1, 2) >> Blackout(duration=0.25)) * 8
    strobe_part3 = Blackout(duration=8.0)

    # -------------------------------------------------------------------------
    # Part 4: Hardware Strobe Test (Ch 21 / DMX 52) (6.0s)
    # Fixtures are turned ON (solid Amber RGB + full WW+CW), and Ch 21 strobe is engaged!
    # Strobe speed ramps from 0.1 -> 1.0 over 4.0s, then solid flash for 2.0s
    # -------------------------------------------------------------------------
    pars_part4 = Hold(Color.RED, duration=6.0)
    rgb_part4 = Hold(Color.AMBER, duration=6.0)
    ww_part4 = Hold(1.0, duration=6.0)
    cw_part4 = Hold(1.0, duration=6.0)
    strobe_part4 = (
        Fade(0.1, 1.0, duration=4.0)
        >> Hold(1.0, duration=2.0)
    )

    # Combine all parts
    pars_anim = (pars_part1 >> pars_part2 >> pars_part3 >> pars_part4) * inf
    rgb_anim = (rgb_part1 >> rgb_part2 >> rgb_part3 >> rgb_part4) * inf
    ww_anim = (ww_part1 >> ww_part2 >> ww_part3 >> ww_part4) * inf
    cw_anim = (cw_part1 >> cw_part2 >> cw_part3 >> cw_part4) * inf
    strobe_anim = (strobe_part1 >> strobe_part2 >> strobe_part3 >> strobe_part4) * inf

    return (
        PARS(pars_anim)
        | STROBE_RGB(rgb_anim)
        | STROBE_WW(ww_anim)
        | STROBE_CW(cw_anim)
        | STROBE_MASTER(strobe_anim)
    )


if __name__ == "__main__":
    run_show_cli("24-Channel Strobe Bar Feature Demo (WW, CW, RGB & Hardware Strobe)", build_24ch_demo())
