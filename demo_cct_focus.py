#!/usr/bin/env python3
"""Slow, focused diagnostic demo for the 24-channel strobe bar.

Steps (39 seconds total):
  1. [00-08s] Segment Orientation: Seg 1 (Left), Seg 2, Seg 3, Seg 4 light up in order (2s each)
  2. [08-13s] Pure Warm White (3200 K) Solo: 100% WW, 0% CW on all 4 segments (5s)
  3. [13-18s] Pure Cold White (6600 K) Solo: 0% WW, 100% CW on all 4 segments (5s)
  4. [18-28s] Smooth CCT Sweep: 3200 K -> 6600 K -> 3200 K continuous crossfade (10s)
  5. [28-33s] Simultaneous Blast: 100% WW + 100% CW together for max neutral brightness (5s)
  6. [33-39s] Master Strobe (Ch 21): 3s slow strobe on Warm White, 3s fast strobe on Cold White
"""

from lightshow import (
    Blackout,
    CCT,
    Color,
    FadeCCT,
    Hold,
    inf,
)
from my_rig import (
    PARS,
    STROBE_BAR,
    STROBE_CW,
    STROBE_MASTER,
    STROBE_RGB,
    STROBE_WW,
    run_show_cli,
)


def build_cct_focus_show():
    # -------------------------------------------------------------------------
    # Step 1 (8.0s): Segment position check (Left -> Right)
    # -------------------------------------------------------------------------
    seg_step = 2.0
    rgb_seg_check = (
        Hold(Color.GREEN, duration=seg_step).on(0)
        >> Hold(Color.CYAN, duration=seg_step).on(1)
        >> Hold(Color.BLUE, duration=seg_step).on(2)
        >> Hold(Color.MAGENTA, duration=seg_step).on(3)
    )
    pars_seg_check = Hold(Color.BLACK, duration=8.0)
    ww_seg_check = Blackout(duration=8.0)
    cw_seg_check = Blackout(duration=8.0)
    strobe_seg_check = Blackout(duration=8.0)

    # -------------------------------------------------------------------------
    # Step 2 (5.0s): Pure Warm White (3200 K) Solo
    # -------------------------------------------------------------------------
    rgb_step2 = Blackout(duration=5.0)
    ww_step2 = Hold(1.0, duration=5.0)
    cw_step2 = Blackout(duration=5.0)
    pars_step2 = Hold(Color.WARM_WHITE * 0.2, duration=5.0)
    strobe_step2 = Blackout(duration=5.0)

    # -------------------------------------------------------------------------
    # Step 3 (5.0s): Pure Cold White (6600 K) Solo
    # -------------------------------------------------------------------------
    rgb_step3 = Blackout(duration=5.0)
    ww_step3 = Blackout(duration=5.0)
    cw_step3 = Hold(1.0, duration=5.0)
    pars_step3 = Hold(Color.CYAN * 0.15, duration=5.0)
    strobe_step3 = Blackout(duration=5.0)

    # -------------------------------------------------------------------------
    # Step 4 (10.0s): Smooth CCT Sweep (3200K -> 6600K -> 3200K)
    # -------------------------------------------------------------------------
    cct_sweep = FadeCCT(3200, 6600, duration=5.0) >> FadeCCT(6600, 3200, duration=5.0)
    rgb_step4 = Blackout(duration=10.0)
    pars_step4 = Hold(Color.BLACK, duration=10.0)
    strobe_step4 = Blackout(duration=10.0)

    # -------------------------------------------------------------------------
    # Step 5 (5.0s): Maximum Brightness Blast (Both 100% WW + 100% CW)
    # -------------------------------------------------------------------------
    rgb_step5 = Blackout(duration=5.0)
    ww_step5 = Hold(1.0, duration=5.0)
    cw_step5 = Hold(1.0, duration=5.0)
    pars_step5 = Hold(Color.WHITE * 0.5, w=1.0, duration=5.0)
    strobe_step5 = Blackout(duration=5.0)

    # -------------------------------------------------------------------------
    # Step 6 (6.0s): Channel 21 Hardware Strobe test
    # -------------------------------------------------------------------------
    rgb_step6 = Blackout(duration=6.0)
    ww_step6 = Hold(1.0, duration=3.0) >> Blackout(duration=3.0)
    cw_step6 = Blackout(duration=3.0) >> Hold(1.0, duration=3.0)
    pars_step6 = Hold(Color.BLACK, duration=6.0)
    # 3s at 25% speed, then 3s at 75% speed
    strobe_step6 = Hold(0.25, duration=3.0) >> Hold(0.75, duration=3.0)

    # Assemble sequences
    pars_scene = (
        pars_seg_check >> pars_step2 >> pars_step3 >> pars_step4 >> pars_step5 >> pars_step6
    ) * inf

    rgb_scene = (
        rgb_seg_check >> rgb_step2 >> rgb_step3 >> rgb_step4 >> rgb_step5 >> rgb_step6
    ) * inf

    # Note: Step 4 uses CCT on STROBE_BAR, while other steps drive WW/CW directly
    # We layer STROBE_BAR for Step 4 on top of WW/CW scenes
    ww_scene = (
        ww_seg_check >> ww_step2 >> ww_step3 >> Blackout(duration=10.0) >> ww_step5 >> ww_step6
    ) * inf

    cw_scene = (
        cw_seg_check >> cw_step2 >> cw_step3 >> Blackout(duration=10.0) >> cw_step5 >> cw_step6
    ) * inf

    bar_cct_scene = (
        Blackout(duration=18.0) >> cct_sweep >> Blackout(duration=11.0)
    ) * inf

    strobe_scene = (
        strobe_seg_check >> strobe_step2 >> strobe_step3 >> strobe_step4 >> strobe_step5 >> strobe_step6
    ) * inf

    return (
        PARS(pars_scene)
        | STROBE_RGB(rgb_scene)
        | STROBE_WW(ww_scene)
        | STROBE_CW(cw_scene)
        | STROBE_BAR(bar_cct_scene)
        | STROBE_MASTER(strobe_scene)
    )


if __name__ == "__main__":
    run_show_cli(
        "Slow Focused Diagnostic (Segments, 3200K, 6600K, CCT Sweep, Blast, Ch21 Strobe)",
        build_cct_focus_show(),
    )
