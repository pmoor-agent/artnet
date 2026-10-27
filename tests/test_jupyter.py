"""Unit tests for the optional Jupyter notebook integration module."""

import unittest
from lightshow import Color, Rainbow, Hold
from my_rig import PARS, STROBE_BAR, create_rig


class TestJupyterIntegration(unittest.TestCase):
    def test_core_isolation(self) -> None:
        """Verify core lightshow does not import or depend on jupyter module."""
        import lightshow
        self.assertFalse(hasattr(lightshow, "LiveStream"))
        self.assertFalse(hasattr(lightshow, "stream"))
        self.assertFalse(hasattr(lightshow, "render_clip_timeline_svg"))

    def test_jupyter_reexports_and_svg(self) -> None:
        """Verify lightshow.jupyter re-exports core and provides _repr_html_."""
        from lightshow.jupyter import (
            Color as JColor,
            Rainbow as JRainbow,
            Hold as JHold,
            render_clip_timeline_svg,
            render_scene_timeline_svg,
            stream,
            stop_stream,
        )

        clip = JRainbow(duration=2.0)
        svg_clip = clip._repr_html_()
        self.assertIn("<svg", svg_clip)
        self.assertIn("</svg>", svg_clip)
        self.assertIn("Fix 1", svg_clip)

        scene = PARS(clip) | STROBE_BAR(JHold(JColor.BLUE, duration=2.0))
        svg_scene = scene._repr_html_()
        self.assertIn("<svg", svg_scene)
        self.assertIn("PARS", svg_scene)
        self.assertIn("STROBE_BAR", svg_scene)

    def test_background_streamer_lifecycle(self) -> None:
        """Verify non-blocking stream start, hot-swap update, and stop."""
        from lightshow.jupyter import stream, stop_stream
        rig = create_rig(dry_run=True)

        s = stream(PARS(Hold(Color.RED, duration=1.0)), rig=rig)
        self.assertTrue(s.is_alive)

        # Hot-swap
        s.update(PARS(Hold(Color.GREEN, duration=1.0)))
        self.assertTrue(s.is_alive)

        stop_stream()
        self.assertFalse(s.is_alive)

    def test_stage_inspect_and_call_html_rendering(self) -> None:
        """Verify Stage.__call__ and Stage.inspect return HTMLView/StageScrubberView with _repr_html_."""
        from my_rig import STAGE
        from lightshow.profiles import HTMLView, StageScrubberView
        from IPython.core.formatters import HTMLFormatter, JavascriptFormatter

        scene = PARS(Hold(Color.RED, duration=1.0))

        # 1. Direct call STAGE(scene, t=0.5)
        call_view = STAGE(scene, t=0.5)
        self.assertIsInstance(call_view, HTMLView)
        self.assertIsInstance(call_view, str)
        self.assertTrue(hasattr(call_view, "_repr_html_"))
        self.assertIn("<svg", call_view._repr_html_())
        # Formatter produces HTML
        self.assertIsNotNone(HTMLFormatter()(call_view))

        # 2. Scrubber STAGE.inspect(scene)
        scrubber = STAGE.inspect(scene, duration=1.0, fps=10.0)
        self.assertIsInstance(scrubber, StageScrubberView)
        self.assertIsInstance(scrubber, str)
        self.assertTrue(hasattr(scrubber, "_repr_html_"))
        # Must NOT define _repr_javascript_, otherwise JupyterLab prioritizes application/javascript
        # over text/html and renders a blank empty output cell!
        self.assertFalse(hasattr(scrubber, "_repr_javascript_"))
        self.assertIn("stage_scrubber_", scrubber._repr_html_())
        self.assertIn("<script>", scrubber._repr_html_())

        # Formatter produces HTML and NOT JavaScript
        self.assertIsNotNone(HTMLFormatter()(scrubber))
        self.assertIsNone(JavascriptFormatter()(scrubber))

    def test_sliced_fixture_groups_in_layer_scene_timeline(self) -> None:
        """Verify multiple slices of the same parent group render all lanes with clean indices in Jupyter."""
        from lightshow.jupyter import Color, Chase, render_scene_timeline_svg
        from lightshow.profiles import EurolitePartySpot

        PARS_16 = EurolitePartySpot.group('PARS', start_channels=[1 + i * 6 for i in range(16)])
        chase = Chase(
            color=Color.YELLOW,
            step_duration=0.15,
            tail=3.0,
            background=Color.from_hex("#0d0033"),
            wrap=False,
        ).pingpong() * 2

        # 2 rows of 8 PARs sliced from 16 PARs
        row1 = PARS_16[0:8]
        row2 = PARS_16[8:16]

        self.assertEqual(row1.name, "PARS[0:8]")
        self.assertEqual(row2.name, "PARS[8:16]")
        self.assertEqual(row1.label(0), "PARS[0]")
        self.assertEqual(row1.label(7), "PARS[7]")
        self.assertEqual(row2.label(0), "PARS[8]")
        self.assertEqual(row2.label(7), "PARS[15]")

        scene = (row1(chase @ 2.0) | row2(chase @ 4.0))

        # Both slices must be present in scene.groups()
        groups = scene.groups()
        self.assertEqual(len(groups), 2)
        self.assertEqual([g.name for g in groups], ["PARS[0:8]", "PARS[8:16]"])

        # Timeline SVG must render all 16 distinct lanes
        svg = render_scene_timeline_svg(scene)
        self.assertNotIn("[slice]", svg)
        for i in range(16):
            self.assertIn(f"PARS[{i}]", svg)


if __name__ == "__main__":
    unittest.main()
