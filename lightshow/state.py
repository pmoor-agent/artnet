"""Core RGB color and generic channel state representations."""

from __future__ import annotations
from dataclasses import dataclass, field
import colorsys
from typing import Mapping, Optional


@dataclass(frozen=True)
class Color:
    """Represents a 3-channel RGB color with components in [0.0, 1.0]."""
    r: float = 0.0
    g: float = 0.0
    b: float = 0.0

    @classmethod
    def from_hex(cls, hex_str: str) -> Color:
        """Create a Color from a hex string like '#ff00aa' or 'ff00aa'."""
        h = hex_str.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 6:
            r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
            return cls(r, g, b)
        raise ValueError(f"Invalid hex color: {hex_str}")

    @classmethod
    def from_hsv(cls, h: float, s: float = 1.0, v: float = 1.0) -> Color:
        """Create a Color from HSV values in [0.0, 1.0]."""
        r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
        return cls(r, g, b)

    @property
    def max_component(self) -> float:
        """Largest RGB component (useful when routing a Color clip to a single monochrome channel)."""
        return max(self.r, self.g, self.b)

    def lerp(self, other: Color, t: float) -> Color:
        """Linearly interpolate between this color and another color."""
        t = max(0.0, min(1.0, t))
        return Color(
            r=self.r + (other.r - self.r) * t,
            g=self.g + (other.g - self.g) * t,
            b=self.b + (other.b - self.b) * t,
        )

    def to_hsv(self) -> tuple[float, float, float]:
        """Convert sRGB components to (hue [0..1], saturation [0..1], value [0..1])."""
        return colorsys.rgb_to_hsv(self.r, self.g, self.b)

    def shift_hsv(self, dh: float = 0.0, ds: float = 0.0, dv: float = 0.0) -> Color:
        """Adjust color in HSV space (hue wraps around [0..1], saturation and value clamped)."""
        h, s, v = colorsys.rgb_to_hsv(self.r, self.g, self.b)
        new_h = (h + dh) % 1.0
        new_s = max(0.0, min(1.0, s + ds))
        new_v = max(0.0, min(1.0, v + dv))
        r, g, b = colorsys.hsv_to_rgb(new_h, new_s, new_v)
        return Color(r, g, b)

    def __mul__(self, factor: float) -> Color:
        return Color(
            r=max(0.0, min(1.0, self.r * factor)),
            g=max(0.0, min(1.0, self.g * factor)),
            b=max(0.0, min(1.0, self.b * factor)),
        )

    def __rmul__(self, factor: float) -> Color:
        return self.__mul__(factor)

    def __truediv__(self, divisor: float) -> Color:
        """Divide RGB channels by a scalar divisor (e.g. `color / 2`)."""
        if divisor == 0:
            raise ZeroDivisionError("Color division by zero")
        return self.__mul__(1.0 / divisor)

    def dim(self, factor: float) -> Color:
        """Dim/scale brightness by a factor in [0.0, 1.0] (e.g. `color.dim(0.5)`)."""
        return self.__mul__(factor)

    def scale(self, factor: float) -> Color:
        """Scale brightness by `factor` (e.g. `color.scale(0.5)`)."""
        return self.__mul__(factor)

    def __add__(self, other: Color) -> Color:
        return Color(
            r=min(1.0, self.r + other.r),
            g=min(1.0, self.g + other.g),
            b=min(1.0, self.b + other.b),
        )

    def hold(self, duration: float = float("inf")):
        """Turn this static Color into a continuous Hold clip."""
        from .clips import Hold
        return Hold(self, duration=duration)

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
        duration: float = float("inf"),
    ):
        """Create a continuous flickering flame clip from this Color."""
        from .clips import Flicker, Hold
        return Flicker(
            Hold(self, duration=duration),
            depth=depth,
            speed=speed,
            low=low,
            high=high,
            octaves=octaves,
            seed=seed,
            decorrelate=decorrelate,
        )

    def jitter_hue(
        self,
        amount: float = 0.08,
        speed: float = 3.0,
        *,
        octaves: int = 2,
        seed: int = 202,
        decorrelate: float = 11.23,
        duration: float = float("inf"),
    ):
        """Create a continuous organic hue-jitter clip from this Color."""
        from .clips import Hold, HueShift
        return HueShift(
            Hold(self, duration=duration),
            amount=amount,
            speed=speed,
            octaves=octaves,
            seed=seed,
            decorrelate=decorrelate,
        )

    def __or__(self, other):
        from .clips import Clip, Hold
        if isinstance(other, Clip):
            return Hold(self) | other
        return NotImplemented

    def __rshift__(self, other):
        from .clips import Clip, Hold
        if isinstance(other, Clip):
            return Hold(self) >> other
        return NotImplemented

    def __and__(self, other):
        from .clips import Clip, Hold
        if isinstance(other, Clip):
            return Hold(self) & other
        return NotImplemented


# Standard RGB color palette constants
Color.BLACK = Color(0.0, 0.0, 0.0)
Color.RED = Color(1.0, 0.0, 0.0)
Color.GREEN = Color(0.0, 1.0, 0.0)
Color.BLUE = Color(0.0, 0.0, 1.0)
Color.WHITE = Color(1.0, 1.0, 1.0)
Color.WARM_WHITE = Color(1.0, 0.75, 0.45)
Color.CYAN = Color(0.0, 1.0, 1.0)
Color.MAGENTA = Color(1.0, 0.0, 1.0)
Color.YELLOW = Color(1.0, 1.0, 0.0)
Color.AMBER = Color(1.0, 0.4, 0.0)
Color.PURPLE = Color(0.5, 0.0, 1.0)
Color.ORANGE = Color(1.0, 0.25, 0.0)


@dataclass(frozen=True)
class Patch:
    """Partial state for a generic fixture element at a point in time.

    The core engine only models two primitives:
      1. `color`: Optional 3-channel `Color` (for RGB attributes)
      2. `channels`: Mapping of named 1-channel scalar floats in [0.0, 1.0]
         (e.g. 'w', 'dimmer', 'strobe', or 'value' for generic single-channel fixtures).

    Unset fields are transparent when layering clips with `|`.
    """
    color: Optional[Color] = None
    channels: Mapping[str, float] = field(default_factory=dict)
    hsv_offset: Optional[tuple[float, float, float]] = None
    dimmer_scale: float = 1.0

    @classmethod
    def from_color(cls, color: Color, **channels: float) -> Patch:
        return cls(color=color, channels=channels)

    @classmethod
    def from_channel(cls, name: str, value: float) -> Patch:
        return cls(color=None, channels={name: value})

    @classmethod
    def from_hsv_offset(
        cls,
        dh: float = 0.0,
        ds: float = 0.0,
        dv: float = 0.0,
        dimmer_scale: float = 1.0,
    ) -> Patch:
        return cls(color=None, channels={}, hsv_offset=(dh, ds, dv), dimmer_scale=dimmer_scale)

    def get(self, name: str, default: Optional[float] = None) -> Optional[float]:
        """Look up a named scalar channel (falling back to 'value' or `color.max_component` if appropriate)."""
        if name in self.channels:
            return self.channels[name]
        if "value" in self.channels:
            return self.channels["value"]
        return default

    def merge(self, top: Patch) -> Patch:
        """Override this patch's fields with non-None fields from `top` (`a | b`), applying any relative offsets."""
        base_color = top.color if top.color is not None else self.color

        if base_color is not None:
            # If self had pending relative offsets and top supplied the base color:
            if top.color is not None and self.hsv_offset is not None:
                base_color = base_color.shift_hsv(*self.hsv_offset)
            if top.color is not None and self.dimmer_scale != 1.0:
                base_color = base_color * self.dimmer_scale
            # Apply top's relative offsets to the base color:
            if top.hsv_offset is not None:
                base_color = base_color.shift_hsv(*top.hsv_offset)
            if top.dimmer_scale != 1.0:
                base_color = base_color * top.dimmer_scale

        merged_channels = dict(self.channels)
        merged_channels.update(top.channels)

        if top.dimmer_scale != 1.0 and "dimmer" in merged_channels:
            merged_channels["dimmer"] = max(0.0, min(1.0, merged_channels["dimmer"] * top.dimmer_scale))

        # If base_color is still None, accumulate relative offsets from both self and top:
        merged_hsv = None
        merged_dimmer = 1.0
        if base_color is None:
            dh, ds, dv = 0.0, 0.0, 0.0
            has_hsv = False
            if self.hsv_offset is not None:
                has_hsv = True
                dh += self.hsv_offset[0]
                ds += self.hsv_offset[1]
                dv += self.hsv_offset[2]
            if top.hsv_offset is not None:
                has_hsv = True
                dh += top.hsv_offset[0]
                ds += top.hsv_offset[1]
                dv += top.hsv_offset[2]
            if has_hsv:
                merged_hsv = (dh, ds, dv)
            merged_dimmer = self.dimmer_scale * top.dimmer_scale

        return Patch(
            color=base_color,
            channels=merged_channels,
            hsv_offset=merged_hsv,
            dimmer_scale=merged_dimmer,
        )

    def add(self, other: Patch) -> Patch:
        """Additively blend RGB colors and scalar channels (`a + b`)."""
        if self.color is None:
            new_color = other.color
        elif other.color is None:
            new_color = self.color
        else:
            new_color = self.color + other.color

        merged_channels = dict(self.channels)
        for k, v in other.channels.items():
            if k in merged_channels:
                merged_channels[k] = min(1.0, merged_channels[k] + v)
            else:
                merged_channels[k] = v
        return Patch(color=new_color, channels=merged_channels)

    def htp(self, other: Patch) -> Patch:
        """Highest-Takes-Precedence (`max`) blend for RGB colors and scalar channels."""
        if self.color is None:
            new_color = other.color
        elif other.color is None:
            new_color = self.color
        else:
            new_color = Color(
                r=max(self.color.r, other.color.r),
                g=max(self.color.g, other.color.g),
                b=max(self.color.b, other.color.b),
            )

        merged_channels = dict(self.channels)
        for k, v in other.channels.items():
            if k in merged_channels:
                merged_channels[k] = max(merged_channels[k], v)
            else:
                merged_channels[k] = v
        return Patch(color=new_color, channels=merged_channels)

    def multiply(self, other: Patch) -> Patch:
        """Multiplicative modulation (`a & b`):

        - If one patch has a `color` and the other has a scalar `'value'` (like `Pulse(1.0)`),
          scales the `color` by that scalar envelope!
        - If both have `color`, multiplies `(r1*r2, g1*g2, b1*b2)`.
        - Scalar channels present in both are multiplied together.
        """
        if self.color is not None and other.color is not None:
            new_color: Optional[Color] = Color(
                r=self.color.r * other.color.r,
                g=self.color.g * other.color.g,
                b=self.color.b * other.color.b,
            )
        elif self.color is not None and "value" in other.channels:
            new_color = self.color * other.channels["value"]
        elif other.color is not None and "value" in self.channels:
            new_color = other.color * self.channels["value"]
        else:
            new_color = self.color if self.color is not None else other.color

        merged_channels = dict(self.channels)
        for k, v in other.channels.items():
            if k in merged_channels:
                merged_channels[k] = merged_channels[k] * v
            else:
                merged_channels[k] = v
        return Patch(color=new_color, channels=merged_channels)

    def scale(self, factor: float, attr: Optional[str] = None) -> Patch:
        """Scale intensity by `factor`.

        If `attr` is None, scales `color` and any intensity-like scalar channels (or all channels).
        If `attr` is specified (e.g. `attr='w'` or `attr='color'`), scales only that attribute.
        """
        if attr == "color":
            return Patch(
                color=self.color * factor if self.color is not None else None,
                channels=self.channels,
            )
        if attr is not None:
            if attr not in self.channels:
                return self
            new_ch = dict(self.channels)
            new_ch[attr] = max(0.0, min(1.0, new_ch[attr] * factor))
            return Patch(color=self.color, channels=new_ch)

        new_color = self.color * factor if self.color is not None else None
        new_ch = {k: max(0.0, min(1.0, v * factor)) for k, v in self.channels.items()}
        return Patch(color=new_color, channels=new_ch)


# Keep ParPatch alias for convenience
ParPatch = Patch
