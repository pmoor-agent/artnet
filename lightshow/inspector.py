"""Interactive DMX channel inspection and scrubber views for Jupyter notebooks and Python scripts.

Provides rich visual previews of raw DMX frames, channel values, fixture groupings,
and optical diode previews with authentic color-coded badges, dark/faint inactive channel
treatment, and interactive timeline scrubbing with frame-by-frame stepping.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import html
import json
import math
import time
from typing import Any, Mapping, Optional, Sequence, Union

from .fixtures import Channel, DMXCanvas, FixtureGroup, PrimitiveSpec, RGB, Scene
from .state import Color


# =============================================================================
# 1. Base Display Views (Rich HTML in Jupyter, text representation in console)
# =============================================================================

class HTMLView(str):
    """A string subclass that implements `_repr_html_()` for rich display in Jupyter Notebooks.

    Inheriting from `str` ensures full backward compatibility with any code expecting a normal string
    (e.g. slicing, regex, file writes, inkscape/ffmpeg pipelines).
    """

    def _repr_html_(self) -> str:
        return str(self)


class StageScrubberView(HTMLView):
    """Interactive Jupyter HTML5/JS scrubber widget for Stage and Scene animations."""

    def __new__(cls, html_content: str):
        return super().__new__(cls, html_content)


class DMXFrameView(HTMLView):
    """Rich DMX frame inspector view for Jupyter notebooks and Python terminal.

    Displays raw DMX channel bytes, fixture semantic grouping, color diode swatches,
    and universe grids with interactive zero-filtering and tab switching.
    """

    dmx: list[int]
    t: float
    universe: int
    metadata: Any

    def __new__(
        cls,
        html_content: str,
        dmx: Sequence[int],
        t: float = 0.0,
        universe: int = 1,
        metadata: Any = None,
    ):
        instance = super().__new__(cls, html_content)
        instance.dmx = list(dmx)
        instance.t = float(t)
        instance.universe = int(universe)
        instance.metadata = metadata
        return instance

    @property
    def active_channels(self) -> list[tuple[int, int]]:
        """List of (1-based channel address, DMX byte value) for all active (non-zero) channels."""
        return [(i + 1, val) for i, val in enumerate(self.dmx) if val > 0]

    def channel(self, address: int) -> int:
        """Return the DMX byte value (0..255) for 1-based `address`."""
        if 1 <= address <= len(self.dmx):
            return self.dmx[address - 1]
        return 0

    def to_dict(self) -> dict[int, int]:
        """Return a mapping of 1-based address -> byte value for all active channels."""
        return {addr: val for addr, val in self.active_channels}

    def summary(self, hide_zeros: bool = False) -> str:
        """Return a formatted plain-text summary of active channels and fixtures for the console."""
        lines = [f"DMX Universe {self.universe} Frame at t = {self.t:.2f}s ({len(self.active_channels)}/{len(self.dmx)} active):"]
        if self.metadata and "fixture_meta" in self.metadata:
            for fm in self.metadata["fixture_meta"]:
                ch_strs = []
                for a in fm.channel_addrs:
                    val = self.dmx[a - 1] if a <= len(self.dmx) else 0
                    if hide_zeros and val == 0:
                        continue
                    cm = self.metadata["channel_meta"].get(a)
                    lbl = cm.role_label if cm else str(a)
                    ch_strs.append(f"{lbl}:{val}")
                if ch_strs:
                    lines.append(f"  {fm.name:<18} ({fm.channel_range:<8}): {' '.join(ch_strs)}")
        else:
            for addr, val in self.active_channels:
                lines.append(f"  Ch {addr:<3}: {val}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        active = len(self.active_channels)
        total = len(self.dmx)
        return f"<DMXFrameView t={self.t:.2f}s Univ {self.universe} ({active}/{total} active channels)>"


def _time_hash() -> int:
    return int(time.time() * 1000) % 10000000


# =============================================================================
# 2. Channel Role Classification & Metadata
# =============================================================================

@dataclass
class ChannelMeta:
    """Metadata describing a single 1-based DMX channel."""
    address: int
    role: str           # 'r', 'g', 'b', 'white', 'cold_white', 'warm_white', 'dimmer', 'strobe', 'speed', 'mode', 'pan', 'tilt', 'generic'
    role_label: str     # 'R', 'G', 'B', 'W', 'CW', 'WW', 'DIM', 'STRB', 'SPD', 'MODE', etc.
    fixture_label: str  # e.g. 'PAR 1', 'STROBE_BAR Seg 1'
    attr_name: str      # 'color.r', 'color.g', 'color.b', 'w', 'dimmer', etc.
    fixture_idx: int = 0
    default_val: int = 0


@dataclass
class FixtureMeta:
    """Metadata describing a logical fixture and its mapped channels."""
    index: int
    name: str
    channel_range: str
    min_address: int
    max_address: int
    r_addr: Optional[int] = None
    g_addr: Optional[int] = None
    b_addr: Optional[int] = None
    w_addr: Optional[int] = None
    dim_addr: Optional[int] = None
    strobe_addr: Optional[int] = None
    channel_addrs: list[int] = field(default_factory=list)


def classify_role(attr: str) -> tuple[str, str]:
    """Map attribute name to `(role_identifier, short_display_label)`."""
    a = attr.lower().strip()
    if a in ("r", "red", "color.r"):
        return ("r", "R")
    if a in ("g", "green", "color.g"):
        return ("g", "G")
    if a in ("b", "blue", "color.b"):
        return ("b", "B")
    if a in ("cw", "cold_white", "coldwhite"):
        return ("cold_white", "CW")
    if a in ("ww", "warm_white", "warmwhite"):
        return ("warm_white", "WW")
    if a in ("w", "white"):
        return ("white", "W")
    if a in ("dimmer", "dim", "intensity", "master"):
        return ("dimmer", "DIM")
    if a in ("strobe", "strb", "shutter", "flash"):
        return ("strobe", "STRB")
    if a in ("speed", "rate", "tempo"):
        return ("speed", "SPD")
    if a in ("mode", "macro", "func", "function", "program"):
        return ("mode", "MODE")
    if a in ("pan", "tilt"):
        return (a, a.upper())
    return ("generic", a.upper()[:4] if a else "CH")


def _to_byte(val: float, dmx_range: tuple[int, int] = (0, 255)) -> int:
    low, high = dmx_range
    if low > 0 and val <= 0.0:
        return 0
    clamped = max(0.0, min(1.0, val))
    return int(round(low + clamped * (high - low)))


def extract_channel_metadata(
    scene_or_dmx: Any,
    *,
    stage: Any = None,
    groups: Optional[Sequence[FixtureGroup]] = None,
    max_channel: Optional[int] = None,
) -> tuple[dict[int, ChannelMeta], list[FixtureMeta], int]:
    """Extract semantic channel metadata from a Scene, Stage, FixtureGroup list, or raw DMX."""
    mapped_channels: dict[int, ChannelMeta] = {}
    fixtures_dict: dict[str, FixtureMeta] = {}

    def register_prim(
        attr: str,
        prim: PrimitiveSpec,
        fix_name: str,
        fix_idx: int,
    ) -> None:
        if isinstance(prim, RGB):
            r_addr = prim.address
            g_addr = prim.address + 1
            b_addr = prim.address + 2

            mapped_channels[r_addr] = ChannelMeta(
                address=r_addr, role="r", role_label="R",
                fixture_label=fix_name, attr_name="color.r", fixture_idx=fix_idx, default_val=0,
            )
            mapped_channels[g_addr] = ChannelMeta(
                address=g_addr, role="g", role_label="G",
                fixture_label=fix_name, attr_name="color.g", fixture_idx=fix_idx, default_val=0,
            )
            mapped_channels[b_addr] = ChannelMeta(
                address=b_addr, role="b", role_label="B",
                fixture_label=fix_name, attr_name="color.b", fixture_idx=fix_idx, default_val=0,
            )

            if fix_name in fixtures_dict:
                fm = fixtures_dict[fix_name]
                fm.r_addr = r_addr
                fm.g_addr = g_addr
                fm.b_addr = b_addr
                for a in (r_addr, g_addr, b_addr):
                    if a not in fm.channel_addrs:
                        fm.channel_addrs.append(a)
                fm.min_address = min(fm.min_address, r_addr)
                fm.max_address = max(fm.max_address, b_addr)

        elif isinstance(prim, Channel):
            addr = prim.address
            role, label = classify_role(attr)
            def_byte = _to_byte(prim.default, prim.dmx_range)
            # Avoid overwriting RGB or primary roles if duplicate alias exists (e.g. 'cw' vs 'w')
            if addr not in mapped_channels or role in ("white", "cold_white", "warm_white", "dimmer", "strobe"):
                mapped_channels[addr] = ChannelMeta(
                    address=addr, role=role, role_label=label,
                    fixture_label=fix_name, attr_name=attr, fixture_idx=fix_idx, default_val=def_byte,
                )

            if fix_name in fixtures_dict:
                fm = fixtures_dict[fix_name]
                if addr not in fm.channel_addrs:
                    fm.channel_addrs.append(addr)
                fm.min_address = min(fm.min_address, addr)
                fm.max_address = max(fm.max_address, addr)
                if role in ("white", "cold_white", "warm_white"):
                    fm.w_addr = addr
                elif role == "dimmer":
                    fm.dim_addr = addr
                elif role == "strobe":
                    fm.strobe_addr = addr

    # 1. Inspect Stage if present
    existing_addr_sets: dict[tuple[int, ...], str] = {}

    if stage is not None and hasattr(stage, "fixtures"):
        for item in stage.fixtures:
            label = getattr(item, "label", "") or "Fixture"
            if hasattr(item, "group") and isinstance(item.group, FixtureGroup):
                grp = item.group
                for i in range(grp.count):
                    el_label = grp.label(i) if hasattr(grp, "label") else f"{label} Seg {i + 1}"
                    f_meta = FixtureMeta(
                        index=len(fixtures_dict),
                        name=el_label,
                        channel_range="",
                        min_address=999999,
                        max_address=0,
                    )
                    fixtures_dict[el_label] = f_meta
                    for attr, prim in grp.elements[i].items():
                        register_prim(attr, prim, el_label, f_meta.index)
                    if f_meta.channel_addrs:
                        existing_addr_sets[tuple(sorted(set(f_meta.channel_addrs)))] = el_label

                if hasattr(item, "master_strobe_element") and item.master_strobe_element:
                    m_label = f"{label} Master"
                    f_meta = FixtureMeta(
                        index=len(fixtures_dict),
                        name=m_label,
                        channel_range="",
                        min_address=999999,
                        max_address=0,
                    )
                    fixtures_dict[m_label] = f_meta
                    for attr, prim in item.master_strobe_element.items():
                        register_prim(attr, prim, m_label, f_meta.index)
                    if f_meta.channel_addrs:
                        existing_addr_sets[tuple(sorted(set(f_meta.channel_addrs)))] = m_label

            elif hasattr(item, "element") and isinstance(item.element, dict):
                f_meta = FixtureMeta(
                    index=len(fixtures_dict),
                    name=label,
                    channel_range="",
                    min_address=999999,
                    max_address=0,
                )
                fixtures_dict[label] = f_meta
                for attr, prim in item.element.items():
                    register_prim(attr, prim, label, f_meta.index)
                if f_meta.channel_addrs:
                    existing_addr_sets[tuple(sorted(set(f_meta.channel_addrs)))] = label

    # 2. Inspect groups from Scene if not already covered
    active_groups = groups
    if active_groups is None and hasattr(scene_or_dmx, "groups"):
        active_groups = scene_or_dmx.groups()

    if active_groups:
        for grp in active_groups:
            for i in range(grp.count):
                el_addrs = tuple(
                    sorted(
                        set(
                            a
                            for prim in grp.elements[i].values()
                            for a in (
                                [prim.address, prim.address + 1, prim.address + 2]
                                if isinstance(prim, RGB)
                                else [prim.address]
                            )
                        )
                    )
                )
                # If these exact channels are already represented by a stage fixture, skip duplicate
                if el_addrs in existing_addr_sets:
                    continue

                el_label = grp.label(i) if hasattr(grp, "label") else (f"{grp.name}[{i}]" if grp.count > 1 else grp.name)
                if el_label not in fixtures_dict:
                    f_meta = FixtureMeta(
                        index=len(fixtures_dict),
                        name=el_label,
                        channel_range="",
                        min_address=999999,
                        max_address=0,
                    )
                    fixtures_dict[el_label] = f_meta
                else:
                    f_meta = fixtures_dict[el_label]

                for attr, prim in grp.elements[i].items():
                    register_prim(attr, prim, el_label, f_meta.index)
                if f_meta.channel_addrs:
                    existing_addr_sets[tuple(sorted(set(f_meta.channel_addrs)))] = el_label

    # Finalize channel ranges for all fixtures and sort by ascending start address
    fixtures_list: list[FixtureMeta] = []
    for fm in fixtures_dict.values():
        fm.channel_addrs.sort()
        if fm.min_address <= fm.max_address:
            fm.channel_range = f"Ch {fm.min_address}–{fm.max_address}" if fm.min_address != fm.max_address else f"Ch {fm.min_address}"
            fixtures_list.append(fm)

    fixtures_list.sort(key=lambda f: f.min_address)
    # Re-index
    for idx, fm in enumerate(fixtures_list):
        fm.index = idx

    # 3. Determine universe channel count
    dmx_len = len(scene_or_dmx) if isinstance(scene_or_dmx, (list, tuple)) else 0
    highest = max([24] + list(mapped_channels.keys()) + [dmx_len])
    if max_channel is not None:
        universe_size = max_channel
    else:
        # Round up to nearest multiple of 16 (e.g. 24 -> 32, 48, 64, ...)
        universe_size = max(32, math.ceil(highest / 16) * 16)

    # 4. Fill unassigned channels up to universe_size
    unassigned_addrs: list[int] = []
    for ch in range(1, universe_size + 1):
        if ch not in mapped_channels:
            mapped_channels[ch] = ChannelMeta(
                address=ch,
                role="generic",
                role_label=str(ch),
                fixture_label="Unassigned",
                attr_name=f"Ch {ch}",
                fixture_idx=-1,
                default_val=0,
            )
            unassigned_addrs.append(ch)

    if unassigned_addrs:
        fixtures_list.append(
            FixtureMeta(
                index=-1,
                name="Unassigned Channels",
                channel_range=f"Ch {unassigned_addrs[0]}–{unassigned_addrs[-1]}",
                min_address=unassigned_addrs[0],
                max_address=unassigned_addrs[-1],
                channel_addrs=unassigned_addrs,
            )
        )

    return mapped_channels, fixtures_list, universe_size


# =============================================================================
# 3. CSS Styles for DMX Frame Inspection
# =============================================================================

DMX_INSPECTOR_CSS = """
<style>
.dmx-inspector {
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0b0f17;
    border: 1px solid #1e293b;
    border-radius: 8px;
    padding: 12px;
    margin: 10px 0;
    color: #e2e8f0;
    box-sizing: border-box;
}
.dmx-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
    padding-bottom: 8px;
    border-bottom: 1px solid #1e293b;
    margin-bottom: 10px;
}
.dmx-title-group {
    display: flex;
    align-items: center;
    gap: 8px;
}
.dmx-title {
    font-size: 13px;
    font-weight: 600;
    color: #f8fafc;
    letter-spacing: 0.3px;
}
.dmx-badge {
    font-family: monospace;
    font-size: 11px;
    padding: 2px 7px;
    border-radius: 4px;
    background: #1e293b;
    color: #94a3b8;
    border: 1px solid #334155;
}
.dmx-badge-time {
    color: #38bdf8;
    font-weight: 600;
}
.dmx-badge-active {
    color: #4ade80;
}
.dmx-actions {
    display: flex;
    align-items: center;
    gap: 6px;
}
.dmx-btn {
    background: #161f30;
    color: #cbd5e1;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
    user-select: none;
}
.dmx-btn:hover {
    background: #25334d;
    border-color: #475569;
    color: #ffffff;
}
.dmx-btn.active {
    background: #2563eb;
    border-color: #3b82f6;
    color: #ffffff;
}
.dmx-btn-toggle.toggled {
    background: #312e81;
    border-color: #6366f1;
    color: #c7d2fe;
}
.dmx-fixture-card {
    background: #0e141f;
    border: 1px solid #1a2333;
    border-radius: 6px;
    padding: 8px 10px;
    margin-bottom: 8px;
    transition: opacity 0.15s ease;
}
.dmx-fixture-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
}
.dmx-fixture-title {
    display: flex;
    align-items: center;
    gap: 8px;
}
.dmx-fixture-swatch {
    display: inline-block;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    border: 1px solid rgba(255, 255, 255, 0.25);
    background-color: #0b0f17;
    transition: background-color 0.1s, box-shadow 0.1s;
}
.dmx-fixture-name {
    font-size: 12px;
    font-weight: 600;
    color: #f1f5f9;
}
.dmx-fixture-range {
    font-family: monospace;
    font-size: 10px;
    color: #64748b;
}
.dmx-channels-row {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
}
.dmx-pill {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 6px;
    border-radius: 4px;
    font-family: monospace;
    font-size: 11px;
    line-height: 1.2;
    border: 1px solid #1e293b;
    background: #0f141c;
    transition: all 0.1s ease;
}
.dmx-pill .ch-num {
    color: #64748b;
    font-size: 10px;
}
.dmx-pill .ch-role {
    font-size: 9px;
    font-weight: 700;
    padding: 1px 3px;
    border-radius: 2px;
    letter-spacing: 0.5px;
}
.dmx-pill .ch-val {
    font-weight: 600;
    min-width: 22px;
    text-align: right;
}

/* Active Roles */
.dmx-pill.ch-active.role-r {
    background: rgba(220, 38, 38, 0.25);
    border-color: rgba(239, 68, 68, 0.7);
    color: #fee2e2;
}
.dmx-pill.ch-active.role-r .ch-role {
    background: #dc2626;
    color: #ffffff;
}

.dmx-pill.ch-active.role-g {
    background: rgba(22, 163, 74, 0.25);
    border-color: rgba(34, 197, 94, 0.7);
    color: #dcfce7;
}
.dmx-pill.ch-active.role-g .ch-role {
    background: #16a34a;
    color: #ffffff;
}

.dmx-pill.ch-active.role-b {
    background: rgba(37, 99, 235, 0.25);
    border-color: rgba(59, 130, 246, 0.7);
    color: #dbeafe;
}
.dmx-pill.ch-active.role-b .ch-role {
    background: #2563eb;
    color: #ffffff;
}

.dmx-pill.ch-active.role-white,
.dmx-pill.ch-active.role-cold_white {
    background: rgba(248, 250, 252, 0.22);
    border-color: rgba(226, 232, 240, 0.8);
    color: #ffffff;
}
.dmx-pill.ch-active.role-white .ch-role,
.dmx-pill.ch-active.role-cold_white .ch-role {
    background: #e2e8f0;
    color: #0f172a;
}

.dmx-pill.ch-active.role-warm_white {
    background: rgba(217, 119, 6, 0.25);
    border-color: rgba(245, 158, 11, 0.8);
    color: #fef3c7;
}
.dmx-pill.ch-active.role-warm_white .ch-role {
    background: #d97706;
    color: #ffffff;
}

/* Strobe: ALWAYS pitch black background! */
.dmx-pill.role-strobe,
.dmx-pill.ch-active.role-strobe {
    background: #000000 !important;
}
.dmx-pill.ch-active.role-strobe {
    border-color: #eab308;
    color: #fef08a;
}
.dmx-pill.ch-active.role-strobe .ch-role {
    background: #000000;
    border: 1px solid #eab308;
    color: #fef08a;
}

/* Dimmer & Utilities */
.dmx-pill.ch-active.role-dimmer {
    background: #030712;
    border-color: #475569;
    color: #f8fafc;
}
.dmx-pill.ch-active.role-dimmer .ch-role {
    background: #1e293b;
    color: #cbd5e1;
}

.dmx-pill.role-speed,
.dmx-pill.role-mode {
    background: #000000 !important;
}
.dmx-pill.ch-active.role-speed,
.dmx-pill.ch-active.role-mode {
    border-color: #64748b;
    color: #cbd5e1;
}
.dmx-pill.ch-active.role-speed .ch-role,
.dmx-pill.ch-active.role-mode .ch-role {
    background: #1e293b;
    color: #94a3b8;
}

/* Zero / Inactive (faint & muted) */
.dmx-pill.ch-zero {
    opacity: 0.38;
    background: #0e131d;
    border-color: #1a2230;
    color: #475569;
}
.dmx-pill.ch-zero .ch-role {
    background: #1a2230;
    color: #475569;
}

/* Universe Grid View */
.dmx-grid-container {
    display: grid;
    grid-template-columns: repeat(16, minmax(0, 1fr));
    gap: 4px;
}
.dmx-grid-cell {
    border-radius: 4px;
    padding: 3px 2px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    font-family: monospace;
    font-size: 10px;
    border: 1px solid #1e293b;
    background: #0f141c;
    transition: all 0.1s ease;
    user-select: none;
    min-height: 38px;
}
.dmx-grid-cell .cell-header {
    display: flex;
    justify-content: space-between;
    width: 100%;
    padding: 0 2px;
    font-size: 8px;
    color: #64748b;
    margin-bottom: 2px;
    box-sizing: border-box;
}
.dmx-grid-cell .cell-val {
    font-size: 11px;
    font-weight: 700;
}
.dmx-grid-cell.ch-zero {
    opacity: 0.38;
    background: #0e131d;
    border-color: #1a2230;
    color: #475569;
}

/* Hide Zeros Mode */
.hide-zeros .ch-zero {
    display: none !important;
}
.hide-zeros .dmx-fixture-card.all-zero {
    display: none !important;
}
</style>
"""


# =============================================================================
# 4. Static DMX Snapshot Inspection
# =============================================================================

def render_dmx_frame_html(
    scene_or_dmx: Union[Scene, Sequence[int], DMXCanvas],
    t: float = 0.0,
    *,
    stage: Any = None,
    groups: Optional[Sequence[FixtureGroup]] = None,
    max_channel: Optional[int] = None,
    hide_zeros: bool = False,
    universe: int = 1,
    widget_id: Optional[str] = None,
) -> DMXFrameView:
    """Render a single static DMX frame snapshot into a rich HTML view."""
    if isinstance(scene_or_dmx, Scene):
        canvas = scene_or_dmx.eval_canvas(t)
        dmx_frame = canvas.to_dmx_list(min_size=max_channel or 64)
    elif isinstance(scene_or_dmx, DMXCanvas):
        dmx_frame = scene_or_dmx.to_dmx_list(min_size=max_channel or 64)
    else:
        dmx_frame = list(scene_or_dmx)

    ch_meta, fix_meta, universe_size = extract_channel_metadata(
        scene_or_dmx, stage=stage, groups=groups, max_channel=max_channel,
    )

    # Pad dmx_frame up to universe_size
    if len(dmx_frame) < universe_size:
        dmx_frame.extend([0] * (universe_size - len(dmx_frame)))

    if widget_id is None:
        widget_id = f"dmx_view_{abs(hash(str(dmx_frame[:32]) + str(t) + str(_time_hash())))}"
    active_count = sum(1 for val in dmx_frame if val > 0)

    # Build Fixtures HTML
    fixtures_html: list[str] = []
    for fm in fix_meta:
        # Check if all channels are zero
        all_zero = all((dmx_frame[a - 1] == 0 if a <= len(dmx_frame) else True) for a in fm.channel_addrs)
        all_zero_class = "all-zero" if all_zero else ""

        # Compute optical swatch preview
        r = dmx_frame[fm.r_addr - 1] if fm.r_addr and fm.r_addr <= len(dmx_frame) else 0
        g = dmx_frame[fm.g_addr - 1] if fm.g_addr and fm.g_addr <= len(dmx_frame) else 0
        b = dmx_frame[fm.b_addr - 1] if fm.b_addr and fm.b_addr <= len(dmx_frame) else 0
        w = dmx_frame[fm.w_addr - 1] if fm.w_addr and fm.w_addr <= len(dmx_frame) else 0
        dim = dmx_frame[fm.dim_addr - 1] if fm.dim_addr and fm.dim_addr <= len(dmx_frame) else 255

        dim_scale = (dim / 255.0) ** 1.8
        ro = min(255, int((r + w * 0.95) * dim_scale))
        go = min(255, int((g + w * 0.98) * dim_scale))
        bo = min(255, int((b + w * 1.00) * dim_scale))
        swatch_bg = f"rgb({ro},{go},{bo})"
        glow = f"box-shadow: 0 0 8px rgba({ro},{go},{bo},0.6);" if (ro > 15 or go > 15 or bo > 15) else ""

        pills: list[str] = []
        for addr in fm.channel_addrs:
            val = dmx_frame[addr - 1] if addr <= len(dmx_frame) else 0
            cm = ch_meta.get(addr)
            role = cm.role if cm else "generic"
            role_label = cm.role_label if cm else f"{addr}"
            attr_name = cm.attr_name if cm else f"Ch {addr}"

            zero_cls = "ch-zero" if val == 0 else "ch-active"
            pills.append(
                f'<div class="dmx-pill {zero_cls} role-{role}" id="{widget_id}_ch_{addr}" '
                f'title="{html.escape(fm.name)} • {html.escape(attr_name)} (Ch {addr}) = {val}">'
                f'<span class="ch-num">{addr}:</span>'
                f'<span class="ch-role">{html.escape(role_label)}</span>'
                f'<span class="ch-val">{val}</span>'
                f'</div>'
            )

        fixtures_html.append(
            f'<div class="dmx-fixture-card {all_zero_class}" id="{widget_id}_fix_{fm.index}">'
            f'<div class="dmx-fixture-header">'
            f'<div class="dmx-fixture-title">'
            f'<span class="dmx-fixture-swatch" id="{widget_id}_swatch_{fm.index}" style="background-color: {swatch_bg}; {glow}"></span>'
            f'<span class="dmx-fixture-name">{html.escape(fm.name)}</span>'
            f'<span class="dmx-fixture-range">{html.escape(fm.channel_range)}</span>'
            f'</div>'
            f'</div>'
            f'<div class="dmx-channels-row">{"".join(pills)}</div>'
            f'</div>'
        )

    # Build Grid HTML
    grid_cells: list[str] = []
    for addr in range(1, universe_size + 1):
        val = dmx_frame[addr - 1] if addr <= len(dmx_frame) else 0
        cm = ch_meta.get(addr)
        role = cm.role if cm else "generic"
        role_label = cm.role_label if cm else f"{addr}"
        fix_name = cm.fixture_label if cm else ""
        attr_name = cm.attr_name if cm else f"Ch {addr}"

        zero_cls = "ch-zero" if val == 0 else "ch-active"
        grid_cells.append(
            f'<div class="dmx-grid-cell {zero_cls} role-{role}" id="{widget_id}_gch_{addr}" '
            f'title="{html.escape(fix_name)} • {html.escape(attr_name)} (Ch {addr}) = {val}">'
            f'<div class="cell-header"><span>{addr}</span><span>{html.escape(role_label)}</span></div>'
            f'<div class="cell-val">{val}</div>'
            f'</div>'
        )

    container_cls = "hide-zeros" if hide_zeros else ""
    hide_btn_txt = "Show 0s" if hide_zeros else "Hide 0s"
    hide_btn_cls = "toggled" if hide_zeros else ""

    html_content = f"""
    {DMX_INSPECTOR_CSS}
    <div id="{widget_id}" class="dmx-inspector {container_cls}">
        <div class="dmx-toolbar">
            <div class="dmx-title-group">
                <span class="dmx-title">📡 DMX Universe {universe}</span>
                <span id="{widget_id}_time_badge" class="dmx-badge dmx-badge-time">t = {t:.2f}s</span>
                <span id="{widget_id}_active_badge" class="dmx-badge dmx-badge-active">{active_count} / {universe_size} active</span>
            </div>
            <div class="dmx-actions">
                <button id="{widget_id}_tab_fix" class="dmx-btn active">Fixtures</button>
                <button id="{widget_id}_tab_grid" class="dmx-btn">Grid ({universe_size})</button>
                <button id="{widget_id}_toggle_zeros" class="dmx-btn dmx-btn-toggle {hide_btn_cls}">{hide_btn_txt}</button>
            </div>
        </div>
        <div id="{widget_id}_view_fixtures">
            {"".join(fixtures_html)}
        </div>
        <div id="{widget_id}_view_grid" class="dmx-grid-container" style="display: none;">
            {"".join(grid_cells)}
        </div>
        <script>
        (function() {{
            const root = document.getElementById("{widget_id}");
            const tabFix = document.getElementById("{widget_id}_tab_fix");
            const tabGrid = document.getElementById("{widget_id}_tab_grid");
            const toggleZeros = document.getElementById("{widget_id}_toggle_zeros");
            const viewFix = document.getElementById("{widget_id}_view_fixtures");
            const viewGrid = document.getElementById("{widget_id}_view_grid");
            if (!root || !tabFix || !tabGrid || !toggleZeros || !viewFix || !viewGrid) return;

            tabFix.onclick = function() {{
                tabFix.classList.add("active");
                tabGrid.classList.remove("active");
                viewFix.style.display = "block";
                viewGrid.style.display = "none";
            }};
            tabGrid.onclick = function() {{
                tabGrid.classList.add("active");
                tabFix.classList.remove("active");
                viewFix.style.display = "none";
                viewGrid.style.display = "grid";
            }};
            toggleZeros.onclick = function() {{
                root.classList.toggle("hide-zeros");
                const hidden = root.classList.contains("hide-zeros");
                toggleZeros.innerText = hidden ? "Show 0s" : "Hide 0s";
                toggleZeros.classList.toggle("toggled", hidden);
            }};
        }})();
        </script>
    </div>
    """

    return DMXFrameView(
        html_content=html_content,
        dmx=dmx_frame,
        t=t,
        universe=universe,
        metadata={"channel_meta": ch_meta, "fixture_meta": fix_meta, "universe_size": universe_size},
    )


# =============================================================================
# 5. Interactive Scrubber with Animated Visualizer & Live Synchronized DMX
# =============================================================================

def render_interactive_inspector(
    scene: Scene,
    *,
    stage: Any = None,
    duration: Optional[float] = None,
    fps: float = 20.0,
    show_dmx: bool = True,
    dmx_collapsed: bool = True,
    max_channel: Optional[int] = None,
    hide_zeros: bool = False,
    universe: int = 1,
) -> StageScrubberView:
    """Render an interactive Jupyter HTML5 widget with slider, frame buttons, and live DMX table."""
    is_inf = math.isinf(scene.duration)
    show_dur = (6.0 if is_inf else scene.duration) if duration is None else duration
    if show_dur <= 0:
        show_dur = 1.0

    frame_count = max(1, round(show_dur * fps))
    step_dt = show_dur / frame_count

    # 1. Pre-render visualizer frames (Stage SVG or multi-track ribbon)
    visualizer_frames: list[str] = []
    if stage is not None and hasattr(stage, "render_svg"):
        for i in range(frame_count):
            t = i * step_dt
            visualizer_frames.append(str(stage.render_svg(scene, t=t, fps=fps)))
        max_w = getattr(stage, "width", 800)
    else:
        # Default synthesized multi-track timeline ribbon if no Stage provided
        from .jupyter import render_scene_timeline_svg
        for i in range(frame_count):
            t = i * step_dt
            # Render scene SVG with moving playhead cursor
            visualizer_frames.append(str(render_scene_timeline_svg(scene, duration=show_dur, current_time=t)))
        max_w = 800

    # 2. Pre-compute DMX byte frames
    ch_meta, fix_meta, universe_size = extract_channel_metadata(
        scene, stage=stage, max_channel=max_channel,
    )
    dmx_frames: list[list[int]] = []
    for i in range(frame_count):
        t = i * step_dt
        canvas = scene.eval_canvas(t)
        dmx_list = canvas.to_dmx_list(min_size=universe_size)
        if len(dmx_list) < universe_size:
            dmx_list.extend([0] * (universe_size - len(dmx_list)))
        dmx_frames.append(dmx_list[:universe_size])

    widget_id = f"stage_scrubber_{abs(hash(str(scene) + str(_time_hash())))}"
    dmx_widget_id = f"{widget_id}_dmx"
    frames_json = json.dumps(visualizer_frames)
    dmx_frames_json = json.dumps(dmx_frames)

    # Simplified channel and fixture metadata for client-side JS updates
    ch_client_meta = [
        {"addr": cm.address, "role": cm.role, "label": cm.role_label, "fixIdx": cm.fixture_idx}
        for cm in ch_meta.values()
    ]
    fix_client_meta = [
        {
            "idx": fm.index,
            "r": fm.r_addr,
            "g": fm.g_addr,
            "b": fm.b_addr,
            "w": fm.w_addr,
            "dim": fm.dim_addr,
            "addrs": fm.channel_addrs,
        }
        for fm in fix_meta if fm.index >= 0
    ]
    ch_meta_json = json.dumps(ch_client_meta)
    fix_meta_json = json.dumps(fix_client_meta)

    # Generate initial static snapshot for frame 0
    initial_dmx_view = render_dmx_frame_html(
        scene,
        t=0.0,
        stage=stage,
        max_channel=universe_size,
        hide_zeros=hide_zeros,
        universe=universe,
        widget_id=dmx_widget_id,
    ) if show_dmx else ""

    container_cls = "hide-zeros" if hide_zeros else ""

    html_body = f"""
    {DMX_INSPECTOR_CSS}
    <div id="{widget_id}" class="{container_cls}" style="max-width: {max_w}px; background: #0b0f17; border: 1px solid #1e293b; 
                border-radius: 8px; padding: 12px; margin: 10px 0; font-family: system-ui, sans-serif;">
        <!-- Visualizer Frame View -->
        <div id="{widget_id}_view">
            {visualizer_frames[0]}
        </div>

        <!-- Scrubber Transport Controls -->
        <div style="display: flex; align-items: center; gap: 8px; margin-top: 8px; padding: 6px 10px; background: #0e131d; border: 1px solid #1e293b; border-radius: 6px;">
            <button id="{widget_id}_prev" class="dmx-btn" title="Previous Frame (Step Back)">◀ Prev</button>
            <button id="{widget_id}_play" class="dmx-btn" style="background: #2563eb; color: white; border-color: #3b82f6;" title="Play / Pause">▶ Play</button>
            <button id="{widget_id}_next" class="dmx-btn" title="Next Frame (Step Forward)">Next ▶</button>
            <input id="{widget_id}_slider" type="range" min="0" max="{frame_count - 1}" value="0" 
                   style="flex: 1; cursor: pointer; accent-color: #3b82f6;">
            <span id="{widget_id}_label" style="font-family: monospace; font-size: 12px; color: #94a3b8; min-width: 96px; text-align: right;">0.00s (0/{frame_count - 1})</span>
            {f'<button id="{widget_id}_toggle_dmx" class="dmx-btn {"active" if not dmx_collapsed else ""}" style="font-size: 11px; padding: 3px 8px; margin-left: 2px;" title="Toggle live DMX channel table">📡 DMX {"▾" if not dmx_collapsed else "▸"}</button>' if show_dmx else ''}
        </div>

        <!-- Synchronized Live DMX Channel Table (Collapsible) -->
        {f'<div id="{widget_id}_dmx_wrap" style="margin-top: 10px; display: {"none" if dmx_collapsed else "block"};">{str(initial_dmx_view)}</div>' if show_dmx else ''}

        <script>
        (function() {{
            const frames = {frames_json};
            const dmxFrames = {dmx_frames_json};
            const chMeta = {ch_meta_json};
            const fixMeta = {fix_meta_json};
            const slider = document.getElementById("{widget_id}_slider");
            const view = document.getElementById("{widget_id}_view");
            const label = document.getElementById("{widget_id}_label");
            const playBtn = document.getElementById("{widget_id}_play");
            const prevBtn = document.getElementById("{widget_id}_prev");
            const nextBtn = document.getElementById("{widget_id}_next");
            const toggleDmxBtn = document.getElementById("{widget_id}_toggle_dmx");
            const dmxWrap = document.getElementById("{widget_id}_dmx_wrap");

            if (!slider || !view || !label || !playBtn) return;
            const totalDur = {show_dur};
            const frameCount = frames.length;
            const stepDt = {step_dt};
            const universeSize = {universe_size};
            let timer = null;

            // Cache direct DMX element references for this specific widget instance (prevents cross-cell interference)
            const dmxPills = {{}};
            const dmxCells = {{}};
            for (let i = 0; i < chMeta.length; i++) {{
                const addr = chMeta[i].addr;
                dmxPills[addr] = document.getElementById("{dmx_widget_id}_ch_" + addr);
                dmxCells[addr] = document.getElementById("{dmx_widget_id}_gch_" + addr);
            }}
            const dmxSwatches = {{}};
            const dmxCards = {{}};
            for (let f = 0; f < fixMeta.length; f++) {{
                const idx = fixMeta[f].idx;
                dmxSwatches[idx] = document.getElementById("{dmx_widget_id}_swatch_" + idx);
                dmxCards[idx] = document.getElementById("{dmx_widget_id}_fix_" + idx);
            }}
            const dmxActiveBadge = document.getElementById("{dmx_widget_id}_active_badge");
            const dmxTimeBadge = document.getElementById("{dmx_widget_id}_time_badge");

            if (toggleDmxBtn && dmxWrap) {{
                toggleDmxBtn.onclick = function() {{
                    const isHidden = (dmxWrap.style.display === "none");
                    dmxWrap.style.display = isHidden ? "block" : "none";
                    toggleDmxBtn.innerText = isHidden ? "📡 DMX ▾" : "📡 DMX ▸";
                    toggleDmxBtn.classList.toggle("active", isHidden);
                }};
            }}

            function update(idx) {{
                slider.value = idx;
                view.innerHTML = frames[idx];
                const t = idx * stepDt;
                label.innerText = t.toFixed(2) + "s (" + idx + "/" + (frameCount - 1) + ")";
                if (dmxTimeBadge) dmxTimeBadge.innerText = "t = " + t.toFixed(2) + "s";

                // Update live DMX elements scoped strictly to this widget
                const dmx = dmxFrames[idx];
                if (dmx) {{
                    let activeCount = 0;
                    for (let i = 0; i < chMeta.length; i++) {{
                        const cm = chMeta[i];
                        const addr = cm.addr;
                        const val = (addr <= dmx.length) ? dmx[addr - 1] : 0;
                        if (val > 0) activeCount++;

                        // Update Fixture Pill
                        const pill = dmxPills[addr];
                        if (pill) {{
                            const valSpan = pill.querySelector(".ch-val");
                            if (valSpan) valSpan.innerText = val;
                            if (val === 0) {{
                                pill.classList.add("ch-zero");
                                pill.classList.remove("ch-active");
                            }} else {{
                                pill.classList.remove("ch-zero");
                                pill.classList.add("ch-active");
                            }}
                        }}

                        // Update Grid Cell
                        const cell = dmxCells[addr];
                        if (cell) {{
                            const cellVal = cell.querySelector(".cell-val");
                            if (cellVal) cellVal.innerText = val;
                            if (val === 0) {{
                                cell.classList.add("ch-zero");
                                cell.classList.remove("ch-active");
                            }} else {{
                                cell.classList.remove("ch-zero");
                                cell.classList.add("ch-active");
                            }}
                        }}
                    }}

                    if (dmxActiveBadge) {{
                        dmxActiveBadge.innerText = activeCount + " / " + universeSize + " active";
                    }}

                    // Update Fixture Swatches and all-zero states
                    for (let f = 0; f < fixMeta.length; f++) {{
                        const fm = fixMeta[f];
                        const r = (fm.r && fm.r <= dmx.length) ? dmx[fm.r - 1] : 0;
                        const g = (fm.g && fm.g <= dmx.length) ? dmx[fm.g - 1] : 0;
                        const b = (fm.b && fm.b <= dmx.length) ? dmx[fm.b - 1] : 0;
                        const w = (fm.w && fm.w <= dmx.length) ? dmx[fm.w - 1] : 0;
                        const dim = (fm.dim && fm.dim <= dmx.length) ? dmx[fm.dim - 1] : 255;

                        const dimScale = Math.pow(dim / 255.0, 1.8);
                        const ro = Math.min(255, Math.round((r + w * 0.95) * dimScale));
                        const go = Math.min(255, Math.round((g + w * 0.98) * dimScale));
                        const bo = Math.min(255, Math.round((b + w * 1.00) * dimScale));

                        const swatch = dmxSwatches[fm.idx];
                        if (swatch) {{
                            swatch.style.backgroundColor = "rgb(" + ro + "," + go + "," + bo + ")";
                            swatch.style.boxShadow = (ro > 15 || go > 15 || bo > 15) ? "0 0 8px rgba(" + ro + "," + go + "," + bo + ",0.6)" : "none";
                        }}

                        // Check all zero
                        const fCard = dmxCards[fm.idx];
                        if (fCard) {{
                            let fAllZero = true;
                            for (let a = 0; a < fm.addrs.length; a++) {{
                                const aAddr = fm.addrs[a];
                                if (aAddr <= dmx.length && dmx[aAddr - 1] > 0) {{
                                    fAllZero = false;
                                    break;
                                }}
                            }}
                            fCard.classList.toggle("all-zero", fAllZero);
                        }}
                    }}
                }}
            }}

            slider.oninput = function() {{
                update(parseInt(this.value));
            }};

            if (prevBtn) {{
                prevBtn.onclick = function() {{
                    let cur = parseInt(slider.value);
                    let prev = (cur - 1 + frameCount) % frameCount;
                    update(prev);
                }};
            }}

            if (nextBtn) {{
                nextBtn.onclick = function() {{
                    let cur = parseInt(slider.value);
                    let next = (cur + 1) % frameCount;
                    update(next);
                }};
            }}

            playBtn.onclick = function() {{
                if (timer) {{
                    clearInterval(timer);
                    timer = null;
                    playBtn.innerText = "▶ Play";
                }} else {{
                    playBtn.innerText = "⏸ Pause";
                    timer = setInterval(function() {{
                        let next = (parseInt(slider.value) + 1) % frameCount;
                        update(next);
                    }}, 1000 / {fps});
                }}
            }};
        }})();
        </script>
    </div>
    """

    return StageScrubberView(html_body)


# =============================================================================
# 6. Top-Level Public Inspection API
# =============================================================================

def inspect_dmx(
    scene_or_dmx: Union[Scene, Sequence[int], DMXCanvas],
    t: float = 0.0,
    *,
    stage: Any = None,
    groups: Optional[Sequence[FixtureGroup]] = None,
    max_channel: Optional[int] = None,
    hide_zeros: bool = False,
    universe: int = 1,
) -> DMXFrameView:
    """Inspect raw DMX frame and channel values at timestamp `t` (or from raw bytes/canvas).

    Args:
        scene_or_dmx: A `Scene`, `DMXCanvas`, or sequence of DMX byte integers (0..255).
        t: Time offset in seconds (when evaluating a `Scene`).
        stage: Optional `Stage` providing physical fixture layout and channel mapping.
        groups: Optional list of `FixtureGroup` instances.
        max_channel: Maximum DMX channel address to display (defaults to highest active/mapped channel).
        hide_zeros: If True, filters out inactive channels (value 0).
        universe: DMX universe number (default 1).

    Returns:
        A `DMXFrameView` implementing `_repr_html_()` for rich display in Jupyter Notebooks.
    """
    return render_dmx_frame_html(
        scene_or_dmx,
        t=t,
        stage=stage,
        groups=groups,
        max_channel=max_channel,
        hide_zeros=hide_zeros,
        universe=universe,
    )


# Convenient alias
dmx = inspect_dmx
