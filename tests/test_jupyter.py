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

        # 3. Verify uniform periodic frame sampling without boundary duplication (no t=1.00s duplicate of t=0.00s)
        import json, re
        m = re.search(r'const frames = (\[.*?\]);', scrubber, re.DOTALL)
        self.assertIsNotNone(m)
        frames = json.loads(m.group(1))
        self.assertEqual(len(frames), 10)  # 1.0s @ 10fps = 10 frames
        frame_times = [re.search(r't = ([\d\.]+)s', f).group(1) for f in frames]
        self.assertEqual(frame_times, ['0.00', '0.10', '0.20', '0.30', '0.40', '0.50', '0.60', '0.70', '0.80', '0.90'])
        self.assertNotIn('1.00', frame_times)  # 1.00s would duplicate 0.00s when looped

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

    def test_dmx_snapshot_inspection(self) -> None:
        """Verify static DMX snapshot inspection for Scene, Stage, DMXCanvas, and raw bytes."""
        from my_rig import STAGE, PARS, STROBE_BAR
        from lightshow.jupyter import (
            Color,
            DMXFrameView,
            Hold,
            Rainbow,
            dmx,
            inspect_dmx,
        )
        from IPython.core.formatters import HTMLFormatter

        scene = PARS(Hold(Color.RED, duration=2.0)) | STROBE_BAR(Hold(Color.BLUE, duration=2.0))

        # 1. Snapshot via scene.dmx(t)
        view = scene.dmx(0.5)
        self.assertIsInstance(view, DMXFrameView)
        self.assertIsInstance(view, str)
        self.assertTrue(hasattr(view, "_repr_html_"))
        self.assertIsNotNone(HTMLFormatter()(view))

        html_str = view._repr_html_()
        self.assertIn("dmx-inspector", html_str)
        self.assertIn("dmx-fixture-card", html_str)
        self.assertIn("dmx-fixture-swatch", html_str)
        self.assertIn("dmx-grid-container", html_str)

        # RGB channels colored
        self.assertIn("role-r", html_str)
        self.assertIn("role-g", html_str)
        self.assertIn("role-b", html_str)
        # White & strobe channels
        self.assertIn("role-strobe", html_str)
        # Verify strobe has pitch black background styling
        self.assertIn(".dmx-pill.role-strobe", html_str)
        self.assertIn("background: #000000 !important;", html_str)
        # Inactive channels are styled as faint zeros
        self.assertIn("ch-zero", html_str)
        self.assertIn("opacity: 0.38", html_str)
        # Hide zeros toggle
        self.assertIn("Hide 0s", html_str)

        # Programmatic access
        self.assertEqual(view.channel(1), 255)  # PAR 1 Red = 255
        self.assertEqual(view.channel(2), 0)    # PAR 1 Green = 0
        self.assertEqual(view.channel(3), 0)    # PAR 1 Blue = 0
        self.assertEqual(view.channel(5), 255)  # PAR 1 Master Dimmer = 255
        self.assertTrue(len(view.active_channels) > 0)
        self.assertIn(1, view.to_dict())
        self.assertIn("active channels", repr(view))

        # 2. Snapshot via stage.dmx(scene, t)
        stage_view = STAGE.dmx(scene, 0.5)
        self.assertIsInstance(stage_view, DMXFrameView)
        self.assertIn("PAR 1", stage_view)
        self.assertIn("BCL-40 Bar", stage_view)

        # 3. Direct dmx() call on raw byte list
        raw_view = dmx([255, 128, 64, 0, 0, 255], hide_zeros=True)
        self.assertIsInstance(raw_view, DMXFrameView)
        self.assertIn("hide-zeros", raw_view)
        self.assertIn("Show 0s", raw_view)

    def test_interactive_stage_and_scene_dmx_scrubber(self) -> None:
        """Verify interactive scrubber widget provides prev/next buttons and live synchronized DMX table."""
        from my_rig import STAGE, PARS
        from lightshow.jupyter import Color, Hold, StageScrubberView
        import json, re

        scene = PARS(Hold(Color.GREEN, duration=1.0))

        # 1. STAGE.inspect with live DMX table enabled
        scrubber = STAGE.inspect(scene, duration=1.0, fps=10.0, show_dmx=True)
        self.assertIsInstance(scrubber, StageScrubberView)
        html_str = scrubber._repr_html_()

        # Transport controls: Prev, Play, Next, Slider, Time/Frame label
        self.assertIn("◀ Prev", html_str)
        self.assertIn("▶ Play", html_str)
        self.assertIn("Next ▶", html_str)
        self.assertIn('type="range"', html_str)

        # Embedded JSON data for 10 frames
        m_dmx = re.search(r'const dmxFrames = (\[.*?\]);', html_str, re.DOTALL)
        self.assertIsNotNone(m_dmx)
        dmx_frames = json.loads(m_dmx.group(1))
        self.assertEqual(len(dmx_frames), 10)
        # Each frame has DMX bytes
        self.assertTrue(len(dmx_frames[0]) >= 24)
        # Green channel (addr 2) is active = 255
        self.assertEqual(dmx_frames[0][1], 255)

        # Embedded metadata for live DOM updates
        self.assertIn("const chMeta =", html_str)
        self.assertIn("const fixMeta =", html_str)

        # 2. Direct scene.inspect() without STAGE
        scene_scrubber = scene.inspect(duration=1.0, fps=10.0, show_dmx=True)
        self.assertIsInstance(scene_scrubber, StageScrubberView)
        self.assertIn("◀ Prev", scene_scrubber)
        self.assertIn("Next ▶", scene_scrubber)
        self.assertIn("dmx-inspector", scene_scrubber)

        # 3. Verify collapsible DMX starts hidden by default
        self.assertIn("display: none;", scrubber)
        self.assertIn("📡 DMX ▸", scrubber)

        # When dmx_collapsed=False, it starts expanded
        expanded_scrubber = STAGE.inspect(scene, duration=1.0, fps=10.0, show_dmx=True, dmx_collapsed=False)
        self.assertIn("display: block;", expanded_scrubber)
        self.assertIn("📡 DMX ▾", expanded_scrubber)

    def test_multi_widget_isolation(self) -> None:
        """Verify multiple inspect widgets in the same session have distinct IDs without DOM collisions."""
        from my_rig import STAGE, PARS, STROBE_BAR
        from lightshow.jupyter import Color, Hold
        import re

        s1 = PARS(Hold(Color.RED, duration=1.0))
        s2 = STROBE_BAR(Hold(Color.BLUE, duration=1.0))

        w1 = STAGE.inspect(s1, duration=1.0, fps=10.0)
        w2 = STAGE.inspect(s2, duration=1.0, fps=10.0)

        id1 = re.search(r'id=\"(stage_scrubber_\d+)\"', w1).group(1)
        id2 = re.search(r'id=\"(stage_scrubber_\d+)\"', w2).group(1)
        self.assertNotEqual(id1, id2)

        # Verify w1 embeds its own scoped IDs and not w2
        self.assertIn(f"{id1}_dmx_ch_1", w1)
        self.assertIn(f"{id2}_dmx_ch_1", w2)
        self.assertNotIn(f"{id2}_dmx", w1)
        self.assertNotIn(f"{id1}_dmx", w2)


if __name__ == "__main__":
    unittest.main()
