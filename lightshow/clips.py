"""Algebraic composable animation clips using Python operator overloading.

Core composition on `Clip`:
  - `Sequence([clip1, clip2])` : Sequence (`clip1` followed by `clip2`)
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
from .tempo import AbsoluteDuration, MusicalDuration, Seconds, abs


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

    _duration: Union[float, Any] = 0.0

    @property
    def duration(self) -> float:
        """Total duration of the clip in seconds (evaluates dynamically for musical clips)."""
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

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        """Evaluate the clip at local time `t` (seconds) for `fixture` (0-indexed)."""
        raise NotImplementedError

    def with_fixture_count(self, count: int) -> Clip:
        """Adapt clip or its child clips to `count` fixtures (e.g. for automatic Chase step count)."""
        return self

    # -------------------------------------------------------------------------
    # Algebraic Operators
    # -------------------------------------------------------------------------

    def __or__(self, other: Clip) -> LayerClip:
        """`a | b`: Play `a` and `b` in parallel; `b`'s non-None attributes override `a`."""
        return LayerClip(self, other, mode="override")

    def __add__(self, other: Clip) -> LayerClip:
        """`a + b`: Play `a` and `b` in parallel, additively blending colors and channels."""
        return LayerClip(self, other, mode="add")

    def __and__(self, other: Clip) -> LayerClip:
        """`a & b`: Multiplicative mask/envelope (e.g. `Rainbow(period=14.4) & spot_envelope`)."""
        return LayerClip(self, other, mode="multiply")

    def __mul__(self, count: Union[int, float, Any]) -> Clip:
        """`clip * n`: Repeat clip `n` times (use `math.inf` for infinite loop, or `bars(n)`)."""
        if hasattr(count, "seconds"):
            return RepeatClip(self, count=count)
        if count == inf or count == float("inf"):
            return RepeatClip(self, count=inf)
        if isinstance(count, int) or (isinstance(count, float) and count.is_integer()):
            return RepeatClip(self, count=int(count))
        raise ValueError("Use integer or `inf` with `*` for repeating, or `dim(factor, clip)` for brightness.")

    def __rmul__(self, count: Union[int, float]) -> Clip:
        return self.__mul__(count)

    @property
    def is_absolute(self) -> bool:
        """Whether this clip has absolute duration and resists scaling in sequences."""
        return False

    def __abs__(self) -> AbsoluteClip:
        """`abs(clip)`: Mark this clip as absolute so it resists time-stretching in sequences."""
        return AbsoluteClip(self)

    def abs(self) -> AbsoluteClip:
        """Fluent alias for `abs(clip)`."""
        return self.__abs__()

    def absolute(self) -> AbsoluteClip:
        """Fluent alias for `abs(clip)`."""
        return self.__abs__()

    def __matmul__(self, target_duration: Union[float, Any]) -> Clip:
        """`clip @ duration`: Stretch or compress a finite clip to `target_duration` seconds or musical beats."""
        return self.with_duration(target_duration)

    def with_duration(self, target_duration: Union[float, Any]) -> Clip:
        """Return a version of this clip scaled to `target_duration`."""
        return TimeScaleClip(self, target_duration)

    def __invert__(self) -> ReverseClip:
        """`~clip`: Play a finite clip backwards in time."""
        return ReverseClip(self)

    def __getitem__(self, item: slice) -> SliceClip:
        """`clip[start:stop]`: Cut a time window from this clip."""
        if not isinstance(item, slice):
            raise TypeError(f"Clip slicing expects a slice like clip[start:stop], got {type(item).__name__}")
        return SliceClip(self, start=item.start, stop=item.stop, step=item.step)

    def cut(self, start: float = 0.0, stop: Optional[float] = None) -> SliceClip:
        """Cut a time window [start, stop] from this clip."""
        return SliceClip(self, start=start, stop=stop)

    def slice(self, start: float = 0.0, stop: Optional[float] = None) -> SliceClip:
        """Alias for .cut()."""
        return self.cut(start, stop)

    # -------------------------------------------------------------------------
    # Fluent Combinators / Modifiers
    # -------------------------------------------------------------------------

    def loop(self, count: Union[int, float] = inf) -> RepeatClip:
        """Loop this clip `count` times (defaults to infinite)."""
        return RepeatClip(self, count=count)

    def pingpong(self) -> SequenceClip:
        """Play forward then backward (`Sequence([clip, ~clip])`)."""
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
    ) -> Flicker:
        """Modulate intensity with organic continuous noise (flame/torch flicker)."""
        return Flicker(
            self,
            speed=speed,
            depth=depth,
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
    ) -> HueShift:
        """Smoothly jitter the hue around the base color with organic continuous noise."""
        return HueShift(
            self,
            amount=amount,
            speed=speed,
            octaves=octaves,
            seed=seed,
            decorrelate=decorrelate,
        )

    def shift_hsv(
        self,
        dh: Union[float, Clip] = 0.0,
        ds: float = 0.0,
        dv: float = 0.0,
        *,
        dimmer_scale: float = 1.0,
    ) -> HueShift:
        """Offset hue, saturation, and/or value in HSV space."""
        return HueShift(
            self,
            dh=dh,
            ds=ds,
            dv=dv,
            dimmer_scale=dimmer_scale,
        )

    def inspect(
        self,
        *,
        fixtures: int = 4,
        duration: Optional[float] = None,
        fps: float = 20.0,
        width: Optional[Union[int, str]] = None,
        show_dmx: bool = True,
        dmx_collapsed: bool = True,
        max_channel: Optional[int] = None,
        hide_zeros: bool = False,
    ) -> Any:
        """Interactive Jupyter widget with animated visualizer, transport controls, and live DMX table."""
        from .fixtures import FixtureGroup, RGB, Channel
        elements = [
            {"color": RGB(1 + i * 4), "white": Channel(4 + i * 4)}
            for i in range(fixtures)
        ]
        group = FixtureGroup("fixtures", elements)
        scene = group(self)
        return scene.inspect(
            duration=duration,
            fps=fps,
            width=width,
            show_dmx=show_dmx,
            dmx_collapsed=dmx_collapsed,
            max_channel=max_channel,
            hide_zeros=hide_zeros,
        )


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
    """Sequential composition (`Sequence([a, b, c])` or `[a, b, c]`)."""

    def __init__(self, *clips: Union[Clip, SeqType[Clip]]) -> None:
        raw: list[Clip] = []
        for c in clips:
            if isinstance(c, (list, tuple)):
                raw.extend(c)
            else:
                raw.append(c)

        flattened: list[Clip] = []
        for c in raw:
            if isinstance(c, SequenceClip):
                flattened.extend(c.clips)
            else:
                flattened.append(c)
        self.clips = flattened

    @property
    def duration(self) -> float:
        return sum(c.duration for c in self.clips)

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

    def with_fixture_count(self, count: int) -> SequenceClip:
        new_clips = [c.with_fixture_count(count) for c in self.clips]
        if all(nc is c for nc, c in zip(new_clips, self.clips)):
            return self
        return SequenceClip(*new_clips)

    def with_duration(self, target_duration: Union[float, Any]) -> SequenceClip:
        abs_clips = [c for c in self.clips if c.is_absolute]
        scalable_clips = [c for c in self.clips if not c.is_absolute]

        if not abs_clips or not scalable_clips:
            total_dur = self.duration
            if total_dur <= 0:
                return self
            scale = target_duration / total_dur
            return SequenceClip(*(c.with_duration(c.duration * scale) for c in self.clips))

        abs_dur = sum(c.duration for c in abs_clips)
        scalable_dur = sum(c.duration for c in scalable_clips)
        target_scalable = target_duration - abs_dur

        if target_scalable <= 0 or scalable_dur <= 0:
            total_dur = self.duration
            scale = target_duration / total_dur if total_dur > 0 else 1.0
            return SequenceClip(*(c.with_duration(c.duration * scale) for c in self.clips))

        if len(scalable_clips) == 1:
            new_clips: list[Clip] = []
            for c in self.clips:
                if c.is_absolute:
                    new_clips.append(c)
                else:
                    new_clips.append(c.with_duration(target_scalable))
            return SequenceClip(*new_clips)

        scale = target_scalable / scalable_dur
        new_clips = []
        for c in self.clips:
            if c.is_absolute:
                new_clips.append(c)
            else:
                new_clips.append(c.with_duration(c.duration * scale))
        return SequenceClip(*new_clips)


class LayerClip(Clip):
    """Parallel composition (`a | b` for override, `a + b` for additive, `a & b` for multiply)."""

    def __init__(self, bottom: Clip, top: Clip, mode: str = "override") -> None:
        self.bottom = bottom
        self.top = top
        self.mode = mode

    @property
    def duration(self) -> float:
        if self.bottom.duration == inf or self.top.duration == inf:
            return inf
        return max(self.bottom.duration, self.top.duration)

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        p_bot = self.bottom.eval(t, fixture, total_fixtures) if t <= self.bottom.duration else Patch()
        p_top = self.top.eval(t, fixture, total_fixtures) if t <= self.top.duration else Patch()
        if self.mode == "add":
            return p_bot.add(p_top)
        if self.mode == "multiply":
            return p_bot.multiply(p_top)
        return p_bot.merge(p_top)

    def with_fixture_count(self, count: int) -> LayerClip:
        new_bot = self.bottom.with_fixture_count(count)
        new_top = self.top.with_fixture_count(count)
        if new_bot is self.bottom and new_top is self.top:
            return self
        return LayerClip(new_bot, new_top, mode=self.mode)


class RepeatClip(Clip):
    """Repeats a finite clip `count` times (`clip * n` or `clip * inf`)."""

    def __init__(self, child: Clip, count: Union[int, float, Any] = inf) -> None:
        if child.duration <= 0:
            raise ValueError("Cannot repeat a clip with 0 duration.")
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

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        if self.child.duration == inf:
            return self.child.eval(t, fixture, total_fixtures)
        if t >= self.duration:
            return self.child.eval(self.child.duration, fixture, total_fixtures)
        local_t = t % self.child.duration
        return self.child.eval(local_t, fixture, total_fixtures)

    def with_fixture_count(self, count: int) -> RepeatClip:
        new_child = self.child.with_fixture_count(count)
        if new_child is self.child:
            return self
        return RepeatClip(new_child, count=self.count)


class TimeScaleClip(Clip):
    """Stretches or compresses a finite clip to `target_duration` (`clip @ seconds`)."""

    def __init__(self, child: Clip, target_duration: Union[float, Any]) -> None:
        if child.duration == inf or child.duration <= 0:
            raise ValueError("Can only time-scale finite clips with positive duration.")
        if target_duration <= 0:
            raise ValueError("Target duration must be positive.")
        self.child = child
        self._target_duration = target_duration

    @property
    def duration(self) -> float:
        return float(self._target_duration)

    @property
    def rate(self) -> float:
        dur = self.duration
        return self.child.duration / dur if dur > 0 else 1.0

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        return self.child.eval(t * self.rate, fixture, total_fixtures)

    def with_duration(self, target_duration: Union[float, Any]) -> Clip:
        return self.child.with_duration(target_duration)

    def with_fixture_count(self, count: int) -> TimeScaleClip:
        new_child = self.child.with_fixture_count(count)
        if new_child is self.child:
            return self
        return TimeScaleClip(new_child, self._target_duration)


class AbsoluteClip(Clip):
    """Wraps a Clip to lock its duration as absolute (resisting time scaling in sequences)."""

    def __init__(self, child: Clip) -> None:
        self.child = child

    @property
    def is_absolute(self) -> bool:
        return True

    @property
    def duration(self) -> float:
        return self.child.duration

    @property
    def duration_beats(self) -> Optional[float]:
        return self.child.duration_beats

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        return self.child.eval(t, fixture, total_fixtures)

    def with_fixture_count(self, count: int) -> AbsoluteClip:
        new_child = self.child.with_fixture_count(count)
        if new_child is self.child:
            return self
        return AbsoluteClip(new_child)

    def with_duration(self, target_duration: Union[float, Any]) -> AbsoluteClip:
        return AbsoluteClip(self.child.with_duration(target_duration))

    def __abs__(self) -> AbsoluteClip:
        return self

    def __repr__(self) -> str:
        return f"abs({self.child!r})"


class ReverseClip(Clip):
    """Reverses time for a finite clip (`~clip`)."""

    def __init__(self, child: Clip) -> None:
        if child.duration == inf:
            raise ValueError("Cannot time-reverse an infinite clip.")
        self.child = child

    @property
    def duration(self) -> float:
        return self.child.duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        local_t = max(0.0, min(self.duration, self.duration - t))
        return self.child.eval(local_t, fixture, total_fixtures)

    def with_fixture_count(self, count: int) -> ReverseClip:
        new_child = self.child.with_fixture_count(count)
        if new_child is self.child:
            return self
        return ReverseClip(new_child)


class SliceClip(Clip):
    """Time-sliced clip capturing a sub-range [start, stop] from child (`clip[start:stop]`)."""

    def __init__(
        self,
        child: Clip,
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

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        if t < 0.0 or (t > self.duration and not math.isinf(self.duration)):
            return Patch()
        if self.step > 0:
            local_t = self.start + t * self.step
        else:
            local_t = self.stop + t * self.step
        return self.child.eval(local_t, fixture, total_fixtures)

    def with_fixture_count(self, count: int) -> SliceClip:
        new_child = self.child.with_fixture_count(count)
        if new_child is self.child:
            return self
        return SliceClip(new_child, start=self.start, stop=self.stop, step=self.step)


class PhaseClip(Clip):
    """Shifts evaluation time per fixture (`clip.phase(offset)`)."""

    def __init__(self, child: Clip, offset_per_fixture: float, wrap: bool = True) -> None:
        self.child = child
        self.offset_per_fixture = offset_per_fixture
        self.wrap = wrap

    @property
    def duration(self) -> float:
        return self.child.duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        shifted = t - fixture * self.offset_per_fixture
        if self.wrap and self.child.duration < inf and self.child.duration > 0:
            shifted = shifted % self.child.duration
        elif shifted < 0 or shifted > self.child.duration:
            return Patch(color=Color.BLACK, channels={"value": 0.0, "w": 0.0})
        return self.child.eval(shifted, fixture, total_fixtures)

    def with_fixture_count(self, count: int) -> PhaseClip:
        new_child = self.child.with_fixture_count(count)
        if new_child is self.child:
            return self
        return PhaseClip(new_child, offset_per_fixture=self.offset_per_fixture, wrap=self.wrap)


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
        self.offset_per_fixture = offset_per_fixture
        self.fixtures = max(1, int(fixtures))
        self.bounce = bounce

    @property
    def duration(self) -> float:
        step = abs(float(self.offset_per_fixture))
        if self.bounce and self.fixtures > 1:
            return 2.0 * (self.fixtures - 1) * step
        return self.child.duration + (self.fixtures - 1) * step

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

    def with_fixture_count(self, count: int) -> StaggerClip:
        new_child = self.child.with_fixture_count(count)
        return StaggerClip(
            new_child,
            offset_per_fixture=self.offset_per_fixture,
            fixtures=count,
            bounce=self.bounce,
        )


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

    @property
    def duration(self) -> float:
        return self.child.duration

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

    def with_fixture_count(self, count: int) -> EnvelopeClip:
        new_child = self.child.with_fixture_count(count)
        if new_child is self.child:
            return self
        return EnvelopeClip(
            new_child,
            fade_in=self.fade_in_dur,
            fade_out=self.fade_out_dur,
            ease=self.ease_fn,
        )


class SpreadClip(Clip):
    """Spreads phase evenly across `total_fixtures` (`clip.spread()`)."""

    def __init__(self, child: Clip, total_offset: Optional[float] = None) -> None:
        self.child = child
        self.total_offset = total_offset

    @property
    def duration(self) -> float:
        return self.child.duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        span = self.total_offset if self.total_offset is not None else (
            self.child.duration if self.child.duration < inf else 1.0
        )
        offset = (fixture / max(1, total_fixtures)) * span
        shifted = t - offset
        if self.child.duration < inf and self.child.duration > 0:
            shifted = shifted % self.child.duration
        return self.child.eval(max(0.0, shifted), fixture, total_fixtures)

    def with_fixture_count(self, count: int) -> SpreadClip:
        new_child = self.child.with_fixture_count(count)
        if new_child is self.child:
            return self
        return SpreadClip(new_child, total_offset=self.total_offset)


class MaskClip(Clip):
    """Applies `child` only to fixtures in `allowed_fixtures`, transparent elsewhere."""

    def __init__(self, child: Clip, allowed_fixtures: frozenset[int]) -> None:
        self.child = child
        self.allowed_fixtures = allowed_fixtures

    @property
    def duration(self) -> float:
        return self.child.duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        if fixture not in self.allowed_fixtures:
            return Patch()
        return self.child.eval(t, fixture, total_fixtures)

    def with_fixture_count(self, count: int) -> MaskClip:
        new_child = self.child.with_fixture_count(count)
        if new_child is self.child:
            return self
        return MaskClip(new_child, allowed_fixtures=self.allowed_fixtures)


class MirrorClip(Clip):
    """Maps fixture index symmetrically from the outside in (e.g. 0->0, 1->1, 2->1, 3->0)."""

    def __init__(self, child: Clip) -> None:
        self.child = child

    @property
    def duration(self) -> float:
        return self.child.duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        mirrored_idx = min(fixture, total_fixtures - 1 - fixture)
        half_count = max(1, (total_fixtures + 1) // 2)
        return self.child.eval(t, mirrored_idx, half_count)

    def with_fixture_count(self, count: int) -> MirrorClip:
        new_child = self.child.with_fixture_count(count)
        if new_child is self.child:
            return self
        return MirrorClip(new_child)


class ReverseFixturesClip(Clip):
    """Reverses fixture index (`total_fixtures - 1 - fixture`)."""

    def __init__(self, child: Clip) -> None:
        self.child = child

    @property
    def duration(self) -> float:
        return self.child.duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        rev_idx = max(0, total_fixtures - 1 - fixture)
        return self.child.eval(t, rev_idx, total_fixtures)

    def with_fixture_count(self, count: int) -> ReverseFixturesClip:
        new_child = self.child.with_fixture_count(count)
        if new_child is self.child:
            return self
        return ReverseFixturesClip(new_child)


class ScaleClip(Clip):
    """Scales intensity of `child` by `factor` (optionally targeting a specific `attr`)."""

    def __init__(self, child: Clip, factor: float, attr: Optional[str] = None) -> None:
        self.child = child
        self.factor = factor
        self.attr = attr

    @property
    def duration(self) -> float:
        return self.child.duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        return self.child.eval(t, fixture, total_fixtures).scale(self.factor, attr=self.attr)

    def with_fixture_count(self, count: int) -> ScaleClip:
        new_child = self.child.with_fixture_count(count)
        if new_child is self.child:
            return self
        return ScaleClip(new_child, factor=self.factor, attr=self.attr)


class ChannelMapClip(Clip):
    """Routes the output of `child` into a single named scalar channel `target_channel`."""

    def __init__(self, child: Clip, target_channel: str) -> None:
        self.child = child
        self.target_channel = target_channel

    @property
    def duration(self) -> float:
        return self.child.duration

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

    def __init__(self, duration: Union[float, Any]) -> None:
        self.duration = duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        return Patch()

    def with_duration(self, target_duration: Union[float, Any]) -> Wait:
        return Wait(target_duration)


# Alias Pause to Wait for semantic clarity
Pause = Wait


class Hold(Clip):
    """Hold a constant RGB `color` and/or any named scalar channels (`w=...`, `dimmer=...`, `strobe=...`, `value=...`)."""

    def __init__(
        self,
        color_or_val: Optional[Union[Color, float]] = None,
        *,
        duration: Union[float, Any] = inf,
        **channels: Optional[float],
    ) -> None:
        self.duration = duration
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
        if t <= float(self.duration):
            return Patch(color=self.color, channels=dict(self.channels))
        return Patch()

    def with_duration(self, target_duration: Union[float, Any]) -> Hold:
        return Hold(self.color, duration=target_duration, **self.channels)


def Blackout(duration: Union[float, Any] = inf) -> Hold:
    """Turn RGB and common intensity/strobe channels off (0.0)."""
    return Hold(Color.BLACK, duration=duration, w=0.0, strobe=0.0, value=0.0)


class Fade(Clip):
    """Smoothly interpolate between two `Color`s (or two scalar `float` values) over `duration` seconds."""

    def __init__(
        self,
        start: Optional[Union[Color, float]] = None,
        end: Optional[Union[Color, float]] = None,
        duration: Union[float, Any] = 1.0,
        *,
        channel: str = "value",
        ease: Callable[[float], float] = Ease.in_out_sine,
    ) -> None:
        self.start = start
        self.end = end
        self.channel = channel
        self.duration = duration
        self.ease_fn = ease

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        dur = float(self.duration)
        u = 1.0 if dur <= 0 else max(0.0, min(1.0, t / dur))
        alpha = self.ease_fn(u)

        if isinstance(self.start, Color) and isinstance(self.end, Color):
            return Patch(color=self.start.lerp(self.end, alpha))
        if isinstance(self.start, (int, float)) and isinstance(self.end, (int, float)):
            val = float(self.start) + (float(self.end) - float(self.start)) * alpha
            return Patch.from_channel(self.channel, val)
        return Patch()

    def with_duration(self, target_duration: Union[float, Any]) -> Fade:
        return Fade(
            start=self.start,
            end=self.end,
            duration=target_duration,
            channel=self.channel,
            ease=self.ease_fn,
        )


class Pulse(Clip):
    """Fade from `low` to `high` and back to `low` over `duration` seconds (with customizable envelope)."""

    def __init__(
        self,
        color_or_peak: Union[Color, float] = 1.0,
        duration: Optional[Union[float, Any]] = None,
        *,
        low: float = 0.0,
        high: float = 1.0,
        lead: Optional[Union[float, Any]] = None,
        hold: Union[float, Any] = 0.0,
        tail: Optional[Union[float, Any]] = None,
        attack: Optional[Union[float, Any]] = None,
        decay: Optional[Union[float, Any]] = None,
        channel: str = "value",
        ease: Callable[[float], float] = Ease.in_out_sine,
    ) -> None:
        self.color_or_peak = color_or_peak
        self.low = low
        self.high = high
        self.channel = channel
        self.ease_fn = ease

        # Resolve aliases: lead/attack, tail/decay
        eff_lead = attack if lead is None else lead
        eff_tail = decay if tail is None else tail
        self.hold = hold
        self._explicit_lead = eff_lead is not None
        self._explicit_tail = eff_tail is not None

        if duration is None:
            if eff_lead is None and eff_tail is None:
                self.duration = 1.0
                rem = max(0.0, float(self.duration) - float(self.hold))
                self.lead = rem / 2.0
                self.tail = rem / 2.0
            else:
                self.lead = eff_lead if eff_lead is not None else 0.0
                self.tail = eff_tail if eff_tail is not None else 0.0
                self.duration = self.lead + self.hold + self.tail
        else:
            self.duration = duration
            if eff_lead is None and eff_tail is None:
                rem = self._duration - self.hold
                self.lead = rem / 2.0
                self.tail = rem / 2.0
            elif eff_lead is not None and eff_tail is None:
                self.lead = eff_lead
                rem = self._duration - self.hold
                self.tail = rem - self.lead
            elif eff_lead is None and eff_tail is not None:
                self.tail = eff_tail
                rem = self._duration - self.hold
                self.lead = rem - self.tail
            else:
                self.lead = eff_lead
                self.tail = eff_tail

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        dur = float(self.duration)
        if dur <= 0:
            level = self.high
        elif t < 0.0 or t >= dur:
            level = self.low
        else:
            t_lead = float(self.lead)
            t_hold = float(self.hold)
            t_tail = float(self.tail)
            if t_lead > 0.0 and t < t_lead:
                u = t / t_lead
                level = self.low + (self.high - self.low) * self.ease_fn(u)
            elif t <= (t_lead + t_hold):
                level = self.high
            else:
                decay_elapsed = t - (t_lead + t_hold)
                if t_tail <= 0.0:
                    level = self.low
                else:
                    u = min(1.0, max(0.0, decay_elapsed / t_tail))
                    level = self.low + (self.high - self.low) * self.ease_fn(1.0 - u)

        if isinstance(self.color_or_peak, Color):
            return Patch(color=self.color_or_peak * level)
        return Patch.from_channel(self.channel, float(self.color_or_peak) * level)

    def with_duration(self, target_duration: Union[float, Any]) -> Clip:
        has_unscaled = (
            getattr(self.lead, "is_absolute", False)
            or getattr(self.tail, "is_absolute", False)
            or getattr(self.hold, "is_absolute", False)
            or isinstance(self.lead, (AbsoluteDuration, Seconds))
            or isinstance(self.tail, (AbsoluteDuration, Seconds))
            or isinstance(self.hold, (AbsoluteDuration, Seconds))
        )
        if not has_unscaled:
            return TimeScaleClip(self, target_duration)

        lead_arg = self.lead if self._explicit_lead else None
        tail_arg = self.tail if self._explicit_tail else None
        return Pulse(
            color_or_peak=self.color_or_peak,
            duration=target_duration,
            low=self.low,
            high=self.high,
            lead=lead_arg,
            hold=self.hold,
            tail=tail_arg,
            channel=self.channel,
            ease=self.ease_fn,
        )


class Strobe(Clip):
    """Set the `'strobe'` channel (and optional `color` or `w`)."""

    def __init__(
        self,
        rate: float = 0.8,
        duration: Union[float, Any] = 1.0,
        color: Optional[Color] = None,
        w: Optional[float] = None,
    ) -> None:
        self.rate = max(0.0, min(1.0, rate))
        self.duration = duration
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
        duration: Union[float, Any] = inf,
        *,
        channel: str = "dimmer",
    ) -> None:
        self.period = float(period)
        self.low = low
        self.high = high
        self.duration = duration
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
        period: Union[float, Any] = 4.0,
        duration: Optional[Union[float, Any]] = None,
        saturation: float = 1.0,
        value: float = 1.0,
    ) -> None:
        self.period = period
        self.duration = period if duration is None else duration
        self.saturation = saturation
        self.value = value

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        p = float(self.period)
        hue = (t / p) % 1.0 if p > 0 else 0.0
        return Patch(color=Color.from_hsv(hue, self.saturation, self.value))

    def with_duration(self, target_duration: Union[float, Any]) -> Rainbow:
        return Rainbow(
            period=target_duration,
            duration=target_duration,
            saturation=self.saturation,
            value=self.value,
        )


class Chase(Clip):
    """Step through fixtures one at a time (or with smooth crossfade tails)."""

    def __init__(
        self,
        color: Union[Color, float] = Color.WHITE,
        step_duration: Union[float, Any] = 0.25,
        *,
        background: Optional[Union[Color, float]] = Color.BLACK,
        lead: Union[float, Any] = 0.0,
        hold: Union[float, Any] = 0.0,
        tail: Union[float, Any] = 0.0,
        num_steps: Optional[int] = None,
        wrap: bool = True,
        _explicit_num_steps: Optional[bool] = None,
    ) -> None:
        self.color = Color(color, color, color) if isinstance(color, (int, float)) else color
        if isinstance(background, (int, float)):
            self.background: Optional[Color] = Color(background, background, background)
        else:
            self.background = background
        self.step_duration = step_duration if hasattr(step_duration, "seconds") else float(step_duration)
        self.lead = lead if hasattr(lead, "seconds") else max(0.0, float(lead))
        self.hold = hold if hasattr(hold, "seconds") else max(0.0, float(hold))
        self.tail = tail if hasattr(tail, "seconds") else max(0.0, float(tail))
        self._explicit_num_steps = (num_steps is not None) if _explicit_num_steps is None else _explicit_num_steps
        self.num_steps = 4 if num_steps is None else max(1, int(num_steps))
        self.wrap = wrap
        self.duration = self.step_duration * self.num_steps

    def with_duration(self, target_duration: Union[float, Any]) -> Chase:
        new_step = target_duration / self.num_steps
        c = Chase(
            self.color,
            new_step,
            background=self.background,
            lead=self.lead,
            hold=self.hold,
            tail=self.tail,
            num_steps=self.num_steps,
            wrap=self.wrap,
            _explicit_num_steps=self._explicit_num_steps,
        )
        c._target_duration = target_duration
        return c

    def with_fixture_count(self, count: int) -> Chase:
        if self._explicit_num_steps:
            return self
        if hasattr(self, "_target_duration") and self._target_duration is not None:
            new_step = self._target_duration / count
        else:
            new_step = self.step_duration
        c = Chase(
            self.color,
            new_step,
            background=self.background,
            lead=self.lead,
            hold=self.hold,
            tail=self.tail,
            num_steps=count,
            wrap=self.wrap,
            _explicit_num_steps=False,
        )
        if hasattr(self, "_target_duration"):
            c._target_duration = self._target_duration
        return c

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        n = max(1, total_fixtures)
        dur = float(self.duration)
        if dur <= 0:
            pos = 0.0
        elif self.wrap:
            pos = ((t / dur) * n) % n
        else:
            pos = (t / dur) * n

        step_dt = float(self.step_duration)
        if step_dt > 0:
            eff_hold = (float(self.hold.seconds) / step_dt) if hasattr(self.hold, "seconds") else float(self.hold)
            eff_lead = (float(self.lead.seconds) / step_dt) if hasattr(self.lead, "seconds") else float(self.lead)
            eff_tail = (float(self.tail.seconds) / step_dt) if hasattr(self.tail, "seconds") else float(self.tail)
        else:
            eff_hold, eff_lead, eff_tail = float(self.hold), float(self.lead), float(self.tail)

        if eff_lead <= 0.0 and eff_hold <= 0.0 and eff_tail <= 0.0:
            active = (int(pos) == (fixture % n)) if self.wrap else (int(pos) == fixture)
            if active:
                return Patch(color=self.color)
            return Patch(color=self.background) if self.background is not None else Patch()

        decay_span = eff_tail if (hasattr(self.tail, "seconds") or eff_hold > 0.0 or eff_lead > 0.0) else (1.0 + eff_tail)

        if self.wrap:
            dist = (pos - fixture) % n
            if dist > n - 1e-9:
                dist = 0.0

            # 1. Hold and tail (time since arrival)
            if dist <= eff_hold:
                i_tail = 1.0
            else:
                if decay_span > 0.0 and (dist - eff_hold) <= decay_span:
                    i_tail = max(0.0, 1.0 - (dist - eff_hold) / decay_span)
                else:
                    i_tail = 0.0

            # 2. Lead ramp-in (time until arrival)
            if eff_lead > 0.0:
                d_ahead = (fixture - pos) % n
                if d_ahead > n - 1e-9:
                    d_ahead = 0.0
                if d_ahead <= eff_lead:
                    i_lead = max(0.0, 1.0 - d_ahead / eff_lead)
                else:
                    i_lead = 0.0
            else:
                i_lead = 0.0

            intensity = max(i_tail, i_lead)
        else:
            dist = pos - fixture
            if dist < -1e-9:
                if eff_lead > 0.0:
                    d_ahead = -dist
                    if d_ahead <= eff_lead:
                        intensity = max(0.0, 1.0 - d_ahead / eff_lead)
                    else:
                        intensity = 0.0
                else:
                    intensity = 0.0
            else:
                d = max(0.0, dist)
                if d <= eff_hold:
                    intensity = 1.0
                else:
                    if decay_span > 0.0 and (d - eff_hold) <= decay_span:
                        intensity = max(0.0, 1.0 - (d - eff_hold) / decay_span)
                    else:
                        intensity = 0.0

        if self.background is not None:
            return Patch(color=self.background.lerp(self.color, intensity))
        if intensity > 0:
            return Patch(color=self.color * intensity)
        return Patch()

    def pingpong(
        self,
        num_steps: Optional[int] = None,
        wrap: bool = True,
        lead: Optional[Union[float, Any]] = None,
        hold: Optional[Union[float, Any]] = None,
    ) -> PingPongChase:
        """Step back and forth through fixtures without repeating turnaround endpoints."""
        explicit = (num_steps is not None) or self._explicit_num_steps
        steps = self.num_steps if num_steps is None else num_steps
        return PingPongChase(
            self.color,
            self.step_duration,
            background=self.background,
            lead=self.lead if lead is None else lead,
            hold=self.hold if hold is None else hold,
            tail=self.tail,
            num_steps=steps,
            wrap=wrap,
            _explicit_num_steps=explicit,
        )


class PingPongChase(Clip):
    """Step back and forth through fixtures without repeating turnaround endpoints.

    In an N-fixture setup, plays the unrolled bounce sequence:
    0 -> 1 -> ... -> N-1 -> N-2 -> ... -> 1 (a cycle of 2 * (N - 1) steps).
    The end fixtures (0 and N-1) bounce immediately on the very next step
    instead of being triggered twice consecutively.
    """

    def __init__(
        self,
        color: Union[Color, float] = Color.WHITE,
        step_duration: Union[float, Any] = 0.25,
        *,
        background: Optional[Union[Color, float]] = Color.BLACK,
        lead: Union[float, Any] = 0.0,
        hold: Union[float, Any] = 0.0,
        tail: Union[float, Any] = 0.0,
        num_steps: Optional[int] = None,
        wrap: bool = True,
        _explicit_num_steps: Optional[bool] = None,
    ) -> None:
        self.color = Color(color, color, color) if isinstance(color, (int, float)) else color
        if isinstance(background, (int, float)):
            self.background: Optional[Color] = Color(background, background, background)
        else:
            self.background = background
        self.step_duration = step_duration if hasattr(step_duration, "seconds") else float(step_duration)
        self.lead = lead if hasattr(lead, "seconds") else max(0.0, float(lead))
        self.hold = hold if hasattr(hold, "seconds") else max(0.0, float(hold))
        self.tail = tail if hasattr(tail, "seconds") else max(0.0, float(tail))
        self._explicit_num_steps = (num_steps is not None) if _explicit_num_steps is None else _explicit_num_steps
        self.num_steps = 4 if num_steps is None else max(1, int(num_steps))
        self.bounce_steps = 2 * (self.num_steps - 1) if self.num_steps > 1 else 1
        self.duration = self.step_duration * self.bounce_steps
        self.wrap = wrap

    def with_duration(self, target_duration: Union[float, Any]) -> PingPongChase:
        new_step = target_duration / self.bounce_steps
        c = PingPongChase(
            self.color,
            new_step,
            background=self.background,
            lead=self.lead,
            hold=self.hold,
            tail=self.tail,
            num_steps=self.num_steps,
            wrap=self.wrap,
            _explicit_num_steps=self._explicit_num_steps,
        )
        c._target_duration = target_duration
        return c

    def with_fixture_count(self, count: int) -> PingPongChase:
        if self._explicit_num_steps:
            return self
        bounce_steps = 2 * (count - 1) if count > 1 else 1
        if hasattr(self, "_target_duration") and self._target_duration is not None:
            new_step = self._target_duration / bounce_steps
        else:
            new_step = self.step_duration
        c = PingPongChase(
            self.color,
            new_step,
            background=self.background,
            lead=self.lead,
            hold=self.hold,
            tail=self.tail,
            num_steps=count,
            wrap=self.wrap,
            _explicit_num_steps=False,
        )
        if hasattr(self, "_target_duration"):
            c._target_duration = self._target_duration
        return c

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        n = max(1, total_fixtures)
        if n <= 1:
            return Patch(color=self.color)
        m = n - 1
        cycle_steps = 2 * m
        dur = float(self.duration)
        step_dt = (dur / cycle_steps) if dur > 0 else float(self.step_duration)
        period = dur if dur > 0 else (cycle_steps * step_dt)
        if period <= 0:
            return Patch(color=self.color)

        local_t = t % period if (self.wrap or t >= period) else t
        if local_t < 0:
            local_t = 0.0

        trigs = [fixture * step_dt]
        if 0 < fixture < m:
            trigs.append((cycle_steps - fixture) * step_dt)

        if step_dt > 0:
            eff_hold = (float(self.hold.seconds) / step_dt) if hasattr(self.hold, "seconds") else float(self.hold)
            eff_lead = (float(self.lead.seconds) / step_dt) if hasattr(self.lead, "seconds") else float(self.lead)
            eff_tail = (float(self.tail.seconds) / step_dt) if hasattr(self.tail, "seconds") else float(self.tail)
        else:
            eff_hold, eff_lead, eff_tail = float(self.hold), float(self.lead), float(self.tail)

        if eff_lead <= 0.0 and eff_hold <= 0.0 and eff_tail <= 0.0:
            for tr in trigs:
                if self.wrap:
                    dt = (local_t - tr) % period
                    if dt > period - 1e-9:
                        dt = 0.0
                    if 0.0 <= dt < step_dt - 1e-9:
                        return Patch(color=self.color)
                else:
                    dt = local_t - tr
                    if -1e-9 <= dt < step_dt - 1e-9:
                        return Patch(color=self.color)
            return Patch(color=self.background) if self.background is not None else Patch()

        intensity = 0.0
        decay_span = eff_tail if (hasattr(self.tail, "seconds") or eff_hold > 0.0 or eff_lead > 0.0) else (1.0 + eff_tail)
        for tr in trigs:
            if self.wrap:
                # 1. Tail and Hold (time elapsed since hit)
                dt_since = (local_t - tr) % period
                if dt_since > period - 1e-9:
                    dt_since = 0.0
                d_steps = dt_since / step_dt
                if d_steps <= eff_hold:
                    intensity = max(intensity, 1.0)
                elif decay_span > 0.0 and (d_steps - eff_hold) <= decay_span:
                    intensity = max(intensity, 1.0 - (d_steps - eff_hold) / decay_span)

                # 2. Lead ramp-in (time until hit)
                if eff_lead > 0.0:
                    dt_until = (tr - local_t) % period
                    if dt_until > period - 1e-9:
                        dt_until = 0.0
                    d_ahead = dt_until / step_dt
                    if 0.0 <= d_ahead <= eff_lead:
                        intensity = max(intensity, 1.0 - d_ahead / eff_lead)
            else:
                # 1. Tail and Hold
                dt_since = local_t - tr
                if -1e-9 <= dt_since < 0.0:
                    dt_since = 0.0
                if dt_since >= 0.0:
                    d_steps = dt_since / step_dt
                    if d_steps <= eff_hold:
                        intensity = max(intensity, 1.0)
                    elif decay_span > 0.0 and (d_steps - eff_hold) <= decay_span:
                        intensity = max(intensity, 1.0 - (d_steps - eff_hold) / decay_span)

                # 2. Lead ramp-in
                if eff_lead > 0.0:
                    dt_until = tr - local_t
                    if -1e-9 <= dt_until < 0.0:
                        dt_until = 0.0
                    if dt_until >= 0.0:
                        d_ahead = dt_until / step_dt
                        if d_ahead <= eff_lead:
                            intensity = max(intensity, 1.0 - d_ahead / eff_lead)

        if self.background is not None:
            return Patch(color=self.background.lerp(self.color, intensity))
        if intensity > 0.0:
            return Patch(color=self.color * intensity)
        return Patch()


class Gradient(Clip):
    """Cycle smoothly through a sequence of colors over `duration` seconds."""

    def __init__(self, colors: SeqType[Color], duration: Union[float, Any] = 4.0) -> None:
        if len(colors) < 2:
            raise ValueError("Gradient requires at least 2 colors.")
        self.colors = list(colors)
        self.duration = duration

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        dur = float(self.duration)
        u = 0.0 if dur <= 0 else max(0.0, min(1.0, t / dur))
        segments = len(self.colors) - 1
        scaled = u * segments
        idx = min(segments - 1, int(scaled))
        frac = scaled - idx
        c = self.colors[idx].lerp(self.colors[idx + 1], frac)
        return Patch(color=c)

    def with_duration(self, target_duration: Union[float, Any]) -> Gradient:
        return Gradient(self.colors, duration=target_duration)


class FnClip(Clip):
    """Custom functional clip from any callable `(t, fixture, total_fixtures) -> Patch | Color`."""

    def __init__(
        self,
        fn: Callable[[float, int, int], Union[Patch, Color]],
        duration: Union[float, Any] = inf,
    ) -> None:
        self.fn = fn
        self.duration = duration

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

    def __init__(self, kelvin: float, brightness: float = 1.0, duration: Union[float, Any] = inf) -> None:
        self.kelvin = float(kelvin)
        self.brightness = float(brightness)
        self.duration = duration
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
        duration: Union[float, Any] = 1.0,
        brightness: float = 1.0,
        ease: Callable[[float], float] = Ease.in_out_sine,
    ) -> None:
        self.start_k = float(start_k)
        self.end_k = float(end_k)
        self.duration = duration
        self.brightness = float(brightness)
        self.ease_fn = ease

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        dur = float(self.duration)
        progress = max(0.0, min(1.0, t / dur)) if dur > 0 else 1.0
        eased = self.ease_fn(progress)
        k = self.start_k + (self.end_k - self.start_k) * eased
        ww, cw = kelvin_to_ww_cw(k, self.brightness)
        return Patch(channels={"ww": ww, "cw": cw, "w": cw})


# =============================================================================
# Pseudo-Random Noise, Flame Flicker & Relative HSV Modulators
# =============================================================================


def _hash1d(n: int, seed: int = 0) -> float:
    """Deterministic integer hash returning float in [0.0, 1.0]."""
    x = (int(n) ^ (int(seed) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x >> 16) ^ x) * 0x45D9F3B
    x = ((x >> 16) ^ x) * 0x45D9F3B
    x = (x >> 16) ^ x
    return (x & 0xFFFFFFFF) / 4294967295.0


def smooth_noise1d(x: float, seed: int = 0) -> float:
    """Continuous 1D value noise with quintic Hermite interpolation, returning [0.0, 1.0]."""
    i0 = math.floor(x)
    i1 = i0 + 1
    f = x - i0
    # Ken Perlin's Improved quintic curve: 6t^5 - 15t^4 + 10t^3 (zero 1st & 2nd derivatives at knots)
    u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0)
    v0 = _hash1d(i0, seed)
    v1 = _hash1d(i1, seed)
    return v0 + (v1 - v0) * u


def fbm_noise1d(
    x: float,
    octaves: int = 3,
    seed: int = 0,
    lacunarity: float = 2.0,
    gain: float = 0.5,
) -> float:
    """Continuous 1D Fractal Brownian Motion (fBm) noise returning [0.0, 1.0].

    Sum of `octaves` harmonics of `smooth_noise1d`, normalized to [0.0, 1.0].
    """
    val = 0.0
    amp = 1.0
    freq = 1.0
    total_amp = 0.0
    for k in range(max(1, int(octaves))):
        val += amp * smooth_noise1d(x * freq, seed + k * 1013)
        total_amp += amp
        amp *= gain
        freq *= lacunarity
    return val / total_amp


class Noise(Clip):
    """Continuous 1D fractal Brownian motion (fBm) noise clip.

    Evaluates to a normalized scalar in `[min_val, max_val]`, accessible
    as a `'value'` channel in `Patch` or via `.sample(t, fixture)`.

    Args:
        speed: Frequency of noise changes (Hz/units per second).
        min_val: Output minimum.
        max_val: Output maximum.
        octaves: Detail octaves for fractal noise (1 = smooth, 4 = chaotic).
        seed: Deterministic integer seed.
        decorrelate: Spatial offset per fixture index.
        duration: Clip duration (default: inf).
    """

    def __init__(
        self,
        speed: float = 1.0,
        min_val: float = 0.0,
        max_val: float = 1.0,
        *,
        octaves: int = 3,
        seed: int = 0,
        decorrelate: float = 17.13,
        duration: float = inf,
    ) -> None:
        self.speed = float(speed)
        self.min_val = float(min_val)
        self.max_val = float(max_val)
        self.octaves = max(1, int(octaves))
        self.seed = int(seed)
        self.decorrelate = float(decorrelate)
        self.duration = duration

    def sample(self, t: float, fixture: int = 0) -> float:
        x = t * self.speed + fixture * self.decorrelate
        n = fbm_noise1d(x, octaves=self.octaves, seed=self.seed)
        return self.min_val + (self.max_val - self.min_val) * n

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        val = self.sample(t, fixture)
        return Patch.from_channel("value", val)


class Flicker(Clip):
    """Organic continuous pseudo-random intensity / flame flicker.

    Can be used:
      1. As a wrapper around another clip: `Flicker(base_clip, depth=0.5)` or `base_clip.flicker()`
      2. As a standalone layer: `base_clip | Flicker(depth=0.5)`
      3. For a dedicated channel: `ch("dimmer", Flicker(depth=0.5))`

    Args:
        child: Optional child clip to modulate.
        speed: Frequency of flicker fluctuations (default: 12.0 Hz).
        depth: Modulation depth in [0.0, 1.0] (0.5 means brightness dips by up to 50%).
        low: Optional explicit minimum intensity floor (overrides `depth`).
        high: Maximum intensity peak (default: 1.0).
        octaves: Detail octaves for fractal noise (default: 3).
        seed: Deterministic integer seed.
        decorrelate: Phase offset per fixture so fixtures flicker independently (default: 13.37).
        duration: Clip duration (defaults to child's duration or inf).
    """

    def __init__(
        self,
        child: Optional[Clip] = None,
        *,
        speed: float = 12.0,
        depth: float = 0.5,
        low: Optional[float] = None,
        high: float = 1.0,
        octaves: int = 3,
        seed: int = 101,
        decorrelate: float = 13.37,
        duration: float = inf,
    ) -> None:
        self.child = child
        self.speed = float(speed)
        self.depth = float(depth)
        self.high = float(high)
        self.low = float(high * (1.0 - depth) if low is None else low)
        self.octaves = max(1, int(octaves))
        self.seed = int(seed)
        self.decorrelate = float(decorrelate)
        self.duration = child.duration if child is not None else duration

    def sample_factor(self, t: float, fixture: int = 0) -> float:
        x = t * self.speed + fixture * self.decorrelate
        n = fbm_noise1d(x, octaves=self.octaves, seed=self.seed)
        return max(0.0, min(1.0, self.low + (self.high - self.low) * n))

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        factor = self.sample_factor(t, fixture)
        if self.child is not None:
            child_patch = self.child.eval(t, fixture, total_fixtures)
            new_color = (child_patch.color * factor) if child_patch.color is not None else None
            new_channels = dict(child_patch.channels)
            if "dimmer" in new_channels:
                new_channels["dimmer"] = max(0.0, min(1.0, new_channels["dimmer"] * factor))
            elif "value" in new_channels:
                new_channels["value"] = max(0.0, min(1.0, new_channels["value"] * factor))
            dimmer_scale = child_patch.dimmer_scale * factor if child_patch.color is None and not new_channels else 1.0
            return Patch(
                color=new_color,
                channels=new_channels,
                hsv_offset=child_patch.hsv_offset,
                dimmer_scale=dimmer_scale,
            )
        else:
            return Patch(
                channels={"dimmer": factor, "value": factor},
                dimmer_scale=factor,
            )

    def with_fixture_count(self, count: int) -> Flicker:
        if self.child is not None:
            new_child = self.child.with_fixture_count(count)
            if new_child is self.child:
                return self
            return Flicker(
                new_child,
                speed=self.speed,
                depth=self.depth,
                low=self.low,
                high=self.high,
                octaves=self.octaves,
                seed=self.seed,
                decorrelate=self.decorrelate,
                duration=self.duration,
            )
        return self


class HueShift(Clip):
    """Relative HSV shift and hue jitter clip.

    Can be used:
      1. As a wrapper around another clip: `HueShift(base_clip, dh=0.1)` or `base_clip.jitter_hue()`
      2. As a standalone layer: `base_clip | HueShift(dh=0.1)` or `base_clip | HueShift(amount=0.06, speed=3.0)`

    Args:
        child: Optional child clip to modulate.
        dh: Static float hue delta or dynamic `Clip` (e.g. `Noise(...)`).
        ds: Saturation delta in [-1.0, 1.0].
        dv: Value/brightness delta in [-1.0, 1.0].
        amount: If > 0, generates continuous pseudo-random hue jitter in `[-amount, +amount]`.
        speed: Frequency of hue jitter (when `amount > 0`).
        octaves: Detail octaves for hue jitter noise.
        seed: Deterministic integer seed.
        decorrelate: Spatial offset per fixture index for hue jitter.
        dimmer_scale: Scaling factor for dimmer/brightness.
        duration: Duration of this clip.
    """

    def __init__(
        self,
        child: Optional[Clip] = None,
        *,
        dh: Union[float, Clip] = 0.0,
        ds: float = 0.0,
        dv: float = 0.0,
        amount: float = 0.0,
        speed: float = 3.0,
        octaves: int = 2,
        seed: int = 202,
        decorrelate: float = 11.23,
        dimmer_scale: float = 1.0,
        duration: float = inf,
    ) -> None:
        self.child = child
        self.dh_input = dh
        self.ds = float(ds)
        self.dv = float(dv)
        self.amount = float(amount)
        self.speed = float(speed)
        self.octaves = max(1, int(octaves))
        self.seed = int(seed)
        self.decorrelate = float(decorrelate)
        self.dimmer_scale = float(dimmer_scale)

        if child is not None:
            self.duration = child.duration
        elif isinstance(dh, Clip):
            self.duration = dh.duration
        else:
            self.duration = duration

    def sample_dh(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> float:
        if self.amount > 0.0:
            x = t * self.speed + fixture * self.decorrelate
            n = fbm_noise1d(x, octaves=self.octaves, seed=self.seed)
            return (n - 0.5) * 2.0 * self.amount
        if isinstance(self.dh_input, Clip):
            p = self.dh_input.eval(t, fixture, total_fixtures)
            return p.get("value", 0.0)
        return float(self.dh_input)

    def eval(self, t: float, fixture: int = 0, total_fixtures: int = 4) -> Patch:
        cur_dh = self.sample_dh(t, fixture, total_fixtures)
        if self.child is not None:
            child_patch = self.child.eval(t, fixture, total_fixtures)
            if child_patch.color is not None:
                new_color = child_patch.color.shift_hsv(cur_dh, self.ds, self.dv)
                if self.dimmer_scale != 1.0:
                    new_color = new_color * self.dimmer_scale
                merged_channels = dict(child_patch.channels)
                if self.dimmer_scale != 1.0 and "dimmer" in merged_channels:
                    merged_channels["dimmer"] = max(0.0, min(1.0, merged_channels["dimmer"] * self.dimmer_scale))
                return Patch(color=new_color, channels=merged_channels)
            else:
                prev_dh, prev_ds, prev_dv = child_patch.hsv_offset if child_patch.hsv_offset else (0.0, 0.0, 0.0)
                return Patch(
                    color=None,
                    channels=child_patch.channels,
                    hsv_offset=(prev_dh + cur_dh, prev_ds + self.ds, prev_dv + self.dv),
                    dimmer_scale=child_patch.dimmer_scale * self.dimmer_scale,
                )
        else:
            return Patch.from_hsv_offset(
                dh=cur_dh,
                ds=self.ds,
                dv=self.dv,
                dimmer_scale=self.dimmer_scale,
            )

    def with_fixture_count(self, count: int) -> HueShift:
        if self.child is not None:
            new_child = self.child.with_fixture_count(count)
            if new_child is self.child:
                return self
            return HueShift(
                new_child,
                dh=self.dh_input,
                ds=self.ds,
                dv=self.dv,
                amount=self.amount,
                speed=self.speed,
                octaves=self.octaves,
                seed=self.seed,
                decorrelate=self.decorrelate,
                dimmer_scale=self.dimmer_scale,
                duration=self.duration,
            )
        return self
