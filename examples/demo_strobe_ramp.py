#!/usr/bin/env python3
"""Simple focused strobe demo:
- Both Cold White and Warm White on at full throttle (100% WW + 100% CW) on all segments
- Hardware Master Strobe (Channel 21 / DMX 52) ramps smoothly up (0-10s) and down (10-20s)
"""


import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
from lightshow import Color, Ease, Fade, Hold, Sequence, inf
from my_rig import PARS, STROBE_BAR, STROBE_MASTER, create_rig


def build_strobe_ramp_show(include_rgb: bool = False):
    color = Color.WHITE if include_rgb else Color.BLACK

    # Solid 100% Warm White + 100% Cold White across all 4 segments
    white_blast = Hold(color, ww=1.0, cw=1.0, duration=20.0) * inf

    # Strobe speed: 0.0 -> 1.0 linearly over 10s, then 1.0 -> 0.0 linearly over 10s
    # DMX Ch 52 maps 0.0 to 0 (off/solid on), and (0.0..1.0] to 9..255 (slowest to fastest strobe)
    strobe_ramp = Sequence([
        Fade(0.0, 1.0, duration=10.0, ease=Ease.linear),
        Fade(1.0, 0.0, duration=10.0, ease=Ease.linear),
    ]) * inf

    # PARs stay off so focus is 100% on the strobe bar
    pars_off = Hold(Color.BLACK, duration=20.0) * inf

    return (
        PARS(pars_off)
        | STROBE_BAR(white_blast)
        | STROBE_MASTER(strobe_ramp)
    )


def main():
    parser = argparse.ArgumentParser(description="Strobe bar speed ramp test (0-10s up, 10-20s down)")
    parser.add_argument("--host", default="192.168.1.158", help="Art-Net node IP (default: 192.168.1.158)")
    parser.add_argument("--universe", type=int, default=1, help="Universe number (default: 1)")
    parser.add_argument("--dry-run", action="store_true", help="Preview in terminal without sending UDP")
    parser.add_argument("--duration", type=float, default=20.0, help="Run duration in seconds (default: 20.0)")
    parser.add_argument("--fps", type=float, default=40.0, help="Frames per second (default: 40.0)")
    parser.add_argument("--rgb", action="store_true", help="Also enable RGB LEDs at 100%% white")
    args = parser.parse_args()

    scene = build_strobe_ramp_show(include_rgb=args.rgb)
    rig = create_rig(host=args.host, universe=args.universe, fps=args.fps, dry_run=args.dry_run)

    print(f"Streaming Strobe Ramp Test to {args.host} (Universe {args.universe}) for {args.duration}s...")
    print("Timeline: 0-10s: Ramping speed up (slow -> fast) | 10-20s: Ramping speed down (fast -> slow)")
    rig.play(scene, max_duration=args.duration, preview=True)
    print("\nDone. Blackout sent.")


if __name__ == "__main__":
    main()
