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
    DMXFrameView,
    EuroliteBCL40Bar,
    EurolitePartySpot,
    HTMLView,
    Stage,
    StageScrubberView,
    WARM_WHITE_RGB,
    blend_rgbw,
    dmx,
    inspect_dmx,
)
from lightshow.inspector import parse_width
from .deck import ControlDeck


def enable_deck_logging(level: int = 20) -> None:  # logging.INFO = 20
    """Enable verbose kernel-side logging for ControlDeck and LiveStream in Jupyter."""
    import logging
    deck_logger = logging.getLogger("lightshow.deck")
    deck_logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter("[%(asctime)s] [Deck] %(message)s", datefmt="%H:%M:%S")
    handler.setFormatter(formatter)
    deck_logger.addHandler(handler)
    deck_logger.info("Kernel logging enabled for ControlDeck.")


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
    width: Union[int, str, None] = None,
    steps: int = 120,
    current_time: Optional[float] = None,
) -> HTMLView:
    """Render an SVG timeline strip visualizing `clip` across `fixtures` fixtures."""
    is_inf = math.isinf(clip.duration)
    show_dur = (6.0 if is_inf else clip.duration) if duration is None else duration
    if show_dur <= 0:
        show_dur = 1.0

    viewbox_w, css_max_w = parse_width(width, default_viewbox=1000)

    track_height = 20
    track_gap = 4
    header_height = 36
    ruler_height = 22
    total_height = header_height + fixtures * (track_height + track_gap) + ruler_height + 10
    left_margin = 70
    plot_width = viewbox_w - left_margin - 16

    # Sample time steps
    svg_elements: list[str] = []

    # Background card
    svg_elements.append(
        f'<rect width="{viewbox_w}" height="{total_height}" rx="8" '
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
        f'<rect x="{viewbox_w - 120}" y="10" width="106" height="20" rx="10" fill="#1f2937" stroke="#374151" stroke-width="1"/>'
        f'<text x="{viewbox_w - 67}" y="24" fill="#9ca3af" font-family="system-ui, sans-serif" '
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

    # Optional vertical playhead cursor for interactive scrubbing
    if current_time is not None and 0.0 <= current_time <= show_dur + 1e-4:
        cx = left_margin + (min(show_dur, max(0.0, current_time)) / show_dur) * plot_width
        svg_elements.append(
            f'<line x1="{cx:.1f}" y1="{header_height}" x2="{cx:.1f}" y2="{ruler_y}" '
            f'stroke="#38bdf8" stroke-width="2" stroke-linecap="round"/>'
            f'<polygon points="{cx-4:.1f},{header_height} {cx+4:.1f},{header_height} {cx:.1f},{header_height+6}" fill="#38bdf8"/>'
        )

    content = "".join(svg_elements)
    return HTMLView(
        f'<div style="width: 100%; max-width: {css_max_w}; margin: 8px 0; box-sizing: border-box;">'
        f'<svg viewBox="0 0 {viewbox_w} {total_height}" style="width: 100%; height: auto; max-width: 100%; border-radius: 8px; display: block;" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'{content}'
        f'</svg></div>'
    )


def render_scene_timeline_svg(
    scene: Scene,
    *,
    duration: Optional[float] = None,
    width: Union[int, str, None] = None,
    steps: int = 120,
    current_time: Optional[float] = None,
) -> HTMLView:
    """Render an SVG timeline strip visualizing a composable `Scene` across all active groups."""
    is_inf = math.isinf(scene.duration)
    show_dur = (6.0 if is_inf else scene.duration) if duration is None else duration
    if show_dur <= 0:
        show_dur = 1.0

    viewbox_w, css_max_w = parse_width(width, default_viewbox=1000)

    groups = scene.groups()
    if not groups:
        return HTMLView("<div><em>Empty Scene</em></div>")

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
    plot_width = viewbox_w - left_margin - 16

    svg_elements: list[str] = [
        f'<rect width="{viewbox_w}" height="{total_height}" rx="8" '
        f'fill="#0e1117" stroke="#262c36" stroke-width="1.2"/>'
    ]

    scene_title = html.escape(type(scene).__name__)
    dur_label = f"⏱ {scene.duration:.2f}s" if not is_inf else "⏱ ∞ (first 6s)"
    svg_elements.append(
        f'<text x="14" y="24" fill="#f3f4f6" font-family="system-ui, sans-serif" '
        f'font-size="13" font-weight="600">Scene ({scene_title})</text>'
    )
    svg_elements.append(
        f'<rect x="{viewbox_w - 120}" y="10" width="106" height="20" rx="10" fill="#1f2937" stroke="#374151" stroke-width="1"/>'
        f'<text x="{viewbox_w - 67}" y="24" fill="#9ca3af" font-family="system-ui, sans-serif" '
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

    # Optional vertical playhead cursor for interactive scrubbing
    if current_time is not None and 0.0 <= current_time <= show_dur + 1e-4:
        cx = left_margin + (min(show_dur, max(0.0, current_time)) / show_dur) * plot_width
        svg_elements.append(
            f'<line x1="{cx:.1f}" y1="{header_height}" x2="{cx:.1f}" y2="{ruler_y}" '
            f'stroke="#38bdf8" stroke-width="2" stroke-linecap="round"/>'
            f'<polygon points="{cx-4:.1f},{header_height} {cx+4:.1f},{header_height} {cx:.1f},{header_height+6}" fill="#38bdf8"/>'
        )

    content = "".join(svg_elements)
    return HTMLView(
        f'<div style="width: 100%; max-width: {css_max_w}; margin: 8px 0; box-sizing: border-box;">'
        f'<svg viewBox="0 0 {viewbox_w} {total_height}" style="width: 100%; height: auto; max-width: 100%; border-radius: 8px; display: block;" '
        f'xmlns="http://www.w3.org/2000/svg">'
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
        tempo: Optional[Tempo] = None,
        host: str = "192.168.1.158",
        universe: int = 1,
        fps: float = 40.0,
        master: float = 1.0,
        loop: bool = True,
        verbose: bool = False,
    ) -> None:
        self.rig = rig or Rig(host=host, universe=universe, fps=fps)
        self.fps = fps
        self.loop = loop
        self.verbose = verbose
        self._scene_lock = threading.Lock()
        self._current_scene: Scene = self.rig._to_scene(scene)

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Playing by default
        self._start_time = time.monotonic()
        self._paused_elapsed = 0.0
        self._pause_timestamp: Optional[float] = None
        self._thread: Optional[threading.Thread] = None
        self._packets_sent = 0

        self.master: float = max(0.0, min(1.0, float(master)))
        self.is_blackout: bool = False

        self._transition_active: bool = False
        self._transition_from: Optional[Scene] = None
        self._transition_from_start: float = 0.0
        self._transition_start_time: float = 0.0
        self._transition_duration: float = 0.0

        self.tempo: Optional[Tempo] = tempo if tempo is not None else self._find_tempo(self._current_scene)
        if self.tempo is not None:
            self.tempo.on_change(self._on_tempo_change)

    @staticmethod
    def _find_tempo(obj: Any) -> Optional[Tempo]:
        """Attempt to extract bound Tempo from a scene or clip tree."""
        if hasattr(obj, "clip"):
            t = LiveStream._find_tempo(obj.clip)
            if t is not None:
                return t
        if hasattr(obj, "scenes"):
            for s in obj.scenes:
                t = LiveStream._find_tempo(s)
                if t is not None:
                    return t
        if hasattr(obj, "clips"):
            for c in obj.clips:
                t = LiveStream._find_tempo(c)
                if t is not None:
                    return t
        if hasattr(obj, "child"):
            t = LiveStream._find_tempo(obj.child)
            if t is not None:
                return t
        if hasattr(obj, "bottom"):
            t = LiveStream._find_tempo(obj.bottom) or LiveStream._find_tempo(getattr(obj, "top", None))
            if t is not None:
                return t
        dur = getattr(obj, "_duration", None)
        if hasattr(dur, "tempo"):
            return dur.tempo
        step_dur = getattr(obj, "step_duration", None)
        if hasattr(step_dur, "tempo"):
            return step_dur.tempo
        return None

    def _on_tempo_change(self, old_bpm: float, new_bpm: float) -> None:
        """Adjust start time on BPM change to preserve loop phase with zero glitch."""
        if old_bpm <= 0 or new_bpm <= 0:
            return
        with self._scene_lock:
            scene = self._current_scene
        dur = scene.duration
        now = time.monotonic()
        if dur <= 0 or math.isinf(dur):
            elapsed = now - self._start_time
            self._start_time = now - (elapsed * (new_bpm / old_bpm))
            return

        elapsed = now - self._start_time
        d_new = dur
        d_old = dur * (new_bpm / old_bpm)
        phi_old = elapsed % d_old if d_old > 0 else 0.0
        phi_new = phi_old * (d_new / d_old) if d_old > 0 else 0.0
        self._start_time = now - phi_new

    def set_bpm(self, bpm: float) -> None:
        """Update streaming BPM at runtime."""
        if self.tempo is not None:
            self.tempo.bpm = bpm

    def tap(self) -> float:
        """Tap tempo to sync with live audio."""
        if self.tempo is not None:
            return self.tempo.tap()
        return 120.0

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
            self._transition_active = False
            self._transition_from = None
            self._current_scene = self.rig._to_scene(new_scene)
            self._start_time = time.monotonic()
            if self.tempo is None:
                new_t = self._find_tempo(self._current_scene)
                if new_t is not None:
                    self.tempo = new_t
                    self.tempo.on_change(self._on_tempo_change)

    def transition_to(self, new_scene: Union[Scene, Clip], duration: float = 1.0) -> None:
        """Smoothly crossfade into `new_scene` over `duration` seconds."""
        if duration <= 0.0:
            self.update(new_scene)
            return

        with self._scene_lock:
            now = time.monotonic()
            self._transition_from = self._current_scene
            self._transition_from_start = self._start_time
            self._current_scene = self.rig._to_scene(new_scene)
            self._start_time = now
            self._transition_start_time = now
            self._transition_duration = max(0.05, float(duration))
            self._transition_active = True

            if self.tempo is None:
                new_t = self._find_tempo(self._current_scene)
                if new_t is not None:
                    self.tempo = new_t
                    self.tempo.on_change(self._on_tempo_change)

    def pause(self) -> None:
        """Pause playback and packet transmission."""
        if self._pause_event.is_set():
            self._pause_event.clear()
            self._pause_timestamp = time.monotonic()

    def resume(self) -> None:
        """Resume playback."""
        if not self._pause_event.is_set():
            if self._pause_timestamp is not None:
                pause_duration = time.monotonic() - self._pause_timestamp
                self._start_time += pause_duration
                self._pause_timestamp = None
            self._pause_event.set()
        if not self.is_alive:
            self.start()

    def set_master(self, master: float) -> None:
        """Set master dimmer intensity in [0.0, 1.0]."""
        with self._scene_lock:
            self.master = max(0.0, min(1.0, float(master)))

    def toggle_blackout(self) -> bool:
        """Toggle master blackout without stopping playback. Returns True if now blacked out."""
        with self._scene_lock:
            self.is_blackout = not self.is_blackout
            return self.is_blackout

    def set_blackout(self, active: bool) -> None:
        """Set master blackout state."""
        with self._scene_lock:
            self.is_blackout = bool(active)

    def blackout(self) -> None:
        """Send immediate blackout."""
        self.rig.blackout()

    def stop(self) -> None:
        """Stop background streaming and blackout the rig."""
        self._stop_event.set()
        if self.tempo is not None:
            self.tempo.remove_callback(self._on_tempo_change)
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self.rig.blackout()

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _canvas_to_dmx(self, scene_canvas: DMXCanvas) -> list[int]:
        """Merge canvas with rig fixture defaults, apply master dimmer/blackout, and return DMX bytes."""
        max_ch = max(
            [g.max_channel for g in self.rig.groups]
            + [24]
        )
        if self.is_blackout:
            return [0] * max_ch

        base_canvas = DMXCanvas()
        for grp in self.rig.groups:
            grp.register_canvas_defaults(base_canvas)
        merged = base_canvas.merge(scene_canvas, mode="override")
        if self.master < 1.0:
            merged = merged.scale(self.master)
        return merged.to_dmx_list(min_size=max_ch)

    def _eval_time(self, now: float, start: float, scene: Optional[Scene]) -> float:
        """Calculate evaluation time, applying automatic loop modulo when loop=True."""
        elapsed = max(0.0, now - start)
        if self.loop and scene is not None:
            dur = scene.duration
            if dur > 0 and not math.isinf(dur):
                return elapsed % dur
        return elapsed

    def _loop(self) -> None:
        frame_interval = 1.0 / self.fps
        next_frame = time.monotonic()
        self._start_time = next_frame

        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                now = time.monotonic()
                with self._scene_lock:
                    if self.is_blackout:
                        dmx = self._canvas_to_dmx(DMXCanvas())
                    else:
                        if self._transition_active:
                            elapsed = now - self._transition_start_time
                            alpha = elapsed / self._transition_duration if self._transition_duration > 0 else 1.0
                            if alpha >= 1.0:
                                self._transition_active = False
                                self._transition_from = None
                                t = self._eval_time(now, self._start_time, self._current_scene)
                                canvas = self._current_scene.eval_canvas(t)
                            else:
                                t_a = self._eval_time(now, self._transition_from_start, self._transition_from)
                                t_b = self._eval_time(now, self._start_time, self._current_scene)
                                canvas_a = self._transition_from.eval_canvas(t_a)
                                canvas_b = self._current_scene.eval_canvas(t_b)
                                canvas = canvas_a.scale(1.0 - alpha).merge(canvas_b.scale(alpha), mode="add")
                        else:
                            t = self._eval_time(now, self._start_time, self._current_scene)
                            canvas = self._current_scene.eval_canvas(t)

                        dmx = self._canvas_to_dmx(canvas)

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
        tempo_badge = ""
        if self.tempo is not None:
            tempo_badge = f'<span style="font-size: 12px; background: #1e293b; border: 1px solid #334155; border-radius: 4px; padding: 2px 8px; color: #38bdf8; font-weight: 500;">🎵 {self.tempo.bpm:g} BPM</span>'

        return f"""
        <div style="font-family: system-ui, -apple-system, sans-serif; background: #0e1117; 
                    border: 1px solid #262c36; border-radius: 8px; padding: 14px 18px; 
                    max-width: 580px; color: #f3f4f6; margin: 8px 0;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: {status_color};"></span>
                    <strong style="font-size: 13px; letter-spacing: 0.5px;">{status_text}</strong>
                    {tempo_badge}
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
    tempo: Optional[Tempo] = None,
    host: str = "192.168.1.158",
    universe: int = 1,
    fps: float = 40.0,
    loop: bool = True,
) -> LiveStream:
    """Stream `scene` in the background (loops continuously by default).

    If an active stream is already running, seamlessly hot-swaps to `scene`
    without stopping or dropping DMX sync!
    """
    global _active_stream
    if _active_stream is not None and _active_stream.is_alive:
        _active_stream.loop = loop
        _active_stream.update(scene)
        if tempo is not None:
            if _active_stream.tempo is not None:
                _active_stream.tempo.remove_callback(_active_stream._on_tempo_change)
            _active_stream.tempo = tempo
            _active_stream.tempo.on_change(_active_stream._on_tempo_change)
        return _active_stream

    _active_stream = LiveStream(scene, rig=rig, tempo=tempo, host=host, universe=universe, fps=fps, loop=loop)
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
    "ControlDeck",
    "enable_deck_logging",
    "DMXFrameView",
    "EuroliteBCL40Bar",
    "EurolitePartySpot",
    "HTMLView",
    "LiveStream",
    "Stage",
    "StageScrubberView",
    "WARM_WHITE_RGB",
    "blend_rgbw",
    "dmx",
    "inspect_dmx",
    "render_clip_timeline_svg",
    "render_scene_timeline_svg",
    "stop_stream",
    "stream",
]
