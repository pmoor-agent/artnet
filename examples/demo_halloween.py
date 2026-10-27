#!/usr/bin/env python3
"""Demo 3: Halloween Lightshow 🎃⚡

Atmospheric spooky show with smoldering crimson/pumpkin embers, organic candle flicker,
and sudden blinding white lightning strikes utilizing BOTH:
  - 4x RGBW PARs with independent hardware strobe channels (Ch 6, 12, 18, 24)
  - 4-segment 24-channel LED Strobe Bar with full WW+CW blast and Master Strobe (Ch 21 / DMX 52)

Structure (32.0s loop):
  Act 1 (12.0s): Smoldering Haunted Grove & Double Lightning Strikes
    - Ambient deep crimson & pumpkin orange gradient breathing
    - Sudden blinding dual-strike lightning at 5.0s and 11.0s across ALL fixtures
  Act 2 (08.0s): The Stalking Jack-O'-Lantern & Jagged Glints
    - Organic candle flicker on PARs, blood-red scanning eye on Strobe bar
    - Localized white reflection glints + quick PAR strobe pops
    - Sudden lightning crack at 7.0s
  Act 3 (12.0s): Heartbeat of the Coven & The Grand Thunderstorm Climax
    - Accelerating dark red/orange heartbeat pulses with synchronized strobe cracks
    - Full-rig rolling lightning storm with all PARs and Strobe Bar strobing at 100% full blast
"""


import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightshow import (
    Blackout,
    Chase,
    Color,
    DimmerLFO,
    Fade,
    Gradient,
    Hold,
    Pulse,
    Sequence,
    Strobe,
    Wait,
    inf,
)
from my_rig import (
    PARS,
    STROBE_BAR,
    STROBE_MASTER,
    run_show_cli,
)

# Halloween Palette
BLOOD_RED = Color(1.0, 0.0, 0.0)
DARK_CRIMSON = Color(0.30, 0.0, 0.0)
PUMPKIN_ORANGE = Color(1.0, 0.22, 0.0)
DEEP_EMBER = Color(0.70, 0.08, 0.0)
CANDLE_AMBER = Color(1.0, 0.38, 0.04)


# =============================================================================
# Lightning Strike Primitives (1.0s total)
# Full synchronized hardware strobe across both PARs and Strobe Bar
# =============================================================================

def build_lightning_strike():
    """A 1.0s realistic multi-flash lightning strike utilizing PAR & Bar hardware strobes."""
    # 1. PARs: Flash 1 (0.15s with Ch 6 strobe=0.95) -> dark gap (0.075s) -> Violent strobe blast (0.35s strobe=1.0) -> Decay (0.425s)
    par_strike = Sequence([
        Hold(Color.WHITE, w=1.0, strobe=0.95, duration=0.15),
        Hold(DARK_CRIMSON * 0.2, duration=0.075),
        Hold(Color.WHITE, w=1.0, strobe=1.0, duration=0.35),
        Fade(Color.WHITE * 0.5, DARK_CRIMSON, duration=0.425),
    ])

    # 2. Strobe Bar: Outside segments (0, 3) flash first -> gap -> All 4 segments full WW+CW blast -> Decay
    bar_strike = Sequence([
        (
            Hold(Color.WHITE, ww=1.0, cw=1.0, duration=0.15).on(0, 3)
            | Hold(Color(0.4, 0.0, 0.0), ww=0.0, cw=0.0, duration=0.15).on(1, 2)
        ),
        Hold(DARK_CRIMSON * 0.2, ww=0.0, cw=0.0, duration=0.075),
        Hold(Color.WHITE, ww=1.0, cw=1.0, duration=0.35),
        Fade(Color.WHITE * 0.6, DARK_CRIMSON * 0.3, duration=0.425),
    ])

    # 3. Master Strobe: Ch 21 triggers fast hardware strobe during both strikes
    strobe_strike = Sequence([
        Hold(1.0, duration=0.15),
        Blackout(duration=0.075),
        Hold(1.0, duration=0.35),
        Blackout(duration=0.425),
    ])

    return par_strike, bar_strike, strobe_strike


def build_halloween_show():
    par_bolt, bar_bolt, strobe_bolt = build_lightning_strike()

    # =========================================================================
    # Act 1 (12.0s): Smoldering Haunted Grove & Double Lightning Strikes
    # =========================================================================
    ember_palette = [DARK_CRIMSON, BLOOD_RED, DEEP_EMBER, PUMPKIN_ORANGE, BLOOD_RED, DARK_CRIMSON]

    # PARs: 5s slow breathe -> 1s lightning -> 5s reverse breathe -> 1s lightning
    pars_breathe_fwd = (
        Gradient(ember_palette, duration=5.0).spread(total_offset=2.5)
        | DimmerLFO(period=2.5, low=0.25, high=1.0, duration=5.0)
    )
    pars_breathe_rev = (
        Gradient(ember_palette, duration=5.0).spread(total_offset=2.5).reverse_fixtures()
        | DimmerLFO(period=2.5, low=0.25, high=1.0, duration=5.0)
    )
    pars_act1 = Sequence([pars_breathe_fwd, par_bolt, pars_breathe_rev, par_bolt])

    # Strobe Bar: 5s deep ember gradient -> 1s lightning -> 5s reverse -> 1s lightning
    bar_breathe_fwd = Gradient(ember_palette, duration=5.0).spread(total_offset=3.0)
    bar_breathe_rev = Gradient(ember_palette, duration=5.0).spread(total_offset=3.0).reverse_fixtures()
    bar_act1 = Sequence([bar_breathe_fwd, bar_bolt, bar_breathe_rev, bar_bolt])

    # Master Strobe: quiet during breathe, fires during lightning
    strobe_act1 = Sequence([Blackout(duration=5.0), strobe_bolt, Blackout(duration=5.0), strobe_bolt])

    # =========================================================================
    # Act 2 (08.0s): The Stalking Jack-O'-Lantern & Eye Glints
    # =========================================================================
    # PARs: Irregular organic candle flicker (7s) punctuated by quick strobe glints -> 1s bolt
    candle_flicker = Sequence([
        Fade(DEEP_EMBER, PUMPKIN_ORANGE, duration=0.35),
        Fade(PUMPKIN_ORANGE, CANDLE_AMBER, duration=0.25),
        Fade(CANDLE_AMBER, DARK_CRIMSON, duration=0.40),
        Fade(DARK_CRIMSON, PUMPKIN_ORANGE, duration=0.40),
    ]).phase(0.35)
    # Quick PAR strobe glints at 2.0s (outside PARs 0, 3) and 4.5s (inside PARs 1, 2)
    par_glints = Sequence([
        Blackout(duration=2.0),
        Hold(Color.WHITE, w=1.0, strobe=0.9, duration=0.08).on(0, 3),
        Blackout(duration=2.42),
        Hold(Color.WHITE, w=1.0, strobe=0.9, duration=0.10).on(1, 2),
        Blackout(duration=2.40),
    ])
    pars_act2 = Sequence([(candle_flicker @ 7.0) | par_glints, par_bolt])

    # Strobe Bar: Blood red eye ping-pong chase (7s) + localized white eye glints -> 1s bolt
    red_eye_chase = (
        Chase(BLOOD_RED, step_duration=0.22, background=DARK_CRIMSON * 0.15, tail=1.6).pingpong() @ 7.0
    )
    eye_glints = Sequence([
        Blackout(duration=2.0),
        Hold(Color.WHITE, ww=1.0, cw=1.0, duration=0.08).on(0, 3),
        Blackout(duration=2.42),
        Hold(Color.WHITE, ww=1.0, cw=1.0, duration=0.10).on(1, 2),
        Blackout(duration=2.40),
    ])
    bar_act2 = Sequence([red_eye_chase | eye_glints, bar_bolt])

    # Master Strobe: Glint strobe blips at 2.0s and 4.5s, then full strike at 7s
    strobe_glints = Sequence([
        Blackout(duration=2.0),
        Hold(0.9, duration=0.08),
        Blackout(duration=2.42),
        Hold(0.9, duration=0.10),
        Blackout(duration=2.40),
    ])
    strobe_act2 = Sequence([strobe_glints, strobe_bolt])

    # =========================================================================
    # Act 3 (12.0s): Heartbeat of the Coven & The Grand Thunderstorm Climax
    # =========================================================================
    # Phase A: 6.0s of accelerating heartbeat
    # On each beat peak, the PARs crack with a rapid colored strobe burst!
    par_heartbeat = Sequence([
        Hold(BLOOD_RED, strobe=0.85, duration=0.10),
        Pulse(BLOOD_RED, duration=0.25, low=0.1, high=1.0),
        Hold(PUMPKIN_ORANGE, strobe=0.85, duration=0.10),
        Pulse(PUMPKIN_ORANGE, duration=0.30, low=0.1, high=1.0),
        Hold(DARK_CRIMSON * 0.2, duration=0.75),
    ]) * 4  # 4 * 1.5s = 6.0s

    # Strobe Bar heartbeat: mirrors from outside-in with blinding white strobe hits on the beat peaks
    bar_heartbeat = Sequence([
        Pulse(BLOOD_RED, duration=0.35).mirror(),
        Pulse(PUMPKIN_ORANGE, duration=0.40).mirror(),
        Hold(DARK_CRIMSON * 0.15, duration=0.75),
    ]) * 4
    bar_heartbeat_whites = Sequence([
        Hold(Color.WHITE, ww=1.0, cw=1.0, duration=0.10),
        Blackout(duration=0.25),
        Hold(Color.WHITE, ww=1.0, cw=1.0, duration=0.10),
        Blackout(duration=1.05),
    ]) * 4
    strobe_heartbeat = Sequence([
        Hold(0.95, duration=0.10),
        Blackout(duration=0.25),
        Hold(0.95, duration=0.10),
        Blackout(duration=1.05),
    ]) * 4

    # Phase B: 6.0s Rolling Thunderstorm Finale!
    # PARs: Staggered white & blood-red strobing across odd/even fixtures for 3s,
    # then 2.0s FULL WHITE HARDWARE STROBE BLAST (strobe=1.0, w=1.0) across all 4 PARs!
    pars_storm_rolling = Sequence([
        (
            Hold(Color.WHITE, w=1.0, strobe=0.95, duration=0.15).on(0, 2)
            | Hold(BLOOD_RED, strobe=0.85, duration=0.15).on(1, 3)
        ),
        (
            Hold(BLOOD_RED, strobe=0.85, duration=0.15).on(0, 2)
            | Hold(Color.WHITE, w=1.0, strobe=0.95, duration=0.15).on(1, 3)
        ),
        Hold(DARK_CRIMSON * 0.2, duration=0.20),
    ]) * 6  # 3.0s rolling lightning
    pars_storm_blast = Sequence([
        Hold(Color.WHITE, w=1.0, strobe=1.0, duration=2.0),  # 2.0s full white strobe blast!
        Fade(Color.WHITE * 0.5, DARK_CRIMSON * 0.1, duration=1.0),
    ])
    pars_storm_end = Sequence([pars_storm_rolling, pars_storm_blast])

    # Strobe Bar: Jagged white segment flashes (3.0s) -> 2.0s 100% full WW+CW blast -> 1.0s decay
    bar_storm_rolling = (
        Sequence([
            Hold(Color.WHITE, ww=1.0, cw=1.0, duration=0.075).on(0, 3),
            Hold(Color.WHITE, ww=1.0, cw=1.0, duration=0.075).on(1, 2),
            Blackout(duration=0.10),
        ]) * 12  # 3.0s of rolling segment lightning
    )
    bar_storm_blast = Sequence([
        Hold(Color.WHITE, ww=1.0, cw=1.0, duration=2.0),  # 2.0s max WW+CW blast
        Fade(Color.WHITE * 0.7, DARK_CRIMSON * 0.1, duration=1.0),
    ])
    bar_storm_end = Sequence([bar_storm_rolling, bar_storm_blast])

    # Master Strobe: Full speed hardware strobe rolling through the storm
    strobe_storm_end = Sequence([
        Hold(0.85, duration=3.0),
        Fade(0.85, 1.0, duration=2.0),
        Fade(1.0, 0.0, duration=1.0),
    ])

    pars_act3 = Sequence([par_heartbeat, pars_storm_end])
    bar_act3 = Sequence([bar_heartbeat | bar_heartbeat_whites, bar_storm_end])
    strobe_act3 = Sequence([strobe_heartbeat, strobe_storm_end])

    # =========================================================================
    # Combine All 3 Acts into an Infinite Loop (32.0s total)
    # =========================================================================
    pars_show = Sequence([pars_act1, pars_act2, pars_act3]) * inf
    bar_show = Sequence([bar_act1, bar_act2, bar_act3]) * inf
    strobe_show = Sequence([strobe_act1, strobe_act2, strobe_act3]) * inf

    return (
        PARS(pars_show)
        | STROBE_BAR(bar_show)
        | STROBE_MASTER(strobe_show)
    )


if __name__ == "__main__":
    run_show_cli("Halloween Show 🎃⚡ (Full-Rig PAR & Bar Strobe)", build_halloween_show())
