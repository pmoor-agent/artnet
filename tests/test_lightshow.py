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
    Hold,
    Rig,
    Strobe,
    build_artdmx_packet,
    ch,
    dim,
)
from my_rig import (
    PAR_DIMMERS,
    PAR_STROBES,
    PAR_WHITES,
    PARS,
    STROBE_BAR,
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

        # 1. Test driving STROBE_W and STROBE_RGB as split views with dim()
        dmx_split = rig.render_dmx(
            {
                PARS: Hold(Color.BLACK, duration=1.0),
                STROBE_W: dim(0.25, Hold(1.0, duration=1.0).on(0, 7)),
                STROBE_RGB: dim(0.35, Hold(Color.CYAN, duration=1.0).on(0, 7)),
            },
            t=0.5,
        )
        self.assertEqual(len(dmx_split), 63)
        self.assertEqual(dmx_split[31:39], [64, 0, 0, 0, 0, 0, 0, 64])
        self.assertEqual(dmx_split[39:42], [0, 89, 89])
        self.assertEqual(dmx_split[60:63], [0, 89, 89])

        # 2. Test driving STROBE_BAR as a single unified 8-segment RGBW fixture!
        unified_clip = (
            dim(0.35, Hold(Color.CYAN, duration=1.0).on(0, 7))
            | dim(0.25, ch("w", Hold(1.0, duration=1.0).on(0, 7)))
        )
        dmx_unified = rig.render_dmx({STROBE_BAR: unified_clip}, t=0.5)
        self.assertEqual(dmx_unified[31:39], [64, 0, 0, 0, 0, 0, 0, 64])
        self.assertEqual(dmx_unified[39:42], [0, 89, 89])
        self.assertEqual(dmx_unified[60:63], [0, 89, 89])

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

    def test_combining_fixture_groups_with_plus_and_slicing(self) -> None:
        from my_rig import ALL_RGB, ALL_WHITES, PAR_RGB, STAGE_RGB, STROBE_RGB

        rig = create_rig(dry_run=True)

        # ALL_RGB = PAR_RGB (4) + STROBE_RGB (8) -> 12 RGB elements
        self.assertEqual(len(ALL_RGB), 12)
        self.assertEqual(len(ALL_WHITES), 12)
        self.assertEqual(len(STAGE_RGB), 12)

        # Drive index 0 (PAR 1) and index 11 (Strobe RGB 8) via ALL_RGB
        # Notice we can even use `.on(4, 5, 6, 7, 8, 9, 10, 11)` or dim the strobe portion!
        dmx = rig.render_dmx(
            {
                ALL_RGB: Hold(Color.MAGENTA, duration=1.0).on(0, 11),
            },
            t=0.5,
        )
        # PAR 1 (ch 1..6): R=255, G=0, B=255, W=0, Dimmer=255 (from default!), Strobe=0
        self.assertEqual(dmx[0:6], [255, 0, 255, 0, 255, 0])
        # Strobe RGB 8 (ch 61..63 -> indices 60..62): R=255, G=0, B=255
        self.assertEqual(dmx[60:63], [255, 0, 255])

        # Test STAGE_RGB = PAR_RGB[:2] + STROBE_RGB + PAR_RGB[2:]
        # Index 0, 1 are PAR 1, 2; Index 2 is Strobe RGB 1; Index 11 is PAR 4
        dmx_stage = rig.render_dmx(
            {
                STAGE_RGB: Hold(Color.GREEN, duration=1.0).on(2, 11),
            },
            t=0.5,
        )
        # Strobe RGB 1 (ch 40..42 -> indices 39..41) is GREEN
        self.assertEqual(dmx_stage[39:42], [0, 255, 0])
        # PAR 4 (ch 19..24 -> indices 18..23) is GREEN with default Dimmer=255
        self.assertEqual(dmx_stage[18:24], [0, 255, 0, 0, 255, 0])

    def test_scene_conflict_resolution_operators(self) -> None:
        from my_rig import ALL_RGB, PAR_RGB, STROBE_RGB

        rig = create_rig(dry_run=True)

        # Suppose ALL_RGB sets Red=0.4 on all 12 RGB fixtures, and PAR_RGB concurrently sets
        # Red=0.5, Blue=0.6 on PAR 1..4.
        s_all = ALL_RGB(Hold(Color(0.4, 0.0, 0.0), duration=1.0))
        s_par = PAR_RGB(Hold(Color(0.5, 0.0, 0.6), duration=1.0))

        # 1. Additive (`+`): overlapping channels add (R = 0.4 + 0.5 = 0.9 -> 230, B = 0.6 -> 153)
        dmx_add = rig.render_dmx(s_all + s_par, t=0.5)
        self.assertEqual(dmx_add[0:3], [230, 0, 153])   # PAR 1 (overlapped: 0.4 + 0.5 = 0.9)
        self.assertEqual(dmx_add[39:42], [102, 0, 0])   # Strobe RGB 1 (untouched by PAR_RGB: 0.4 -> 102)

        # 2. Override / LTP (`|`): PAR_RGB overrides ALL_RGB on PAR 1..4 (R = 0.5 -> 128, B = 0.6 -> 153)
        dmx_ltp = rig.render_dmx(s_all | s_par, t=0.5)
        self.assertEqual(dmx_ltp[0:3], [128, 0, 153])
        self.assertEqual(dmx_ltp[39:42], [102, 0, 0])

        # 3. HTP (`^`): Highest Takes Precedence per DMX channel (`max(a, b)`)
        s_par_low_r = PAR_RGB(Hold(Color(0.2, 0.0, 0.8), duration=1.0))
        dmx_htp = rig.render_dmx(s_all ^ s_par_low_r, t=0.5)
        # R takes max(0.4, 0.2) = 0.4 -> 102; B takes max(0.0, 0.8) = 0.8 -> 204
        self.assertEqual(dmx_htp[0:3], [102, 0, 204])

        # 4. Sequential composition of multi-group scenes (`scene1 >> scene2`)
        seq_scene = (s_all | STROBE_RGB(dim(0.5, Hold(Color.GREEN, duration=1.0)))) >> s_par
        self.assertEqual(seq_scene.duration, 2.0)
        self.assertEqual(rig.render_dmx(seq_scene, t=0.5)[39:42], [0, 128, 0])
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


if __name__ == "__main__":
    unittest.main()
