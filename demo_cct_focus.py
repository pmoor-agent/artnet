#!/usr/bin/env python3
"""Slow, focused diagnostic demo for the 24-channel strobe bar.

Steps (39 seconds total):
  1. [00-08s] Segment Orientation: Seg 1 (Left, Green) -> Seg 2 (Cyan) -> Seg 3 (Blue) -> Seg 4 (Right, Magenta) (2s each)
  2. [08-13s] Pure Warm White (3200 K) Solo: 100% WW, 0% CW on all 4 segments (5s)
  3. [13-18s] Pure Cold White (6600 K) Solo: 0% WW, 100% CW on all 4 segments (5s)
  4. [18-28s] Smooth CCT Sweep: 3200 K -> 6600 K -> 3200 K continuous crossfade (10s)
  5. [28-33s] Simultaneous Blast: 100% WW + 100% CW together for max neutral brightness (5s)
  6. [33-39s] Master Strobe (Ch 21): 3s slow strobe on Warm White, 3s fast strobe on Cold White
"""

from lightshow import (
    Blackout,
    Color,
    FadeCCT,
    Hold,
    inf,
)
from my_rig import (
    PARS,
    STROBE_BAR,
    STROBE_MASTER,
    run_show_cli,
)


def build_cct_focus_show():
    # -------------------------------------------------------------------------
    # Step 1 (8.0s): Segment position check (Left -> Right in distinct colors)
    # -------------------------------------------------------------------------
    seg_step = 2.0
    step1 = (
        Hold(Color.GREEN, ww=0.0, cw=0.0, duration=seg_step).on(0)
        >> Hold(Color.CYAN, ww=0.0, cw=0.0, duration=seg_step).on(1)
        >> Hold(Color.BLUE, ww=0.0, cw=0.0, duration=seg_step).on(2)
        >> Hold(Color.MAGENTA, ww=0.0, cw=0.0, duration=seg_step).on(3)
    )
    pars_step1 = Hold(Color.BLACK, duration=8.0)

    # -------------------------------------------------------------------------
    # Step 2 (5.0s): Pure Warm White (3200 K) Solo
    # -------------------------------------------------------------------------
    step2 = Hold(Color.BLACK, ww=1.0, cw=0.0, duration=5.0)
    pars_step2 = Hold(Color.WARM_WHITE * 0.15, duration=5.0)

    # -------------------------------------------------------------------------
    # Step 3 (5.0s): Pure Cold White (6600 K) Solo
    # -------------------------------------------------------------------------
    step3 = Hold(Color.BLACK, ww=0.0, cw=1.0, duration=5.0)
    pars_step3 = Hold(Color.CYAN * 0.15, duration=5.0)

    # -------------------------------------------------------------------------
    # Step 4 (10.0s): Smooth CCT Sweep (3200K -> 6600K -> 3200K)
    # -------------------------------------------------------------------------
    step4 = FadeCCT(3200, 6600, duration=5.0) >> FadeCCT(6600, 3200, duration=5.0)
    pars_step4 = Hold(Color.BLACK, duration=10.0)

    # -------------------------------------------------------------------------
    # Step 5 (5.0s): Maximum Brightness Blast (Both 100% WW + 100% CW)
    # -------------------------------------------------------------------------
    step5 = Hold(Color.BLACK, ww=1.0, cw=1.0, duration=5.0)
    pars_step5 = Hold(Color.WHITE * 0.4, w=1.0, duration=5.0)

    # -------------------------------------------------------------------------
    # Step 6 (6.0s): Channel 21 Hardware Strobe test
    # -------------------------------------------------------------------------
    # 3s solid Warm White, then 3s solid Cold White
    step6 = Hold(Color.BLACK, ww=1.0, cw=0.0, duration=3.0) >> Hold(Color.BLACK, ww=0.0, cw=1.0, duration=3.0)
    pars_step6 = Hold(Color.BLACK, duration=6.0)

    # Build sequence for STROBE_BAR (channels 32..51)
    bar_anim = (step1 >> step2 >> step3 >> step4 >> step5 >> step6) * inf
    pars_anim = (pars_step1 >> pars_step2 >> pars_step3 >> pars_step4 >> pars_step5 >> pars_step6) * inf

    # Build sequence for STROBE_MASTER (channel 52): 33s off, 3s slow (25%), 3s fast (75%)
    strobe_master_anim = (
        Blackout(duration=33.0)
        >> Hold(0.25, duration=3.0)
        >> Hold(0.75, duration=3.0)
    ) * inf

    return (
        PARS(pars_anim)
        | STROBE_BAR(bar_anim)
        | STROBE_MASTER(strobe_master_anim)
    )


if __name__ == "__main__":
    run_show_cli(
        "Slow Focused Diagnostic (Segments, 3200K, 6600K, CCT Sweep, Blast, Ch21 Strobe)",
        build_cct_focus_show(),
    )
