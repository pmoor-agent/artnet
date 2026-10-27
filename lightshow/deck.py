"""Interactive DJ/VJ live mixing and control deck for Art-Net lighting shows.

Provides a hardware-console style interface to control live background streaming:
- Dropdown selectors for Active (Program) and Cue (Preview) scenes.
- Smooth crossfading (Transition / GO) and instant Hard Cuts.
- Full transport controls: Play, Pause, Stop, Blackout.
- Real-time BPM slider, number field, Tap Tempo, and multiplier buttons (/2, *2).
- Master dimmer slider with quick presets (100%, 75%, 50%, 0%).
- Full programmatic control so everything can also be scripted in Python.
"""

from __future__ import annotations
from collections import OrderedDict
import html
import math
import threading
import time
from typing import Any, Mapping, Optional, Sequence, Union

from .artnet import Rig
from .clips import Clip
from .fixtures import Scene
from .tempo import Tempo

try:
    import ipywidgets as widgets
    from IPython.display import display
    HAS_IPYWIDGETS = True
except ImportError:
    widgets = None  # type: ignore
    HAS_IPYWIDGETS = False


class ControlDeck:
    """Interactive DJ/VJ live mixing and control deck for Art-Net lighting shows.

    Args:
        scenes: A dict mapping names to scenes/clips (e.g. `{"Disco": disco, "Drop": drop}`),
            or a sequence of `(name, scene)` tuples, or a list of scenes.
        rig: Optional `Rig` to stream through (defaults to `Rig(host="192.168.1.158")`).
        tempo: Optional `Tempo` instance (inferred from scenes or defaults to 120 BPM).
        bpm: Initial BPM if no Tempo is provided.
        fps: Art-Net output frame rate (default 40 Hz).
        transition_time: Default duration in seconds for smooth scene crossfading (default 1.0s).
        master: Initial master intensity in [0.0, 1.0] (default 1.0).
        autoplay: Whether to begin streaming immediately on initialization (default False).
        host: Target Art-Net node IP if `rig` is omitted.
        universe: Target Art-Net universe if `rig` is omitted.
    """

    def __init__(
        self,
        scenes: Union[
            Mapping[str, Union[Scene, Clip]],
            Sequence[Union[Scene, Clip, tuple[str, Union[Scene, Clip]]]]
        ],
        rig: Optional[Rig] = None,
        *,
        tempo: Optional[Tempo] = None,
        bpm: float = 120.0,
        fps: float = 40.0,
        transition_time: float = 1.0,
        master: float = 1.0,
        autoplay: bool = False,
        host: str = "192.168.1.158",
        universe: int = 1,
    ) -> None:
        self.rig = rig or Rig(host=host, universe=universe, fps=fps)
        self.fps = fps
        self.transition_time = max(0.0, float(transition_time))

        # Normalize scenes into an OrderedDict[str, Scene]
        self._scenes: OrderedDict[str, Scene] = OrderedDict()
        if isinstance(scenes, Mapping):
            for k, v in scenes.items():
                self._scenes[str(k)] = self.rig._to_scene(v)
        elif isinstance(scenes, Sequence):
            for i, item in enumerate(scenes):
                if isinstance(item, tuple) and len(item) == 2:
                    k, v = item
                    self._scenes[str(k)] = self.rig._to_scene(v)
                else:
                    name = getattr(item, "name", f"Scene {i + 1}")
                    self._scenes[str(name)] = self.rig._to_scene(item)
        else:
            raise TypeError("scenes must be a dict or sequence of scenes/clips")

        if not self._scenes:
            raise ValueError("ControlDeck requires at least one scene.")

        self._scene_keys: list[str] = list(self._scenes.keys())
        self._active_key: str = self._scene_keys[0]
        self._cue_key: str = self._scene_keys[min(1, len(self._scene_keys) - 1)]

        # Resolve tempo
        from .jupyter import LiveStream
        found_tempo = tempo
        if found_tempo is None:
            for s in self._scenes.values():
                t = LiveStream._find_tempo(s)
                if t is not None:
                    found_tempo = t
                    break
        self.tempo: Tempo = found_tempo if found_tempo is not None else Tempo(bpm=bpm)

        # Initialize background streamer
        self.streamer: LiveStream = LiveStream(
            self.current_scene,
            rig=self.rig,
            tempo=self.tempo,
            fps=self.fps,
        )
        self.streamer.set_master(master)
        if autoplay:
            self.streamer.start()
        else:
            self.streamer.pause()
            self.streamer.start()

        # UI Widget components
        self._widget: Optional[Any] = None
        self._ui_elements: dict[str, Any] = {}
        if HAS_IPYWIDGETS:
            self._build_widget()

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def scene_names(self) -> list[str]:
        """List of all registered scene names."""
        return list(self._scenes.keys())

    @property
    def current_scene_name(self) -> str:
        """Name of the currently playing scene."""
        return self._active_key

    @property
    def current_scene(self) -> Scene:
        """The currently active playing Scene."""
        return self._scenes[self._active_key]

    @property
    def cue_scene_name(self) -> str:
        """Name of the cued next scene."""
        return self._cue_key

    @property
    def cue_scene(self) -> Scene:
        """The cued next Scene."""
        return self._scenes[self._cue_key]

    @property
    def bpm(self) -> float:
        """Current playback tempo in BPM."""
        return self.tempo.bpm

    @property
    def master(self) -> float:
        """Grand master intensity in [0.0, 1.0]."""
        return self.streamer.master

    @property
    def is_playing(self) -> bool:
        """Whether the deck is currently transmitting active DMX frames."""
        return self.streamer.is_alive and self.streamer._pause_event.is_set()

    @property
    def is_paused(self) -> bool:
        """Whether playback is currently paused."""
        return self.streamer.is_alive and not self.streamer._pause_event.is_set()

    @property
    def is_blackout(self) -> bool:
        """Whether master blackout is active."""
        return self.streamer.is_blackout

    @property
    def widget(self) -> Optional[Any]:
        """The top-level `ipywidgets.VBox` GUI container, or None if ipywidgets is not installed."""
        return self._widget

    # =========================================================================
    # Transport Controls
    # =========================================================================

    def play(self) -> None:
        """Start or resume live streaming."""
        self.streamer.resume()
        self._sync_ui()

    def pause(self) -> None:
        """Pause live streaming without dropping DMX frame clock."""
        self.streamer.pause()
        self._sync_ui()

    def toggle_play(self) -> None:
        """Toggle between play and pause."""
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        """Stop background streaming and blackout the rig."""
        self.streamer.stop()
        self._sync_ui()

    def blackout(self) -> None:
        """Engage immediate master blackout."""
        self.streamer.set_blackout(True)
        self._sync_ui()

    def toggle_blackout(self) -> bool:
        """Toggle master blackout without stopping playback. Returns True if now blacked out."""
        active = self.streamer.toggle_blackout()
        self._sync_ui()
        return active

    def set_blackout(self, active: bool) -> None:
        """Set master blackout state."""
        self.streamer.set_blackout(active)
        self._sync_ui()

    def set_master(self, level: float) -> None:
        """Set grand master intensity in [0.0, 1.0]."""
        self.streamer.set_master(level)
        self._sync_ui()

    # =========================================================================
    # Scene Selection & Mixing
    # =========================================================================

    def select(self, name_or_index: Union[str, int]) -> None:
        """Immediately switch to a scene (hard cut)."""
        key = self._resolve_key(name_or_index)
        self._active_key = key
        self.streamer.update(self._scenes[key])
        self._sync_ui()

    def cue(self, name_or_index: Union[str, int]) -> None:
        """Set the cued next scene without affecting the live output."""
        key = self._resolve_key(name_or_index)
        self._cue_key = key
        self._sync_ui()

    def transition_to(self, name_or_index: Union[str, int], duration: Optional[float] = None) -> None:
        """Smoothly crossfade to `name_or_index` over `duration` seconds."""
        key = self._resolve_key(name_or_index)
        self._active_key = key
        dur = self.transition_time if duration is None else max(0.0, float(duration))
        self.streamer.transition_to(self._scenes[key], duration=dur)
        self._sync_ui()

    def go(self, duration: Optional[float] = None) -> None:
        """Crossfade from active scene to the cued next scene, and advance cue to the subsequent scene."""
        target_key = self._cue_key
        dur = self.transition_time if duration is None else max(0.0, float(duration))
        self.transition_to(target_key, duration=dur)

        # Advance cue to the next in order
        keys = list(self._scenes.keys())
        idx = keys.index(target_key)
        next_idx = (idx + 1) % len(keys)
        self._cue_key = keys[next_idx]
        self._sync_ui()

    def cut(self) -> None:
        """Cut immediately to the cued next scene, and advance cue to the subsequent scene."""
        target_key = self._cue_key
        self.select(target_key)
        keys = list(self._scenes.keys())
        idx = keys.index(target_key)
        next_idx = (idx + 1) % len(keys)
        self._cue_key = keys[next_idx]
        self._sync_ui()

    def next(self, fade: bool = False) -> None:
        """Advance to the next scene in the list (cycles back to start)."""
        keys = list(self._scenes.keys())
        idx = keys.index(self._active_key)
        next_key = keys[(idx + 1) % len(keys)]
        if fade:
            self.transition_to(next_key)
        else:
            self.select(next_key)

    def prev(self, fade: bool = False) -> None:
        """Step backward to the previous scene in the list."""
        keys = list(self._scenes.keys())
        idx = keys.index(self._active_key)
        prev_key = keys[(idx - 1) % len(keys)]
        if fade:
            self.transition_to(prev_key)
        else:
            self.select(prev_key)

    def add(self, name: str, scene: Union[Scene, Clip]) -> None:
        """Register a new scene into the deck on the fly."""
        key = str(name)
        self._scenes[key] = self.rig._to_scene(scene)
        self._scene_keys = list(self._scenes.keys())
        if self._widget is not None and "active_dropdown" in self._ui_elements:
            opts = list(self._scenes.keys())
            self._ui_elements["active_dropdown"].options = opts
            self._ui_elements["cue_dropdown"].options = opts
        self._sync_ui()

    # =========================================================================
    # Tempo & Timing
    # =========================================================================

    def set_bpm(self, bpm: float) -> None:
        """Set tempo in BPM."""
        self.tempo.bpm = max(20.0, min(300.0, float(bpm)))
        self.streamer.set_bpm(self.tempo.bpm)
        self._sync_ui()

    def tap(self) -> float:
        """Record a tap and update tempo."""
        new_bpm = self.tempo.tap()
        self.streamer.set_bpm(new_bpm)
        self._sync_ui()
        return new_bpm

    def multiply_bpm(self, factor: float) -> float:
        """Multiply BPM by factor (e.g. 0.5 for half time, 2.0 for double time)."""
        new_bpm = self.tempo.bpm * float(factor)
        self.set_bpm(new_bpm)
        return self.tempo.bpm

    # =========================================================================
    # Helpers
    # =========================================================================

    def _resolve_key(self, name_or_index: Union[str, int]) -> str:
        keys = list(self._scenes.keys())
        if isinstance(name_or_index, int):
            if not (0 <= name_or_index < len(keys)):
                raise IndexError(f"Scene index {name_or_index} out of range [0..{len(keys)-1}]")
            return keys[name_or_index]
        s = str(name_or_index)
        if s not in self._scenes:
            raise KeyError(f"Scene {s!r} not found in deck. Available: {keys}")
        return s

    # =========================================================================
    # ipywidgets GUI Builder
    # =========================================================================

    def _build_widget(self) -> None:
        """Construct the interactive DJ/VJ controller widget."""
        css_style = widgets.HTML("""
        <style>
        .artnet-deck-container {
            background: #0b0f17;
            border: 1px solid #1e293b;
            border-radius: 12px;
            padding: 16px;
            font-family: system-ui, -apple-system, sans-serif;
            color: #f8fafc;
            width: 100%;
            max-width: 900px;
            box-sizing: border-box;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
            margin: 10px 0;
        }
        .artnet-deck-card {
            background: #111827;
            border: 1px solid #1f2937;
            border-radius: 8px;
            padding: 10px;
            margin: 6px 0;
            box-sizing: border-box;
        }
        .artnet-deck-flex {
            display: flex;
            align-items: center;
        }
        .artnet-deck-title {
            font-size: 15px;
            font-weight: 700;
            letter-spacing: 0.8px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .artnet-deck-badge {
            font-size: 11px;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .badge-live { background: #064e3b; color: #34d399; border: 1px solid #059669; }
        .badge-paused { background: #78350f; color: #fcd34d; border: 1px solid #d97706; }
        .badge-stopped { background: #1e293b; color: #94a3b8; border: 1px solid #475569; }
        .badge-blackout { background: #7f1d1d; color: #fca5a5; border: 1px solid #dc2626; }
        .artnet-deck-label {
            font-size: 11px;
            font-weight: 600;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }
        .artnet-btn-go {
            font-weight: bold !important;
            background: linear-gradient(135deg, #0284c7, #0369a1) !important;
            color: #ffffff !important;
        }
        </style>
        """)

        # 1. Header Banner
        header_html = widgets.HTML(self._render_header_html())
        self._ui_elements["header_html"] = header_html

        # 2. Program (Active) vs Cue (Next) Channels
        scene_names = list(self._scenes.keys())

        active_dropdown = widgets.Dropdown(
            options=scene_names,
            value=self._active_key,
            description="Live:",
            layout=widgets.Layout(width="100%"),
            style={"description_width": "45px"},
        )
        self._ui_elements["active_dropdown"] = active_dropdown

        cue_dropdown = widgets.Dropdown(
            options=scene_names,
            value=self._cue_key,
            description="Cue:",
            layout=widgets.Layout(width="100%"),
            style={"description_width": "45px"},
        )
        self._ui_elements["cue_dropdown"] = cue_dropdown

        prev_btn = widgets.Button(description="⏮ Prev", layout=widgets.Layout(width="80px"))
        next_btn = widgets.Button(description="Next ⏭", layout=widgets.Layout(width="80px"))
        go_btn = widgets.Button(
            description="⇄ FADE / GO",
            layout=widgets.Layout(width="130px"),
            button_style="primary",
        )
        cut_btn = widgets.Button(description="⚡ CUT", layout=widgets.Layout(width="80px"))

        self._ui_elements["prev_btn"] = prev_btn
        self._ui_elements["next_btn"] = next_btn
        self._ui_elements["go_btn"] = go_btn
        self._ui_elements["cut_btn"] = cut_btn

        prog_box = widgets.VBox([
            widgets.HTML('<div class="artnet-deck-label" style="color: #ef4444;">🔴 LIVE PROGRAM</div>'),
            active_dropdown,
            widgets.HBox([prev_btn, next_btn], layout=widgets.Layout(margin="4px 0 0 0")),
        ], layout=widgets.Layout(flex="1", padding="8px", border="1px solid #1f2937"))
        prog_box.add_class("artnet-deck-card")

        cue_box = widgets.VBox([
            widgets.HTML('<div class="artnet-deck-label" style="color: #eab308;">🟡 CUE (NEXT)</div>'),
            cue_dropdown,
            widgets.HBox([go_btn, cut_btn], layout=widgets.Layout(margin="4px 0 0 0")),
        ], layout=widgets.Layout(flex="1", padding="8px", border="1px solid #1f2937"))
        cue_box.add_class("artnet-deck-card")

        channels_row = widgets.HBox([prog_box, cue_box], layout=widgets.Layout(margin="4px 0"))

        # 3. Transport Controls & Master Dimmer
        play_btn = widgets.Button(description="▶ Play", layout=widgets.Layout(width="90px"), button_style="success")
        pause_btn = widgets.Button(description="⏸ Pause", layout=widgets.Layout(width="90px"), button_style="warning")
        stop_btn = widgets.Button(description="⏹ Stop", layout=widgets.Layout(width="80px"))
        blackout_btn = widgets.Button(description="⚡ Blackout", layout=widgets.Layout(width="110px"), button_style="danger")

        self._ui_elements["play_btn"] = play_btn
        self._ui_elements["pause_btn"] = pause_btn
        self._ui_elements["stop_btn"] = stop_btn
        self._ui_elements["blackout_btn"] = blackout_btn

        transport_box = widgets.VBox([
            widgets.HTML('<div class="artnet-deck-label">TRANSPORT</div>'),
            widgets.HBox([play_btn, pause_btn, stop_btn, blackout_btn], layout=widgets.Layout(margin="4px 0")),
        ], layout=widgets.Layout(flex="1"))

        master_slider = widgets.IntSlider(
            value=int(self.master * 100),
            min=0,
            max=100,
            step=1,
            description="Master:",
            continuous_update=True,
            layout=widgets.Layout(width="100%"),
            style={"description_width": "55px"},
        )
        self._ui_elements["master_slider"] = master_slider

        m_100_btn = widgets.Button(description="100%", layout=widgets.Layout(width="50px"))
        m_50_btn = widgets.Button(description="50%", layout=widgets.Layout(width="50px"))
        m_0_btn = widgets.Button(description="0%", layout=widgets.Layout(width="50px"))

        master_box = widgets.VBox([
            widgets.HTML('<div class="artnet-deck-label">GRAND MASTER</div>'),
            master_slider,
            widgets.HBox([m_100_btn, m_50_btn, m_0_btn], layout=widgets.Layout(margin="2px 0")),
        ], layout=widgets.Layout(flex="1"))

        control_row = widgets.HBox([transport_box, master_box], layout=widgets.Layout(
            padding="10px", border="1px solid #1f2937", margin="6px 0"
        ))
        control_row.add_class("artnet-deck-card")

        # 4. Tempo & Transition Timing
        bpm_slider = widgets.FloatSlider(
            value=self.tempo.bpm,
            min=50.0,
            max=220.0,
            step=0.5,
            description="BPM:",
            continuous_update=True,
            layout=widgets.Layout(width="100%"),
            style={"description_width": "45px"},
        )
        self._ui_elements["bpm_slider"] = bpm_slider

        tap_btn = widgets.Button(description="🥁 TAP TEMPO", layout=widgets.Layout(width="130px"), button_style="info")
        half_btn = widgets.Button(description="÷2", layout=widgets.Layout(width="50px"))
        double_btn = widgets.Button(description="×2", layout=widgets.Layout(width="50px"))

        self._ui_elements["tap_btn"] = tap_btn

        fade_time_slider = widgets.FloatSlider(
            value=self.transition_time,
            min=0.0,
            max=5.0,
            step=0.1,
            description="Fade (s):",
            continuous_update=True,
            layout=widgets.Layout(width="100%"),
            style={"description_width": "65px"},
        )
        self._ui_elements["fade_time_slider"] = fade_time_slider

        tempo_box = widgets.VBox([
            widgets.HTML('<div class="artnet-deck-label">TEMPO / BPM SYNC</div>'),
            bpm_slider,
            widgets.HBox([tap_btn, half_btn, double_btn], layout=widgets.Layout(margin="4px 0")),
        ], layout=widgets.Layout(flex="1"))

        transition_box = widgets.VBox([
            widgets.HTML('<div class="artnet-deck-label">TRANSITION TIME</div>'),
            fade_time_slider,
            widgets.HTML('<div style="font-size: 11px; color: #64748b; margin-top: 4px;">Smooth crossfade active duration</div>'),
        ], layout=widgets.Layout(flex="1"))

        tempo_row = widgets.HBox([tempo_box, transition_box], layout=widgets.Layout(
            padding="10px", border="1px solid #1f2937", margin="6px 0"
        ))
        tempo_row.add_class("artnet-deck-card")

        # 5. Status / Telemetry Output
        telemetry_html = widgets.HTML(self._render_telemetry_html())
        self._ui_elements["telemetry_html"] = telemetry_html

        # Connect Callbacks
        def _on_active_change(change):
            if change["name"] == "value" and change["new"] in self._scenes:
                self.select(change["new"])

        def _on_cue_change(change):
            if change["name"] == "value" and change["new"] in self._scenes:
                self.cue(change["new"])

        def _on_bpm_change(change):
            if change["name"] == "value":
                self.set_bpm(change["new"])

        def _on_fade_change(change):
            if change["name"] == "value":
                self.transition_time = float(change["new"])

        def _on_master_change(change):
            if change["name"] == "value":
                self.set_master(change["new"] / 100.0)

        active_dropdown.observe(_on_active_change, names="value")
        cue_dropdown.observe(_on_cue_change, names="value")
        bpm_slider.observe(_on_bpm_change, names="value")
        fade_time_slider.observe(_on_fade_change, names="value")
        master_slider.observe(_on_master_change, names="value")

        play_btn.on_click(lambda b: self.play())
        pause_btn.on_click(lambda b: self.pause())
        stop_btn.on_click(lambda b: self.stop())
        blackout_btn.on_click(lambda b: self.toggle_blackout())

        prev_btn.on_click(lambda b: self.prev())
        next_btn.on_click(lambda b: self.next())
        go_btn.on_click(lambda b: self.go())
        cut_btn.on_click(lambda b: self.cut())

        tap_btn.on_click(lambda b: self.tap())
        half_btn.on_click(lambda b: self.multiply_bpm(0.5))
        double_btn.on_click(lambda b: self.multiply_bpm(2.0))

        m_100_btn.on_click(lambda b: self.set_master(1.0))
        m_50_btn.on_click(lambda b: self.set_master(0.5))
        m_0_btn.on_click(lambda b: self.set_master(0.0))

        # Assemble top-level container
        self._widget = widgets.VBox([
            css_style,
            header_html,
            channels_row,
            control_row,
            tempo_row,
            telemetry_html,
        ], layout=widgets.Layout(width="100%"))
        self._widget.add_class("artnet-deck-container")

    def _sync_ui(self) -> None:
        """Synchronize UI widget properties with internal state."""
        if self._widget is None or not self._ui_elements:
            return

        elems = self._ui_elements
        # Header & Telemetry
        if "header_html" in elems:
            elems["header_html"].value = self._render_header_html()
        if "telemetry_html" in elems:
            elems["telemetry_html"].value = self._render_telemetry_html()

        # Dropdowns
        if "active_dropdown" in elems and elems["active_dropdown"].value != self._active_key:
            elems["active_dropdown"].value = self._active_key
        if "cue_dropdown" in elems and elems["cue_dropdown"].value != self._cue_key:
            elems["cue_dropdown"].value = self._cue_key

        # Sliders
        if "bpm_slider" in elems and abs(elems["bpm_slider"].value - self.tempo.bpm) > 0.1:
            elems["bpm_slider"].value = round(self.tempo.bpm, 1)
        if "master_slider" in elems:
            val = int(round(self.master * 100))
            if elems["master_slider"].value != val:
                elems["master_slider"].value = val

        # Blackout button visual styling
        if "blackout_btn" in elems:
            if self.is_blackout:
                elems["blackout_btn"].description = "⚡ BLACKOUT ON"
                elems["blackout_btn"].button_style = "danger"
            else:
                elems["blackout_btn"].description = "⚡ Blackout"
                elems["blackout_btn"].button_style = ""

    def _render_header_html(self) -> str:
        """Render the status header HTML snippet."""
        if self.is_blackout:
            badge = '<span class="artnet-deck-badge badge-blackout">⚡ BLACKOUT</span>'
        elif self.is_playing:
            badge = f'<span class="artnet-deck-badge badge-live">● LIVE ({self.fps:g} Hz)</span>'
        elif self.is_paused:
            badge = '<span class="artnet-deck-badge badge-paused">⏸ PAUSED</span>'
        else:
            badge = '<span class="artnet-deck-badge badge-stopped">■ STOPPED</span>'

        host = self.rig.client.host
        univ = self.rig.client.universe
        dur_str = f"{self.current_scene.duration:.2f}s" if not math.isinf(self.current_scene.duration) else "∞ (loop)"

        return f"""
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; border-bottom: 1px solid #1e293b; padding-bottom: 10px;">
            <div style="display: flex; align-items: center; gap: 10px;">
                <span style="font-size: 20px;">🎛️</span>
                <span class="artnet-deck-title">ARTNET CONTROL DECK</span>
                {badge}
            </div>
            <div style="display: flex; align-items: center; gap: 14px; font-size: 12px; color: #94a3b8; font-family: monospace;">
                <span>{host} (Univ {univ})</span>
                <span style="color: #38bdf8; font-weight: 600;">{self.tempo.bpm:g} BPM</span>
            </div>
        </div>
        """

    def _render_telemetry_html(self) -> str:
        """Render the telemetry status panel HTML snippet."""
        beat_dur = 60.0 / self.tempo.bpm
        bar_dur = beat_dur * 4.0
        packets = getattr(self.streamer, "_packets_sent", 0)

        trans_status = "Idle"
        if getattr(self.streamer, "_transition_active", False):
            trans_status = f'<span style="color: #38bdf8; font-weight: bold;">Crossfading ({self.transition_time:.1f}s)...</span>'

        return f"""
        <div style="display: flex; align-items: center; justify-content: space-between; font-size: 11px; color: #64748b; font-family: monospace; padding-top: 6px;">
            <div>
                <strong>Active:</strong> <span style="color: #f1f5f9;">{html.escape(self.current_scene_name)}</span> &nbsp;|&nbsp;
                <strong>Cue:</strong> <span style="color: #fcd34d;">{html.escape(self.cue_scene_name)}</span> &nbsp;|&nbsp;
                <strong>Trans:</strong> {trans_status}
            </div>
            <div>
                1 Beat = {beat_dur:.3f}s &nbsp;|&nbsp; Packets Sent: {packets:,}
            </div>
        </div>
        """

    # =========================================================================
    # Jupyter Display Hooks
    # =========================================================================

    def show(self) -> Any:
        """Display the interactive control deck widget in the notebook."""
        if self._widget is not None:
            return self._widget
        from IPython.display import HTML, display
        display(HTML(self._repr_html_()))
        return self

    def _ipython_display_(self) -> None:
        """Automatic rich display when evaluated in a Jupyter notebook cell."""
        if self._widget is not None:
            from IPython.display import display
            display(self._widget)
        else:
            from IPython.display import HTML, display
            display(HTML(self._repr_html_()))

    def _repr_html_(self) -> str:
        """Fallback HTML representation if ipywidgets is unavailable."""
        scene_rows = "".join(
            f"<tr><td style='padding: 4px 8px; color: {'#34d399' if k == self._active_key else '#e2e8f0'};'>{'▶ ' if k == self._active_key else ''}{html.escape(k)}</td>"
            f"<td style='padding: 4px 8px; color: #94a3b8;'>{s.duration:.2f}s" if not math.isinf(s.duration) else "<td style='padding: 4px 8px; color: #94a3b8;'>∞ (loop)</td></tr>"
            for k, s in self._scenes.items()
        )
        status_text = "STREAMING" if self.is_playing else ("PAUSED" if self.is_paused else "STOPPED")
        status_color = "#22c55e" if self.is_playing else ("#eab308" if self.is_paused else "#64748b")

        return f"""
        <div style="font-family: system-ui, sans-serif; background: #0b0f17; border: 1px solid #1e293b; border-radius: 8px; padding: 14px; max-width: 600px; color: #f8fafc; margin: 8px 0;">
            <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #1e293b; padding-bottom: 8px; margin-bottom: 8px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="width: 10px; height: 10px; border-radius: 50%; background: {status_color}; display: inline-block;"></span>
                    <strong style="font-size: 13px;">CONTROL DECK: {status_text}</strong>
                </div>
                <span style="font-size: 12px; color: #38bdf8; font-weight: 600;">{self.tempo.bpm:g} BPM</span>
            </div>
            <table style="width: 100%; font-size: 12px; border-collapse: collapse; margin: 8px 0;">
                <thead>
                    <tr style="border-bottom: 1px solid #334155; text-align: left; color: #94a3b8;">
                        <th style="padding: 4px 8px;">Scene Name</th>
                        <th style="padding: 4px 8px;">Duration</th>
                    </tr>
                </thead>
                <tbody>
                    {scene_rows}
                </tbody>
            </table>
            <div style="font-size: 11px; color: #94a3b8; margin-top: 6px;">
                Programmatic control: <code>deck.play()</code>, <code>deck.next()</code>, <code>deck.go()</code>, <code>deck.set_bpm({self.tempo.bpm:g})</code>.
            </div>
        </div>
        """
