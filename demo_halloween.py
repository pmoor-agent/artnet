#!/usr/bin/env python3
"""Demo 3: Halloween lightshow with crimson/ember glow, pumpkin waves, and lightning strikes."""

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
    dim,
    inf,
)
from my_rig import PARS, STROBE_RGB, STROBE_W, run_show_cli


BLOOD_RED = Color(1.0, 0.0, 0.0)
DARK_CRIMSON = Color(0.35, 0.0, 0.0)
PUMPKIN_ORANGE = Color(1.0, 0.22, 0.0)
DEEP_EMBER = Color(0.7, 0.08, 0.0)
CANDLE_AMBER = Color(1.0, 0.38, 0.05)


def build_lightning_strike():
    """A 1.0s jagged double-bolt lightning strike (exact multiples of 25ms for 40Hz DMX)."""
    par_strike = (
        Hold(Color.WHITE, w=1.0, duration=0.10)
        >> Hold(BLOOD_RED * 0.2, duration=0.075)
        >> (Hold(Color.WHITE, w=1.0, duration=0.225) | Strobe(rate=0.95, duration=0.225))
        >> Fade(Color.WHITE * 0.6, DARK_CRIMSON, duration=0.60)
    )
    w8_strike = (
        Hold(Color.WHITE, duration=0.10).on(0, 1, 4, 5)
        >> Blackout(duration=0.075)
        >> Hold(Color.WHITE, duration=0.125).on(2, 3, 6, 7)
        >> Hold(Color.WHITE, duration=0.10)
        >> Chase(Color.WHITE * 0.8, step_duration=0.075, tail=1.2).mirror()
        >> Blackout(duration=0.30)
    )
    rgb8_strike = (
        Hold(Color(1.0, 0.9, 1.0), duration=0.10)
        >> Hold(DARK_CRIMSON, duration=0.075)
        >> Hold(Color(1.0, 0.95, 1.0), duration=0.225)
        >> Fade(PUMPKIN_ORANGE, DEEP_EMBER * 0.4, duration=0.60)
    )
    return par_strike, w8_strike, rgb8_strike


def build_halloween_show():
    par_bolt, w8_bolt, rgb8_bolt = build_lightning_strike()

    # 1. Smoldering Haunted Ember & Crimson Breathing + 2 Lightning Strikes (12.0s)
    ember_palette = [DARK_CRIMSON, BLOOD_RED, DEEP_EMBER, PUMPKIN_ORANGE, BLOOD_RED, DARK_CRIMSON]

    pars_breathe_1 = (
        Gradient(ember_palette, duration=5.0).spread(total_offset=2.5)
        | DimmerLFO(period=2.5, low=0.35, high=1.0, duration=5.0)
    )
    pars_breathe_2 = (
        Gradient(ember_palette, duration=5.0).spread(total_offset=2.5).reverse_fixtures()
        | DimmerLFO(period=2.5, low=0.35, high=1.0, duration=5.0)
    )
    rgb8_breathe_1 = Gradient(ember_palette, duration=5.0).spread(total_offset=3.0)
    rgb8_breathe_2 = Gradient(ember_palette, duration=5.0).spread(total_offset=3.0).reverse_fixtures()
    w8_breathe = Blackout(duration=5.0)

    pars_scene1 = pars_breathe_1 >> par_bolt >> pars_breathe_2 >> par_bolt
    w8_scene1 = w8_breathe >> w8_bolt >> w8_breathe >> w8_bolt
    rgb8_scene1 = rgb8_breathe_1 >> rgb8_bolt >> rgb8_breathe_2 >> rgb8_bolt

    # 2. Jack-O'-Lantern Flicker & Stalking Red Eye Scanner (8.0s)
    flicker_cycle = (
        Fade(DEEP_EMBER, PUMPKIN_ORANGE, duration=0.35)
        >> Fade(PUMPKIN_ORANGE, CANDLE_AMBER, duration=0.25)
        >> Fade(CANDLE_AMBER, DARK_CRIMSON, duration=0.40)
        >> Fade(DARK_CRIMSON, PUMPKIN_ORANGE, duration=0.40)
    ).phase(0.35) * 5

    pars_scene2 = flicker_cycle >> par_bolt

    rgb8_stalker = (
        Chase(BLOOD_RED, step_duration=0.175, background=DEEP_EMBER * 0.25, tail=1.6).pingpong() * 5
    )
    rgb8_scene2 = rgb8_stalker >> rgb8_bolt

    w8_glints = (
        Blackout(duration=1.1)
        >> Hold(Color.WHITE * 0.6, duration=0.075).on(1, 6)
        >> Blackout(duration=1.15)
        >> Hold(Color.WHITE * 0.7, duration=0.075).on(3, 4)
        >> Blackout(duration=1.1)
    ) * 2
    w8_scene2 = w8_glints >> w8_bolt

    # 3. Blood Pulse & Thunderstorm Finale (8.0s)
    heartbeat_pair = (
        Pulse(BLOOD_RED, duration=0.35, low=0.1, high=1.0)
        >> Pulse(PUMPKIN_ORANGE, duration=0.45, low=0.1, high=1.0)
        >> Hold(DARK_CRIMSON * 0.5, duration=0.70)
    )

    white_interruption = (
        Wait(1.25)
        >> (Hold(Color.WHITE, duration=0.25) | Strobe(rate=0.85, duration=0.25))
    ) * 4

    pars_storm_finale = (
        (Pulse(BLOOD_RED, duration=0.5).on(0, 2) | Pulse(PUMPKIN_ORANGE, duration=0.5).on(1, 3)) * 4
        | (Wait(0.3) >> Strobe(rate=0.9, duration=0.2, color=Color.WHITE)) * 4
    )

    pars_scene3 = ((heartbeat_pair * 4) | white_interruption) >> pars_storm_finale

    rgb8_heartbeat = (
        Pulse(BLOOD_RED, duration=0.35).mirror()
        >> Pulse(PUMPKIN_ORANGE, duration=0.45).mirror()
        >> Fade(DEEP_EMBER, DARK_CRIMSON * 0.3, duration=0.70)
    ) * 4
    rgb8_storm_finale = (
        Chase(BLOOD_RED, step_duration=0.125, background=PUMPKIN_ORANGE * 0.35, tail=1.5).pingpong() * 2
    )
    rgb8_scene3 = rgb8_heartbeat >> rgb8_storm_finale

    w8_heartbeat_flashes = (
        Blackout(duration=1.25)
        >> (
            Hold(Color.WHITE, duration=0.05).on(0, 2, 4, 6)
            >> Hold(Color.WHITE, duration=0.05).on(1, 3, 5, 7)
        ) * 2
        >> Blackout(duration=0.05)
    ) * 4
    w8_storm_finale = (
        Blackout(duration=0.3)
        >> Hold(Color.WHITE, duration=0.05).on(0, 3, 4, 7)
        >> Hold(Color.WHITE, duration=0.05).on(1, 2, 5, 6)
        >> Hold(Color.WHITE, duration=0.10)
    ) * 4
    w8_scene3 = w8_heartbeat_flashes >> w8_storm_finale

    pars_anim = (pars_scene1 >> pars_scene2 >> pars_scene3) * inf
    w8_anim = (w8_scene1 >> w8_scene2 >> w8_scene3) * inf
    rgb8_anim = (rgb8_scene1 >> rgb8_scene2 >> rgb8_scene3) * inf

    return (
        PARS(pars_anim)
        | STROBE_W(dim(0.25, w8_anim))
        | STROBE_RGB(dim(0.35, rgb8_anim))
    )


if __name__ == "__main__":
    run_show_cli("Demo 3 (Halloween Show 🎃⚡)", build_halloween_show())
