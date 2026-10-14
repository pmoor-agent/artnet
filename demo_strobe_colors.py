#!/usr/bin/env python3
"""Multi-Color Strobe Test Demo for the 24-channel strobe bar.

Tests if Channel 21 (Master Strobe) modulates the RGB segments:
  Part 1 (00-12s): Pure RGB Test Colors (No White)
    - Seg 1: Red | Seg 2: Green | Seg 3: Blue | Seg 4: Yellow
    - Strobe rate ramps up (0-6s) and down (6-12s)

  Part 2 (12-24s): Pastel/Neon RGB + Warm & Cold White Underneath
    - Seg 1: Magenta | Seg 2: Cyan | Seg 3: Orange | Seg 4: Lime Green
    - 50% WW + 50% CW active simultaneously
    - Strobe rate ramps up (12-18s) and down (18-24s)

  Part 3 (24-36s): Continuous Rainbow Wave with Fixed-Rate Strobe
    - Full spectrum spatial rainbow wave across the 4 segments
    - Strobe pulsing at a crisp medium-fast rate (60% / ~14 Hz)
"""

import argparse
from lightshow import (
    Color,
    Ease,
    Fade,
    Hold,
    Rainbow,
    inf,
)
from my_rig import PARS, STROBE_BAR, STROBE_MASTER, create_rig


def build_strobe_colors_show():
    # -------------------------------------------------------------------------
    # Part 1 (12.0s): Pure RGB Test Colors (No White)
    # Seg 1: Red, Seg 2: Green, Seg 3: Blue, Seg 4: Yellow
    # -------------------------------------------------------------------------
    part1_colors = (
        Hold(Color.RED, ww=0.0, cw=0.0, duration=12.0).on(0)
        | Hold(Color.GREEN, ww=0.0, cw=0.0, duration=12.0).on(1)
        | Hold(Color.BLUE, ww=0.0, cw=0.0, duration=12.0).on(2)
        | Hold(Color.YELLOW, ww=0.0, cw=0.0, duration=12.0).on(3)
    )

    # -------------------------------------------------------------------------
    # Part 2 (12.0s): Neon RGB + 50% Warm & Cold White underglow
    # Seg 1: Magenta, Seg 2: Cyan, Seg 3: Orange, Seg 4: Lime
    # -------------------------------------------------------------------------
    part2_colors = (
        Hold(Color.MAGENTA, ww=0.5, cw=0.5, duration=12.0).on(0)
        | Hold(Color.CYAN, ww=0.5, cw=0.5, duration=12.0).on(1)
        | Hold(Color.ORANGE, ww=0.5, cw=0.5, duration=12.0).on(2)
        | Hold(Color(0.5, 1.0, 0.0), ww=0.5, cw=0.5, duration=12.0).on(3)
    )

    # -------------------------------------------------------------------------
    # Part 3 (12.0s): Dynamic Rainbow Wave across segments
    # -------------------------------------------------------------------------
    part3_colors = Rainbow(period=3.0).spread() * 4

    bar_sequence = (part1_colors >> part2_colors >> part3_colors) * inf

    # -------------------------------------------------------------------------
    # Channel 21 Strobe Sequence:
    # 0-6s: Ramp up (0->1), 6-12s: Ramp down (1->0)
    # 12-18s: Ramp up (0->1), 18-24s: Ramp down (1->0)
    # 24-36s: Solid 60% strobe speed (~14 Hz)
    # -------------------------------------------------------------------------
    strobe_ramp_12s = (
        Fade(0.0, 1.0, duration=6.0, ease=Ease.linear)
        >> Fade(1.0, 0.0, duration=6.0, ease=Ease.linear)
    )
    strobe_steady = Hold(0.60, duration=12.0)

    strobe_sequence = (strobe_ramp_12s >> strobe_ramp_12s >> strobe_steady) * inf

    # PARs stay off so the strobe bar is isolated
    pars_off = Hold(Color.BLACK, duration=36.0) * inf

    return (
        PARS(pars_off)
        | STROBE_BAR(bar_sequence)
        | STROBE_MASTER(strobe_sequence)
    )


def main():
    parser = argparse.ArgumentParser(description="Multi-color strobe test on 24-channel strobe bar")
    parser.add_argument("--host", default="192.168.1.158", help="Art-Net node IP (default: 192.168.1.158)")
    parser.add_argument("--universe", type=int, default=1, help="Universe number (default: 1)")
    parser.add_argument("--dry-run", action="store_true", help="Preview in terminal without sending UDP")
    parser.add_argument("--duration", type=float, default=36.0, help="Run duration in seconds (default: 36.0)")
    parser.add_argument("--fps", type=float, default=40.0, help="Frames per second (default: 40.0)")
    args = parser.parse_args()

    scene = build_strobe_colors_show()
    rig = create_rig(host=args.host, universe=args.universe, fps=args.fps, dry_run=args.dry_run)

    print(f"Streaming Multi-Color Strobe Test to {args.host} (Universe {args.universe}) for {args.duration}s...")
    print("  00-12s: Pure RGB Test Colors (Red / Green / Blue / Yellow) with 0-100%% strobe speed ramp")
    print("  12-24s: Neon RGB + WW/CW blend with 0-100%% strobe speed ramp")
    print("  24-36s: Moving Rainbow Wave with constant 60%% strobe rate")
    rig.play(scene, max_duration=args.duration, preview=True)
    print("\nDone. Blackout sent.")


if __name__ == "__main__":
    main()
