"""User hardware configuration for 192.168.1.158 (Universe 1, 40Hz DMX).

The `lightshow` engine only knows about two DMX primitives:
  - `RGB(address)`     : 3-channel RGB color triplet
  - `Channel(address)` : 1-channel scalar (with optional `default` and `dmx_range`)

Here in user code we compose them into fixture templates and views!
"""

from __future__ import annotations
import argparse
from lightshow import RGB, Channel, FixtureGroup, Rig


# =============================================================================
# 1. 4x RGBW PARs (Channels 1-6, 7-12, 13-18, 19-24)
# =============================================================================

def rgbw_par_template(base_channel: int) -> dict[str, RGB | Channel]:
    """6-channel RGBW PAR template composed from `RGB` and `Channel` primitives."""
    return {
        "color":  RGB(base_channel),                            # Ch +0..+2 : RGB
        "w":      Channel(base_channel + 3, default=0.0),       # Ch +3     : White LED
        "dimmer": Channel(base_channel + 4, default=1.0),       # Ch +4     : Master brightness
        "strobe": Channel(base_channel + 5, dmx_range=(11, 255)),  # Ch +5  : Strobe (0=off, 11..255)
    }


# Full 6-channel PAR group
PARS = FixtureGroup.from_template("PARS", rgbw_par_template, start_channels=(1, 7, 13, 19))

# Or slice out individual attributes into standalone 4-element groups whenever desired:
PAR_RGB     = PARS.select("color",  name="PAR_RGB")
PAR_WHITES  = PARS.select("w",      name="PAR_W")
PAR_DIMMERS = PARS.select("dimmer", name="PAR_DIM")
PAR_STROBES = PARS.select("strobe", name="PAR_STR")


# =============================================================================
# 2. 4-Segment Strobe Bar in 24-Channel Mode (starting at Channel 32)
#    Per manual:
#      Seg 1: Ch 1-3 RGB, Ch 4 WW, Ch 5 CW
#      Seg 2: Ch 6-8 RGB, Ch 9 WW, Ch 10 CW
#      Seg 3: Ch 11-13 RGB, Ch 14 WW, Ch 15 CW
#      Seg 4: Ch 16-18 RGB, Ch 19 WW, Ch 20 CW
#      Master Strobe: Ch 21 (0-8: off, 9-255: strobe rate)
#      Ch 22-24: Autoprograms (left at 0)
# =============================================================================

STROBE_START = 32

def _strobe_seg(i: int) -> dict[str, RGB | Channel]:
    # Segment i base offset: i * 5 channels
    base = STROBE_START + i * 5
    return {
        "color": RGB(base),
        "ww":    Channel(base + 3),
        "cw":    Channel(base + 4),
        "w":     Channel(base + 4),  # Default 'w' maps to cold white (or ww+cw)
    }

# Unified 4-segment strobe fixture with RGB, WW, CW per segment:
STROBE_BAR = FixtureGroup(
    name="STROBE_BAR",
    elements=[_strobe_seg(i) for i in range(4)],
)

# Dedicated sub-views:
STROBE_RGB = STROBE_BAR.select("color", name="STROBE_RGB")
STROBE_WW  = STROBE_BAR.select("ww",    name="STROBE_WW")
STROBE_CW  = STROBE_BAR.select("cw",    name="STROBE_CW")
STROBE_W   = STROBE_CW  # Alias for existing scripts expecting STROBE_W

# Master strobe channel on the strobe bar (Channel 21 from base = Channel 52):
STROBE_MASTER = FixtureGroup(
    name="STROBE_MASTER",
    elements=[{"strobe": Channel(STROBE_START + 20, dmx_range=(9, 255))}],
)


# =============================================================================
# 3. Combined Cross-Fixture Groups (`+` concatenation & slicing)
# =============================================================================

# All 8 RGB elements across the entire rig (4 PARs + 4 Strobe RGB segments):
ALL_RGB = PAR_RGB + STROBE_RGB

# All 8 White channels across the entire rig (4 PAR Whites + 4 Strobe Cold White segments):
ALL_WHITES = PAR_WHITES + STROBE_W

# Spatial stage layout: PARs 1-2 -> Strobe Segments 1-4 -> PARs 3-4:
STAGE_RGB = (PAR_RGB[:2] + STROBE_RGB + PAR_RGB[2:]).named("STAGE_RGB")


# =============================================================================
# 4. Declarative 2D Virtual Stage Layout (Physical Geometry & Profiles)
# =============================================================================
from lightshow.profiles import EurolitePartySpot, EuroliteBCL40Bar, Stage

STAGE = Stage(
    width=860,
    height=240,
    title="Physical Rig (4x Eurolite PARty Spot + BCL-40 Strobe Bar)",
    fixtures=[
        EurolitePartySpot(PARS[0], x=95, y=115, radius=28, label="PAR 1"),
        EurolitePartySpot(PARS[1], x=225, y=115, radius=28, label="PAR 2"),
        EuroliteBCL40Bar(
            STROBE_BAR,
            x=340,
            y=86,
            width=260,
            height=58,
            master_strobe=STROBE_MASTER,
            label="BCL-40 Bar",
        ),
        EurolitePartySpot(PARS[2], x=635, y=115, radius=28, label="PAR 3"),
        EurolitePartySpot(PARS[3], x=765, y=115, radius=28, label="PAR 4"),
    ],
)


# =============================================================================
# Rig Factory & CLI Runner
# =============================================================================

def create_rig(
    host: str = "192.168.1.158",
    universe: int = 1,
    universe_base: int = 0,
    fps: float = 40.0,
    dry_run: bool = False,
) -> Rig:
    """Create the configured Rig for this physical setup."""
    return Rig(
        groups=[PARS, STROBE_RGB, STROBE_WW, STROBE_CW, STROBE_MASTER],
        host=host,
        universe=universe,
        universe_base=universe_base,
        fps=fps,
        dry_run=dry_run,
    )


def run_show_cli(description: str, scene) -> None:
    """Standard CLI runner for any show built for this rig."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--host", default="192.168.1.158", help="Art-Net node IP (default: 192.168.1.158)")
    parser.add_argument("--universe", type=int, default=1, help="Universe number (default: 1)")
    parser.add_argument(
        "--universe-base",
        type=int,
        default=0,
        choices=(0, 1),
        help="Set to 1 if your node uses 0-indexed wire universes",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview in terminal without sending UDP packets")
    parser.add_argument("--duration", type=float, default=None, help="Stop after N seconds")
    args = parser.parse_args()

    rig = create_rig(
        host=args.host,
        universe=args.universe,
        universe_base=args.universe_base,
        dry_run=args.dry_run,
    )
    print(
        f"Streaming {description} to {args.host} (universe={args.universe}) "
        f"{'[DRY RUN]' if args.dry_run else ''} — Press Ctrl+C to stop."
    )
    rig.play(scene, max_duration=args.duration, preview=True)
    print()
