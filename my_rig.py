"""User hardware configuration for 192.168.1.17 (Universe 1, 40Hz DMX).

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
# 2. 8-Segment RGBW Strobe Bar (Channels 32..39 = 8x White, Channels 40..63 = 8x RGB)
# =============================================================================

# Unified 8-segment RGBW Strobe Bar (each segment `i` combines White at 32+i and RGB at 40+3*i!)
STROBE_BAR = FixtureGroup(
    name="STROBE_BAR",
    elements=[
        {
            "w":     Channel(32 + i),
            "color": RGB(40 + i * 3),
        }
        for i in range(8)
    ],
)

# Or use the split 8-White and 8-RGB views sliced directly from STROBE_BAR:
STROBE_W   = STROBE_BAR.select("w",     name="W8")
STROBE_RGB = STROBE_BAR.select("color", name="RGB8")


# =============================================================================
# 3. Combined Cross-Fixture Groups (`+` concatenation & slicing)
# =============================================================================

# All 12 RGB elements across the entire rig (4 PARs + 8 Strobe RGB segments):
ALL_RGB = PAR_RGB + STROBE_RGB

# All 12 White channels across the entire rig (4 PAR Whites + 8 Strobe White segments):
ALL_WHITES = PAR_WHITES + STROBE_W

# Spatial stage layout (e.g. if the strobe bar sits in the middle between PARs 1-2 and PARs 3-4):
STAGE_RGB = (PAR_RGB[:2] + STROBE_RGB + PAR_RGB[2:]).named("STAGE_RGB")


# =============================================================================
# Rig Factory & CLI Runner
# =============================================================================

def create_rig(
    host: str = "192.168.1.17",
    universe: int = 1,
    universe_base: int = 0,
    fps: float = 40.0,
    dry_run: bool = False,
) -> Rig:
    """Create the configured Rig for this physical setup."""
    return Rig(
        groups=[PARS, STROBE_W, STROBE_RGB],
        host=host,
        universe=universe,
        universe_base=universe_base,
        fps=fps,
        dry_run=dry_run,
    )


def run_show_cli(description: str, scene) -> None:
    """Standard CLI runner for any show built for this rig."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--host", default="192.168.1.17", help="Art-Net node IP (default: 192.168.1.17)")
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
