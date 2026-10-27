"""Reusable fixture profiles with optical color science and authentic physical SVG rendering.

This module provides physical fixture profiles (such as the EUROLITE LED PARty Spot
and EUROLITE LED BCL-40 SMD Strobe Bar) that encapsulate:
1. DMX Channel mapping (templates).
2. Optical color blending (RGB + CCT-calibrated White diodes + Master Dimmer).
3. Authentic 2D physical face rendering (concentric LED rings, SMD diode rows, strobe bloom).
4. `Stage` visualizer for 2D stage layout and interactive scrubbing in Jupyter.
"""

from __future__ import annotations
import html
import json
import math
from typing import Mapping, Optional, Sequence, Union

from .fixtures import Channel, DMXCanvas, FixtureGroup, PrimitiveSpec, RGB, Scene
from .inspector import (
    DMXFrameView,
    HTMLView,
    StageScrubberView,
    dmx,
    inspect_dmx,
    render_interactive_inspector,
)
from .state import Color


# =============================================================================
# Optical Color Mixing Utilities
# =============================================================================

# Pre-calibrated sRGB chromaticity coordinates for white diodes
COOL_WHITE_RGB = (0.95, 0.98, 1.00)   # ~6500K
WARM_WHITE_RGB = (1.00, 0.78, 0.45)   # ~3200K


def blend_rgbw(
    r_byte: int,
    g_byte: int,
    b_byte: int,
    w_byte: int = 0,
    dimmer_byte: int = 255,
    white_tint: tuple[float, float, float] = COOL_WHITE_RGB,
) -> tuple[int, int, int]:
    """Mix RGB with a White diode (optical desaturation) scaled by master dimmer."""
    dimmer_norm = max(0.0, min(1.0, dimmer_byte / 255.0))
    # Gamma correction (~1.8) for perceived optical brightness
    perceived_dim = math.pow(dimmer_norm, 1.8)

    w_norm = max(0.0, min(1.0, w_byte / 255.0))
    w_r = w_norm * white_tint[0] * 255.0
    w_g = w_norm * white_tint[1] * 255.0
    w_b = w_norm * white_tint[2] * 255.0

    r_out = min(255, int((r_byte + w_r) * perceived_dim))
    g_out = min(255, int((g_byte + w_g) * perceived_dim))
    b_out = min(255, int((b_byte + w_b) * perceived_dim))
    return (r_out, g_out, b_out)


# =============================================================================
# Fixture Profile: EUROLITE LED PARty Spot (12x 1W RGBW, 2 Concentric Rings)
# =============================================================================

class EurolitePartySpot:
    """Fixture profile for the EUROLITE LED PARty Spot (Compact 12x 1W RGBW spotlight).

    Physical layout:
      - 2 concentric rings of individual lenses:
        * Inner ring: 3 LEDs
        * Outer ring: 9 LEDs
      - Concentric reflector dish inside a circular can
      - Hardware strobe creates an expanding bloom / halo effect
    """

    def __init__(
        self,
        element: Union[FixtureGroup, Mapping[str, PrimitiveSpec]],
        x: float,
        y: float,
        radius: float = 32.0,
        label: str = "",
    ) -> None:
        if isinstance(element, FixtureGroup):
            self.element = dict(element.elements[0])
            self.label = label or element.name
        else:
            self.element = dict(element)
            self.label = label
        self.x = float(x)
        self.y = float(y)
        self.radius = float(radius)

    @classmethod
    def template(cls, base_channel: int) -> dict[str, PrimitiveSpec]:
        """6-channel DMX profile for Eurolite LED PARty Spot."""
        return {
            "color":  RGB(base_channel),
            "w":      Channel(base_channel + 3, default=0.0),
            "dimmer": Channel(base_channel + 4, default=1.0),
            "strobe": Channel(base_channel + 5, dmx_range=(11, 255)),
        }

    @classmethod
    def group(cls, name: str, start_channels: Sequence[int]) -> FixtureGroup:
        """Create a FixtureGroup for multiple PARty Spot fixtures."""
        return FixtureGroup.from_template(name, cls.template, start_channels)

    def extract_dmx(self, dmx_frame: Sequence[int]) -> tuple[int, int, int, int, int, int]:
        """Extract (r, g, b, w, dimmer, strobe) DMX byte values from a frame."""
        r, g, b = 0, 0, 0
        w = 0
        dimmer = 255
        strobe = 0

        for attr, prim in self.element.items():
            if isinstance(prim, RGB) and prim.address + 2 <= len(dmx_frame):
                idx = prim.address - 1
                r, g, b = dmx_frame[idx], dmx_frame[idx + 1], dmx_frame[idx + 2]
            elif isinstance(prim, Channel) and prim.address <= len(dmx_frame):
                v = dmx_frame[prim.address - 1]
                if attr == "w":
                    w = v
                elif attr == "dimmer":
                    dimmer = v
                elif attr == "strobe":
                    strobe = v
        return (r, g, b, w, dimmer, strobe)

    def render_svg(
        self,
        dmx_frame: Sequence[int],
        t: float = 0.0,
        *,
        fps: Optional[float] = None,
        max_strobe_freq: float = 7.5,
    ) -> str:
        """Render the authentic physical face of this PAR (2 rings of 3 and 9 LEDs)."""
        r_b, g_b, b_b, w_b, dim_b, strobe_b = self.extract_dmx(dmx_frame)
        r_out, g_out, b_out = blend_rgbw(r_b, g_b, b_b, w_b, dim_b)
        is_lit = (r_out > 0 or g_out > 0 or b_out > 0)

        # Hardware strobe on the PAR is rapid flickering of whatever color is currently showing
        # Cap frequency to Nyquist limit (<= fps / 2) so frames never alias to static white
        strobe_active = (strobe_b >= 11)
        is_flash_on = True
        if strobe_active and t > 0:
            limit = (fps / 2.0) if fps is not None else max_strobe_freq
            effective_max = max(2.0, min(max_strobe_freq, limit))
            rate_norm = (strobe_b - 11) / (255 - 11)
            freq = 1.0 + rate_norm * (effective_max - 1.0)
            flash_phase = (t * freq) % 1.0
            is_flash_on = (flash_phase < 0.50)  # 50% duty cycle flash

        # If in the dark phase of the strobe flicker, attenuate output
        if strobe_active and not is_flash_on:
            r_out = int(r_out * 0.08)
            g_out = int(g_out * 0.08)
            b_out = int(b_out * 0.08)
            is_lit = (r_out > 0 or g_out > 0 or b_out > 0)

        color_str = f"rgb({r_out},{g_out},{b_out})" if is_lit else "#09090b"

        cx, cy = self.x, self.y
        r_can = self.radius
        r_dish = r_can * 0.82
        r_inner = r_dish * 0.26
        r_outer = r_dish * 0.72
        r_led = max(2.6, r_can * 0.125)

        svg: list[str] = []

        # 1. Spotlight Beam Halo / Colored Strobe Bloom
        # Retains the fixture's ACTUAL active color (e.g. red strobe flashes red, blue flashes blue)
        if is_lit and not (strobe_active and not is_flash_on):
            halo_r = r_can * (2.1 if strobe_active else 1.4)
            halo_opacity = 0.42 if strobe_active else 0.22
            svg.append(
                f'<circle cx="{cx}" cy="{cy}" r="{halo_r:.1f}" '
                f'fill="{color_str}" opacity="{halo_opacity:.2f}" filter="url(#glow-blur)"/>'
            )

        # 2. Outer Metal Can Housing & Bezel
        svg.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r_can:.1f}" '
            f'fill="#18181b" stroke="#3f3f46" stroke-width="1.8"/>'
        )

        # 3. Reflector Bowl (dark brushed metal with diffused ambient light wash)
        dish_fill = f"rgba({r_out},{g_out},{b_out},0.28)" if is_lit else "#121214"
        svg.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r_dish:.1f}" '
            f'fill="{dish_fill}" stroke="#27272a" stroke-width="1"/>'
        )

        # 4. Concentric LED Diodes:
        # Ring 1 (Inner): 3 LEDs at 120° intervals (rotated 60°)
        diode_color = "#ffffff" if (is_lit and w_b > 220) else (color_str if is_lit else "#1c1917")
        for i in range(3):
            angle = i * (2.0 * math.pi / 3.0) - math.pi / 2.0 + (math.pi / 3.0)
            lx = cx + r_inner * math.cos(angle)
            ly = cy + r_inner * math.sin(angle)
            svg.append(
                f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="{r_led:.1f}" '
                f'fill="{diode_color}" stroke="#3f3f46" stroke-width="0.8"/>'
            )
            if is_lit:
                svg.append(
                    f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="{r_led * 0.5:.1f}" '
                    f'fill="#ffffff" opacity="0.6"/>'
                )

        # Ring 2 (Outer): 9 LEDs at 40° intervals
        for i in range(9):
            angle = i * (2.0 * math.pi / 9.0) - math.pi / 2.0
            lx = cx + r_outer * math.cos(angle)
            ly = cy + r_outer * math.sin(angle)
            svg.append(
                f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="{r_led:.1f}" '
                f'fill="{diode_color}" stroke="#3f3f46" stroke-width="0.8"/>'
            )
            if is_lit:
                svg.append(
                    f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="{r_led * 0.5:.1f}" '
                    f'fill="#ffffff" opacity="0.6"/>'
                )

        # 5. Strobe Indicator Badge
        if strobe_active:
            svg.append(
                f'<text x="{cx}" y="{cy + 4}" fill="#fef08a" stroke="#000000" stroke-width="0.8" '
                f'font-family="system-ui, sans-serif" font-size="12" font-weight="bold" text-anchor="middle">⚡</text>'
            )

        # 6. Optional Label below fixture
        if self.label:
            svg.append(
                f'<text x="{cx}" y="{cy + r_can + 16}" fill="#9ca3af" font-family="system-ui, sans-serif" '
                f'font-size="11" text-anchor="middle">{html.escape(self.label)}</text>'
            )

        return "".join(svg)


# =============================================================================
# Fixture Profile: EUROLITE LED BCL-40 SMD White / RGB Bar (24-Channel Mode)
# =============================================================================

class EuroliteBCL40Bar:
    """Fixture profile for the EUROLITE LED BCL-40 SMD White / RGB Bar (24-Channel Mode).

    Physical layout:
      - 4 columns (segments 1 to 4) arranged left to right
      - Each column is split vertically into two square RGB backlight compartments:
        * Top RGB square
        * Bottom RGB square
      - In-between the top and bottom squares runs a horizontal channel of
        split Cold White (~6600K) and Warm White (~3200K) SMD LEDs
      - Master strobe channel gating all segments
    """

    def __init__(
        self,
        group: FixtureGroup,
        x: float,
        y: float,
        width: float = 260.0,
        height: float = 58.0,
        master_strobe: Optional[Union[FixtureGroup, Mapping[str, PrimitiveSpec]]] = None,
        label: str = "BCL-40 Bar",
    ) -> None:
        self.group = group
        self.x = float(x)
        self.y = float(y)
        self.width = float(width)
        self.height = float(height)
        if isinstance(master_strobe, FixtureGroup):
            self.master_strobe_element = dict(master_strobe.elements[0])
        elif master_strobe:
            self.master_strobe_element = dict(master_strobe)
        else:
            self.master_strobe_element = None
        self.label = label

    @classmethod
    def template_24ch(cls, base_channel: int = 32) -> list[dict[str, PrimitiveSpec]]:
        """Return the 4 segment definitions for 24-channel mode."""
        segments = []
        for i in range(4):
            base = base_channel + i * 5
            segments.append({
                "color": RGB(base),
                "ww":    Channel(base + 3),
                "cw":    Channel(base + 4),
                "w":     Channel(base + 4),
            })
        return segments

    def render_svg(
        self,
        dmx_frame: Sequence[int],
        t: float = 0.0,
        *,
        fps: Optional[float] = None,
        max_strobe_freq: float = 7.5,
    ) -> str:
        """Render the authentic 4-segment physical bar: split top/bottom RGB squares with center CW/WW strip."""
        bx, by = self.x, self.y
        bw, bh = self.width, self.height
        seg_count = min(4, len(self.group.elements))
        pad = 2.0
        gap = 2.0
        strip_h = 8.6
        sq_h = (bh - 2 * pad - strip_h - 2 * gap) / 2.0  # Height of each RGB square
        seg_w = (bw - (seg_count - 1) * 3) / seg_count

        # Check master strobe
        master_strobe = 0
        if self.master_strobe_element:
            for attr, prim in self.master_strobe_element.items():
                if isinstance(prim, Channel) and prim.address <= len(dmx_frame):
                    master_strobe = dmx_frame[prim.address - 1]

        # Strobe frequency capped at Nyquist limit (<= fps / 2) to prevent aliasing
        strobe_active = (master_strobe >= 9)
        is_flash_on = True
        if strobe_active and t > 0:
            limit = (fps / 2.0) if fps is not None else max_strobe_freq
            effective_max = max(2.0, min(max_strobe_freq, limit))
            rate_norm = (master_strobe - 9) / (255 - 9)
            freq = 2.0 + rate_norm * (effective_max - 2.0)
            flash_phase = (t * freq) % 1.0
            is_flash_on = (flash_phase < 0.50)  # 50% duty cycle shutter flash

        svg: list[str] = []

        # 1. Bar Master Strobe Bloom (active only during the blinding flash phase)
        if strobe_active and is_flash_on:
            svg.append(
                f'<rect x="{bx - 16}" y="{by - 14}" width="{bw + 32}" height="{bh + 28}" rx="14" '
                f'fill="rgba(255,255,245,0.65)" filter="url(#glow-blur)"/>'
            )

        # 2. Outer Heavy-Duty Aluminum Enclosure
        svg.append(
            f'<rect x="{bx - 2}" y="{by - 2}" width="{bw + 4}" height="{bh + 4}" rx="4" '
            f'fill="#141417" stroke="#3f3f46" stroke-width="1.8"/>'
        )

        y_top_sq = by + pad
        y_strip = y_top_sq + sq_h + gap
        y_bot_sq = y_strip + strip_h + gap

        # 3. 4 Segment Columns
        for i in range(seg_count):
            el = self.group.elements[i]
            sx = bx + i * (seg_w + 3)

            r_b, g_b, b_b = 0, 0, 0
            ww_b, cw_b = 0, 0
            for attr, prim in el.items():
                if isinstance(prim, RGB) and prim.address + 2 <= len(dmx_frame):
                    idx = prim.address - 1
                    r_b, g_b, b_b = dmx_frame[idx], dmx_frame[idx + 1], dmx_frame[idx + 2]
                elif isinstance(prim, Channel) and prim.address <= len(dmx_frame):
                    v = dmx_frame[prim.address - 1]
                    if attr == "ww":
                        ww_b = v
                    elif attr in ("cw", "w"):
                        cw_b = max(cw_b, v)

            # If master strobe is active and in dark phase, shutter cut-off
            if strobe_active and not is_flash_on:
                r_b = int(r_b * 0.05)
                g_b = int(g_b * 0.05)
                b_b = int(b_b * 0.05)
                ww_b = int(ww_b * 0.05)
                cw_b = int(cw_b * 0.05)

            # Colors for top & bottom RGB squares
            has_rgb = (r_b > 0 or g_b > 0 or b_b > 0)
            rgb_fill = f"rgb({r_b},{g_b},{b_b})" if has_rgb else "#0f172a"
            rgb_stroke = f"rgba({r_b},{g_b},{b_b},0.4)" if has_rgb else "#1e293b"

            # Top RGB square compartment
            svg.append(
                f'<rect x="{sx:.1f}" y="{y_top_sq:.1f}" width="{seg_w:.1f}" height="{sq_h:.1f}" '
                f'rx="2" fill="{rgb_fill}" stroke="{rgb_stroke}" stroke-width="0.8"/>'
            )

            # Bottom RGB square compartment
            svg.append(
                f'<rect x="{sx:.1f}" y="{y_bot_sq:.1f}" width="{seg_w:.1f}" height="{sq_h:.1f}" '
                f'rx="2" fill="{rgb_fill}" stroke="{rgb_stroke}" stroke-width="0.8"/>'
            )

            # Center White Strip (in-between top and bottom squares)
            ww_norm = ww_b / 255.0
            cw_norm = cw_b / 255.0
            has_ww = (ww_b > 0)
            has_cw = (cw_b > 0)
            has_white = has_ww or has_cw

            # Reflector channel background
            strip_bg = "#09090b"
            svg.append(
                f'<rect x="{sx:.1f}" y="{y_strip:.1f}" width="{seg_w:.1f}" height="{strip_h:.1f}" '
                f'rx="1" fill="{strip_bg}" stroke="#27272a" stroke-width="0.6"/>'
            )

            # Diffuse glow when white is lit
            if has_white:
                glow_r = min(255, int(ww_norm * WARM_WHITE_RGB[0] * 255 + cw_norm * COOL_WHITE_RGB[0] * 255))
                glow_g = min(255, int(ww_norm * WARM_WHITE_RGB[1] * 255 + cw_norm * COOL_WHITE_RGB[1] * 255))
                glow_b = min(255, int(ww_norm * WARM_WHITE_RGB[2] * 255 + cw_norm * COOL_WHITE_RGB[2] * 255))
                svg.append(
                    f'<rect x="{sx + 1:.1f}" y="{y_strip + 1:.1f}" width="{seg_w - 2:.1f}" height="{strip_h - 2:.1f}" '
                    f'rx="1" fill="rgb({glow_r},{glow_g},{glow_b})" opacity="0.35"/>'
                )

            # Dense Dual-Row SMD White Diodes:
            # Top row: Warm White (3200K), Bottom row: Cold White (6600K)
            # High density (16 pairs per segment, 128 diodes total) with minimal inter-chip gaps
            chip_cols = 16
            chip_w = 3.4
            chip_h = 3.4
            v_gap = 0.5
            h_step = (seg_w - 2.0 - chip_w) / max(1, chip_cols - 1)
            y_ww = y_strip + (strip_h - (2 * chip_h + v_gap)) / 2.0
            y_cw = y_ww + chip_h + v_gap

            # Top row: Warm White (3200K)
            ww_fill = (
                f"rgb(255,{int(190 + 30*ww_norm)},{int(100 + 40*ww_norm)})"
                if has_ww else "#292524"
            )
            # Bottom row: Cold White (6600K)
            cw_fill = (
                f"rgb({int(230 + 25*cw_norm)},{int(240 + 15*cw_norm)},255)"
                if has_cw else "#262626"
            )

            for c in range(chip_cols):
                cx_chip = sx + 1.0 + c * h_step
                # Top diode: Warm White
                svg.append(
                    f'<rect x="{cx_chip:.1f}" y="{y_ww:.1f}" width="{chip_w:.1f}" height="{chip_h:.1f}" rx="0.4" '
                    f'fill="{ww_fill}" stroke="#18181b" stroke-width="0.3"/>'
                )
                # Bottom diode: Cold White
                svg.append(
                    f'<rect x="{cx_chip:.1f}" y="{y_cw:.1f}" width="{chip_w:.1f}" height="{chip_h:.1f}" rx="0.4" '
                    f'fill="{cw_fill}" stroke="#18181b" stroke-width="0.3"/>'
                )

        # 4. Label
        if self.label:
            svg.append(
                f'<text x="{bx + bw / 2.0}" y="{by + bh + 16}" fill="#9ca3af" font-family="system-ui, sans-serif" '
                f'font-size="11" text-anchor="middle">{html.escape(self.label)}</text>'
            )

        return "".join(svg)


# =============================================================================
# Stage Visualizer (2D Layout + Interactive Jupyter Scrubber)
# =============================================================================

StageItem = Union[EurolitePartySpot, EuroliteBCL40Bar]


class Stage:
    """Virtual 2D stage canvas composed of physically positioned fixture profiles."""

    def __init__(
        self,
        fixtures: Sequence[StageItem],
        *,
        width: int = 800,
        height: int = 240,
        title: str = "Virtual Stage Visualizer",
    ) -> None:
        self.fixtures = list(fixtures)
        self.width = int(width)
        self.height = int(height)
        self.title = title

    def render_svg(
        self,
        scene_or_dmx: Union[Scene, Sequence[int]],
        t: float = 0.0,
        *,
        fps: Optional[float] = None,
        max_strobe_freq: float = 7.5,
    ) -> str:
        """Render a single 2D stage snapshot at time `t` (or from raw DMX bytes)."""
        if isinstance(scene_or_dmx, Scene):
            canvas = scene_or_dmx.eval_canvas(t)
            dmx_frame = canvas.to_dmx_list(min_size=64)
        else:
            dmx_frame = list(scene_or_dmx)

        w, h = self.width, self.height
        parts: list[str] = [
            '<defs>'
            '<filter id="glow-blur" x="-50%" y="-50%" width="200%" height="200%">'
            '<feGaussianBlur stdDeviation="6"/>'
            '</filter>'
            '</defs>',
            f'<rect width="{w}" height="{h}" rx="8" fill="#0b0f17" stroke="#1e293b" stroke-width="1.2"/>',
            # Stage background grid lines
            f'<line x1="20" y1="{h - 35}" x2="{w - 20}" y2="{h - 35}" stroke="#1e293b" stroke-width="1" stroke-dasharray="4,4"/>',
            # Header title
            f'<text x="16" y="24" fill="#f8fafc" font-family="system-ui, sans-serif" font-size="13" font-weight="600">{html.escape(self.title)}</text>',
            f'<text x="{w - 16}" y="24" fill="#64748b" font-family="monospace" font-size="11" text-anchor="end">t = {t:.2f}s</text>',
        ]

        # Render all fixtures
        for fix in self.fixtures:
            parts.append(fix.render_svg(dmx_frame, t=t, fps=fps, max_strobe_freq=max_strobe_freq))

        content = "".join(parts)
        return HTMLView(
            f'<div style="max-width: {w}px; margin: 10px 0;">'
            f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" xmlns="http://www.w3.org/2000/svg" '
            f'style="border-radius: 8px; display: block; box-shadow: 0 4px 12px rgba(0,0,0,0.4);">'
            f'{content}'
            f'</svg></div>'
        )

    def __call__(self, scene_or_dmx: Union[Scene, Sequence[int]], t: float = 0.0) -> HTMLView:
        """Shorthand `stage(scene, t=1.0)` to render SVG in notebook cells or scripts."""
        return self.render_svg(scene_or_dmx, t=t)

    def _repr_html_(self) -> str:
        """Render default stage layout in notebook cell."""
        return str(self.render_svg([0] * 64, t=0.0))

    def render_animated_svg(
        self,
        scene: Scene,
        *,
        duration: Optional[float] = None,
        fps: float = 10.0,
        max_strobe_freq: float = 7.5,
    ) -> HTMLView:
        """Render a self-contained animated SVG using standard W3C SMIL animation.

        Plays automatically in modern browsers, markdown previews, <img> tags,
        and Jupyter notebook cells without external JavaScript or stylesheets.
        """
        is_inf = math.isinf(scene.duration)
        show_dur = (6.0 if is_inf else scene.duration) if duration is None else duration
        if show_dur <= 0:
            show_dur = 1.0

        frame_count = max(1, round(show_dur * fps))
        step_dt = show_dur / frame_count
        w, h = self.width, self.height

        parts: list[str] = [
            '<defs>',
            '<filter id="glow-blur" x="-50%" y="-50%" width="200%" height="200%">',
            '<feGaussianBlur stdDeviation="6"/>',
            '</filter>',
            '</defs>',
            f'<rect width="{w}" height="{h}" rx="8" fill="#0b0f17" stroke="#1e293b" stroke-width="1.2"/>',
            f'<line x1="20" y1="{h - 35}" x2="{w - 20}" y2="{h - 35}" stroke="#1e293b" stroke-width="1" stroke-dasharray="4,4"/>',
            f'<text x="16" y="24" fill="#f8fafc" font-family="system-ui, sans-serif" font-size="13" font-weight="600">{html.escape(self.title)}</text>',
        ]

        last_id = f"f_anim_{frame_count - 1}"

        for i in range(frame_count):
            t = i * step_dt
            canvas = scene.eval_canvas(t)
            dmx_frame = canvas.to_dmx_list(min_size=64)
            inner_parts: list[str] = [
                f'<text x="{w - 16}" y="24" fill="#64748b" font-family="monospace" font-size="11" text-anchor="end">t = {t:.2f}s</text>'
            ]
            for fix in self.fixtures:
                inner_parts.append(fix.render_svg(dmx_frame, t=t, fps=fps, max_strobe_freq=max_strobe_freq))
            inner = "".join(inner_parts)

            if i == 0:
                parts.append(
                    f'<g id="f0">\n'
                    f'<set id="f_anim_0" attributeName="display" to="inline" begin="0s; {last_id}.end" dur="{step_dt:.3f}s"/>\n'
                    f'<set attributeName="display" to="none" begin="f_anim_0.end" end="{last_id}.end"/>\n'
                    f'{inner}\n'
                    f'</g>\n'
                )
            else:
                parts.append(
                    f'<g id="f{i}" display="none">\n'
                    f'<set id="f_anim_{i}" attributeName="display" to="inline" begin="f_anim_{i - 1}.end" dur="{step_dt:.3f}s"/>\n'
                    f'{inner}\n'
                    f'</g>\n'
                )

        content = "".join(parts)
        return HTMLView(
            f'<div style="max-width: {w}px; margin: 10px 0;">'
            f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" xmlns="http://www.w3.org/2000/svg" '
            f'style="border-radius: 8px; display: block; box-shadow: 0 4px 12px rgba(0,0,0,0.4);">'
            f'{content}'
            f'</svg></div>'
        )

    def save_animated_svg(
        self,
        scene: Scene,
        path: str,
        *,
        duration: Optional[float] = None,
        fps: float = 10.0,
        max_strobe_freq: float = 7.5,
    ) -> None:
        """Export the stage animation to a standalone .svg file."""
        html_view = self.render_animated_svg(scene, duration=duration, fps=fps, max_strobe_freq=max_strobe_freq)
        s = str(html_view)
        svg_pure = s[s.find('<svg'):s.rfind('</svg>') + 6]
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg_pure)

    def save_animated_gif(
        self,
        scene: Scene,
        path: str,
        *,
        duration: Optional[float] = None,
        fps: float = 10.0,
        max_strobe_freq: float = 7.5,
    ) -> None:
        """Export the stage animation to an animated .gif file using inkscape and ffmpeg.

        Requires 'inkscape' and 'ffmpeg' on the system.
        """
        import os
        import shutil
        import subprocess
        import tempfile

        if not shutil.which("inkscape"):
            raise RuntimeError("save_animated_gif requires 'inkscape' installed on the system.")
        if not shutil.which("ffmpeg"):
            raise RuntimeError("save_animated_gif requires 'ffmpeg' installed on the system.")

        is_inf = math.isinf(scene.duration)
        show_dur = (6.0 if is_inf else scene.duration) if duration is None else duration
        if show_dur <= 0:
            show_dur = 1.0

        frame_count = max(1, round(show_dur * fps))
        step_dt = show_dur / frame_count

        with tempfile.TemporaryDirectory() as tmpdir:
            shell_cmds = []
            for i in range(frame_count):
                t = i * step_dt
                svg_view = self.render_svg(scene, t=t, fps=fps, max_strobe_freq=max_strobe_freq)
                svg_str = str(svg_view)
                svg_pure = svg_str[svg_str.find("<svg"):svg_str.rfind("</svg>") + 6]
                s_path = os.path.join(tmpdir, f"frame_{i:04d}.svg")
                p_path = os.path.join(tmpdir, f"frame_{i:04d}.png")
                with open(s_path, "w", encoding="utf-8") as f:
                    f.write(svg_pure)
                shell_cmds.append(f"file-open:{s_path}; export-filename:{p_path}; export-width:{self.width}; export-height:{self.height}; export-do;")
            shell_cmds.append("quit")

            proc = subprocess.Popen(
                ["inkscape", "--shell"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            proc.communicate("\n".join(shell_cmds) + "\n")

            palette_path = os.path.join(tmpdir, "palette.png")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-framerate", str(fps),
                    "-i", os.path.join(tmpdir, "frame_%04d.png"),
                    "-vf", "palettegen=stats_mode=diff",
                    palette_path,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            subprocess.run(
                [
                    "ffmpeg", "-y", "-framerate", str(fps),
                    "-i", os.path.join(tmpdir, "frame_%04d.png"),
                    "-i", palette_path,
                    "-lavfi", "paletteuse=dither=bayer:bayer_scale=3",
                    path,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def dmx(
        self,
        scene_or_dmx: Union[Scene, Sequence[int]],
        t: float = 0.0,
        *,
        max_channel: Optional[int] = None,
        hide_zeros: bool = False,
        universe: int = 1,
    ) -> DMXFrameView:
        """Inspect the raw DMX frame and channel values at timestamp `t` on this stage."""
        return inspect_dmx(
            scene_or_dmx,
            t=t,
            stage=self,
            max_channel=max_channel,
            hide_zeros=hide_zeros,
            universe=universe,
        )

    def inspect(
        self,
        scene: Scene,
        *,
        duration: Optional[float] = None,
        fps: float = 20.0,
        show_dmx: bool = True,
        max_channel: Optional[int] = None,
        hide_zeros: bool = False,
    ) -> StageScrubberView:
        """Interactive Jupyter widget with animated visualizer, transport controls, and live DMX table."""
        return render_interactive_inspector(
            scene=scene,
            stage=self,
            duration=duration,
            fps=fps,
            show_dmx=show_dmx,
            max_channel=max_channel,
            hide_zeros=hide_zeros,
        )


def time_hash() -> int:
    import time
    return int(time.time() * 1000) % 10000000


__all__ = [
    "COOL_WHITE_RGB",
    "DMXFrameView",
    "EuroliteBCL40Bar",
    "EurolitePartySpot",
    "HTMLView",
    "Stage",
    "StageScrubberView",
    "WARM_WHITE_RGB",
    "blend_rgbw",
    "dmx",
    "inspect_dmx",
]
