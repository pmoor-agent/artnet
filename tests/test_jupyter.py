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
        self.assertTrue(hasattr(scrubber, "_repr_javascript_"))
        self.assertIn("stage_scrubber_", scrubber._repr_html_())
        self.assertIn("initWidget", scrubber._repr_javascript_())

        # Formatter produces both HTML and JS
        self.assertIsNotNone(HTMLFormatter()(scrubber))
        self.assertIsNotNone(JavascriptFormatter()(scrubber))


if __name__ == "__main__":
    unittest.main()
