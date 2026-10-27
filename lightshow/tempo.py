"""Musical tempo, beat clock, and dynamic timing abstractions for `lightshow`.

Enables composing lighting animations in musical time (bars, beats, subdivisions)
alongside fixed wall-clock seconds (for strobes, camera sync, and physics).

Key concepts:
  - `Tempo(bpm=120, time_signature=(4, 4))` : Beat clock and subdivision generator.
  - `MusicalDuration` : Live duration bound to a `Tempo`; dynamically updates in
    seconds when `tempo.bpm` changes at runtime.
  - `beats(count)` and `bars(count)` : Convenience helpers bound to active tempo.
  - Zero phase jump : Live streamer preserves loop phase when BPM is adjusted mid-play.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable, Optional, Union


class MusicalDuration:
    """A duration expressed in musical beats, dynamically bound to a `Tempo`.

    Behaves numerically like a float (seconds) in math and comparisons, but
    evaluates dynamically against its parent `Tempo`'s current BPM.
    """

    __slots__ = ("_beats", "_tempo")

    def __init__(self, beats: float, tempo: Optional[Tempo] = None) -> None:
        self._beats = float(beats)
        self._tempo = tempo if tempo is not None else get_tempo()

    @property
    def beats(self) -> float:
        """Duration in musical beats."""
        return self._beats

    @property
    def tempo(self) -> Tempo:
        """The bound `Tempo` object."""
        return self._tempo

    @property
    def bpm(self) -> float:
        """Current BPM of the bound tempo."""
        return self._tempo.bpm

    @property
    def seconds(self) -> float:
        """Current duration in wall-clock seconds: `beats * (60.0 / bpm)`."""
        return self._beats * (60.0 / self._tempo.bpm)

    @property
    def bars(self) -> float:
        """Duration in bars according to tempo's time signature."""
        beats_per_bar = self._tempo.time_signature[0]
        return self._beats / beats_per_bar

    def __float__(self) -> float:
        return self.seconds

    def __int__(self) -> int:
        return int(self.seconds)

    def __repr__(self) -> str:
        return f"MusicalDuration({self._beats:g} beats @ {self._tempo.bpm:g} BPM = {self.seconds:.3f}s)"

    def __format__(self, format_spec: str) -> str:
        return format(self.seconds, format_spec)

    # -------------------------------------------------------------------------
    # Arithmetic Operators
    # -------------------------------------------------------------------------

    def __add__(self, other: Union[MusicalDuration, float, int]) -> MusicalDuration:
        if isinstance(other, MusicalDuration):
            return MusicalDuration(self._beats + other._beats, tempo=self._tempo)
        # Raw seconds added: convert seconds to beats at current BPM
        beats_to_add = float(other) * (self._tempo.bpm / 60.0)
        return MusicalDuration(self._beats + beats_to_add, tempo=self._tempo)

    def __radd__(self, other: Union[float, int]) -> MusicalDuration:
        return self.__add__(other)

    def __sub__(self, other: Union[MusicalDuration, float, int]) -> MusicalDuration:
        if isinstance(other, MusicalDuration):
            return MusicalDuration(self._beats - other._beats, tempo=self._tempo)
        beats_to_sub = float(other) * (self._tempo.bpm / 60.0)
        return MusicalDuration(self._beats - beats_to_sub, tempo=self._tempo)

    def __rsub__(self, other: Union[float, int]) -> MusicalDuration:
        beats_other = float(other) * (self._tempo.bpm / 60.0)
        return MusicalDuration(beats_other - self._beats, tempo=self._tempo)

    def __mul__(self, factor: Union[float, int]) -> MusicalDuration:
        return MusicalDuration(self._beats * float(factor), tempo=self._tempo)

    def __rmul__(self, factor: Union[float, int]) -> MusicalDuration:
        return self.__mul__(factor)

    def __truediv__(self, divisor: Union[MusicalDuration, float, int]) -> Union[float, MusicalDuration]:
        if isinstance(divisor, MusicalDuration):
            return self._beats / divisor._beats
        return MusicalDuration(self._beats / float(divisor), tempo=self._tempo)

    def __rtruediv__(self, dividend: Any) -> float:
        sec = self.seconds
        return float(dividend) / sec if sec > 0 else 0.0

    def __mod__(self, divisor: Union[MusicalDuration, float, int]) -> float:
        div_sec = float(divisor)
        return self.seconds % div_sec if div_sec > 0 else 0.0

    def __rmod__(self, dividend: Any) -> float:
        sec = self.seconds
        return float(dividend) % sec if sec > 0 else 0.0

    def __neg__(self) -> MusicalDuration:
        return MusicalDuration(-self._beats, tempo=self._tempo)

    def __abs__(self) -> MusicalDuration:
        return MusicalDuration(abs(self._beats), tempo=self._tempo)

    # -------------------------------------------------------------------------
    # Rich Comparisons (compared in seconds for natural mixing with floats)
    # -------------------------------------------------------------------------

    def __lt__(self, other: Any) -> bool:
        return self.seconds < float(other)

    def __le__(self, other: Any) -> bool:
        return self.seconds <= float(other)

    def __gt__(self, other: Any) -> bool:
        return self.seconds > float(other)

    def __ge__(self, other: Any) -> bool:
        return self.seconds >= float(other)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, MusicalDuration):
            return self._beats == other._beats and self._tempo.bpm == other._tempo.bpm
        return math.isclose(self.seconds, float(other), rel_tol=1e-9, abs_tol=1e-9)

    def __hash__(self) -> int:
        return hash((self._beats, id(self._tempo)))


class Tempo:
    """Musical tempo manager and beat-clock generator.

    Provides musical subdivision durations (`quarter`, `eighth`, `sixteenth`, `bars(2)`),
    tap-tempo averaging, and runtime dynamic BPM modulation with zero-glitch phase preservation.
    """

    def __init__(self, bpm: float = 120.0, time_signature: tuple[int, int] = (4, 4)) -> None:
        self._bpm = max(1.0, float(bpm))
        self.time_signature = (max(1, int(time_signature[0])), max(1, int(time_signature[1])))
        self._callbacks: list[Callable[[float, float], None]] = []
        self._lock = threading.Lock()
        self._tap_history: list[float] = []

    # -------------------------------------------------------------------------
    # BPM Property & Change Notifications
    # -------------------------------------------------------------------------

    @property
    def bpm(self) -> float:
        """Current tempo in Beats Per Minute (BPM)."""
        with self._lock:
            return self._bpm

    @bpm.setter
    def bpm(self, val: float) -> None:
        new_bpm = max(1.0, float(val))
        with self._lock:
            old_bpm = self._bpm
            if math.isclose(old_bpm, new_bpm, abs_tol=1e-6):
                return
            self._bpm = new_bpm
            callbacks = list(self._callbacks)

        for cb in callbacks:
            try:
                cb(old_bpm, new_bpm)
            except Exception:
                pass

    def on_change(self, callback: Callable[[float, float], None]) -> None:
        """Register a callback `callback(old_bpm, new_bpm)` invoked when BPM changes."""
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[float, float], None]) -> None:
        """Remove a previously registered BPM change callback."""
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    # -------------------------------------------------------------------------
    # Duration Generators (Beats & Bars)
    # -------------------------------------------------------------------------

    def beats(self, count: float = 1.0) -> MusicalDuration:
        """Return a duration of `count` musical beats."""
        return MusicalDuration(count, tempo=self)

    def bars(self, count: float = 1.0) -> MusicalDuration:
        """Return a duration of `count` musical bars (e.g. 4 beats per bar in 4/4)."""
        beats_per_bar = self.time_signature[0]
        return MusicalDuration(count * beats_per_bar, tempo=self)

    # Note Subdivisions
    @property
    def whole(self) -> MusicalDuration:
        """Whole note duration (4 beats in 4/4)."""
        return self.beats(4.0)

    @property
    def half(self) -> MusicalDuration:
        """Half note duration (2 beats in 4/4)."""
        return self.beats(2.0)

    @property
    def quarter(self) -> MusicalDuration:
        """Quarter note duration (1 beat)."""
        return self.beats(1.0)

    @property
    def eighth(self) -> MusicalDuration:
        """Eighth note duration (0.5 beats)."""
        return self.beats(0.5)

    @property
    def sixteenth(self) -> MusicalDuration:
        """Sixteenth note duration (0.25 beats)."""
        return self.beats(0.25)

    @property
    def thirtysecond(self) -> MusicalDuration:
        """Thirty-second note duration (0.125 beats)."""
        return self.beats(0.125)

    # Shorthands
    @property
    def beat(self) -> MusicalDuration:
        """Alias for 1 beat (`self.beats(1.0)`)."""
        return self.beats(1.0)

    @property
    def bar(self) -> MusicalDuration:
        """Alias for 1 bar (`self.bars(1.0)`)."""
        return self.bars(1.0)

    def triplet(self, subdivision: int = 8) -> MusicalDuration:
        """Triplet duration for subdivision (e.g. 8 -> 8th note triplet = 1/3 beat)."""
        nominal_beats = 4.0 / subdivision
        return self.beats(nominal_beats * (2.0 / 3.0))

    def dotted(self, subdivision: int = 4) -> MusicalDuration:
        """Dotted duration (1.5x nominal note length, e.g. dotted quarter = 1.5 beats)."""
        nominal_beats = 4.0 / subdivision
        return self.beats(nominal_beats * 1.5)

    # -------------------------------------------------------------------------
    # Tap Tempo
    # -------------------------------------------------------------------------

    def tap(self, timestamp: Optional[float] = None) -> float:
        """Record a tap and update BPM using rolling average interval.

        Returns the newly updated BPM.
        """
        now = time.monotonic() if timestamp is None else float(timestamp)
        with self._lock:
            # Purge taps older than 3 seconds
            self._tap_history = [t for t in self._tap_history if now - t < 3.0]
            self._tap_history.append(now)

            if len(self._tap_history) >= 2:
                intervals = [
                    self._tap_history[i] - self._tap_history[i - 1]
                    for i in range(1, len(self._tap_history))
                ]
                avg_interval = sum(intervals) / len(intervals)
                if avg_interval > 0.05:  # filter debounce bounces
                    new_bpm = round(max(20.0, min(300.0, 60.0 / avg_interval)), 1)
                    old_bpm = self._bpm
                    self._bpm = new_bpm
                    callbacks = list(self._callbacks)
                else:
                    return self._bpm
            else:
                return self._bpm

        for cb in callbacks:
            try:
                cb(old_bpm, new_bpm)
            except Exception:
                pass

        return new_bpm

    def __repr__(self) -> str:
        return f"Tempo(bpm={self._bpm:g}, time_signature={self.time_signature})"


# =============================================================================
# Global / Default Active Tempo and Convenience Helpers
# =============================================================================

_DEFAULT_TEMPO = Tempo(120.0)


def get_tempo() -> Tempo:
    """Get the active default `Tempo` instance."""
    return _DEFAULT_TEMPO


def set_bpm(bpm: float) -> Tempo:
    """Set the BPM of the active default `Tempo`."""
    _DEFAULT_TEMPO.bpm = bpm
    return _DEFAULT_TEMPO


def beats(count: float = 1.0, tempo: Optional[Tempo] = None) -> MusicalDuration:
    """Create a `MusicalDuration` of `count` beats using `tempo` (or default active tempo)."""
    t = tempo or _DEFAULT_TEMPO
    return t.beats(count)


def bars(count: float = 1.0, tempo: Optional[Tempo] = None) -> MusicalDuration:
    """Create a `MusicalDuration` of `count` bars using `tempo` (or default active tempo)."""
    t = tempo or _DEFAULT_TEMPO
    return t.bars(count)


# =============================================================================
# Explicit Absolute Wall-Clock Timing (`abs`, `Abs`, `Seconds`)
# =============================================================================

import builtins


class AbsoluteDuration:
    """An explicit absolute duration in wall-clock seconds.

    When passed to clips (like `Chase(..., tail=abs(1.0))` or
    `Pulse(..., attack=abs(0.05))`), it explicitly declares that this
    parameter represents absolute seconds that should NOT scale when the clip
    is stretched or compressed via `@ target_duration`.
    """

    __slots__ = ("_seconds",)

    def __init__(self, s: Union[float, int, AbsoluteDuration, Any] = 1.0) -> None:
        if isinstance(s, AbsoluteDuration):
            self._seconds = s._seconds
        else:
            self._seconds = max(0.0, float(builtins.abs(float(s))))

    @property
    def seconds(self) -> float:
        return self._seconds

    @property
    def is_absolute(self) -> bool:
        return True

    def __float__(self) -> float:
        return self._seconds

    def __int__(self) -> int:
        return int(self._seconds)

    def __abs__(self) -> AbsoluteDuration:
        return self

    def __repr__(self) -> str:
        return f"abs({self._seconds:g}s)"

    def __format__(self, format_spec: str) -> str:
        return format(self._seconds, format_spec)

    def __add__(self, other: Any) -> AbsoluteDuration:
        return AbsoluteDuration(self._seconds + float(other))

    def __radd__(self, other: Any) -> AbsoluteDuration:
        return AbsoluteDuration(float(other) + self._seconds)

    def __sub__(self, other: Any) -> AbsoluteDuration:
        return AbsoluteDuration(max(0.0, self._seconds - float(other)))

    def __rsub__(self, other: Any) -> AbsoluteDuration:
        return AbsoluteDuration(max(0.0, float(other) - self._seconds))

    def __mul__(self, factor: Union[float, int]) -> AbsoluteDuration:
        return AbsoluteDuration(self._seconds * float(factor))

    def __rmul__(self, factor: Union[float, int]) -> AbsoluteDuration:
        return self.__mul__(factor)

    def __truediv__(self, divisor: Any) -> float:
        return self._seconds / float(divisor)

    def __rtruediv__(self, dividend: Any) -> float:
        return float(dividend) / self._seconds if self._seconds > 0 else 0.0

    def __mod__(self, divisor: Any) -> float:
        div = float(divisor)
        return self._seconds % div if div > 0 else 0.0

    def __rmod__(self, dividend: Any) -> float:
        return float(dividend) % self._seconds if self._seconds > 0 else 0.0

    def __lt__(self, other: Any) -> bool:
        return self._seconds < float(other)

    def __le__(self, other: Any) -> bool:
        return self._seconds <= float(other)

    def __gt__(self, other: Any) -> bool:
        return self._seconds > float(other)

    def __ge__(self, other: Any) -> bool:
        return self._seconds >= float(other)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, AbsoluteDuration):
            return self._seconds == other._seconds
        return math.isclose(self._seconds, float(other), rel_tol=1e-9, abs_tol=1e-9)

    def __hash__(self) -> int:
        return hash(self._seconds)


# Aliases for AbsoluteDuration
Abs = AbsoluteDuration
Absolute = AbsoluteDuration
Seconds = AbsoluteDuration
seconds = AbsoluteDuration
sec = AbsoluteDuration


def abs(target: Any = 1.0) -> Any:
    """Mark a Clip, Scene, or timing parameter as absolute (unscaled by time-stretching `@`).

    Examples:
      - In a sequence: `Seq[abs(intro), main_loop, abs(outro)] @ 10.0`
        (only `main_loop` will stretch to fill the 10.0s).
      - In a chase: `Chase(Color.WHITE, step_duration=beats(1), tail=abs(1.0))`
        (decay tail takes exactly 1.0s, unaffected by BPM or `@` scaling).
      - In a pulse: `Pulse(Color.RED, duration=1.0, attack=abs(0.05)) @ 5.0`
        (attack stays at 50ms while decay stretches).
    """
    if hasattr(target, "__abs__") and not isinstance(target, (int, float)):
        return target.__abs__()
    if isinstance(target, (int, float, AbsoluteDuration)):
        return AbsoluteDuration(builtins.abs(float(target)))
    return builtins.abs(target)


absolute = abs

