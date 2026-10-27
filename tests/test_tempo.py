"""Unit tests for musical tempo, beat clock, and dynamic timing abstractions."""

import math
import time
import unittest

from lightshow import (
    Chase,
    Color,
    Fade,
    FixtureGroup,
    Hold,
    MusicalDuration,
    Patch,
    PingPongChase,
    Pulse,
    RGB,
    Rig,
    Sequence,
    Tempo,
    bars,
    beats,
    get_tempo,
    set_bpm,
)
from lightshow.jupyter import LiveStream


def make_test_group(count: int = 4) -> FixtureGroup:
    """Create a 4-channel RGBW test fixture group."""
    elements = []
    for i in range(count):
        base = 1 + i * 4
        elements.append({
            "color": RGB(base),
            "w": base + 3,
        })
    return FixtureGroup(f"TEST_{count}", elements)


class TestTempo(unittest.TestCase):
    """Test Tempo, MusicalDuration, subdivisions, and tap tempo."""

    def test_tempo_initialization_and_subdivisions(self) -> None:
        t = Tempo(120.0, time_signature=(4, 4))
        self.assertEqual(t.bpm, 120.0)
        self.assertEqual(t.time_signature, (4, 4))

        # At 120 BPM: 1 beat = 0.5s, 1 bar = 2.0s
        self.assertAlmostEqual(float(t.beat), 0.5)
        self.assertAlmostEqual(float(t.bar), 2.0)
        self.assertAlmostEqual(float(t.quarter), 0.5)
        self.assertAlmostEqual(float(t.half), 1.0)
        self.assertAlmostEqual(float(t.whole), 2.0)
        self.assertAlmostEqual(float(t.eighth), 0.25)
        self.assertAlmostEqual(float(t.sixteenth), 0.125)
        self.assertAlmostEqual(float(t.thirtysecond), 0.0625)

        # Polyrhythms / triplets and dotted notes
        # 8th note triplet = 1/3 beat = 0.5 / 3 = 0.1666...s
        self.assertAlmostEqual(float(t.triplet(8)), 0.5 / 3.0)
        # Dotted quarter = 1.5 beats = 0.75s
        self.assertAlmostEqual(float(t.dotted(4)), 0.75)

    def test_dynamic_bpm_update_and_callbacks(self) -> None:
        t = Tempo(120.0)
        b = t.beats(2.0)
        self.assertAlmostEqual(float(b), 1.0)

        # Change BPM
        history = []
        t.on_change(lambda old, new: history.append((old, new)))
        t.bpm = 240.0

        self.assertEqual(t.bpm, 240.0)
        self.assertEqual(history, [(120.0, 240.0)])
        # At 240 BPM: 2 beats = 0.5s
        self.assertAlmostEqual(float(b), 0.5)

    def test_tap_tempo_averaging(self) -> None:
        t = Tempo(100.0)
        # Simulate tapping at 0.5s intervals (120 BPM)
        t.tap(timestamp=10.0)
        t.tap(timestamp=10.5)
        t.tap(timestamp=11.0)
        t.tap(timestamp=11.5)

        self.assertAlmostEqual(t.bpm, 120.0, places=1)

    def test_musical_duration_arithmetic_and_comparisons(self) -> None:
        t = Tempo(120.0)
        d1 = t.beats(1.0)  # 0.5s
        d2 = t.beats(2.0)  # 1.0s

        # Addition
        d3 = d1 + d2
        self.assertEqual(d3.beats, 3.0)
        self.assertAlmostEqual(float(d3), 1.5)

        # Mixed addition with float seconds (0.5s = 1 beat at 120 BPM)
        d4 = d1 + 0.5
        self.assertAlmostEqual(d4.beats, 2.0)
        self.assertAlmostEqual(float(d4), 1.0)

        # Multiplication
        d5 = d1 * 4
        self.assertEqual(d5.beats, 4.0)
        self.assertAlmostEqual(float(d5), 2.0)

        # Division
        ratio = d2 / d1
        self.assertAlmostEqual(ratio, 2.0)
        d_div = d2 / 2
        self.assertAlmostEqual(d_div.beats, 1.0)

        # Comparisons
        self.assertTrue(d1 < d2)
        self.assertTrue(d1 <= d2)
        self.assertTrue(d2 > d1)
        self.assertTrue(d2 >= d1)
        self.assertTrue(d1 == 0.5)
        self.assertTrue(d2 == 1.0)
        self.assertFalse(d1 == d2)

        # Formatting
        self.assertEqual(f"{d1:.2f}s", "0.50s")

    def test_active_tempo_helpers(self) -> None:
        set_bpm(120.0)
        self.assertEqual(get_tempo().bpm, 120.0)

        b = beats(4.0)
        bar = bars(1.0)
        self.assertAlmostEqual(float(b), 2.0)
        self.assertAlmostEqual(float(bar), 2.0)

        set_bpm(60.0)
        self.assertAlmostEqual(float(b), 4.0)
        self.assertAlmostEqual(float(bar), 4.0)

        # Reset back to 120
        set_bpm(120.0)


class TestClipTempoIntegration(unittest.TestCase):
    """Test clips and scenes with musical durations."""

    def setUp(self) -> None:
        self.t = Tempo(120.0)
        self.pars = make_test_group(4)

    def test_pulse_with_beats_duration(self) -> None:
        # 1-beat pulse at 120 BPM (0.5s duration)
        p = Pulse(Color.RED, duration=self.t.beats(1.0))
        self.assertAlmostEqual(p.duration, 0.5)
        self.assertEqual(p.duration_beats, 1.0)

        # Evaluated at peak (0.25s)
        patch = p.eval(0.25)
        self.assertAlmostEqual(patch.color.r, 1.0)

        # Change BPM to 240: duration dynamically halves to 0.25s!
        self.t.bpm = 240.0
        self.assertAlmostEqual(p.duration, 0.25)

        # Peak is now at 0.125s
        patch_new_peak = p.eval(0.125)
        self.assertAlmostEqual(patch_new_peak.color.r, 1.0)

    def test_chase_with_beats_step_duration(self) -> None:
        # Chase with 16th note steps (0.125s at 120 BPM)
        chase = Chase(Color.CYAN, step_duration=self.t.sixteenth, num_steps=4)
        self.assertAlmostEqual(chase.duration, 0.5)

        # At 240 BPM, step_duration is 0.0625s, total duration is 0.25s
        self.t.bpm = 240.0
        self.assertAlmostEqual(chase.duration, 0.25)

    def test_composite_sequence_and_scene_dynamic_duration(self) -> None:
        p1 = Pulse(Color.RED, duration=self.t.beats(1.0))
        p2 = Pulse(Color.BLUE, duration=self.t.beats(1.0))
        scene = self.pars([p1, p2])

        # 2 beats at 120 BPM = 1.0s
        self.assertAlmostEqual(scene.duration, 1.0)

        # Speed up to 240 BPM
        self.t.bpm = 240.0
        self.assertAlmostEqual(scene.duration, 0.5)

        # Sequence of scenes
        s1 = self.pars(Hold(Color.GREEN, duration=self.t.bars(1.0)))
        s2 = self.pars(Hold(Color.AMBER, duration=self.t.bars(1.0)))
        show = Sequence([s1, s2])

        # 2 bars at 240 BPM (4 beats/bar = 8 beats total = 2.0s)
        self.assertAlmostEqual(show.duration, 2.0)

        # Slow down to 60 BPM (8 beats = 8.0s)
        self.t.bpm = 60.0
        self.assertAlmostEqual(show.duration, 8.0)

    def test_repeat_with_musical_duration(self) -> None:
        cue = self.pars(Pulse(Color.WHITE, duration=self.t.beats(1.0)))
        # Repeat until 4 bars
        loop = cue * self.t.bars(4.0)
        # 4 bars at 120 BPM = 16 beats = 8.0s
        self.assertAlmostEqual(loop.duration, 8.0)

    def test_mixing_fixed_seconds_and_musical_beats(self) -> None:
        # Musical pulse (1 beat) layered with a fixed 0.1s strobe
        pulse = Pulse(Color.PURPLE, duration=self.t.beats(1.0))
        strobe = Hold(Color.WHITE, strobe=0.9, duration=0.1)
        mixed = self.pars(pulse | strobe)

        # At 120 BPM, max(0.5, 0.1) = 0.5s
        self.assertAlmostEqual(mixed.duration, 0.5)

        # At 1200 BPM (extreme), 1 beat = 0.05s, max(0.05, 0.1) = 0.1s (strobe stays 0.1s!)
        self.t.bpm = 1200.0
        self.assertAlmostEqual(mixed.duration, 0.1)


class TestLiveStreamTempoSync(unittest.TestCase):
    """Test LiveStream integration with Tempo and phase continuity."""

    def test_livestream_tempo_phase_continuity(self) -> None:
        t = Tempo(120.0)
        pars = make_test_group(4)
        scene = pars(Pulse(Color.BLUE, duration=t.bars(1.0))) * 4
        # Total duration = 4 bars = 16 beats = 8.0s at 120 BPM

        stream = LiveStream(scene, Rig([pars], dry_run=True), tempo=t)
        self.assertEqual(stream.tempo, t)

        # Simulate 1.0s elapsed into the show (12.5% through the 8.0s show)
        now = time.monotonic()
        stream._start_time = now - 1.0
        elapsed_before = now - stream._start_time
        progress_before = (elapsed_before % scene.duration) / scene.duration
        self.assertAlmostEqual(progress_before, 1.0 / 8.0)

        # Change BPM to 240.0: duration changes to 4.0s
        t.bpm = 240.0
        self.assertAlmostEqual(scene.duration, 4.0)

        # Check that loop progress immediately after change is PRESERVED!
        elapsed_after = now - stream._start_time
        progress_after = (elapsed_after % scene.duration) / scene.duration
        self.assertAlmostEqual(progress_after, progress_before, places=5)

    def test_livestream_auto_tempo_detection(self) -> None:
        t = Tempo(135.0)
        pars = make_test_group(4)
        scene = pars(Chase(Color.MAGENTA, step_duration=t.sixteenth))
        # Did not pass tempo explicitly:
        stream = LiveStream(scene, Rig([pars], dry_run=True))
        self.assertEqual(stream.tempo, t)
        self.assertEqual(stream.tempo.bpm, 135.0)


if __name__ == "__main__":
    unittest.main()
