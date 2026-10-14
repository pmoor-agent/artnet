#!/usr/bin/env python3
"""Demo 3: Halloween Lightshow 🎃⚡

Atmospheric spooky show with smoldering crimson/pumpkin embers, organic candle flicker,
and sudden blinding white lightning strikes from the 24-channel strobe bar (WW + CW + Ch 21 strobe)
and RGBW PARs.

Structure (32.0s loop):
  Act 1 (12.0s): Smoldering Haunted Grove & Double Lightning Strikes
    - Ambient deep crimson & pumpkin orange gradient breathing
    - Sudden blinding dual-strike lightning at 5.0s and 11.0s
  Act 2 (08.0s): The Stalking Jack-O'-Lantern & Eye Glints
    - Organic candle flicker on PARs, blood-red scanning eye on Strobe bar
    - Localized white reflection glints on individual segments
    - Sudden lightning crack at 7.0s
  Act 3 (12.0s): Heartbeat of the Coven & The Thunderstorm Climax
    - Accelerating dark red/orange heartbeat pulses with white strobe pops
    - Full-rig rolling lightning storm with Ch 21 strobe ramping to 100% full blast
"""

from lightshow import (
    Blackout,
    Chase,
    Color,
    DimmerLFO,
    Fade,
    Gradient,
    Hold,
    Pulse,
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
# =============================================================================

def build_lightning_strike():
    """A 1.0s realistic multi-flash lightning strike across PARs and Strobe Bar."""
    # 1. PARs: Flash 1 (0.10s) -> dark gap (0.075s) -> Hardware Strobe burst (0.25s) -> Decay (0.575s)
    par_strike = (
        Hold(Color.WHITE, w=1.0, duration=0.10)
        >> Hold(DARK_CRIMSON * 0.2, duration=0.075)
        >> (Hold(Color.WHITE, w=1.0, duration=0.25) | Strobe(rate=0.95, duration=0.25))
        >> Fade(Color.WHITE * 0.5, DARK_CRIMSON, duration=0.575)
    )

    # 2. Strobe Bar: Outside segments (0, 3) flash first -> gap -> All 4 segments full WW+CW blast -> Decay
    bar_strike = (
        (
            Hold(Color.WHITE, ww=1.0, cw=1.0, duration=0.10).on(0, 3)
            | Hold(Color(0.4, 0.0, 0.0), ww=0.0, cw=0.0, duration=0.10).on(1, 2)
        )
        >> Hold(DARK_CRIMSON * 0.2, ww=0.0, cw=0.0, duration=0.075)
        >> Hold(Color.WHITE, ww=1.0, cw=1.0, duration=0.25)
        >> Fade(Color.WHITE * 0.6, DARK_CRIMSON * 0.3, duration=0.575)
    )

    # 3. Master Strobe: Ch 21 triggers fast strobe on the second blast
    strobe_strike = (
        Hold(1.0, duration=0.10)
        >> Blackout(duration=0.075)
        >> Hold(0.95, duration=0.25)
        >> Blackout(duration=0.575)
    )

    return par_strike, bar_strike, strobe_strike


def build_halloween_show():
    par_bolt, bar_bolt, strobe_bolt = build_lightning_strike()

    # =========================================================================
    # Act 1 (12.0s): Smoldering Haunted Grove & Double Lightning Strikes
    # =========================================================================
    ember_palette = [DARK_CRIMSON, BLOOD_RED, DEEP_EMBER, PUMPKIN_ORANGE, BLOOD_RED, DARK_CRIMSON]

    # PARs: 5s slow breathe -> 1s bolt -> 5s reverse breathe -> 1s bolt
    pars_breathe_fwd = (
        Gradient(ember_palette, duration=5.0).spread(total_offset=2.5)
        | DimmerLFO(period=2.5, low=0.25, high=1.0, duration=5.0)
    )
    pars_breathe_rev = (
        Gradient(ember_palette, duration=5.0).spread(total_offset=2.5).reverse_fixtures()
        | DimmerLFO(period=2.5, low=0.25, high=1.0, duration=5.0)
    )
    pars_act1 = pars_breathe_fwd >> par_bolt >> pars_breathe_rev >> par_bolt

    # Strobe Bar: 5s deep ember gradient -> 1s bolt -> 5s reverse -> 1s bolt
    bar_breathe_fwd = Gradient(ember_palette, duration=5.0).spread(total_offset=3.0)
    bar_breathe_rev = Gradient(ember_palette, duration=5.0).spread(total_offset=3.0).reverse_fixtures()
    bar_act1 = bar_breathe_fwd >> bar_bolt >> bar_breathe_rev >> bar_bolt

    # Master Strobe: quiet during breathe, fires during bolt
    strobe_act1 = Blackout(duration=5.0) >> strobe_bolt >> Blackout(duration=5.0) >> strobe_bolt

    # =========================================================================
    # Act 2 (08.0s): The Stalking Jack-O'-Lantern & Eye Glints
    # =========================================================================
    # PARs: Irregular organic candle flicker inside carved pumpkin (7s) -> 1s bolt
    candle_flicker = (
        Fade(DEEP_EMBER, PUMPKIN_ORANGE, duration=0.35)
        >> Fade(PUMPKIN_ORANGE, CANDLE_AMBER, duration=0.25)
        >> Fade(CANDLE_AMBER, DARK_CRIMSON, duration=0.40)
        >> Fade(DARK_CRIMSON, PUMPKIN_ORANGE, duration=0.40)
    ).phase(0.35)
    pars_act2 = (candle_flicker @ 7.0) >> par_bolt

    # Strobe Bar: Blood red eye ping-pong chase (7s) + localized white eye glints -> 1s bolt
    red_eye_chase = (
        Chase(BLOOD_RED, step_duration=0.22, background=DARK_CRIMSON * 0.15, tail=1.6).pingpong() @ 7.0
    )
    # Sudden eye glints: Segment 0 & 3 flash white at 2.0s, Segments 1 & 2 flash at 4.5s
    eye_glints = (
        Blackout(duration=2.0)
        >> Hold(Color.WHITE, ww=1.0, cw=1.0, duration=0.08).on(0, 3)
        >> Blackout(duration=2.42)
        >> Hold(Color.WHITE, ww=1.0, cw=1.0, duration=0.10).on(1, 2)
        >> Blackout(duration=2.40)
    )
    bar_act2 = (red_eye_chase | eye_glints) >> bar_bolt

    # Master Strobe: Glint strobe blip at 2.0s and 4.5s, then full strike at 7s
    strobe_glints = (
        Blackout(duration=2.0)
        >> Hold(0.9, duration=0.08)
        >> Blackout(duration=2.42)
        >> Hold(0.9, duration=0.10)
        >> Blackout(duration=2.40)
    )
    strobe_act2 = strobe_glints >> strobe_bolt

    # =========================================================================
    # Act 3 (12.0s): Heartbeat of the Coven & The Thunderstorm Climax
    # =========================================================================
    # Phase A: 6.0s of accelerating heartbeat (Blood Red -> Pumpkin Orange -> Shadow)
    heartbeat_cycle = (
        Pulse(BLOOD_RED, duration=0.35, low=0.05, high=1.0)
        >> Pulse(PUMPKIN_ORANGE, duration=0.40, low=0.05, high=1.0)
        >> Hold(DARK_CRIMSON * 0.2, duration=0.75)
    ) * 4  # 4 * 1.5s = 6.0s

    # Strobe Bar heartbeat: mirrors from outside-in with white strobe hits on the beat peaks
    bar_heartbeat = (
        Pulse(BLOOD_RED, duration=0.35).mirror()
        >> Pulse(PUMPKIN_ORANGE, duration=0.40).mirror()
        >> Hold(DARK_CRIMSON * 0.15, duration=0.75)
    ) * 4
    # White strobe hits on the heartbeat
    bar_heartbeat_whites = (
        Hold(Color.WHITE, ww=1.0, cw=1.0, duration=0.075)
        >> Blackout(duration=0.275)
        >> Hold(Color.WHITE, ww=1.0, cw=1.0, duration=0.075)
        >> Blackout(duration=1.075)
    ) * 4
    strobe_heartbeat = (
        Hold(0.95, duration=0.075)
        >> Blackout(duration=0.275)
        >> Hold(0.95, duration=0.075)
        >> Blackout(duration=1.075)
    ) * 4

    # Phase B: 6.0s Rolling Thunderstorm Finale!
    pars_storm_end = (
        (Pulse(BLOOD_RED, duration=0.50).on(0, 2) | Pulse(PUMPKIN_ORANGE, duration=0.50).on(1, 3)) * 6
        | (Wait(0.25) >> Strobe(rate=0.95, duration=0.25, color=Color.WHITE)) * 6
    )

    # Strobe Bar: Jagged white flashes bouncing across segments + full white blast
    bar_storm_end = (
        (
            Hold(Color.WHITE, ww=1.0, cw=1.0, duration=0.075).on(0, 3)
            >> Hold(Color.WHITE, ww=1.0, cw=1.0, duration=0.075).on(1, 2)
            >> Blackout(duration=0.10)
        ) * 12  # 3.0s of rolling segment lightning
        >> Hold(Color.WHITE, ww=1.0, cw=1.0, duration=2.0)  # 2.0s maximum full white blast!
        >> Fade(Color.WHITE * 0.7, DARK_CRIMSON * 0.1, duration=1.0)  # 1.0s dissolve to darkness
    )

    # Master Strobe: Fast 20Hz strobe rolling throughout the 6s storm
    strobe_storm_end = (
        Hold(0.85, duration=3.0)
        >> Fade(0.85, 1.0, duration=2.0)
        >> Fade(1.0, 0.0, duration=1.0)
    )

    pars_act3 = heartbeat_cycle >> pars_storm_end
    bar_act3 = (bar_heartbeat | bar_heartbeat_whites) >> bar_storm_end
    strobe_act3 = strobe_heartbeat >> strobe_storm_end

    # =========================================================================
    # Combine All 3 Acts into an Infinite Loop
    # Total duration = 12.0 + 8.0 + 12.0 = 32.0s
    # =========================================================================
    pars_show = (pars_act1 >> pars_act2 >> pars_act3) * inf
    bar_show = (bar_act1 >> bar_act2 >> bar_act3) * inf
    strobe_show = (strobe_act1 >> strobe_act2 >> strobe_act3) * inf

    return (
        PARS(pars_show)
        | STROBE_BAR(bar_show)
        | STROBE_MASTER(strobe_show)
    )


if __name__ == "__main__":
    run_show_cli("Halloween Show 🎃⚡ (Blood, Embers & Lightning)", build_halloween_show())
