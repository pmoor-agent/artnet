"""Composable DMX channel primitives (`RGB` and `Channel`), `FixtureGroup`s, and `Scene`s.

At the core, the engine only understands two hardware primitives:
  1. `RGB(dmx_channel)`     : 3 contiguous DMX channels (R, G, B)
  2. `Channel(dmx_channel)` : 1 single DMX channel (with optional `default` and `dmx_range`)

Calling a `FixtureGroup` with a `Clip`—e.g. `PARS(clip)` or `ALL_RGB(clip)`—produces a
composable `Scene` supporting the same operators as `Clip`:
  - `scene1 | scene2`  : Override (LTP) on overlapping DMX channels
  - `scene1 + scene2`  : Additive blend (`min(1.0, a + b)`) on overlapping DMX channels
  - `scene1 ^ scene2`  : HTP (`max(a, b)`) on overlapping DMX channels
  - `Sequence([s1, s2])` : Play `s1` followed by `s2`
  - `scene * n`        : Loop `scene` `n` times (or `* inf`)
  - `scene @ duration` : Time-stretch `scene` to `duration` seconds
  - `~scene`           : Time-reverse a finite `scene`
  - `dim(factor, scene)` : Scale all active channels in `scene` by `factor`
"""

from __future__ import annotations
from dataclasses import dataclass
import math
from math import inf
from typing import Callable, Mapping, Optional, Sequence, Union

from .clips import Clip
from .state import Color, Patch


def _to_dmx_byte(val: float, dmx_range: tuple[int, int] = (0, 255), zero_off: bool = False) -> int:
    """Map normalized float [0.0, 1.0] to a DMX byte in `dmx_range`."""
    low, high = dmx_range
    if (zero_off or low > 0) and val <= 0.0:
        return 0
    clamped = max(0.0, min(1.0, val))
    span = high - low
    byte = int(round(low + clamped * span))
    return max(low, min(high, byte))


@dataclass(frozen=True)
class Channel:
    """A single DMX channel primitive (1 byte).

    Args:
        address: 1-based DMX channel number (1..512).
        default: Default normalized value [0.0..1.0] when no clip sets this channel
            (e.g. `default=1.0` for a master dimmer channel so RGB works out of the box).
        dmx_range: Tuple of `(min_dmx, max_dmx)` when active. For example, `dmx_range=(11, 255)`
            maps `0.0` to `0` (off) and `(0.0..1.0]` to `11..255`.
    """
    address: int
    default: float = 0.0
    dmx_range: tuple[int, int] = (0, 255)

    @property
    def max_channel(self) -> int:
        return self.address

    def write(self, dmx: list[int], val: float) -> None:
        dmx[self.address - 1] = _to_dmx_byte(val, self.dmx_range)


@dataclass(frozen=True)
class RGB:
    """A 3-channel RGB color primitive occupying `address`, `address+1`, `address+2`."""
    address: int
    default: Color = Color.BLACK

    @property
    def max_channel(self) -> int:
        return self.address + 2

    def write(self, dmx: list[int], color: Color) -> None:
        idx = self.address - 1
        dmx[idx] = _to_dmx_byte(color.r)
        dmx[idx + 1] = _to_dmx_byte(color.g)
        dmx[idx + 2] = _to_dmx_byte(color.b)


PrimitiveSpec = Union[Channel, RGB]
ElementPatch = Mapping[str, PrimitiveSpec]


def _normalize_element(spec: Union[PrimitiveSpec, ElementPatch]) -> dict[str, PrimitiveSpec]:
    """Normalize a single `Channel`, `RGB`, or attribute dict into `{attr_name: PrimitiveSpec}`."""
    if isinstance(spec, RGB):
        return {"color": spec}
    if isinstance(spec, Channel):
        return {"value": spec}
    return dict(spec)


def _format_slice(s: slice) -> str:
    """Format a slice object like `[0:8]`, `[:4]`, or `[::2]`."""
    start = "" if s.start is None else str(s.start)
    stop = "" if s.stop is None else str(s.stop)
    if s.step is not None:
        return f"[{start}:{stop}:{s.step}]"
    return f"[{start}:{stop}]"


# =============================================================================
# Sparse DMX Frame Representation for Composable Scenes
# =============================================================================


@dataclass
class DMXCanvas:
    """Sparse normalized float [0.0, 1.0] DMX channel map before byte quantization.

    Maps 1-based DMX channel address -> `(normalized_value, dmx_range)`.
    """
    values: dict[int, float]
    ranges: dict[int, tuple[int, int]]
    defaults: dict[int, tuple[float, tuple[int, int]]]

    def __init__(self) -> None:
        self.values = {}
        self.ranges = {}
        self.defaults = {}

    def register_default(self, address: int, default_val: float, dmx_range: tuple[int, int] = (0, 255)) -> None:
        if address not in self.defaults or default_val > 0.0:
            self.defaults[address] = (default_val, dmx_range)

    def set_channel(self, address: int, val: float, dmx_range: tuple[int, int] = (0, 255)) -> None:
        self.values[address] = max(0.0, min(1.0, val))
        self.ranges[address] = dmx_range

    def merge(self, other: DMXCanvas, mode: str = "override") -> DMXCanvas:
        """Combine two `DMXCanvas` instances using `'override'` (`|`), `'add'` (`+`), or `'htp'` (`^`)."""
        out = DMXCanvas()
        out.defaults.update(self.defaults)
        out.defaults.update(other.defaults)

        out.values.update(self.values)
        out.ranges.update(self.ranges)

        for addr, val in other.values.items():
            rng = other.ranges.get(addr, (0, 255))
            if addr not in out.values or mode == "override":
                out.values[addr] = val
                out.ranges[addr] = rng
            elif mode == "add":
                out.values[addr] = min(1.0, out.values[addr] + val)
                out.ranges[addr] = rng
            elif mode == "htp":
                out.values[addr] = max(out.values[addr], val)
                out.ranges[addr] = rng
            else:
                raise ValueError(f"Unknown merge mode: {mode}")
        return out

    def scale(self, factor: float) -> DMXCanvas:
        out = DMXCanvas()
        out.defaults.update(self.defaults)
        out.ranges.update(self.ranges)
        for addr, val in self.values.items():
            out.values[addr] = max(0.0, min(1.0, val * factor))
        return out

    def to_dmx_list(self, min_size: int = 24) -> list[int]:
        max_addr = max(
            [min_size]
            + list(self.values.keys())
            + list(self.defaults.keys())
        )
        dmx = [0] * max_addr
        for addr, (def_val, def_rng) in self.defaults.items():
            dmx[addr - 1] = _to_dmx_byte(def_val, def_rng)
        for addr, val in self.values.items():
            rng = self.ranges.get(addr, (0, 255))
            dmx[addr - 1] = _to_dmx_byte(val, rng)
        return dmx


# =============================================================================
# FixtureGroup
# =============================================================================


class FixtureGroup:
    """A logical array of fixtures, where each fixture element is a composition of `RGB` and/or `Channel`s.

    Calling `group(clip)` binds `clip` to this `FixtureGroup` and returns a composable `Scene`.
    """

    def __init__(
        self,
        name: str,
        elements: Sequence[Union[PrimitiveSpec, ElementPatch]],
        labels: Optional[Sequence[str]] = None,
    ) -> None:
        if not elements:
            raise ValueError("FixtureGroup requires at least one element.")
        self.name = name
        self.elements: tuple[dict[str, PrimitiveSpec], ...] = tuple(
            _normalize_element(e) for e in elements
        )
        if labels is not None:
            if len(labels) != len(self.elements):
                raise ValueError(
                    f"Length of labels ({len(labels)}) must match elements ({len(self.elements)})"
                )
            self.labels: tuple[str, ...] = tuple(labels)
        else:
            if len(self.elements) == 1:
                self.labels = (name,)
            else:
                self.labels = tuple(f"{name}[{i}]" for i in range(len(self.elements)))

    def label(self, index: int) -> str:
        """Return the display label for element at `index`."""
        if 0 <= index < len(self.labels):
            return self.labels[index]
        return f"{self.name}[{index}]"

    def __repr__(self) -> str:
        return f"<FixtureGroup {self.name!r} ({self.count} fixtures)>"

    def __str__(self) -> str:
        return self.name

    def __call__(self, clip: Union[Clip, Sequence[Clip]]) -> BoundScene:
        """Bind `clip` (or a sequence/list of clips) to this `FixtureGroup`, returning an algebraically composable `Scene`!

        Example:
            `ALL_RGB(Rainbow()) + PAR_RGB(Pulse(Color.RED))`
            `PARS([Fade(Color.BLUE, Color.MAGENTA), Pulse(Color.CYAN)])`
        """
        if isinstance(clip, (list, tuple)):
            from .clips import SequenceClip
            clip = SequenceClip(*clip)
        adapted_clip = clip.with_fixture_count(self.count)
        return BoundScene(self, adapted_clip)

    @classmethod
    def from_template(
        cls,
        name: str,
        template: Callable[[int], Union[PrimitiveSpec, ElementPatch]],
        start_channels: Sequence[int],
    ) -> FixtureGroup:
        """Build a FixtureGroup by applying a user template function to each start channel."""
        return cls(name=name, elements=[template(ch) for ch in start_channels])

    @classmethod
    def contiguous(
        cls,
        name: str,
        profile: object,
        start_channel: int,
        count: int,
    ) -> FixtureGroup:
        """Helper for creating contiguous 1-channel or 3-channel groups."""
        raise NotImplementedError("Use FixtureGroup(name, [Channel(...)]) or [RGB(...)] directly.")

    def select(self, *attrs: str, name: Optional[str] = None) -> FixtureGroup:
        """Extract a subset of attributes (e.g. `.select('w')` or `.select('color')`) as a new FixtureGroup view."""
        if not attrs:
            raise ValueError("Must specify at least one attribute name to select.")
        attr_suffix = ",".join(attrs)
        sub_label = name or f"{self.name}.{attr_suffix}"
        if len(attrs) == 1:
            attr = attrs[0]
            single_prim_list: list[Union[PrimitiveSpec, ElementPatch]] = []
            for el in self.elements:
                if attr not in el:
                    raise KeyError(f"Attribute {attr!r} not found in fixture group {self.name!r}")
                prim = el[attr]
                if isinstance(prim, RGB):
                    single_prim_list.append({"color": prim})
                else:
                    single_prim_list.append({attr: prim, "value": prim})
            new_labels = tuple(f"{l}.{attr}" for l in self.labels) if name is None else None
            return FixtureGroup(name=sub_label, elements=single_prim_list, labels=new_labels)

        multi_list: list[ElementPatch] = []
        for el in self.elements:
            sub = {a: el[a] for a in attrs if a in el}
            multi_list.append(sub)
        new_labels = tuple(f"{l}.{attr_suffix}" for l in self.labels) if name is None else None
        return FixtureGroup(name=sub_label, elements=multi_list, labels=new_labels)

    def named(self, name: str) -> FixtureGroup:
        """Return a copy of this FixtureGroup with a custom display name."""
        return FixtureGroup(name=name, elements=self.elements)

    def __add__(self, other: FixtureGroup) -> FixtureGroup:
        """`group1 + group2`: Concatenate two FixtureGroups into a combined group."""
        if not isinstance(other, FixtureGroup):
            return NotImplemented
        return FixtureGroup(
            name=f"{self.name}+{other.name}",
            elements=self.elements + other.elements,
            labels=self.labels + other.labels,
        )

    def __getitem__(self, item: Union[int, slice]) -> FixtureGroup:
        """Slice or index a FixtureGroup (e.g. `PARS[0:8]`, `PARS[8:16]`, `PARS[3]`)."""
        if isinstance(item, int):
            idx = item if item >= 0 else len(self.elements) + item
            lbl = self.labels[idx] if 0 <= idx < len(self.labels) else f"{self.name}[{item}]"
            return FixtureGroup(
                name=f"{self.name}[{item}]",
                elements=[self.elements[item]],
                labels=(lbl,),
            )
        if isinstance(item, slice):
            sliced = self.elements[item]
            sliced_labels = self.labels[item]
            return FixtureGroup(
                name=f"{self.name}{_format_slice(item)}",
                elements=sliced,
                labels=sliced_labels,
            )
        raise TypeError(f"Invalid index type: {type(item)}")

    def __len__(self) -> int:
        return len(self.elements)

    @property
    def count(self) -> int:
        return len(self.elements)

    @property
    def max_channel(self) -> int:
        return max(
            prim.max_channel
            for el in self.elements
            for prim in el.values()
        )

    def write_defaults(self, dmx: list[int]) -> None:
        """Write each primitive's default value into `dmx`."""
        for el in self.elements:
            for prim in el.values():
                if isinstance(prim, RGB):
                    prim.write(dmx, prim.default)
                elif isinstance(prim, Channel):
                    prim.write(dmx, prim.default)

    def register_canvas_defaults(self, canvas: DMXCanvas) -> None:
        """Register each primitive's default value into a `DMXCanvas`."""
        for el in self.elements:
            for prim in el.values():
                if isinstance(prim, RGB):
                    canvas.register_default(prim.address, prim.default.r)
                    canvas.register_default(prim.address + 1, prim.default.g)
                    canvas.register_default(prim.address + 2, prim.default.b)
                elif isinstance(prim, Channel):
                    canvas.register_default(prim.address, prim.default, prim.dmx_range)

    def render_patches(self, clip: Clip, t: float) -> list[Patch]:
        """Evaluate `clip` at time `t` across all fixture elements in this group."""
        return [
            clip.eval(t, fixture=i, total_fixtures=self.count)
            for i in range(self.count)
        ]

    def write_canvas(self, canvas: DMXCanvas, clip: Clip, t: float) -> None:
        """Evaluate `clip` at time `t` and write active normalized values into `canvas`."""
        self.register_canvas_defaults(canvas)
        patches = self.render_patches(clip, t)
        for el, patch in zip(self.elements, patches):
            for attr, prim in el.items():
                if isinstance(prim, RGB):
                    if patch.color is not None:
                        canvas.set_channel(prim.address, patch.color.r)
                        canvas.set_channel(prim.address + 1, patch.color.g)
                        canvas.set_channel(prim.address + 2, patch.color.b)
                elif isinstance(prim, Channel):
                    val: Optional[float] = None
                    if attr in patch.channels:
                        val = patch.channels[attr]
                    elif "value" in patch.channels and (len(el) == 1 or "value" in el):
                        val = patch.channels["value"]
                    elif (attr == "value" or len(el) == 1) and patch.color is not None:
                        val = patch.color.max_component
                    if val is not None:
                        canvas.set_channel(prim.address, val, prim.dmx_range)

    def write_dmx(self, dmx: list[int], clip: Clip, t: float) -> None:
        """Evaluate `clip` at time `t` and write all mapped primitives into `dmx`."""
        patches = self.render_patches(clip, t)
        for el, patch in zip(self.elements, patches):
            for attr, prim in el.items():
                if isinstance(prim, RGB):
                    if patch.color is not None:
                        prim.write(dmx, patch.color)
                elif isinstance(prim, Channel):
                    val: Optional[float] = None
                    if attr in patch.channels:
                        val = patch.channels[attr]
                    elif "value" in patch.channels and (len(el) == 1 or "value" in el):
                        val = patch.channels["value"]
                    elif (attr == "value" or len(el) == 1) and patch.color is not None:
                        val = patch.color.max_component
                    if val is not None:
                        prim.write(dmx, val)

    def preview_from_dmx(self, dmx: Sequence[int]) -> str:
        """Render a 24-bit ANSI terminal preview of this FixtureGroup directly from a DMX frame!"""
        blocks: list[str] = []
        for el in self.elements:
            has_rgb = any(isinstance(p, RGB) for p in el.values())
            if not has_rgb:
                # Monochrome channel group
                b_val = 0
                is_strobe = any("strobe" in attr for attr in el)
                for prim in el.values():
                    if isinstance(prim, Channel) and prim.address - 1 < len(dmx):
                        b_val = dmx[prim.address - 1]
                        break
                if is_strobe and b_val > 0:
                    blocks.append(f"\033[48;2;{b_val};{b_val};{b_val}m⚡\033[0m")
                else:
                    blocks.append(f"\033[48;2;{b_val};{b_val};{b_val}m \033[0m")
            else:
                r_b, g_b, b_b = 0, 0, 0
                w_b = 0
                dim_b = 255
                strobe_b = 0
                for attr, prim in el.items():
                    if isinstance(prim, RGB) and prim.address + 1 < len(dmx):
                        idx = prim.address - 1
                        r_b, g_b, b_b = dmx[idx], dmx[idx + 1], dmx[idx + 2]
                    elif isinstance(prim, Channel) and prim.address - 1 < len(dmx):
                        val_b = dmx[prim.address - 1]
                        if attr in ("w", "cw", "ww"):
                            w_b = max(w_b, val_b)
                        elif attr == "dimmer":
                            dim_b = val_b
                        elif attr == "strobe":
                            strobe_b = val_b
                scale = dim_b / 255.0
                r_out = min(255, int((r_b + w_b * 0.85) * scale))
                g_out = min(255, int((g_b + w_b * 0.85) * scale))
                b_out = min(255, int((b_b + w_b * 0.85) * scale))
                if "strobe" in el:
                    ind = "⚡" if strobe_b > 0 else " "
                    blocks.append(f"\033[48;2;{r_out};{g_out};{b_out}m {ind}\033[0m")
                else:
                    blocks.append(f"\033[48;2;{r_out};{g_out};{b_out}m \033[0m")
        return f"{self.name}:[{''.join(blocks)}]"

    def preview_str(self, clip: Clip, t: float) -> str:
        """Render a compact 24-bit ANSI terminal visualization of this group at time `t`."""
        dmx = [0] * self.max_channel
        self.write_defaults(dmx)
        self.write_dmx(dmx, clip, t)
        return self.preview_from_dmx(dmx)


# =============================================================================
# Composable Multi-Group Scenes (`GROUP(clip)`)
# =============================================================================


class Scene:
    """Base class for algebraically composable multi-fixture scenes."""

    _duration: Union[float, Any] = 0.0

    @property
    def duration(self) -> float:
        """Total duration of the scene in seconds (evaluates dynamically for musical clips)."""
        return float(self._duration)

    @duration.setter
    def duration(self, value: Any) -> None:
        self._duration = value

    @property
    def duration_beats(self) -> Optional[float]:
        """Duration in musical beats if bound to a tempo, else None."""
        if hasattr(self._duration, "beats"):
            return float(self._duration.beats)
        return None

    def eval_canvas(self, t: float) -> DMXCanvas:
        raise NotImplementedError

    def groups(self) -> list[FixtureGroup]:
        raise NotImplementedError

    def __or__(self, other: Scene) -> LayerScene:
        """`scene1 | scene2`: Parallel override (LTP) on overlapping DMX channels."""
        return LayerScene(self, other, mode="override")

    def __add__(self, other: Scene) -> LayerScene:
        """`scene1 + scene2`: Parallel additive blend (`min(1.0, a + b)`) on overlapping DMX channels."""
        return LayerScene(self, other, mode="add")

    def __xor__(self, other: Scene) -> LayerScene:
        """`scene1 ^ scene2`: Parallel HTP (`max(a, b)`) on overlapping DMX channels."""
        return LayerScene(self, other, mode="htp")

    def __mul__(self, count: Union[int, float, Any]) -> RepeatScene:
        """`scene * n`: Loop `scene` `n` times (or `scene * inf`, or `bars(n)`)."""
        if hasattr(count, "seconds"):
            return RepeatScene(self, count=count)
        if count == inf or count == float("inf"):
            return RepeatScene(self, count=inf)
        if isinstance(count, int) or (isinstance(count, float) and count.is_integer()):
            return RepeatScene(self, count=int(count))
        raise ValueError("Use integer or `inf` with `*` for repeating, or `dim(factor, scene)` for brightness.")

    def __rmul__(self, count: Union[int, float]) -> RepeatScene:
        return self.__mul__(count)

    def __matmul__(self, target_duration: float) -> TimeScaleScene:
        """`scene @ duration`: Stretch or compress a finite scene to `target_duration` seconds."""
        return TimeScaleScene(self, target_duration)

    def __invert__(self) -> ReverseScene:
        """`~scene`: Play a finite scene backwards in time."""
        return ReverseScene(self)

    def __getitem__(self, item: slice) -> SliceScene:
        """`scene[start:stop]`: Cut a time window from this scene."""
        if not isinstance(item, slice):
            raise TypeError(f"Scene slicing expects a slice like scene[start:stop], got {type(item).__name__}")
        return SliceScene(self, start=item.start, stop=item.stop, step=item.step)

    def cut(self, start: float = 0.0, stop: Optional[float] = None) -> SliceScene:
        """Cut a time window [start, stop] from this scene."""
        return SliceScene(self, start=start, stop=stop)

    def slice(self, start: float = 0.0, stop: Optional[float] = None) -> SliceScene:
        """Alias for .cut()."""
        return self.cut(start, stop)

    def dim(self, factor: float) -> ScaleScene:
        """Scale all active channel values in this scene by `factor`."""
        return ScaleScene(self, factor)

    def scale(self, factor: float) -> ScaleScene:
        return ScaleScene(self, factor)

    def flicker(
        self,
        depth: float = 0.5,
        speed: float = 12.0,
        *,
        low: Optional[float] = None,
        high: float = 1.0,
        octaves: int = 3,
        seed: int = 101,
        decorrelate: float = 13.37,
    ) -> Scene:
        """Modulate all fixture groups in this scene with organic flicker."""
        raise NotImplementedError

    def jitter_hue(
        self,
        amount: float = 0.08,
        speed: float = 3.0,
        *,
        octaves: int = 2,
        seed: int = 202,
        decorrelate: float = 11.23,
    ) -> Scene:
        """Smoothly jitter the hue of all RGB fixtures in this scene with organic noise."""
        raise NotImplementedError

    def shift_hsv(
        self,
        dh: Union[float, Clip] = 0.0,
        ds: float = 0.0,
        dv: float = 0.0,
        *,
        dimmer_scale: float = 1.0,
    ) -> Scene:
        """Relative HSV shift for all RGB fixtures in this scene."""
        raise NotImplementedError


class BoundScene(Scene):
    """A `Clip` bound to a specific `FixtureGroup` (`group(clip)`)."""

    def __init__(self, group: FixtureGroup, clip: Clip) -> None:
        self.group = group
        self.clip = clip

    @property
    def duration(self) -> float:
        return self.clip.duration

    def eval_canvas(self, t: float) -> DMXCanvas:
        canvas = DMXCanvas()
        if t <= self.duration:
            self.group.write_canvas(canvas, self.clip, t)
        else:
            self.group.register_canvas_defaults(canvas)
        return canvas

    def groups(self) -> list[FixtureGroup]:
        return [self.group]

    def flicker(
        self,
        depth: float = 0.5,
        speed: float = 12.0,
        *,
        low: Optional[float] = None,
        high: float = 1.0,
        octaves: int = 3,
        seed: int = 101,
        decorrelate: float = 13.37,
    ) -> Scene:
        return BoundScene(
            self.group,
            self.clip.flicker(
                depth=depth,
                speed=speed,
                low=low,
                high=high,
                octaves=octaves,
                seed=seed,
                decorrelate=decorrelate,
            ),
        )

    def jitter_hue(
        self,
        amount: float = 0.08,
        speed: float = 3.0,
        *,
        octaves: int = 2,
        seed: int = 202,
        decorrelate: float = 11.23,
    ) -> Scene:
        return BoundScene(
            self.group,
            self.clip.jitter_hue(
                amount=amount,
                speed=speed,
                octaves=octaves,
                seed=seed,
                decorrelate=decorrelate,
            ),
        )

    def shift_hsv(
        self,
        dh: Union[float, Clip] = 0.0,
        ds: float = 0.0,
        dv: float = 0.0,
        *,
        dimmer_scale: float = 1.0,
    ) -> Scene:
        return BoundScene(
            self.group,
            self.clip.shift_hsv(
                dh=dh,
                ds=ds,
                dv=dv,
                dimmer_scale=dimmer_scale,
            ),
        )


class LayerScene(Scene):
    """Parallel composition of two `Scene`s (`|`, `+`, or `^`)."""

    def __init__(self, bottom: Scene, top: Scene, mode: str = "override") -> None:
        self.bottom = bottom
        self.top = top
        self.mode = mode

    @property
    def duration(self) -> float:
        if self.bottom.duration == inf or self.top.duration == inf:
            return inf
        return max(self.bottom.duration, self.top.duration)

    def eval_canvas(self, t: float) -> DMXCanvas:
        c_bot = self.bottom.eval_canvas(t)
        c_top = self.top.eval_canvas(t)
        return c_bot.merge(c_top, mode=self.mode)

    def groups(self) -> list[FixtureGroup]:
        seen: dict[tuple, FixtureGroup] = {}
        for g in self.bottom.groups() + self.top.groups():
            sig = (
                g.name,
                tuple(
                    tuple(sorted((a, getattr(p, "address", None)) for a, p in el.items()))
                    for el in g.elements
                ),
            )
            seen.setdefault(sig, g)
        return list(seen.values())

    def flicker(self, depth: float = 0.5, speed: float = 12.0, **kwargs) -> Scene:
        return LayerScene(
            self.bottom.flicker(depth=depth, speed=speed, **kwargs),
            self.top.flicker(depth=depth, speed=speed, **kwargs),
            mode=self.mode,
        )

    def jitter_hue(self, amount: float = 0.08, speed: float = 3.0, **kwargs) -> Scene:
        return LayerScene(
            self.bottom.jitter_hue(amount=amount, speed=speed, **kwargs),
            self.top.jitter_hue(amount=amount, speed=speed, **kwargs),
            mode=self.mode,
        )

    def shift_hsv(self, dh: Union[float, Clip] = 0.0, ds: float = 0.0, dv: float = 0.0, **kwargs) -> Scene:
        return LayerScene(
            self.bottom.shift_hsv(dh=dh, ds=ds, dv=dv, **kwargs),
            self.top.shift_hsv(dh=dh, ds=ds, dv=dv, **kwargs),
            mode=self.mode,
        )


class SequenceScene(Scene):
    """Sequential composition of `Scene`s (`Sequence([s1, s2])` or `[s1, s2]`)."""

    def __init__(self, *scenes: Union[Scene, Sequence[Scene]]) -> None:
        raw: list[Scene] = []
        for s in scenes:
            if isinstance(s, (list, tuple)):
                raw.extend(s)
            else:
                raw.append(s)

        flattened: list[Scene] = []
        for s in raw:
            if isinstance(s, SequenceScene):
                flattened.extend(s.scenes)
            else:
                flattened.append(s)
        self.scenes = flattened

    @property
    def duration(self) -> float:
        return sum(s.duration for s in self.scenes)

    def eval_canvas(self, t: float) -> DMXCanvas:
        if not self.scenes:
            return DMXCanvas()
        elapsed = 0.0
        for i, scene in enumerate(self.scenes):
            if t < elapsed + scene.duration or i == len(self.scenes) - 1:
                local_t = max(0.0, min(scene.duration, t - elapsed))
                return scene.eval_canvas(local_t)
            elapsed += scene.duration
        return self.scenes[-1].eval_canvas(self.scenes[-1].duration)

    def groups(self) -> list[FixtureGroup]:
        seen: dict[tuple, FixtureGroup] = {}
        for s in self.scenes:
            for g in s.groups():
                sig = (
                    g.name,
                    tuple(
                        tuple(sorted((a, getattr(p, "address", None)) for a, p in el.items()))
                        for el in g.elements
                    ),
                )
                seen.setdefault(sig, g)
        return list(seen.values())

    def flicker(self, depth: float = 0.5, speed: float = 12.0, **kwargs) -> Scene:
        return SequenceScene(*(s.flicker(depth=depth, speed=speed, **kwargs) for s in self.scenes))

    def jitter_hue(self, amount: float = 0.08, speed: float = 3.0, **kwargs) -> Scene:
        return SequenceScene(*(s.jitter_hue(amount=amount, speed=speed, **kwargs) for s in self.scenes))

    def shift_hsv(self, dh: Union[float, Clip] = 0.0, ds: float = 0.0, dv: float = 0.0, **kwargs) -> Scene:
        return SequenceScene(*(s.shift_hsv(dh=dh, ds=ds, dv=dv, **kwargs) for s in self.scenes))


class RepeatScene(Scene):
    """Loops a finite `Scene` `count` times (`scene * n` or `scene * inf`)."""

    def __init__(self, child: Scene, count: Union[int, float, Any] = inf) -> None:
        if child.duration <= 0:
            raise ValueError("Cannot repeat a scene with 0 duration.")
        self.child = child
        self.count = count

    @property
    def duration(self) -> float:
        if self.child.duration == inf:
            return inf
        if hasattr(self.count, "seconds"):
            return float(self.count)
        if self.count == inf:
            return inf
        return self.child.duration * float(self.count)

    def eval_canvas(self, t: float) -> DMXCanvas:
        if self.child.duration == inf:
            return self.child.eval_canvas(t)
        if t >= self.duration:
            return self.child.eval_canvas(self.child.duration)
        return self.child.eval_canvas(t % self.child.duration)

    def groups(self) -> list[FixtureGroup]:
        return self.child.groups()

    def flicker(self, depth: float = 0.5, speed: float = 12.0, **kwargs) -> Scene:
        return RepeatScene(self.child.flicker(depth=depth, speed=speed, **kwargs), count=self.count)

    def jitter_hue(self, amount: float = 0.08, speed: float = 3.0, **kwargs) -> Scene:
        return RepeatScene(self.child.jitter_hue(amount=amount, speed=speed, **kwargs), count=self.count)

    def shift_hsv(self, dh: Union[float, Clip] = 0.0, ds: float = 0.0, dv: float = 0.0, **kwargs) -> Scene:
        return RepeatScene(self.child.shift_hsv(dh=dh, ds=ds, dv=dv, **kwargs), count=self.count)


class TimeScaleScene(Scene):
    """Stretches or compresses a finite `Scene` to `target_duration` (`scene @ seconds`)."""

    def __init__(self, child: Scene, target_duration: Union[float, Any]) -> None:
        if child.duration == inf or child.duration <= 0:
            raise ValueError("Can only time-scale finite scenes with positive duration.")
        self.child = child
        self._target_duration = target_duration

    @property
    def duration(self) -> float:
        return float(self._target_duration)

    @property
    def rate(self) -> float:
        dur = self.duration
        return self.child.duration / dur if dur > 0 else 1.0

    def eval_canvas(self, t: float) -> DMXCanvas:
        return self.child.eval_canvas(t * self.rate)

    def groups(self) -> list[FixtureGroup]:
        return self.child.groups()

    def flicker(self, depth: float = 0.5, speed: float = 12.0, **kwargs) -> Scene:
        return TimeScaleScene(self.child.flicker(depth=depth, speed=speed, **kwargs), target_duration=self.duration)

    def jitter_hue(self, amount: float = 0.08, speed: float = 3.0, **kwargs) -> Scene:
        return TimeScaleScene(self.child.jitter_hue(amount=amount, speed=speed, **kwargs), target_duration=self.duration)

    def shift_hsv(self, dh: Union[float, Clip] = 0.0, ds: float = 0.0, dv: float = 0.0, **kwargs) -> Scene:
        return TimeScaleScene(self.child.shift_hsv(dh=dh, ds=ds, dv=dv, **kwargs), target_duration=self.duration)


class ReverseScene(Scene):
    """Reverses time for a finite `Scene` (`~scene`)."""

    def __init__(self, child: Scene) -> None:
        if child.duration == inf:
            raise ValueError("Cannot time-reverse an infinite scene.")
        self.child = child

    @property
    def duration(self) -> float:
        return self.child.duration

    def eval_canvas(self, t: float) -> DMXCanvas:
        local_t = max(0.0, min(self.duration, self.duration - t))
        return self.child.eval_canvas(local_t)

    def groups(self) -> list[FixtureGroup]:
        return self.child.groups()

    def flicker(self, depth: float = 0.5, speed: float = 12.0, **kwargs) -> Scene:
        return ReverseScene(self.child.flicker(depth=depth, speed=speed, **kwargs))

    def jitter_hue(self, amount: float = 0.08, speed: float = 3.0, **kwargs) -> Scene:
        return ReverseScene(self.child.jitter_hue(amount=amount, speed=speed, **kwargs))

    def shift_hsv(self, dh: Union[float, Clip] = 0.0, ds: float = 0.0, dv: float = 0.0, **kwargs) -> Scene:
        return ReverseScene(self.child.shift_hsv(dh=dh, ds=ds, dv=dv, **kwargs))


class SliceScene(Scene):
    """A scene time-sliced to [start, stop] (`scene[start:stop]`)."""

    def __init__(
        self,
        child: Scene,
        start: Optional[float] = 0.0,
        stop: Optional[float] = None,
        step: Optional[float] = None,
    ) -> None:
        self.child = child
        self.start = max(0.0, float(start if start is not None else 0.0))
        self._stop = float(stop) if stop is not None else None
        self.step = float(step if step is not None else 1.0)
        if self.step == 0.0:
            raise ValueError("Slice step cannot be zero.")

    @property
    def stop(self) -> float:
        return self.child.duration if self._stop is None else max(self.start, self._stop)

    @property
    def duration(self) -> float:
        raw_dur = self.stop - self.start
        return raw_dur / abs(self.step) if not math.isinf(raw_dur) else inf

    def eval_canvas(self, t: float) -> DMXCanvas:
        if t < 0.0 or (t > self.duration and not math.isinf(self.duration)):
            return DMXCanvas()
        if self.step > 0:
            local_t = self.start + t * self.step
        else:
            local_t = self.stop + t * self.step
        return self.child.eval_canvas(local_t)

    def groups(self) -> list[FixtureGroup]:
        return self.child.groups()

    def flicker(self, depth: float = 0.5, speed: float = 12.0, **kwargs) -> Scene:
        return SliceScene(self.child.flicker(depth=depth, speed=speed, **kwargs), start=self.start, stop=self.stop, step=self.step)

    def jitter_hue(self, amount: float = 0.08, speed: float = 3.0, **kwargs) -> Scene:
        return SliceScene(self.child.jitter_hue(amount=amount, speed=speed, **kwargs), start=self.start, stop=self.stop, step=self.step)

    def shift_hsv(self, dh: Union[float, Clip] = 0.0, ds: float = 0.0, dv: float = 0.0, **kwargs) -> Scene:
        return SliceScene(self.child.shift_hsv(dh=dh, ds=ds, dv=dv, **kwargs), start=self.start, stop=self.stop, step=self.step)


class ScaleScene(Scene):
    """Scales all active channel values in `child` by `factor` (`dim(factor, scene)`)."""

    def __init__(self, child: Scene, factor: float) -> None:
        self.child = child
        self.factor = factor

    @property
    def duration(self) -> float:
        return self.child.duration

    def eval_canvas(self, t: float) -> DMXCanvas:
        return self.child.eval_canvas(t).scale(self.factor)

    def groups(self) -> list[FixtureGroup]:
        return self.child.groups()

    def flicker(self, depth: float = 0.5, speed: float = 12.0, **kwargs) -> Scene:
        return ScaleScene(self.child.flicker(depth=depth, speed=speed, **kwargs), factor=self.factor)

    def jitter_hue(self, amount: float = 0.08, speed: float = 3.0, **kwargs) -> Scene:
        return ScaleScene(self.child.jitter_hue(amount=amount, speed=speed, **kwargs), factor=self.factor)

    def shift_hsv(self, dh: Union[float, Clip] = 0.0, ds: float = 0.0, dv: float = 0.0, **kwargs) -> Scene:
        return ScaleScene(self.child.shift_hsv(dh=dh, ds=ds, dv=dv, **kwargs), factor=self.factor)


def Sequence(*items: Union[Clip, Scene, Sequence[Union[Clip, Scene]]]) -> Union[Clip, Scene]:
    """Compose clips or scenes sequentially in chronological time.

    Supports both positional arguments and a single list/tuple:
      `Sequence(clip1, clip2, clip3)`
      `Sequence([clip1, clip2, clip3])`
      `Sequence(scene1, scene2, scene3)`
      `Sequence([scene1, scene2, scene3])`
    """
    from .clips import SequenceClip

    raw: list[Union[Clip, Scene]] = []
    for item in items:
        if isinstance(item, (list, tuple)):
            raw.extend(item)
        else:
            raw.append(item)

    if not raw:
        return SequenceClip()

    if isinstance(raw[0], Scene):
        return SequenceScene(*raw)
    return SequenceClip(*raw)


Seq = Sequence
