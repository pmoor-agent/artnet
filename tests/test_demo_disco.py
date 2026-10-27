"""Unit tests for the 16-PAR Disco Extravaganza demo show."""

import unittest
from demo_disco_16par import STAGE_16, DISCO_SHOW, PARS, ROW_TOP, ROW_BOT


class TestDemoDisco16Par(unittest.TestCase):
    def test_rig_layout(self) -> None:
        """Verify fixture counts and names for the 2x8 PAR rig."""
        self.assertEqual(len(PARS), 16)
        self.assertEqual(len(ROW_TOP), 8)
        self.assertEqual(len(ROW_BOT), 8)
        self.assertEqual(len(STAGE_16.fixtures), 16)

    def test_disco_show_duration(self) -> None:
        """Verify show duration is exactly 30 seconds."""
        self.assertAlmostEqual(DISCO_SHOW.duration, 30.0, places=3)

    def test_frame_evaluation_and_dmx(self) -> None:
        """Verify DMX canvas evaluation across all movements."""
        sample_times = [0.0, 3.0, 6.0, 9.0, 12.0, 15.0, 18.0, 21.0, 24.0, 27.0, 29.9]
        for t in sample_times:
            canvas = DISCO_SHOW.eval_canvas(t)
            dmx = canvas.to_dmx_list(min_size=96)
            self.assertEqual(len(dmx), 96)
            for ch_idx, val in enumerate(dmx):
                self.assertGreaterEqual(val, 0, f"Channel {ch_idx+1} at t={t} is negative")
                self.assertLessEqual(val, 255, f"Channel {ch_idx+1} at t={t} exceeds 255")

    def test_stage_render_svg(self) -> None:
        """Verify SVG rendering contains expected fixture tags and labels."""
        svg_out = STAGE_16.render_svg(DISCO_SHOW, t=5.0)
        svg_str = str(svg_out)
        self.assertIn("<svg", svg_str)
        self.assertIn("</svg>", svg_str)
        # Check that top and bottom labels are present
        for i in range(1, 9):
            self.assertIn(f"T{i}", svg_str)
            self.assertIn(f"B{i}", svg_str)

    def test_stage_render_animated_svg(self) -> None:
        """Verify animated SMIL SVG generation for a 2-second snippet."""
        import tempfile
        import os
        anim_svg = STAGE_16.render_animated_svg(DISCO_SHOW, duration=2.0, fps=5.0)
        svg_str = str(anim_svg)
        self.assertIn("<svg", svg_str)
        self.assertIn("</svg>", svg_str)
        self.assertIn("attributeName=\"display\"", svg_str)
        self.assertIn("f_anim_0", svg_str)

        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            temp_path = f.name
        try:
            STAGE_16.save_animated_svg(DISCO_SHOW, temp_path, duration=1.0, fps=4.0)
            self.assertTrue(os.path.exists(temp_path))
            self.assertGreater(os.path.getsize(temp_path), 1000)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
