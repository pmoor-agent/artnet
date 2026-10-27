"""16-PAR Disco Extravaganza Show (30 Seconds, 2 Rows of 8 PARs).

Showcases 5 distinct musical/lighting movements:
  1. [0.0s -  6.0s] The Intro Groove       : Dual counter-comets crossing in the center
  2. [6.0s - 12.0s] Saturday Night Checkerboard : Alternating tile flashes on the beat
  3. [12.0s - 18.0s] Mirror Ripple & Burst  : Outward/inward stereo ripples + glitterball jitter
  4. [18.0s - 24.0s] Dual-Helix Rainbow Wheel: Counter-rotating color wheels + white pinspot chase
  5. [24.0s - 30.0s] Peak Time Drop & Finale: Staccato beat hits, high-speed chases & warm candle fade
"""

from __future__ import annotations
from lightshow import (
    Color,
    Chase,
    Pulse,
    Fade,
    Hold,
    Rainbow,
    Wait,
    Blackout,
    Ease,
    ch,
)
from lightshow.profiles import EurolitePartySpot, Stage


# =============================================================================
# 1. 16-PAR Rig Setup (2 Rows of 8 PARty Spots)
# =============================================================================

# Build 16 PARty Spots (6 DMX channels each: RGB, White, Dimmer, Strobe)
PARS = EurolitePartySpot.group("PARS", start_channels=[1 + i * 6 for i in range(16)])

ROW_TOP = PARS[0:8].named("ROW_TOP")    # Top row: PAR 1 - 8
ROW_BOT = PARS[8:16].named("ROW_BOT")  # Bottom row: PAR 9 - 16

# 2D Virtual Stage Geometry for 2 Rows of 8 PARs
STAGE_16 = Stage(
    width=900,
    height=260,
    title="Disco Rig: 2 Rows of 8 PARs (16x EUROLITE LED PARty Spot)",
    fixtures=[
        *(
            EurolitePartySpot(ROW_TOP[i], x=65 + i * 110, y=70, radius=28, label=f"T{i+1}")
            for i in range(8)
        ),
        *(
            EurolitePartySpot(ROW_BOT[i], x=65 + i * 110, y=190, radius=28, label=f"B{i+1}")
            for i in range(8)
        ),
    ],
)


# =============================================================================
# 2. Color Palette
# =============================================================================

HOT_MAGENTA = Color.from_hex("#ff007f")
DISCO_CYAN  = Color.from_hex("#00f0ff")
ELECTRIC_LIME = Color.from_hex("#00ff66")
DISCO_GOLD  = Color.from_hex("#ffbb00")
DEEP_PURPLE = Color.from_hex("#6600cc")
DARK_AMBER  = Color.from_hex("#331800")
WARM_WHITE  = Color.from_hex("#ffeedd")


# =============================================================================
# 3. The 5 Movements (6.0 Seconds Each = 30.0 Seconds Total)
# =============================================================================

def build_movement_1_intro() -> tuple:
    """[0.0s - 6.0s] The Intro Groove: Dual counter-comets crossing in the center."""
    dur = 6.0

    # Top: Hot Magenta comet left -> right with soft lead & long tail
    top_comet = (
        Chase(
            HOT_MAGENTA,
            step_duration=0.14,
            lead=1.0,
            hold=0.5,
            tail=2.0,
            background=DEEP_PURPLE * 0.12,
        ).pingpong()
    ) @ dur

    # Bottom: Disco Cyan comet right -> left (counter-directional)
    bot_comet = (
        Chase(
            DISCO_CYAN,
            step_duration=0.14,
            lead=1.0,
            hold=0.5,
            tail=2.0,
            background=DEEP_PURPLE * 0.12,
        ).reverse_fixtures().pingpong()
    ) @ dur

    # Floor beat shimmer: warm gold pulse every 0.75s
    beat_shimmer = (
        Pulse(DISCO_GOLD * 0.25, lead=0.05, hold=0.10, tail=0.60) * 8
    ) @ dur

    scene = (
        ROW_TOP(top_comet + beat_shimmer)
        | ROW_BOT(bot_comet + beat_shimmer)
    )
    return scene


def build_movement_2_checkerboard() -> tuple:
    """[6.0s - 12.0s] Saturday Night Checkerboard: Alternating diagonal tiles."""
    dur = 6.0
    beat = 0.50  # 120 BPM

    # First half (3s): Lime vs Magenta
    flash_lime = Pulse(ELECTRIC_LIME, lead=0.03, hold=0.10, tail=0.37) * 6
    flash_pink = (Wait(0.25) >> (Pulse(HOT_MAGENTA, lead=0.03, hold=0.10, tail=0.37) * 5) >> Wait(0.25))

    part_a = (
        ROW_TOP(flash_lime.on(0, 2, 4, 6) | flash_pink.on(1, 3, 5, 7))
        | ROW_BOT(flash_lime.on(1, 3, 5, 7) | flash_pink.on(0, 2, 4, 6))
    )

    # Second half (3s): Gold vs Deep Purple with white diode hits
    flash_gold = Pulse(DISCO_GOLD, lead=0.03, hold=0.10, tail=0.37) * 6
    flash_purp = (Wait(0.25) >> (Pulse(DEEP_PURPLE, lead=0.03, hold=0.10, tail=0.37) * 5) >> Wait(0.25))

    part_b = (
        ROW_TOP(flash_purp.on(0, 2, 4, 6) | flash_gold.on(1, 3, 5, 7))
        | ROW_BOT(flash_purp.on(1, 3, 5, 7) | flash_gold.on(0, 2, 4, 6))
    )

    # Add white LED accent punch on odd beats
    white_kick = ch("w", (Pulse(1.0, lead=0.02, hold=0.05, tail=0.18) >> Wait(0.25)) * 12)

    return (part_a >> part_b) | (ROW_TOP(white_kick) | ROW_BOT(white_kick))


def build_movement_3_mirror_ripple() -> tuple:
    """[12.0s - 18.0s] Mirror Ripple & Burst: Center-out expansion + glitterball jitter."""
    dur = 6.0

    # Top: Outward stereo ripple from center to edges (Gold/Amber)
    top_ripple = (
        (Pulse(DISCO_GOLD, lead=0.04, hold=0.08, tail=0.32).stagger(0.10, bounce=True) * 4)
        .mirror()
        .jitter_hue(amount=0.12, speed=6.0)
    ) @ dur

    # Bottom: Inward stereo ripple from edges to center (Electric Cyan)
    bot_ripple = (
        (Pulse(DISCO_CYAN, lead=0.04, hold=0.08, tail=0.32).stagger(0.10, bounce=True) * 4)
        .reverse_fixtures()
        .mirror()
        .jitter_hue(amount=0.12, speed=6.0)
    ) @ dur

    # Ambient deep purple underglow
    ambient = Hold(DEEP_PURPLE * 0.15, duration=dur)

    return (
        ROW_TOP(ambient | top_ripple)
        | ROW_BOT(ambient | bot_ripple)
    )


def build_movement_4_rainbow_spiral() -> tuple:
    """[18.0s - 24.0s] Dual-Helix Rainbow Wheel: Counter-rotating color wheels + spotlight chase."""
    dur = 6.0

    # Top row rotates rainbow left -> right
    top_wheel = Rainbow(period=3.0).spread() * 2

    # Bottom row rotates rainbow right -> left (opposite direction)
    bot_wheel = Rainbow(period=3.0).reverse_fixtures().spread() * 2

    # Fast white pinspot beam dancing across the mirror ball (dimmer & white channels)
    pinspot_top = Chase(1.0, step_duration=0.075, lead=0.5, hold=0.2, tail=1.2).pingpong() * 5
    pinspot_bot = Chase(1.0, step_duration=0.075, lead=0.5, hold=0.2, tail=1.2).reverse_fixtures().pingpong() * 5

    # Building intensity ramp towards the drop (dimmer ramping from 0.6 -> 1.0)
    swell = Fade(0.6, 1.0, duration=dur)

    return (
        ROW_TOP((top_wheel @ dur) & swell | ch("w", pinspot_top @ dur))
        | ROW_BOT((bot_wheel @ dur) & swell | ch("w", pinspot_bot @ dur))
    )


def build_movement_5_peak_drop() -> tuple:
    """[24.0s - 30.0s] Peak Time Drop & Finale: Staccato beat hits, high-speed chases & candle fade."""
    dur = 6.0

    # First 4.5 seconds: High-energy drop
    drop_dur = 4.5

    # Double-speed interlocking chases
    fast_chase_top = (
        Chase(HOT_MAGENTA, step_duration=0.06, lead=0.4, hold=0.2, tail=1.4).pingpong() * 6
    ) @ drop_dur
    fast_chase_bot = (
        Chase(DISCO_GOLD, step_duration=0.06, lead=0.4, hold=0.2, tail=1.4).reverse_fixtures().pingpong() * 6
    ) @ drop_dur

    # Massive quarter-note white/cyan stabs on the beat
    beat_stab = (
        (Pulse(WARM_WHITE, lead=0.02, hold=0.06, tail=0.22) | ch("w", Pulse(1.0, lead=0.02, hold=0.06, tail=0.22)))
        >> Wait(0.20)
    ) * 9  # 9 beat hits over 4.5s
    beat_stab = beat_stab @ drop_dur

    drop_section = (
        ROW_TOP(fast_chase_top + beat_stab.scale(0.6))
        | ROW_BOT(fast_chase_bot + beat_stab.scale(0.6))
    )

    # Final 1.5 seconds: Warm candlelight sparkle fading slowly into blackout
    fade_dur = 1.5
    candle_color = Color.from_hex("#ff7700")
    warm_glow = Hold(candle_color, duration=fade_dur).flicker(depth=0.6, speed=14.0)
    fade_envelope = Fade(1.0, 0.0, duration=fade_dur)

    finale_section = (
        ROW_TOP(warm_glow & fade_envelope)
        | ROW_BOT(warm_glow & fade_envelope)
    )

    return drop_section >> finale_section


# =============================================================================
# 4. Master 30-Second Disco Show Composition
# =============================================================================

def create_disco_show():
    """Compose all 5 movements into a seamless 30-second disco show."""
    m1 = build_movement_1_intro()           # 0.0s -  6.0s
    m2 = build_movement_2_checkerboard()    # 6.0s - 12.0s
    m3 = build_movement_3_mirror_ripple()   # 12.0s - 18.0s
    m4 = build_movement_4_rainbow_spiral()  # 18.0s - 24.0s
    m5 = build_movement_5_peak_drop()       # 24.0s - 30.0s

    disco_show = m1 >> m2 >> m3 >> m4 >> m5
    return disco_show


DISCO_SHOW = create_disco_show()

if __name__ == "__main__":
    print(f"DISCO_SHOW compiled successfully! Total duration: {DISCO_SHOW.duration:.2f}s")
