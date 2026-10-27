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
        self.assertTrue(s.loop)

        # Test automatic modulo looping when loop=True
        self.assertAlmostEqual(s._eval_time(now=2.5, start=0.0, scene=s._current_scene), 0.5)
        s.loop = False
        self.assertAlmostEqual(s._eval_time(now=2.5, start=0.0, scene=s._current_scene), 2.5)
        s.loop = True

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

    def test_width_scaling_and_clip_inspect(self) -> None:
        """Verify responsive 100% width default and manual width scaling across clips, scenes, and inspector."""
        from lightshow import Rainbow, Hold, Color
        from my_rig import PARS, STAGE
        from lightshow.jupyter import (
            parse_width,
            render_clip_timeline_svg,
            render_scene_timeline_svg,
            StageScrubberView,
        )

        # 1. parse_width helper behavior
        self.assertEqual(parse_width(None), (1000, "100%"))
        self.assertEqual(parse_width("100%"), (1000, "100%"))
        self.assertEqual(parse_width("auto"), (1000, "100%"))
        self.assertEqual(parse_width(800), (800, "800px"))
        self.assertEqual(parse_width("1200px"), (1200, "1200px"))
        self.assertEqual(parse_width("75%"), (1000, "75%"))
        # Clamped minimum width
        self.assertEqual(parse_width(100), (300, "300px"))

        clip = Rainbow(duration=2.0)
        scene = PARS(clip)

        # 2. SVG ribbon default (100% responsive) vs explicit width
        clip_svg_default = render_clip_timeline_svg(clip)
        self.assertIn("max-width: 100%", clip_svg_default)
        self.assertIn('viewBox="0 0 1000', clip_svg_default)
        self.assertIn("style=\"width: 100%; height: auto;", clip_svg_default)

        clip_svg_custom = render_clip_timeline_svg(clip, width=800)
        self.assertIn("max-width: 800px", clip_svg_custom)
        self.assertIn('viewBox="0 0 800', clip_svg_custom)

        scene_svg_default = render_scene_timeline_svg(scene)
        self.assertIn("max-width: 100%", scene_svg_default)
        self.assertIn('viewBox="0 0 1000', scene_svg_default)

        scene_svg_custom = render_scene_timeline_svg(scene, width=1200)
        self.assertIn("max-width: 1200px", scene_svg_custom)
        self.assertIn('viewBox="0 0 1200', scene_svg_custom)

        # 3. Direct scene.inspect() default (100%) vs custom width
        scrubber_scene_default = scene.inspect(duration=1.0, fps=5.0)
        self.assertIn("max-width: 100%", scrubber_scene_default)
        self.assertIn('viewBox="0 0 1000', scrubber_scene_default)

        scrubber_scene_custom = scene.inspect(duration=1.0, fps=5.0, width=800)
        self.assertIn("max-width: 800px", scrubber_scene_custom)
        self.assertIn('viewBox="0 0 800', scrubber_scene_custom)

        # 4. Direct clip.inspect()
        scrubber_clip = clip.inspect(fixtures=4, duration=1.0, fps=5.0)
        self.assertIsInstance(scrubber_clip, StageScrubberView)
        self.assertIn("max-width: 100%", scrubber_clip)
        self.assertIn("◀ Prev", scrubber_clip)
        self.assertIn("Next ▶", scrubber_clip)
        self.assertIn("dmx-inspector", scrubber_clip)

        scrubber_clip_custom = clip.inspect(fixtures=4, duration=1.0, fps=5.0, width=1200)
        self.assertIn("max-width: 1200px", scrubber_clip_custom)
        self.assertIn('viewBox="0 0 1200', scrubber_clip_custom)

        # 5. STAGE.inspect() with custom width
        scrubber_stage_custom = STAGE.inspect(scene, duration=1.0, fps=5.0, width=1200)
        self.assertIn("max-width: 1200px", scrubber_stage_custom)

    def test_control_deck_and_crossfade(self) -> None:
        """Verify ControlDeck live scene mixing, cueing, transport, tempo, master, and widget callbacks."""
        from lightshow import Hold, Color
        from my_rig import PARS, STROBE_BAR, create_rig
        from lightshow.jupyter import ControlDeck

        rig = create_rig(dry_run=True)
        s1 = PARS(Hold(Color.RED, duration=1.0))
        s2 = STROBE_BAR(Hold(Color.BLUE, duration=1.0))
        s3 = PARS(Hold(Color.GREEN, duration=1.0))

        deck = ControlDeck(
            {"Red PARs": s1, "Blue Bar": s2, "Green PARs": s3},
            rig=rig,
            bpm=120.0,
            transition_time=0.5,
        )

        try:
            # 1. Initial State
            self.assertEqual(deck.scene_names, ["Red PARs", "Blue Bar", "Green PARs"])
            self.assertEqual(deck.current_scene_name, "Red PARs")
            self.assertEqual(deck.cue_scene_name, "Blue Bar")
            self.assertEqual(deck.bpm, 120.0)
            self.assertEqual(deck.master, 1.0)
            self.assertFalse(deck.is_blackout)

            # 2. Transport
            deck.play()
            self.assertTrue(deck.is_playing)
            deck.pause()
            self.assertTrue(deck.is_paused)

            # 3. Scene Selection & Cueing
            deck.select("Blue Bar")
            self.assertEqual(deck.current_scene_name, "Blue Bar")
            deck.cue("Green PARs")
            self.assertEqual(deck.cue_scene_name, "Green PARs")

            # 4. Crossfade GO and Cue Advance
            deck.go()
            self.assertEqual(deck.current_scene_name, "Green PARs")
            # Advances cue to next in order: Green is index 2 -> loops to index 0 ("Red PARs")
            self.assertEqual(deck.cue_scene_name, "Red PARs")

            # 5. Next & Prev
            deck.next()
            self.assertEqual(deck.current_scene_name, "Red PARs")
            deck.prev()
            self.assertEqual(deck.current_scene_name, "Green PARs")

            # 6. Tempo Controls
            deck.set_bpm(140.0)
            self.assertEqual(deck.bpm, 140.0)
            deck.multiply_bpm(0.5)
            self.assertEqual(deck.bpm, 70.0)
            deck.multiply_bpm(2.0)
            self.assertEqual(deck.bpm, 140.0)

            # 7. Grand Master & Blackout & Looping
            deck.set_master(0.65)
            self.assertAlmostEqual(deck.master, 0.65)
            self.assertTrue(deck.toggle_blackout())
            self.assertTrue(deck.is_blackout)
            self.assertFalse(deck.toggle_blackout())
            self.assertFalse(deck.is_blackout)

            # Loop controls
            self.assertTrue(deck.loop)
            self.assertFalse(deck.toggle_loop())
            self.assertFalse(deck.loop)
            self.assertTrue(deck.toggle_loop())
            self.assertTrue(deck.loop)

            # 8. Dynamic Scene Addition
            s4 = PARS(Hold(Color.WHITE, duration=1.0))
            deck.add("White PARs", s4)
            self.assertIn("White PARs", deck.scene_names)
            self.assertIn("White PARs", deck._ui_elements["active_dropdown"].options)

            # 9. Widget & UI Handlers
            self.assertIsNotNone(deck.widget)
            play_btn = deck._ui_elements["play_btn"]
            play_btn._click_handlers(play_btn)
            self.assertTrue(deck.is_playing)

            pause_btn = deck._ui_elements["pause_btn"]
            pause_btn._click_handlers(pause_btn)
            self.assertTrue(deck.is_paused)

            # 10. Kernel logging & history
            self.assertTrue(len(deck.history) >= 5)
            self.assertTrue(any("PLAY" in msg for _, msg in deck.history))

            # 11. Rich MIME bundle display (no HTML fallback, pure widget)
            bundle = deck._repr_mimebundle_()
            self.assertIsNotNone(bundle)
            self.assertIn("application/vnd.jupyter.widget-view+json", bundle)
            self.assertFalse(hasattr(deck, "_repr_html_"))
        finally:
            deck.stop()

        # 12. Missing dependency error handling
        from unittest import mock
        with mock.patch("lightshow.deck._check_ipywidgets", return_value=(False, "No module named 'ipywidgets'")):
            with self.assertRaises(ImportError) as ctx:
                ControlDeck({"A": s1}, rig=rig)
            self.assertIn("pip install ipywidgets", str(ctx.exception))
            self.assertIn("Restart Kernel", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
