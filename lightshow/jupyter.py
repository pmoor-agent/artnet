"""Jupyter Notebook integration for `lightshow`.

Keeps the core `lightshow` library completely pristine and vanilla Python,
while providing rich visual previews and non-blocking background streaming
when imported inside Jupyter/IPython notebooks:

    from lightshow.jupyter import *
    from my_rig import create_rig, PARS, STROBE_BAR

This module:
1. Re-exports everything from `lightshow` so you only need a single import.
2. Automatically attaches `_repr_html_` to `Clip` and `Scene` to render
   beautiful, self-contained SVG timeline ribbons in notebook cells.
3. Provides `stream(scene)` for smooth 40Hz background playback with
   zero kernel blocking and seamless hot-reloading.
"""

from __future__ import annotations
import html
import math
import sys
import threading
import time
from typing import Optional, Union

# 1. Re-export all core lightshow symbols
import lightshow
from lightshow import *
from lightshow.clips import Clip
from lightshow.fixtures import BoundScene, DMXCanvas, FixtureGroup, Scene
from lightshow.artnet import ArtNetClient, Rig
from lightshow.state import Color, Patch
from lightshow.profiles import (
    COOL_WHITE_RGB,
    EuroliteBCL40Bar,
    EurolitePartySpot,
    HTMLView,
    Stage,
    StageScrubberView,
    WARM_WHITE_RGB,
    blend_rgbw,
)


# =============================================================================
# SVG Timeline Visualizer (Zero-dependency pure-Python string generation)
# =============================================================================

def _color_to_rgb_str(color: Optional[Color], w: float = 0.0, dimmer: float = 1.0) -> str:
    """Convert Color + white + dimmer to an SVG rgb(...) string."""
    if color is None:
        if w > 0:
            val = int(min(255, max(0, w * dimmer * 255)))
            return f"rgb({val},{val},{val})"
        return "rgb(12,12,14)"
    r = min(255, max(0, int((color.r * 255 + w * 215) * dimmer)))
    g = min(255, max(0, int((color.g * 255 + w * 215) * dimmer)))
    b = min(255, max(0, int((color.b * 255 + w * 215) * dimmer)))
    return f"rgb({r},{g},{b})"


def render_clip_timeline_svg(
    clip: Clip,
    *,
    duration: Optional[float] = None,
    fixtures: int = 4,
    width: int = 700,
    steps: int = 120,
) -> str:
    """Render an SVG timeline strip visualizing `clip` across `fixtures` fixtures."""
    is_inf = math.isinf(clip.duration)
    show_dur = (6.0 if is_inf else clip.duration) if duration is None else duration
    if show_dur <= 0:
        show_dur = 1.0

    track_height = 20
    track_gap = 4
    header_height = 36
    ruler_height = 22
    total_height = header_height + fixtures * (track_height + track_gap) + ruler_height + 10
    left_margin = 70
    plot_width = width - left_margin - 16

    # Sample time steps
    svg_elements: list[str] = []

    # Background card
    svg_elements.append(
        f'<rect width="{width}" height="{total_height}" rx="8" '
        f'fill="#0e1117" stroke="#262c36" stroke-width="1.2"/>'
    )

    # Header title & duration badge
    clip_name = html.escape(type(clip).__name__)
    dur_label = f"⏱ {clip.duration:.2f}s" if not is_inf else "⏱ ∞ (first 6s)"
    svg_elements.append(
        f'<text x="14" y="24" fill="#f3f4f6" font-family="system-ui, -apple-system, sans-serif" '
        f'font-size="13" font-weight="600">{clip_name}</text>'
    )
    svg_elements.append(
        f'<rect x="{width - 120}" y="10" width="106" height="20" rx="10" fill="#1f2937" stroke="#374151" stroke-width="1"/>'
        f'<text x="{width - 67}" y="24" fill="#9ca3af" font-family="system-ui, sans-serif" '
        f'font-size="11" text-anchor="middle">{dur_label}</text>'
    )

    step_dt = show_dur / steps
    slice_w = plot_width / steps

    # Draw tracks
    for f_idx in range(fixtures):
        y_top = header_height + f_idx * (track_height + track_gap)

        # Track label
        svg_elements.append(
            f'<text x="14" y="{y_top + 14}" fill="#9ca3af" font-family="monospace" '
            f'font-size="11">Fix {f_idx + 1}</text>'
        )

        # Track background trough
        svg_elements.append(
            f'<rect x="{left_margin}" y="{y_top}" width="{plot_width}" height="{track_height}" '
            f'rx="3" fill="#161b22"/>'
        )

        for step in range(steps):
            t = (step + 0.5) * step_dt
            patch = clip.eval(t, fixture=f_idx, total_fixtures=fixtures)
            w = patch.channels.get("w", patch.channels.get("cw", 0.0))
            dimmer = patch.channels.get("dimmer", 1.0)
            fill_color = _color_to_rgb_str(patch.color, w=w, dimmer=dimmer)
            x = left_margin + step * slice_w

            svg_elements.append(
                f'<rect x="{x:.2f}" y="{y_top}" width="{slice_w + 0.5:.2f}" height="{track_height}" '
                f'fill="{fill_color}"/>'
            )

            # Strobe indicator pulse
            strobe_rate = patch.channels.get("strobe", 0.0)
            if strobe_rate > 0:
                svg_elements.append(
                    f'<rect x="{x:.2f}" y="{y_top}" width="{slice_w + 0.5:.2f}" height="3" '
                    f'fill="#fef08a"/>'
                )

    # Time ruler at bottom
    ruler_y = header_height + fixtures * (track_height + track_gap) + 4
    svg_elements.append(
        f'<line x1="{left_margin}" y1="{ruler_y}" x2="{left_margin + plot_width}" y2="{ruler_y}" '
        f'stroke="#374151" stroke-width="1"/>'
    )

    # Ticks every 1.0s or 0.5s depending on show_dur
    tick_step = 1.0 if show_dur >= 2.0 else (0.5 if show_dur >= 1.0 else 0.2)
    current_tick = 0.0
    while current_tick <= show_dur + 1e-5:
        tx = left_margin + (current_tick / show_dur) * plot_width
        svg_elements.append(
            f'<line x1="{tx:.1f}" y1="{ruler_y}" x2="{tx:.1f}" y2="{ruler_y + 4}" stroke="#4b5563" stroke-width="1"/>'
            f'<text x="{tx:.1f}" y="{ruler_y + 16}" fill="#6b7280" font-family="monospace" '
            f'font-size="10" text-anchor="middle">{current_tick:.1f}s</text>'
        )
        current_tick += tick_step

    content = "".join(svg_elements)
    return HTMLView(
        f'<div style="max-width: {width}px; margin: 8px 0;">'
        f'<svg viewBox="0 0 {width} {total_height}" width="100%" height="{total_height}" '
        f'xmlns="http://www.w3.org/2000/svg" style="border-radius: 8px; display: block;">'
        f'{content}'
        f'</svg></div>'
    )


def render_scene_timeline_svg(
    scene: Scene,
    *,
    duration: Optional[float] = None,
    width: int = 700,
    steps: int = 120,
) -> str:
    """Render an SVG timeline strip visualizing a composable `Scene` across all active groups."""
    is_inf = math.isinf(scene.duration)
    show_dur = (6.0 if is_inf else scene.duration) if duration is None else duration
    if show_dur <= 0:
        show_dur = 1.0

    groups = scene.groups()
    if not groups:
        return "<div><em>Empty Scene</em></div>"

    # Flatten elements
    lanes: list[tuple[str, int, FixtureGroup, int]] = []
    seen_elements: set[tuple[tuple[str, Optional[int]], ...]] = set()

    for grp in groups:
        for i in range(grp.count):
            el = grp.elements[i]
            el_key = tuple(sorted((attr, getattr(prim, "address", None)) for attr, prim in el.items()))
            if el_key in seen_elements:
                continue
            seen_elements.add(el_key)

            label = grp.label(i) if hasattr(grp, "label") else (f"{grp.name}[{i}]" if grp.count > 1 else grp.name)
            lanes.append((label, i, grp, len(lanes)))

    track_height = 18
    track_gap = 3
    header_height = 36
    ruler_height = 22
    total_height = header_height + len(lanes) * (track_height + track_gap) + ruler_height + 10
    left_margin = 110
    plot_width = width - left_margin - 16

    svg_elements: list[str] = [
        f'<rect width="{width}" height="{total_height}" rx="8" '
        f'fill="#0e1117" stroke="#262c36" stroke-width="1.2"/>'
    ]

    scene_title = html.escape(type(scene).__name__)
    dur_label = f"⏱ {scene.duration:.2f}s" if not is_inf else "⏱ ∞ (first 6s)"
    svg_elements.append(
        f'<text x="14" y="24" fill="#f3f4f6" font-family="system-ui, sans-serif" '
        f'font-size="13" font-weight="600">Scene ({scene_title})</text>'
    )
    svg_elements.append(
        f'<rect x="{width - 120}" y="10" width="106" height="20" rx="10" fill="#1f2937" stroke="#374151" stroke-width="1"/>'
        f'<text x="{width - 67}" y="24" fill="#9ca3af" font-family="system-ui, sans-serif" '
        f'font-size="11" text-anchor="middle">{dur_label}</text>'
    )

    step_dt = show_dur / steps
    slice_w = plot_width / steps

    for label, el_idx, grp, lane_idx in lanes:
        y_top = header_height + lane_idx * (track_height + track_gap)
        svg_elements.append(
            f'<text x="14" y="{y_top + 13}" fill="#9ca3af" font-family="monospace" '
            f'font-size="10">{html.escape(label[:16])}</text>'
        )
        svg_elements.append(
            f'<rect x="{left_margin}" y="{y_top}" width="{plot_width}" height="{track_height}" '
            f'rx="2" fill="#161b22"/>'
        )

    # Sample canvas at each time step
    max_channel = max([64] + [grp.max_channel for grp in groups])
    for step in range(steps):
        t = (step + 0.5) * step_dt
        canvas = scene.eval_canvas(t)
        dmx_frame = canvas.to_dmx_list(min_size=max_channel)
        x = left_margin + step * slice_w

        for label, el_idx, grp, lane_idx in lanes:
            y_top = header_height + lane_idx * (track_height + track_gap)
            el = grp.elements[el_idx]

            # Inspect element primitives
            r_b, g_b, b_b, w_b = 0, 0, 0, 0
            dim_b = 255
            strobe_b = 0

            has_rgb = False
            for attr, prim in el.items():
                if isinstance(prim, lightshow.RGB) and prim.address + 2 <= len(dmx_frame):
                    has_rgb = True
                    idx = prim.address - 1
                    r_b, g_b, b_b = dmx_frame[idx], dmx_frame[idx + 1], dmx_frame[idx + 2]
                elif isinstance(prim, lightshow.Channel) and prim.address <= len(dmx_frame):
                    v = dmx_frame[prim.address - 1]
                    if attr in ("w", "cw", "ww"):
                        w_b = max(w_b, v)
                    elif attr == "dimmer":
                        dim_b = v
                    elif attr == "strobe":
                        strobe_b = v
                    elif not has_rgb and attr == "value":
                        w_b = max(w_b, v)

            if not has_rgb:
                r_b, g_b, b_b = w_b, w_b, w_b

            scale = dim_b / 255.0
            r_out = min(255, int((r_b + w_b * 0.8) * scale))
            g_out = min(255, int((g_b + w_b * 0.8) * scale))
            b_out = min(255, int((b_b + w_b * 0.8) * scale))

            fill_color = f"rgb({r_out},{g_out},{b_out})" if (r_out > 0 or g_out > 0 or b_out > 0) else "#111418"
            svg_elements.append(
                f'<rect x="{x:.2f}" y="{y_top}" width="{slice_w + 0.5:.2f}" height="{track_height}" '
                f'fill="{fill_color}"/>'
            )
            if strobe_b > 0:
                svg_elements.append(
                    f'<rect x="{x:.2f}" y="{y_top}" width="{slice_w + 0.5:.2f}" height="2" '
                    f'fill="#fef08a"/>'
                )

    # Time ruler
    ruler_y = header_height + len(lanes) * (track_height + track_gap) + 4
    svg_elements.append(
        f'<line x1="{left_margin}" y1="{ruler_y}" x2="{left_margin + plot_width}" y2="{ruler_y}" '
        f'stroke="#374151" stroke-width="1"/>'
    )
    tick_step = 1.0 if show_dur >= 2.0 else 0.5
    current_tick = 0.0
    while current_tick <= show_dur + 1e-5:
        tx = left_margin + (current_tick / show_dur) * plot_width
        svg_elements.append(
            f'<line x1="{tx:.1f}" y1="{ruler_y}" x2="{tx:.1f}" y2="{ruler_y + 4}" stroke="#4b5563" stroke-width="1"/>'
            f'<text x="{tx:.1f}" y="{ruler_y + 16}" fill="#6b7280" font-family="monospace" '
            f'font-size="10" text-anchor="middle">{current_tick:.1f}s</text>'
        )
        current_tick += tick_step

    content = "".join(svg_elements)
    return HTMLView(
        f'<div style="max-width: {width}px; margin: 8px 0;">'
        f'<svg viewBox="0 0 {width} {total_height}" width="100%" height="{total_height}" '
        f'xmlns="http://www.w3.org/2000/svg" style="border-radius: 8px; display: block;">'
        f'{content}'
        f'</svg></div>'
    )


# Attach `_repr_html_` dynamically without altering core library code
Clip._repr_html_ = lambda self: render_clip_timeline_svg(self)
Scene._repr_html_ = lambda self: render_scene_timeline_svg(self)


# =============================================================================
# Non-Blocking Background Live Streamer (Hot-Reloadable)
# =============================================================================

class LiveStream:
    """Non-blocking Art-Net background streamer for Jupyter notebooks."""

    def __init__(
        self,
        scene: Union[Scene, Clip],
        rig: Optional[Rig] = None,
        *,
        host: str = "192.168.1.158",
        universe: int = 1,
        fps: float = 40.0,
    ) -> None:
        self.rig = rig or Rig(host=host, universe=universe, fps=fps)
        self.fps = fps
        self._scene_lock = threading.Lock()
        self._current_scene: Scene = self.rig._to_scene(scene)

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Playing by default
        self._start_time = time.monotonic()
        self._paused_elapsed = 0.0
        self._thread: Optional[threading.Thread] = None
        self._packets_sent = 0

    def start(self) -> LiveStream:
        """Start streaming in a background daemon thread."""
        if self._thread is None or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="ArtNetLiveStream")
            self._thread.start()
        return self

    def update(self, new_scene: Union[Scene, Clip]) -> None:
        """Hot-swap the playing scene immediately on the fly without stopping DMX."""
        with self._scene_lock:
            self._current_scene = self.rig._to_scene(new_scene)

    def pause(self) -> None:
        """Pause playback and packet transmission."""
        self._pause_event.clear()

    def resume(self) -> None:
        """Resume playback."""
        self._pause_event.set()

    def blackout(self) -> None:
        """Send immediate blackout."""
        self.rig.blackout()

    def stop(self) -> None:
        """Stop background streaming and blackout the rig."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self.rig.blackout()

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        frame_interval = 1.0 / self.fps
        next_frame = time.monotonic()
        self._start_time = next_frame

        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                now = time.monotonic()
                t = now - self._start_time
                with self._scene_lock:
                    scene = self._current_scene
                dmx = self.rig.render_dmx(scene, t)
                if not self.rig.dry_run:
                    self.rig.client.send_dmx(dmx)
                self._packets_sent += 1

            next_frame += frame_interval
            sleep_time = next_frame - time.monotonic()
            if sleep_time > 0:
                time.sleep(sleep_time)
            elif sleep_time < -frame_interval:
                next_frame = time.monotonic()

    def _repr_html_(self) -> str:
        status_color = "#22c55e" if self.is_alive and self._pause_event.is_set() else "#eab308"
        status_text = "STREAMING (40 Hz)" if (self.is_alive and self._pause_event.is_set()) else "PAUSED"
        host = self.rig.client.host
        univ = self.rig.client.universe

        return f"""
        <div style="font-family: system-ui, -apple-system, sans-serif; background: #0e1117; 
                    border: 1px solid #262c36; border-radius: 8px; padding: 14px 18px; 
                    max-width: 580px; color: #f3f4f6; margin: 8px 0;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: {status_color};"></span>
                    <strong style="font-size: 13px; letter-spacing: 0.5px;">{status_text}</strong>
                </div>
                <span style="font-size: 12px; color: #9ca3af; font-family: monospace;">{host} (Univ {univ})</span>
            </div>
            <div style="font-size: 12px; color: #9ca3af; line-height: 1.5;">
                Non-blocking background stream active. Hot-swap scenes with <code>streamer.update(new_scene)</code> or stop with <code>streamer.stop()</code>.
            </div>
        </div>
        """


# Global active stream handle for seamless single-call hot-reloading
_active_stream: Optional[LiveStream] = None

def stream(
    scene: Union[Scene, Clip],
    rig: Optional[Rig] = None,
    *,
    host: str = "192.168.1.158",
    universe: int = 1,
    fps: float = 40.0,
) -> LiveStream:
    """Stream `scene` in the background.

    If an active stream is already running, seamlessly hot-swaps to `scene`
    without stopping or dropping DMX sync!
    """
    global _active_stream
    if _active_stream is not None and _active_stream.is_alive:
        _active_stream.update(scene)
        return _active_stream

    _active_stream = LiveStream(scene, rig=rig, host=host, universe=universe, fps=fps)
    _active_stream.start()
    return _active_stream


def stop_stream() -> None:
    """Stop any active background stream."""
    global _active_stream
    if _active_stream is not None:
        _active_stream.stop()
        _active_stream = None


__all__ = list(lightshow.__all__) + [
    "COOL_WHITE_RGB",
    "EuroliteBCL40Bar",
    "EurolitePartySpot",
    "HTMLView",
    "LiveStream",
    "Stage",
    "StageScrubberView",
    "WARM_WHITE_RGB",
    "blend_rgbw",
    "render_clip_timeline_svg",
    "render_scene_timeline_svg",
    "stop_stream",
    "stream",
]
