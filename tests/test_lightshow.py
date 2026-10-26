"""Unit tests for the composable RGB + Channel lightshow package."""

import struct
import unittest
from math import inf

from lightshow import (
    RGB,
    Channel,
    Chase,
    Color,
    Fade,
    FixtureGroup,
    Flicker,
    Gradient,
    Hold,
    HueShift,
    Noise,
    Patch,
    Rig,
    Strobe,
    build_artdmx_packet,
    ch,
    dim,
    fbm_noise1d,
    smooth_noise1d,
)
from my_rig import (
    PAR_DIMMERS,
    PAR_STROBES,
    PAR_WHITES,
    PARS,
    STROBE_BAR,
    STROBE_MASTER,
    STROBE_RGB,
    STROBE_W,
    create_rig,
)


class TestLightshow(unittest.TestCase):
    def test_channel_dmx_range_and_strobe_threshold(self) -> None:
        dmx = [0] * 6
        strobe_ch = Channel(6, dmx_range=(11, 255))
        strobe_ch.write(dmx, 0.0)
        self.assertEqual(dmx[5], 0)

        strobe_ch.write(dmx, 0.001)
        self.assertGreaterEqual(dmx[5], 11)

        strobe_ch.write(dmx, 1.0)
        self.assertEqual(dmx[5], 255)

    def test_artdmx_packet_structure_and_universe_config(self) -> None:
        pkt = build_artdmx_packet([255, 0, 128], universe=1, sequence=7)
        self.assertEqual(pkt[:8], b"Art-Net\x00")
        opcode = struct.unpack("<H", pkt[8:10])[0]
        self.assertEqual(opcode, 0x5000)
        prot_ver = struct.unpack(">H", pkt[10:12])[0]
        self.assertEqual(prot_ver, 14)
        self.assertEqual(pkt[12], 7)
        universe = struct.unpack("<H", pkt[14:16])[0]
        self.assertEqual(universe, 1)
        length = struct.unpack(">H", pkt[16:18])[0]
        self.assertEqual(length, 4)

        group = FixtureGroup("test", [Channel(i) for i in range(1, 5)])
        rig_direct = Rig([group], universe=1, universe_base=0, dry_run=True)
        self.assertEqual(rig_direct.client.wire_universe, 1)

        rig_zero_based = Rig([group], universe=1, universe_base=1, dry_run=True)
        self.assertEqual(rig_zero_based.client.wire_universe, 0)

    def test_algebraic_operators_and_fixture_channels(self) -> None:
        rig = Rig([PARS], dry_run=True)

        clip = (
            (Hold(Color.RED, duration=1.0).on(0, 2) | Hold(Color.BLUE, duration=1.0).on(1, 3))
            >> (Hold(Color.GREEN, duration=1.0) | Strobe(rate=0.5, duration=1.0))
        )
        self.assertEqual(clip.duration, 2.0)

        dmx_t0 = rig.render_dmx(clip, t=0.5)
        self.assertEqual(len(dmx_t0), 24)
        self.assertEqual(dmx_t0[0:6], [255, 0, 0, 0, 255, 0])
        self.assertEqual(dmx_t0[6:12], [0, 0, 255, 0, 255, 0])
        self.assertEqual(dmx_t0[12:18], [255, 0, 0, 0, 255, 0])
        self.assertEqual(dmx_t0[18:24], [0, 0, 255, 0, 255, 0])

        dmx_t1 = rig.render_dmx(clip, t=1.5)
        for offset in (0, 6, 12, 18):
            self.assertEqual(dmx_t1[offset : offset + 5], [0, 255, 0, 0, 255])
            self.assertGreater(dmx_t1[offset + 5], 10)

    def test_unified_and_split_views_composition(self) -> None:
        rig = create_rig(dry_run=True)

        # 1. Test driving STROBE_W (CW) and STROBE_RGB as split views with dim()
        # In 24ch mode: 4 segments (Ch 32..36, 37..41, 42..46, 47..51)
        dmx_split = rig.render_dmx(
            {
                PARS: Hold(Color.BLACK, duration=1.0),
                STROBE_W: dim(0.25, Hold(1.0, duration=1.0).on(0, 3)),
                STROBE_RGB: dim(0.35, Hold(Color.CYAN, duration=1.0).on(0, 3)),
            },
            t=0.5,
        )
        self.assertEqual(len(dmx_split), 52)
        # Seg 1 RGB (ch 32..34 -> indices 31..33): 0, 89, 89
        self.assertEqual(dmx_split[31:34], [0, 89, 89])
        # Seg 1 CW (ch 36 -> index 35): 64
        self.assertEqual(dmx_split[35], 64)

        # 2. Test driving STROBE_BAR as a unified RGB + WW + CW fixture
        unified_clip = (
            dim(0.35, Hold(Color.CYAN, duration=1.0).on(0, 3))
            | dim(0.25, ch("cw", Hold(1.0, duration=1.0).on(0, 3)))
        )
        dmx_unified = rig.render_dmx({STROBE_BAR: unified_clip}, t=0.5)
        self.assertEqual(dmx_unified[31:34], [0, 89, 89])
        self.assertEqual(dmx_unified[35], 64)

        # 3. Test driving sliced PAR sub-channels (PAR_WHITES, PAR_DIMMERS, PAR_STROBES)
        dmx_par_slices = rig.render_dmx(
            {
                PARS: Hold(Color.RED, duration=1.0),
                PAR_WHITES: Hold(0.5, duration=1.0).on(0),
                PAR_DIMMERS: Hold(0.5, duration=1.0),
                PAR_STROBES: Hold(1.0, duration=1.0).on(3),
            },
            t=0.5,
        )
        # PAR 1 (ch 1..6): R=255, G=0, B=0, W=128, Dimmer=128, Strobe=0
        self.assertEqual(dmx_par_slices[0:6], [255, 0, 0, 128, 128, 0])
        # PAR 4 (ch 19..24): R=255, G=0, B=0, W=0, Dimmer=128, Strobe=255
        self.assertEqual(dmx_par_slices[18:24], [255, 0, 0, 0, 128, 255])

        # 4. Test driving STROBE_MASTER at channel 52 (dmx index 51)
        dmx_master = rig.render_dmx({STROBE_MASTER: Hold(0.5, duration=1.0)}, t=0.5)
        self.assertEqual(dmx_master[51], 132)

    def test_combining_fixture_groups_with_plus_and_slicing(self) -> None:
        from my_rig import ALL_RGB, ALL_WHITES, PAR_RGB, STAGE_RGB, STROBE_RGB

        rig = create_rig(dry_run=True)

        # ALL_RGB = PAR_RGB (4) + STROBE_RGB (4) -> 8 RGB elements
        self.assertEqual(len(ALL_RGB), 8)
        self.assertEqual(len(ALL_WHITES), 8)
        self.assertEqual(len(STAGE_RGB), 8)

        # Drive index 0 (PAR 1) and index 7 (Strobe RGB 4) via ALL_RGB
        dmx = rig.render_dmx(
            {
                ALL_RGB: Hold(Color.MAGENTA, duration=1.0).on(0, 7),
            },
            t=0.5,
        )
        # PAR 1 (ch 1..6): R=255, G=0, B=255, W=0, Dimmer=255, Strobe=0
        self.assertEqual(dmx[0:6], [255, 0, 255, 0, 255, 0])
        # Strobe RGB 4 (ch 47..49 -> indices 46..48): R=255, G=0, B=255
        self.assertEqual(dmx[46:49], [255, 0, 255])

        # Test STAGE_RGB = PAR_RGB[:2] + STROBE_RGB + PAR_RGB[2:]
        # Index 0, 1 are PAR 1, 2; Index 2 is Strobe RGB 1; Index 7 is PAR 4
        dmx_stage = rig.render_dmx(
            {
                STAGE_RGB: Hold(Color.GREEN, duration=1.0).on(2, 7),
            },
            t=0.5,
        )
        # Strobe RGB 1 (ch 32..34 -> indices 31..33) is GREEN
        self.assertEqual(dmx_stage[31:34], [0, 255, 0])
        # PAR 4 (ch 19..24 -> indices 18..23) is GREEN with default Dimmer=255
        self.assertEqual(dmx_stage[18:24], [0, 255, 0, 0, 255, 0])

    def test_scene_conflict_resolution_operators(self) -> None:
        from my_rig import ALL_RGB, PAR_RGB, STROBE_RGB

        rig = create_rig(dry_run=True)

        # ALL_RGB sets Red=0.4 on all 8 RGB elements, PAR_RGB sets Red=0.5, Blue=0.6 on PAR 1..4
        s_all = ALL_RGB(Hold(Color(0.4, 0.0, 0.0), duration=1.0))
        s_par = PAR_RGB(Hold(Color(0.5, 0.0, 0.6), duration=1.0))

        # 1. Additive (`+`): overlapping channels add (R = 0.4 + 0.5 = 0.9 -> 230, B = 0.6 -> 153)
        dmx_add = rig.render_dmx(s_all + s_par, t=0.5)
        self.assertEqual(dmx_add[0:3], [230, 0, 153])   # PAR 1 (overlapped: 0.4 + 0.5 = 0.9)
        self.assertEqual(dmx_add[31:34], [102, 0, 0])   # Strobe RGB 1 (untouched by PAR_RGB: 0.4 -> 102)

        # 2. Override / LTP (`|`): PAR_RGB overrides ALL_RGB on PAR 1..4
        dmx_ltp = rig.render_dmx(s_all | s_par, t=0.5)
        self.assertEqual(dmx_ltp[0:3], [128, 0, 153])
        self.assertEqual(dmx_ltp[31:34], [102, 0, 0])

        # 3. HTP (`^`): Highest Takes Precedence per DMX channel (`max(a, b)`)
        s_par_low_r = PAR_RGB(Hold(Color(0.2, 0.0, 0.8), duration=1.0))
        dmx_htp = rig.render_dmx(s_all ^ s_par_low_r, t=0.5)
        self.assertEqual(dmx_htp[0:3], [102, 0, 204])

        # 4. Sequential composition of multi-group scenes (`scene1 >> scene2`)
        seq_scene = (s_all | STROBE_RGB(dim(0.5, Hold(Color.GREEN, duration=1.0)))) >> s_par
        self.assertEqual(seq_scene.duration, 2.0)
        self.assertEqual(rig.render_dmx(seq_scene, t=0.5)[31:34], [0, 128, 0])
        self.assertEqual(rig.render_dmx(seq_scene, t=1.5)[0:3], [128, 0, 153])

    def test_time_scaling_reverse_and_repeat(self) -> None:
        fade = Fade(0.0, 1.0, duration=2.0, channel="w", ease=lambda t: t)
        stretched = fade @ 4.0
        self.assertEqual(stretched.duration, 4.0)
        self.assertAlmostEqual(stretched.eval(2.0).get("w") or 0.0, 0.5, places=3)

        rev = ~fade
        self.assertAlmostEqual(rev.eval(0.5).get("w") or 0.0, 0.75, places=3)

        looped = fade * 3
        self.assertEqual(looped.duration, 6.0)

        inf_loop = fade * inf
        self.assertEqual(inf_loop.duration, inf)

    def test_cct_and_color_temperature(self) -> None:
        from lightshow import CCT, FadeCCT, kelvin_to_ww_cw
        from my_rig import STROBE_BAR, create_rig

        # 3200K (Warm White only)
        ww_3200, cw_3200 = kelvin_to_ww_cw(3200)
        self.assertAlmostEqual(ww_3200, 1.0, places=3)
        self.assertAlmostEqual(cw_3200, 0.0, places=3)

        # 6600K (Cold White only)
        ww_6600, cw_6600 = kelvin_to_ww_cw(6600)
        self.assertAlmostEqual(ww_6600, 0.0, places=3)
        self.assertAlmostEqual(cw_6600, 1.0, places=3)

        # Mid temperature (4500K)
        ww_4500, cw_4500 = kelvin_to_ww_cw(4500)
        self.assertGreater(ww_4500, 0.3)
        self.assertGreater(cw_4500, 0.3)
        self.assertAlmostEqual(ww_4500 + cw_4500, 1.0, places=3)

        # Render on STROBE_BAR via Rig
        rig = create_rig(dry_run=True)
        dmx_warm = rig.render_dmx({STROBE_BAR: CCT(3200, duration=1.0)}, t=0.5)
        # Seg 1 WW (ch 35 -> index 34) is 255, CW (ch 36 -> index 35) is 0
        self.assertEqual(dmx_warm[34], 255)
        self.assertEqual(dmx_warm[35], 0)

        dmx_cold = rig.render_dmx({STROBE_BAR: CCT(6600, duration=1.0)}, t=0.5)
        self.assertEqual(dmx_cold[34], 0)
    def test_wait_and_pause_transparency(self) -> None:
        from lightshow import Blackout, Pause, Wait
        from my_rig import PARS, create_rig

        rig = create_rig(dry_run=True)

        # Baseline: PARs red
        base = Hold(Color.RED, duration=2.0)

        # 1. Layering with Blackout: actively overwrites to black
        dmx_blackout = rig.render_dmx({PARS: base | Blackout(2.0)}, t=1.0)
        self.assertEqual(dmx_blackout[0:3], [0, 0, 0])

        # 2. Layering with Wait: completely transparent, base shows through
        dmx_wait = rig.render_dmx({PARS: base | Wait(2.0)}, t=1.0)
        self.assertEqual(dmx_wait[0:3], [255, 0, 0])

        # 3. Layering with Pause (alias): also completely transparent
        dmx_pause = rig.render_dmx({PARS: base | Pause(2.0)}, t=1.0)
        self.assertEqual(dmx_pause[0:3], [255, 0, 0])

    def test_chase_wrap_and_pingpong_symmetry(self) -> None:
        """Verify Chase wrap behavior and pingpong linear boundary symmetry."""
        # 1. Circular Chase (wrap=True) wraps tail to the last fixture when at index 0
        chase_circ = Chase(Color.YELLOW, step_duration=0.2, tail=2.0, wrap=True)
        p0_circ = chase_circ.eval(0.0, fixture=0, total_fixtures=8)
        p7_circ = chase_circ.eval(0.0, fixture=7, total_fixtures=8)
        self.assertEqual(p0_circ.color, Color.YELLOW)
        self.assertGreater(p7_circ.color.r, 0.5)

        # 2. Linear Chase (wrap=False) does not bleed into fixture 7 when at index 0
        chase_lin = Chase(Color.YELLOW, step_duration=0.2, tail=2.0, wrap=False)
        p0_lin = chase_lin.eval(0.0, fixture=0, total_fixtures=8)
        p7_lin = chase_lin.eval(0.0, fixture=7, total_fixtures=8)
        self.assertEqual(p0_lin.color, Color.YELLOW)
        self.assertEqual(p7_lin.color, Color(0, 0, 0))

        # 3. Pingpong is perfectly symmetric: at t=0 only PAR 0 is lit, at middle only PAR 7 is lit
        pp = chase_circ.pingpong()  # Automatically uses linear boundary for both directions
        dur = pp.duration
        # At start of bounce (t=0.0): PAR 0 is yellow, PAR 7 is 0.0
        self.assertEqual(pp.eval(0.0, fixture=0, total_fixtures=8).color, Color.YELLOW)
        self.assertEqual(pp.eval(0.0, fixture=7, total_fixtures=8).color, Color(0, 0, 0))
        # At turnaround bounce (t=dur / 2): PAR 7 is yellow, PAR 0 is 0.0
        self.assertEqual(pp.eval(dur / 2.0, fixture=7, total_fixtures=8).color, Color.YELLOW)
        self.assertEqual(pp.eval(dur / 2.0, fixture=0, total_fixtures=8).color, Color(0, 0, 0))

    def test_clip_and_scene_time_slicing(self) -> None:
        """Verify time slicing clip[start:stop] and scene[start:stop] with repeating."""
        from lightshow import Rainbow, SliceClip, SliceScene
        from my_rig import PARS

        base_clip = Rainbow(duration=4.0)

        # 1. Slice clip to [0.3s, 1.2s]
        cut_clip = base_clip[0.3:1.2]
        self.assertIsInstance(cut_clip, SliceClip)
        self.assertAlmostEqual(cut_clip.duration, 0.9, places=6)

        # At t=0.0 of cut, matches base at t=0.3
        self.assertAlmostEqual(cut_clip.eval(0.0).color.r, base_clip.eval(0.3).color.r, places=6)
        self.assertAlmostEqual(cut_clip.eval(0.0).color.g, base_clip.eval(0.3).color.g, places=6)
        # At t=0.45 of cut, matches base at t=0.75
        self.assertAlmostEqual(cut_clip.eval(0.45).color.r, base_clip.eval(0.75).color.r, places=6)
        self.assertAlmostEqual(cut_clip.eval(0.45).color.g, base_clip.eval(0.75).color.g, places=6)

        # 2. Repeat cut indefinitely (`* inf`)
        loop_clip = cut_clip * inf
        self.assertEqual(loop_clip.duration, inf)
        # Verify periodic wrap around
        self.assertAlmostEqual(loop_clip.eval(0.0).color.r, base_clip.eval(0.3).color.r, places=6)
        self.assertAlmostEqual(loop_clip.eval(0.9).color.r, base_clip.eval(0.3).color.r, places=6)
        self.assertAlmostEqual(loop_clip.eval(1.35).color.r, base_clip.eval(0.75).color.r, places=6)
        self.assertAlmostEqual(loop_clip.eval(1.8).color.r, base_clip.eval(0.3).color.r, places=6)

        # 3. Method aliases .cut() and .slice()
        cut_via_method = base_clip.cut(0.3, 1.2)
        self.assertAlmostEqual(cut_via_method.duration, 0.9, places=6)

        # 4. Scene time slicing
        scene = PARS(base_clip)
        cut_scene = scene[0.3:1.2]
        self.assertIsInstance(cut_scene, SliceScene)
        self.assertAlmostEqual(cut_scene.duration, 0.9, places=6)

        loop_scene = cut_scene * inf
        self.assertEqual(loop_scene.duration, inf)

        # Compare DMX output of loop_scene at t=1.0 (local_t = 0.1 -> base at 0.4s)
        dmx_loop = loop_scene.eval_canvas(1.0).to_dmx_list(min_size=24)
        dmx_expected = scene.eval_canvas(0.4).to_dmx_list(min_size=24)
        self.assertEqual(dmx_loop, dmx_expected)

        # 5. Invalid slicing error checks
        with self.assertRaises(TypeError):
            _ = base_clip[0]  # Integer indexing not allowed on temporal clip
        with self.assertRaises(TypeError):
            _ = scene[0]  # Integer indexing not allowed on temporal scene

    def test_noise_and_fbm_determinism_and_continuity(self) -> None:
        """Verify smooth_noise1d and fbm_noise1d properties."""
        # 1. Determinism
        n1 = smooth_noise1d(3.1415, seed=42)
        n2 = smooth_noise1d(3.1415, seed=42)
        self.assertEqual(n1, n2)

        # 2. Output bounds [0.0, 1.0]
        for x in [0.0, 0.5, 1.0, 2.7, 10.99, -5.2]:
            val = fbm_noise1d(x, octaves=3, seed=123)
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 1.0)

        # 3. Continuity (small dx yields small dy)
        x0 = 5.25
        y0 = fbm_noise1d(x0, octaves=3, seed=99)
        y1 = fbm_noise1d(x0 + 0.001, octaves=3, seed=99)
        self.assertLess(abs(y1 - y0), 0.01)

    def test_color_hsv_math_and_relative_shifting(self) -> None:
        """Verify Color.to_hsv() and Color.shift_hsv(dh, ds, dv)."""
        # Red is (0.0, 1.0, 1.0) in HSV
        red = Color.RED
        h, s, v = red.to_hsv()
        self.assertAlmostEqual(h, 0.0, places=4)
        self.assertAlmostEqual(s, 1.0, places=4)
        self.assertAlmostEqual(v, 1.0, places=4)

        # Shifting red by +0.08 yields orange (r=1.0, g>0, b=0)
        orange = red.shift_hsv(dh=0.08)
        self.assertAlmostEqual(orange.r, 1.0, places=4)
        self.assertGreater(orange.g, 0.3)
        self.assertAlmostEqual(orange.b, 0.0, places=4)

        # Shifting red by -0.05 wraps around to crimson (r=1.0, g=0, b>0)
        crimson = red.shift_hsv(dh=-0.05)
        self.assertAlmostEqual(crimson.r, 1.0, places=4)
        self.assertAlmostEqual(crimson.g, 0.0, places=4)
        self.assertGreater(crimson.b, 0.1)

        # Saturation and value clamping
        white_desat = red.shift_hsv(ds=-1.0)
        self.assertAlmostEqual(white_desat.r, 1.0, places=4)
        self.assertAlmostEqual(white_desat.g, 1.0, places=4)
        self.assertAlmostEqual(white_desat.b, 1.0, places=4)

    def test_flicker_and_fixture_decorrelation(self) -> None:
        """Verify Flicker modulation and per-fixture decorrelation."""
        base = Hold(Color.RED)
        flicker = base.flicker(depth=0.5, speed=12.0, low=0.4, high=1.0, seed=101)

        # 1. Output stays within [low, high]
        p0 = flicker.eval(0.5, fixture=0, total_fixtures=4)
        self.assertIsNotNone(p0.color)
        self.assertGreaterEqual(p0.color.r, 0.39)
        self.assertLessEqual(p0.color.r, 1.01)
        self.assertEqual(p0.color.g, 0.0)
        self.assertEqual(p0.color.b, 0.0)

        # 2. Per-fixture decorrelation: fixture 0 and fixture 1 have different intensities
        p1 = flicker.eval(0.5, fixture=1, total_fixtures=4)
        self.assertNotEqual(p0.color.r, p1.color.r)

        # 3. Layering syntax: base | Flicker(...)
        layered = base | Flicker(depth=0.5, speed=12.0, low=0.4, high=1.0, seed=101)
        p_lay = layered.eval(0.5, fixture=0, total_fixtures=4)
        self.assertAlmostEqual(p0.color.r, p_lay.color.r, places=4)

    def test_hueshift_and_jitter_hue(self) -> None:
        """Verify HueShift relative hue rotation and jitter."""
        # 1. Static hue shift
        shifted = Hold(Color.RED).shift_hsv(dh=0.08)
        p = shifted.eval(0.0)
        self.assertAlmostEqual(p.color.r, 1.0, places=4)
        self.assertGreater(p.color.g, 0.3)

        # 2. Continuous organic hue jitter
        jitter = Hold(Color.RED).jitter_hue(amount=0.08, speed=3.0)
        p_j0 = jitter.eval(0.2, fixture=0)
        p_j1 = jitter.eval(0.2, fixture=1)
        self.assertNotEqual(p_j0.color.g, p_j1.color.g)

        # 3. Layering syntax: base | HueShift(dh=0.08)
        layered = Hold(Color.RED) | HueShift(dh=0.08)
        p_layer = layered.eval(0.0)
        self.assertAlmostEqual(p.color.r, p_layer.color.r, places=4)
        self.assertAlmostEqual(p.color.g, p_layer.color.g, places=4)

    def test_relative_composition_and_scene_modifiers(self) -> None:
        """Verify chaining relative effects and scene-level modifiers."""
        # 1. Chained modifiers on clip: flicker + hue jitter
        fx_clip = Hold(Color.RED).flicker(depth=0.5, speed=10.0).jitter_hue(amount=0.06, speed=3.0)
        p = fx_clip.eval(0.3, fixture=0)
        self.assertIsNotNone(p.color)
        self.assertGreater(p.color.r, 0.0)

        # 2. Relative FX combined first then applied to base: (Flicker | HueShift)
        rel_fx = Flicker(depth=0.5, speed=10.0) | HueShift(amount=0.06, speed=3.0)
        p_rel = (Hold(Color.RED) | rel_fx).eval(0.3, fixture=0)
        self.assertIsNotNone(p_rel.color)
        self.assertGreater(p_rel.color.r, 0.0)

        # 3. Scene-level flicker and hue jitter on multi-fixture group
        scene = PARS(Hold(Color.RED))
        scene_fx = scene.flicker(depth=0.5).jitter_hue(amount=0.06)
        dmx_fx = scene_fx.eval_canvas(0.5).to_dmx_list(min_size=24)

        # PAR 1 (ch 1..3) and PAR 2 (ch 7..9) have non-zero red, decorrelated values
        self.assertGreater(dmx_fx[0], 0)
        self.assertGreater(dmx_fx[6], 0)
        self.assertNotEqual(dmx_fx[0], dmx_fx[6])


if __name__ == "__main__":
    unittest.main()
