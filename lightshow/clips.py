"""Algebraic composable animation clips using Python operator overloading.

Core operators on `Clip`:
  - `clip1 >> clip2`       : Sequence (`clip1` followed by `clip2`)
  - `clip1 | clip2`        : Layer / Override (`clip2` overrides non-None channels of `clip1`)
  - `clip1 + clip2`        : Additive blend (`clip1` and `clip2` colors/channels added together)
  - `clip * n`             : Repeat `n` times (or `clip * inf` for infinite loop)
  - `clip @ duration`      : Time-stretch / compress clip to fit `duration` seconds
  - `~clip`                : Time-reverse a finite clip
  - `clip.phase(offset)`   : Shift time across fixtures by `fixture_index * offset`
  - `clip.spread()`        : Spread phase evenly across all fixtures in the group
  - `clip.on(0, 2)`        : Restrict clip to specific fixture indices (0-based)
  - `dim(factor, clip)`    : Scale intensity of a clip (or a specific attribute via `attr=`)
  - `ch(name, clip)`       : Route a clip's output into a named scalar channel (e.g. `'w'`, `'strobe'`)
"""

from __future__ import annotations
import math
from math import inf
from typing import Callable, Iterable, Optional, Sequence as SeqType, Union

from .state import Color, Patch


class Ease:
    """Common easing functions for smooth transitions."""

    @staticmethod
    def linear(t: float) -> float:
        return t

    @staticmethod
    def in_quad(t: float) -> float:
        return t * t

    @staticmethod
    def out_quad(t: float) -> float:
        return t * (2.0 - t)

    @staticmethod
    def in_out_sine(t: float) -> float:
        return 0.5 * (1.0 - math.cos(math.pi * t))

    @staticmethod
    def in_out_cubic(t: float) -> float:
        return 4.0 * t * t * t if t < 0.5 else 1.0 - pow(-2.0 * t + 2.0, 3) / 2.0


class Clip:
    """Base class for composable lighting animations.

    Every Clip has a `duration` (in seconds, or `math.inf` for infinite clips)
    and evaluates to a `Patch` at `(t, fixture_index, total_fixtures)`.
    """

    duration: float = 0.0

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        """Evaluate the clip at local time `t` (seconds) for `fixture` (0-indexed)."""
        raise NotImplementedError

    # -------------------------------------------------------------------------
    # Algebraic Operators
    # -------------------------------------------------------------------------

    def __rshift__(self, other: Clip) -> SequenceClip:
        """`a >> b`: Play `a` then `b` sequentially."""
        return SequenceClip(self, other)

    def __or__(self, other: Clip) -> LayerClip:
        """`a | b`: Play `a` and `b` in parallel; `b`'s non-None attributes override `a`."""
        return LayerClip(self, other, mode="override")

    def __add__(self, other: Clip) -> LayerClip:
        """`a + b`: Play `a` and `b` in parallel, additively blending colors and channels."""
        return LayerClip(self, other, mode="add")

    def __and__(self, other: Clip) -> LayerClip:
        """`a & b`: Multiplicative mask/envelope (e.g. `Rainbow(period=14.4) & spot_envelope`)."""
        return LayerClip(self, other, mode="multiply")

    def __mul__(self, count: Union[int, float]) -> Clip:
        """`clip * n`: Repeat clip `n` times (use `math.inf` for infinite loop)."""
        if count == inf or count == float("inf"):
            return RepeatClip(self, count=inf)
        if isinstance(count, int) or (isinstance(count, float) and count.is_integer()):
            return RepeatClip(self, count=int(count))
        raise ValueError("Use integer or `inf` with `*` for repeating, or `dim(factor, clip)` for brightness.")

    def __rmul__(self, count: Union[int, float]) -> Clip:
        return self.__mul__(count)

    def __matmul__(self, target_duration: float) -> TimeScaleClip:
        """`clip @ duration`: Stretch or compress a finite clip to `target_duration` seconds."""
        return TimeScaleClip(self, target_duration)

    def __invert__(self) -> ReverseClip:
        """`~clip`: Play a finite clip backwards in time."""
        return ReverseClip(self)

    # -------------------------------------------------------------------------
    # Fluent Combinators / Modifiers
    # -------------------------------------------------------------------------

    def loop(self, count: Union[int, float] = inf) -> RepeatClip:
        """Loop this clip `count` times (defaults to infinite)."""
        return RepeatClip(self, count=count)

    def pingpong(self) -> SequenceClip:
        """Play forward then backward (`clip >> ~clip`)."""
        return SequenceClip(self, ReverseClip(self))

    def phase(self, offset_per_fixture: float, wrap: bool = True) -> PhaseClip:
        """Offset time for each fixture by `fixture_index * offset_per_fixture` seconds."""
        return PhaseClip(self, offset_per_fixture=offset_per_fixture, wrap=wrap)

    def stagger(
        self,
        offset_per_fixture: float,
        fixtures: int = 4,
        *,
        bounce: bool = False,
    ) -> StaggerClip:
        """Play a finite clip staggered across `fixtures` by `offset_per_fixture` seconds each.

        If `bounce=True`, seamlessly bounces back and forth (`0 -> 1 -> ... -> N-1 -> ... -> 1`)
        without double-hitting the end fixtures, overlapping the turnaround crossfade cleanly!
        """
        return StaggerClip(
            self,
            offset_per_fixture=offset_per_fixture,
            fixtures=fixtures,
            bounce=bounce,
        )

    def fade_in(
        self,
        duration: float = 0.3,
        ease: Callable[[float], float] = Ease.in_out_sine,
    ) -> EnvelopeClip:
        """Smoothly ramp intensity from 0.0 -> 1.0 over the first `duration` seconds."""
        return EnvelopeClip(self, fade_in=duration, fade_out=0.0, ease=ease)

    def fade_out(
        self,
        duration: float = 0.3,
        ease: Callable[[float], float] = Ease.in_out_sine,
    ) -> EnvelopeClip:
        """Smoothly ramp intensity from 1.0 -> 0.0 over the final `duration` seconds."""
        return EnvelopeClip(self, fade_in=0.0, fade_out=duration, ease=ease)

    def spread(self, total_offset: Optional[float] = None) -> SpreadClip:
        """Automatically spread phase evenly across all fixtures in the group."""
        return SpreadClip(self, total_offset=total_offset)

    def on(self, *fixtures: Union[int, Iterable[int]]) -> MaskClip:
        """Restrict this clip to only affect the specified 0-based fixture indices."""
        flat: set[int] = set()
        for f in fixtures:
            if isinstance(f, Iterable):
                flat.update(f)
            else:
                flat.add(int(f))
        return MaskClip(self, allowed_fixtures=frozenset(flat))

    def mirror(self) -> MirrorClip:
        """Mirror fixture indexing from outside-in (e.g. 0 and N-1 pair up)."""
        return MirrorClip(self)

    def reverse_fixtures(self) -> ReverseFixturesClip:
        """Reverse spatial order of fixtures (N-1 .. 0)."""
        return ReverseFixturesClip(self)

    def scale(self, factor: float, attr: Optional[str] = None) -> ScaleClip:
        """Scale output intensity of this clip by `factor` (optionally only on `attr`)."""
        return ScaleClip(self, factor, attr=attr)

    def dim(self, factor: float, attr: Optional[str] = None) -> ScaleClip:
        """Dim/scale output intensity of this clip by `factor` in [0.0, 1.0]."""
        return ScaleClip(self, factor, attr=attr)


def dim(factor: float, target, *, attr: Optional[str] = None):
    """Composable combinator that dims a `Clip` or a `Scene` by `factor` (e.g. `dim(0.3, strobe_anim)`).

    Args:
        factor: Brightness multiplier in [0.0, 1.0].
        target: The `Clip` or `Scene` to dim.
        attr: Optional attribute name (e.g. `'w'` or `'color'`) when dimming a `Clip`.
    """
    if isinstance(target, Clip):
        return ScaleClip(target, factor, attr=attr)
    if hasattr(target, "dim"):
        return target.dim(factor)
    raise TypeError(f"Cannot dim object of type {type(target)}")


def ch(name: str, clip_or_val: Union[Clip, float], *, duration: float = inf) -> Clip:
    """Route a scalar value or any `Clip` into a named single channel `name` (e.g. `'w'`, `'strobe'`, `'dimmer'`).

    Examples:
      - `ch("w", 1.0, duration=2.0)`                  : Hold white channel at 1.0 for 2s
      - `ch("strobe", 0.8, duration=0.5)`             : Activate strobe channel at 0.8 for 0.5s
      - `ch("w", Chase(Color.WHITE, step_duration=0.1))` : Run a chase specifically on the `'w'` channel!
    """
    if isinstance(clip_or_val, (int, float)):
        return Hold(duration=duration, **{name: float(clip_or_val)})
    return ChannelMapClip(clip_or_val, target_channel=name)


# =============================================================================
# Composite Clips (Operators & Modifiers)
# =============================================================================


class SequenceClip(Clip):
    """Sequential composition (`a >> b >> c`)."""

    def __init__(self, *clips: Clip) -> None:
        flattened: list[Clip] = []
        for c in clips:
            if isinstance(c, SequenceClip):
                flattened.extend(c.clips)
            else:
                flattened.append(c)
        self.clips = flattened
        self.duration = sum(c.duration for c in self.clips)

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        if not self.clips:
            return Patch()
        elapsed = 0.0
        for i, clip in enumerate(self.clips):
            if t < elapsed + clip.duration or i == len(self.clips) - 1:
                local_t = max(0.0, min(clip.duration, t - elapsed))
                return clip.eval(local_t, fixture, total_fixtures)
            elapsed += clip.duration
        return self.clips[-1].eval(self.clips[-1].duration, fixture, total_fixtures)


class LayerClip(Clip):
    """Parallel composition (`a | b` for override, `a + b` for additive, `a & b` for multiply)."""

    def __init__(self, bottom: Clip, top: Clip, mode: str = "override") -> None:
        self.bottom = bottom
        self.top = top
        self.mode = mode
        if bottom.duration == inf or top.duration == inf:
            self.duration = inf
        else:
            self.duration = max(bottom.duration, top.duration)

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        p_bot = self.bottom.eval(t, fixture, total_fixtures) if t <= self.bottom.duration else Patch()
        p_top = self.top.eval(t, fixture, total_fixtures) if t <= self.top.duration else Patch()
        if self.mode == "add":
            return p_bot.add(p_top)
        if self.mode == "multiply":
            return p_bot.multiply(p_top)
        return p_bot.merge(p_top)


class RepeatClip(Clip):
    """Repeats a finite clip `count` times (`clip * n` or `clip * inf`)."""

    def __init__(self, child: Clip, count: Union[int, float] = inf) -> None:
        if child.duration <= 0:
            raise ValueError("Cannot repeat a clip with 0 duration.")
        self.child = child
        self.count = count
        self.duration = child.duration * count

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        if self.child.duration == inf:
            return self.child.eval(t, fixture, total_fixtures)
        if t >= self.duration:
            return self.child.eval(self.child.duration, fixture, total_fixtures)
        local_t = t % self.child.duration
        return self.child.eval(local_t, fixture, total_fixtures)


class TimeScaleClip(Clip):
    """Stretches or compresses a finite clip to `target_duration` (`clip @ seconds`)."""

    def __init__(self, child: Clip, target_duration: float) -> None:
        if child.duration == inf or child.duration <= 0:
            raise ValueError("Can only time-scale finite clips with positive duration.")
        if target_duration <= 0:
            raise ValueError("Target duration must be positive.")
        self.child = child
        self.duration = float(target_duration)
        self.rate = child.duration / self.duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        return self.child.eval(t * self.rate, fixture, total_fixtures)


class ReverseClip(Clip):
    """Reverses time for a finite clip (`~clip`)."""

    def __init__(self, child: Clip) -> None:
        if child.duration == inf:
            raise ValueError("Cannot time-reverse an infinite clip.")
        self.child = child
        self.duration = child.duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        local_t = max(0.0, min(self.duration, self.duration - t))
        return self.child.eval(local_t, fixture, total_fixtures)


class PhaseClip(Clip):
    """Shifts evaluation time per fixture (`clip.phase(offset)`)."""

    def __init__(self, child: Clip, offset_per_fixture: float, wrap: bool = True) -> None:
        self.child = child
        self.offset_per_fixture = offset_per_fixture
        self.wrap = wrap
        self.duration = child.duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        shifted = t - fixture * self.offset_per_fixture
        if self.wrap and self.child.duration < inf and self.child.duration > 0:
            shifted = shifted % self.child.duration
        elif shifted < 0 or shifted > self.child.duration:
            return Patch(color=Color.BLACK, channels={"value": 0.0, "w": 0.0})
        return self.child.eval(shifted, fixture, total_fixtures)


class StaggerClip(Clip):
    """Staggers a finite `child` clip across fixtures by `offset_per_fixture` seconds.

    - When `bounce=False`:
      Total duration is `child.duration + (fixtures - 1) * offset_per_fixture`, so each fixture
      stays dark (`0.0`) before its turn and after it finishes.
    - When `bounce=True`:
      Bounces back and forth (`0 -> 1 -> ... -> N-1 -> ... -> 1`) without double-hitting the
      end fixtures (`0` and `N-1`). Period is `2 * (fixtures - 1) * offset_per_fixture`, and
      overlapping tails across the turnaround wrap seamlessly!
    """

    def __init__(
        self,
        child: Clip,
        offset_per_fixture: float,
        fixtures: int = 4,
        *,
        bounce: bool = False,
    ) -> None:
        if child.duration == inf:
            raise ValueError("Use `.phase(offset)` for infinite clips, or `.stagger(offset)` for finite clips.")
        self.child = child
        self.offset_per_fixture = float(offset_per_fixture)
        self.fixtures = max(1, int(fixtures))
        self.bounce = bounce
        step = abs(self.offset_per_fixture)
        if self.bounce and self.fixtures > 1:
            self.duration = 2.0 * (self.fixtures - 1) * step
        else:
            self.duration = child.duration + (self.fixtures - 1) * step

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        step = abs(self.offset_per_fixture)
        if not self.bounce or self.fixtures <= 1 or self.duration <= 0:
            shifted = t - fixture * self.offset_per_fixture
            if shifted < 0.0 or shifted > self.child.duration:
                return Patch(color=Color.BLACK, channels={"value": 0.0, "w": 0.0})
            return self.child.eval(shifted, fixture, total_fixtures)

        # In bounce mode, one full cycle of `2 * (N - 1)` steps has:
        # - Forward trigger for fixture `i` at `i * step`
        # - Reverse trigger for interior fixtures `0 < i < N - 1` at `(2*(N - 1) - i) * step`
        period = self.duration
        local_t = t % period
        triggers = [fixture * step]
        if 0 < fixture < self.fixtures - 1:
            triggers.append((2 * (self.fixtures - 1) - fixture) * step)

        result: Optional[Patch] = None
        for trig in triggers:
            # Check current, previous, and two-cycles-ago so even very long fade tails wrap seamlessly
            for delta in (local_t - trig, local_t + period - trig, local_t + 2.0 * period - trig):
                if 0.0 <= delta <= self.child.duration:
                    p = self.child.eval(delta, fixture, total_fixtures)
                    result = p if result is None else result.htp(p)
        if result is not None:
            return result
        return Patch(color=Color.BLACK, channels={"value": 0.0, "w": 0.0})


class EnvelopeClip(Clip):
    """Applies a smooth fade-in and/or fade-out intensity envelope to `child`."""

    def __init__(
        self,
        child: Clip,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
        ease: Callable[[float], float] = Ease.in_out_sine,
    ) -> None:
        self.child = child
        self.fade_in_dur = max(0.0, float(fade_in))
        self.fade_out_dur = max(0.0, float(fade_out))
        self.ease_fn = ease
        self.duration = child.duration

    def fade_in(
        self,
        duration: float = 0.3,
        ease: Optional[Callable[[float], float]] = None,
    ) -> EnvelopeClip:
        return EnvelopeClip(
            self.child,
            fade_in=duration,
            fade_out=self.fade_out_dur,
            ease=ease or self.ease_fn,
        )

    def fade_out(
        self,
        duration: float = 0.3,
        ease: Optional[Callable[[float], float]] = None,
    ) -> EnvelopeClip:
        return EnvelopeClip(
            self.child,
            fade_in=self.fade_in_dur,
            fade_out=duration,
            ease=ease or self.ease_fn,
        )

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        patch = self.child.eval(t, fixture, total_fixtures)
        gain = 1.0
        if self.fade_in_dur > 0.0 and t < self.fade_in_dur:
            gain *= self.ease_fn(max(0.0, min(1.0, t / self.fade_in_dur)))
        if self.fade_out_dur > 0.0 and self.duration < inf:
            rem = self.duration - t
            if rem < self.fade_out_dur:
                gain *= self.ease_fn(max(0.0, min(1.0, rem / self.fade_out_dur)))
        if gain < 1.0:
            return patch.scale(gain)
        return patch


class SpreadClip(Clip):
    """Spreads phase evenly across `total_fixtures` (`clip.spread()`)."""

    def __init__(self, child: Clip, total_offset: Optional[float] = None) -> None:
        self.child = child
        self.total_offset = total_offset
        self.duration = child.duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        span = self.total_offset if self.total_offset is not None else (
            self.child.duration if self.child.duration < inf else 1.0
        )
        offset = (fixture / max(1, total_fixtures)) * span
        shifted = t - offset
        if self.child.duration < inf and self.child.duration > 0:
            shifted = shifted % self.child.duration
        return self.child.eval(max(0.0, shifted), fixture, total_fixtures)


class MaskClip(Clip):
    """Applies `child` only to fixtures in `allowed_fixtures`, transparent elsewhere."""

    def __init__(self, child: Clip, allowed_fixtures: frozenset[int]) -> None:
        self.child = child
        self.allowed_fixtures = allowed_fixtures
        self.duration = child.duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        if fixture not in self.allowed_fixtures:
            return Patch()
        return self.child.eval(t, fixture, total_fixtures)


class MirrorClip(Clip):
    """Maps fixture index symmetrically from the outside in (e.g. 0->0, 1->1, 2->1, 3->0)."""

    def __init__(self, child: Clip) -> None:
        self.child = child
        self.duration = child.duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        mirrored_idx = min(fixture, total_fixtures - 1 - fixture)
        half_count = max(1, (total_fixtures + 1) // 2)
        return self.child.eval(t, mirrored_idx, half_count)


class ReverseFixturesClip(Clip):
    """Reverses fixture index (`total_fixtures - 1 - fixture`)."""

    def __init__(self, child: Clip) -> None:
        self.child = child
        self.duration = child.duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        rev_idx = max(0, total_fixtures - 1 - fixture)
        return self.child.eval(t, rev_idx, total_fixtures)


class ScaleClip(Clip):
    """Scales intensity of `child` by `factor` (optionally targeting a specific `attr`)."""

    def __init__(self, child: Clip, factor: float, attr: Optional[str] = None) -> None:
        self.child = child
        self.factor = factor
        self.attr = attr
        self.duration = child.duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        return self.child.eval(t, fixture, total_fixtures).scale(self.factor, attr=self.attr)


class ChannelMapClip(Clip):
    """Routes the output of `child` into a single named scalar channel `target_channel`."""

    def __init__(self, child: Clip, target_channel: str) -> None:
        self.child = child
        self.target_channel = target_channel
        self.duration = child.duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        p = self.child.eval(t, fixture, total_fixtures)
        if self.target_channel in p.channels:
            val = p.channels[self.target_channel]
        elif "value" in p.channels:
            val = p.channels["value"]
        elif p.color is not None:
            val = p.color.max_component
        else:
            return Patch()
        return Patch.from_channel(self.target_channel, val)


# =============================================================================
# Primitive Clips (Building Blocks)
# =============================================================================


class Wait(Clip):
    """Transparent clip that waits for `duration` seconds without overriding channels."""

    def __init__(self, duration: float) -> None:
        self.duration = float(duration)

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        return Patch()


# Alias Pause to Wait for semantic clarity
Pause = Wait


class Hold(Clip):
    """Hold a constant RGB `color` and/or any named scalar channels (`w=...`, `dimmer=...`, `strobe=...`, `value=...`)."""

    def __init__(
        self,
        color_or_val: Optional[Union[Color, float]] = None,
        *,
        duration: float = inf,
        **channels: Optional[float],
    ) -> None:
        self.duration = float(duration)
        clean_channels: dict[str, float] = {
            k: float(v) for k, v in channels.items() if v is not None
        }
        if isinstance(color_or_val, (int, float)):
            clean_channels.setdefault("value", float(color_or_val))
            self.color = None
        else:
            self.color = color_or_val
        self.channels = clean_channels

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        return Patch(color=self.color, channels=dict(self.channels))


def Blackout(duration: float = inf) -> Hold:
    """Turn RGB and common intensity/strobe channels off (0.0)."""
    return Hold(Color.BLACK, duration=duration, w=0.0, strobe=0.0, value=0.0)


class Fade(Clip):
    """Smoothly interpolate between two `Color`s (or two scalar `float` values) over `duration` seconds."""

    def __init__(
        self,
        start: Optional[Union[Color, float]] = None,
        end: Optional[Union[Color, float]] = None,
        duration: float = 1.0,
        *,
        channel: str = "value",
        ease: Callable[[float], float] = Ease.in_out_sine,
    ) -> None:
        self.start = start
        self.end = end
        self.channel = channel
        self.duration = float(duration)
        self.ease_fn = ease

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        u = 1.0 if self.duration <= 0 else max(0.0, min(1.0, t / self.duration))
        alpha = self.ease_fn(u)

        if isinstance(self.start, Color) and isinstance(self.end, Color):
            return Patch(color=self.start.lerp(self.end, alpha))
        if isinstance(self.start, (int, float)) and isinstance(self.end, (int, float)):
            val = float(self.start) + (float(self.end) - float(self.start)) * alpha
            return Patch.from_channel(self.channel, val)
        return Patch()


class Pulse(Clip):
    """Fade from `low` to `high` and back to `low` over `duration` seconds."""

    def __init__(
        self,
        color_or_peak: Union[Color, float] = 1.0,
        duration: float = 1.0,
        *,
        low: float = 0.0,
        high: float = 1.0,
        channel: str = "value",
        ease: Callable[[float], float] = Ease.in_out_sine,
    ) -> None:
        self.color_or_peak = color_or_peak
        self.duration = float(duration)
        self.low = low
        self.high = high
        self.channel = channel
        self.ease_fn = ease

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        u = 0.0 if self.duration <= 0 else max(0.0, min(1.0, t / self.duration))
        tri = 1.0 - abs(2.0 * u - 1.0)
        level = self.low + (self.high - self.low) * self.ease_fn(tri)
        if isinstance(self.color_or_peak, Color):
            return Patch(color=self.color_or_peak * level)
        return Patch.from_channel(self.channel, float(self.color_or_peak) * level)


class Strobe(Clip):
    """Set the `'strobe'` channel (and optional `color` or `w`)."""

    def __init__(
        self,
        rate: float = 0.8,
        duration: float = 1.0,
        color: Optional[Color] = None,
        w: Optional[float] = None,
    ) -> None:
        self.rate = max(0.0, min(1.0, rate))
        self.duration = float(duration)
        self.color = color
        self.w = w

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        ch_dict: dict[str, float] = {"strobe": self.rate, "value": self.rate}
        if self.w is not None:
            ch_dict["w"] = self.w
        return Patch(color=self.color, channels=ch_dict)


class SineLFO(Clip):
    """Modulate a named scalar channel (default `'dimmer'`) using a sine wave."""

    def __init__(
        self,
        period: float = 2.0,
        low: float = 0.1,
        high: float = 1.0,
        duration: float = inf,
        *,
        channel: str = "dimmer",
    ) -> None:
        self.period = float(period)
        self.low = low
        self.high = high
        self.duration = float(duration)
        self.channel = channel

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        wave = 0.5 * (1.0 - math.cos(2.0 * math.pi * t / self.period))
        val = self.low + (self.high - self.low) * wave
        return Patch(channels={self.channel: val, "value": val})


# Alias for backward compatibility
DimmerLFO = SineLFO


class Rainbow(Clip):
    """Cycle through HSV hues over `period` seconds."""

    def __init__(
        self,
        period: float = 4.0,
        duration: Optional[float] = None,
        saturation: float = 1.0,
        value: float = 1.0,
    ) -> None:
        self.period = float(period)
        self.duration = float(period if duration is None else duration)
        self.saturation = saturation
        self.value = value

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        hue = (t / self.period) % 1.0
        return Patch(color=Color.from_hsv(hue, self.saturation, self.value))


class Chase(Clip):
    """Step through fixtures one at a time (or with smooth crossfade tails)."""

    def __init__(
        self,
        color: Union[Color, float] = Color.WHITE,
        step_duration: float = 0.25,
        *,
        background: Optional[Union[Color, float]] = Color.BLACK,
        tail: float = 0.0,
        num_steps: int = 4,
        wrap: bool = True,
    ) -> None:
        self.color = Color(color, color, color) if isinstance(color, (int, float)) else color
        if isinstance(background, (int, float)):
            self.background: Optional[Color] = Color(background, background, background)
        else:
            self.background = background
        self.step_duration = float(step_duration)
        self.tail = max(0.0, tail)
        self.num_steps = num_steps
        self.wrap = wrap
        self.duration = self.step_duration * self.num_steps

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        n = max(1, total_fixtures)
        if self.duration <= 0:
            pos = 0.0
        elif self.wrap:
            pos = ((t / self.duration) * n) % n
        else:
            pos = (t / self.duration) * n

        if self.tail <= 0.0:
            active = (int(pos) == (fixture % n)) if self.wrap else (int(pos) == fixture)
            if active:
                return Patch(color=self.color)
            return Patch(color=self.background) if self.background is not None else Patch()

        if self.wrap:
            dist = (pos - fixture) % n
            intensity = max(0.0, 1.0 - dist / (1.0 + self.tail))
        else:
            dist = pos - fixture
            if dist < -1e-9 or dist > (1.0 + self.tail):
                intensity = 0.0
            else:
                intensity = max(0.0, 1.0 - max(0.0, dist) / (1.0 + self.tail))

        if self.background is not None:
            return Patch(color=self.background.lerp(self.color, intensity))
        if intensity > 0:
            return Patch(color=self.color * intensity)
        return Patch()

    def pingpong(self) -> SequenceClip:
        """Play forward then backward with spatial reversal and linear boundaries."""
        forward = Chase(
            self.color,
            self.step_duration,
            background=self.background,
            tail=self.tail,
            num_steps=self.num_steps,
            wrap=False,
        )
        return SequenceClip(forward, ReverseFixturesClip(forward))


class Gradient(Clip):
    """Cycle smoothly through a sequence of colors over `duration` seconds."""

    def __init__(self, colors: SeqType[Color], duration: float = 4.0) -> None:
        if len(colors) < 2:
            raise ValueError("Gradient requires at least 2 colors.")
        self.colors = list(colors)
        self.duration = float(duration)

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        u = 0.0 if self.duration <= 0 else max(0.0, min(1.0, t / self.duration))
        segments = len(self.colors) - 1
        scaled = u * segments
        idx = min(segments - 1, int(scaled))
        frac = scaled - idx
        c = self.colors[idx].lerp(self.colors[idx + 1], frac)
        return Patch(color=c)


class FnClip(Clip):
    """Custom functional clip from any callable `(t, fixture, total_fixtures) -> Patch | Color`."""

    def __init__(
        self,
        fn: Callable[[float, int, int], Union[Patch, Color]],
        duration: float = inf,
    ) -> None:
        self.fn = fn
        self.duration = float(duration)

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        res = self.fn(t, fixture, total_fixtures)
        if isinstance(res, Color):
            return Patch(color=res)
        return res


def kelvin_to_ww_cw(kelvin: float, brightness: float = 1.0) -> tuple[float, float]:
    """Calculate normalized (ww, cw) levels in [0.0, 1.0] for a target color temperature in Kelvin.

    Calibrated to the Eurolite BCL 2in1 CW/WW LED specs (Warm White = 3200K, Cold White = 6600K).
    Interpolates in perceptual mired (micro-reciprocal degree) space.
    """
    k = max(3200.0, min(6600.0, float(kelvin)))
    mired_warm = 1e6 / 3200.0  # 312.50
    mired_cold = 1e6 / 6600.0  # 151.52
    mired_target = 1e6 / k
    ww_ratio = (mired_target - mired_cold) / (mired_warm - mired_cold)
    cw_ratio = 1.0 - ww_ratio
    scale = max(0.0, min(1.0, float(brightness)))
    return (ww_ratio * scale, cw_ratio * scale)


class CCT(Clip):
    """Hold a specific correlated color temperature in Kelvin (3200K - 6600K).

    Controls both 'ww' and 'cw' channels according to the physical BCL LED mixing curve.
    """

    def __init__(self, kelvin: float, brightness: float = 1.0, duration: float = inf) -> None:
        self.kelvin = float(kelvin)
        self.brightness = float(brightness)
        self.duration = float(duration)
        ww, cw = kelvin_to_ww_cw(self.kelvin, self.brightness)
        self.channels = {"ww": ww, "cw": cw, "w": cw}

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        return Patch(channels=dict(self.channels))


class FadeCCT(Clip):
    """Smoothly transition correlated color temperature between `start_k` and `end_k` over `duration`."""

    def __init__(
        self,
        start_k: float,
        end_k: float,
        duration: float = 1.0,
        brightness: float = 1.0,
        ease: Callable[[float], float] = Ease.in_out_sine,
    ) -> None:
        self.start_k = float(start_k)
        self.end_k = float(end_k)
        self.duration = float(duration)
        self.brightness = float(brightness)
        self.ease_fn = ease

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        progress = max(0.0, min(1.0, t / self.duration)) if self.duration > 0 else 1.0
        eased = self.ease_fn(progress)
        k = self.start_k + (self.end_k - self.start_k) * eased
        ww, cw = kelvin_to_ww_cw(k, self.brightness)
        return Patch(channels={"ww": ww, "cw": cw, "w": cw})
