"""Unit tests for the reusable fixture profiles and 2D Stage visualizer."""

import unittest
from lightshow import Color, Hold, Rainbow
from lightshow.profiles import (
    EuroliteBCL40Bar,
    EurolitePartySpot,
    Stage,
    blend_rgbw,
)
from my_rig import PARS, STROBE_BAR, STROBE_MASTER, STAGE


class TestFixtureProfiles(unittest.TestCase):
    def test_blend_rgbw_optics(self) -> None:
        """Test optical RGB + White LED mixing and dimmer scaling."""
        # 1. Pure red without white at full dimmer
        r, g, b = blend_rgbw(255, 0, 0, w_byte=0, dimmer_byte=255)
        self.assertEqual((r, g, b), (255, 0, 0))

        # 2. Red + 50% white desaturates red into pink/coral
        r_pink, g_pink, b_pink = blend_rgbw(255, 0, 0, w_byte=128, dimmer_byte=255)
        self.assertEqual(r_pink, 255)
        self.assertGreater(g_pink, 100)
        self.assertGreater(b_pink, 100)

        # 3. Dimmer at 0 shuts off photons completely
        r_dim, g_dim, b_dim = blend_rgbw(255, 255, 255, w_byte=255, dimmer_byte=0)
        self.assertEqual((r_dim, g_dim, b_dim), (0, 0, 0))

    def test_eurolite_party_spot_rendering(self) -> None:
        """Test concentric rings (3 inner + 9 outer) rendering in PARty Spot."""
        spot = EurolitePartySpot(PARS[0], x=100, y=100, radius=30, label="Spot 1")
        dmx_lit = [255, 0, 0, 0, 255, 0] + [0] * 50
        svg_lit = spot.render_svg(dmx_lit)

        # Must have outer can, reflector dish, and at least 12 diode circles
        self.assertIn("<circle", svg_lit)
        circle_count = svg_lit.count("<circle")
        # 1 beam halo + 1 outer can + 1 reflector dish + 12 diodes + 12 diode highlights = ~27
        self.assertGreaterEqual(circle_count, 14)
        self.assertIn("Spot 1", svg_lit)

        # When strobe is active, must render lightning bolt icon
        dmx_strobe = [255, 255, 255, 255, 255, 240] + [0] * 50
        svg_strobe = spot.render_svg(dmx_strobe)
        self.assertIn("⚡", svg_strobe)

    def test_eurolite_bcl40_bar_rendering(self) -> None:
        """Test BCL-40 bar rendering with 4 segments and SMD diodes."""
        bar = EuroliteBCL40Bar(
            STROBE_BAR,
            x=200,
            y=100,
            width=240,
            height=30,
            master_strobe=STROBE_MASTER,
            label="Bar",
        )
        dmx_frame = [0] * 31 + [255, 0, 0, 0, 255] + [0] * 20
        svg = bar.render_svg(dmx_frame)
        self.assertIn("<rect", svg)
        self.assertIn("Bar", svg)

    def test_my_rig_stage_integration(self) -> None:
        """Test the configured STAGE in my_rig.py."""
        scene = PARS(Rainbow(duration=2.0)) | STROBE_BAR(Hold(Color.BLUE, duration=2.0))
        svg = STAGE.render_svg(scene, t=0.5)
        self.assertIn("<svg", svg)
        self.assertIn("PAR 1", svg)
        self.assertIn("BCL-40 Bar", svg)
        self.assertIn("PAR 4", svg)

        # Test interactive scrubber widget output
        widget = STAGE.inspect(scene, duration=1.0, fps=5.0)
        self.assertIn("stage_scrubber_", widget)
        self.assertIn("Play", widget)


if __name__ == "__main__":
    unittest.main()
