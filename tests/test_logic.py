"""Logic without a screen: eye_aim, markdown and the face from the bot definition.

No window or toolkit: only calculating and parsing, so this also runs on a CI
machine without a display.
"""

import io
import json
import os
import plistlib
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from botwidget import (
    animation,
    avatar,
    bubble,
    bubble_layout,
    channel,
    config,
    delivery,
    dev,
    instance,
    markdown,
    openbot,
    startup,
    theme,
    updates,
)
from botwidget.system import linux, macos, windows
from botwidget.system.current import process_cmdline


class EyeAim(unittest.TestCase):
    """Should aim the gaze: far away nothing, nearby follows, on the face it looks at you."""

    def test_far_away_there_is_nothing_to_follow(self):
        self.assertIsNone(avatar.eye_aim(400, 0))
        self.assertIsNone(avatar.eye_aim(0, 900))
        self.assertIsNone(avatar.eye_aim(avatar.GAZE_NEAR, 0))

    def test_on_the_face_it_looks_straight_at_you(self):
        self.assertEqual(avatar.eye_aim(0, 0), (0.0, 0.0, 0.0, 1.0))
        self.assertEqual(avatar.eye_aim(avatar.ON_FACE, 0), (0.0, 0.0, 0.0, 1.0))
        self.assertEqual(avatar.eye_aim(-10, 12), (0.0, 0.0, 0.0, 1.0))

    def test_close_by_but_off_the_face_follows_the_pointer(self):
        dx, dy, conv, scale = avatar.eye_aim(45, 0)
        self.assertGreater(dx, 0)
        self.assertEqual(dy, 0)
        self.assertGreaterEqual(conv, 0)
        self.assertLess(conv, 6)
        self.assertLessEqual(scale, 1.0)

    def test_direction_is_kept(self):
        right = avatar.eye_aim(45, 0)
        left = avatar.eye_aim(-45, 0)
        self.assertEqual(round(right[0], 6), round(-left[0], 6))
        up = avatar.eye_aim(0, -45)
        self.assertLess(up[1], 0)

    def test_shift_is_capped(self):
        for vx, vy in ((35, 35), (40, 30), (-40, 3), (0, 36)):
            dx, dy = avatar.eye_aim(vx, vy)[:2]
            self.assertLessEqual(abs(dx), 8.0)
            self.assertLessEqual(abs(dy), 8.0)


class Markdown(unittest.TestCase):
    """Should turn markdown into blocks: headings, lists, code, links."""

    def test_inline_styles(self):
        self.assertEqual(markdown.md_inline("plain"), [("plain", "")])
        self.assertEqual(markdown.md_inline("**bold**"), [("bold", "b")])
        self.assertEqual(markdown.md_inline("*italic*"), [("italic", "i")])
        self.assertEqual(markdown.md_inline("`code`"), [("code", "code")])

    def test_link_is_label_plus_host(self):
        chunks = markdown.md_inline("[docs](https://example.com/pad?x=1)")
        self.assertEqual(chunks[0], ("docs", "link:https://example.com/pad?x=1"))
        self.assertEqual(chunks[1], (" (example.com)", "dim"))

    def test_only_http_links_are_clickable(self):
        self.assertEqual(markdown.anchor_url("link:https://example.com/x"), "https://example.com/x")
        self.assertEqual(markdown.anchor_url("link:http://example.com"), "http://example.com")
        self.assertEqual(markdown.anchor_url("link:file:///etc/passwd"), "")
        self.assertEqual(markdown.anchor_url("link:mailto:a@b.c"), "")
        self.assertEqual(markdown.anchor_url("b"), "")

    def test_a_bare_url_is_a_link_piece(self):
        self.assertEqual(markdown.md_inline("read https://example.com/x now"),
                         [("read ", ""), ("https://example.com/x", "link:https://example.com/x"),
                          (" now", "")])
        self.assertEqual(markdown.md_inline("go to https://example.com/x."),
                         [("go to ", ""), ("https://example.com/x", "link:https://example.com/x"),
                          (".", "")], "the sentence period stays text")
        self.assertEqual(markdown.md_inline("http://example.com"),
                         [("http://example.com", "link:http://example.com")])
        self.assertEqual(markdown.md_inline("a file:///etc/passwd b"), [("a file:///etc/passwd b", "")])

    def test_a_markdown_link_keeps_the_parentheses_in_its_url(self):
        url = "https://en.wikipedia.org/wiki/Foo_(bar)"
        chunks = markdown.md_inline(f"[page]({url})")
        self.assertEqual(chunks[0], ("page", "link:" + url), "the whole url is the href")
        self.assertEqual(chunks[1], (" (en.wikipedia.org)", "dim"))

    def test_a_bare_url_keeps_its_own_parentheses(self):
        url = "https://en.wikipedia.org/wiki/Foo_(bar)"
        self.assertEqual(markdown.md_inline("see " + url),
                         [("see ", ""), (url, "link:" + url)])
        self.assertEqual(markdown.md_inline("see " + url + "."),
                         [("see ", ""), (url, "link:" + url), (".", "")],
                         "the sentence period stays text")
        self.assertEqual(markdown.md_inline("(see " + url + ")."),
                         [("(see ", ""), (url, "link:" + url), (").", "")],
                         "the closing bracket that only ends the sentence stays text")

    def test_a_url_in_a_code_span_stays_code(self):
        self.assertEqual(markdown.md_inline("`https://example.com/x`"),
                         [("https://example.com/x", "code")])

    def test_blocks(self):
        blocks = markdown.md_blocks("# Heading\n\ntext\n\n- one\n- two")
        kinds = [b["kind"] for b in blocks]
        self.assertEqual(kinds[0], "text")
        self.assertTrue(blocks[0]["head"])
        self.assertEqual(theme.MD_HEAD_SIZE[1], blocks[0]["size"])
        bullets = [b for b in blocks if b.get("prefix") == "\u2022 "]
        self.assertEqual(len(bullets), 2)

    def test_code_block_keeps_lines(self):
        blocks = markdown.md_blocks("```\nline one\nline two\n```")
        self.assertEqual([b["kind"] for b in blocks], ["code"])
        self.assertEqual(blocks[0]["lines"], ["line one", "line two"])

    def test_code_block_is_cut_off(self):
        body = "\n".join(f"r{i}" for i in range(theme.BUBBLE_CODE_LINES + 3))
        lines = markdown.md_blocks("```\n" + body + "\n```")[0]["lines"]
        self.assertEqual(len(lines), theme.BUBBLE_CODE_LINES + 1)
        self.assertEqual(lines[-1], "\u2026")

    def test_block_text_is_plain(self):
        self.assertEqual(markdown.block_text(markdown.md_blocks("**bold** and *italic*")), "bold and italic")
        self.assertEqual(markdown.block_text(markdown.md_blocks("# Heading")), "Heading")
        self.assertEqual(markdown.block_text(markdown.md_blocks("- one\n- two")), "\u2022 one\n\u2022 two")

    def test_conversation_labels(self):
        blocks = markdown.conversation_blocks(
            [{"role": "user", "text": "hi"}, {"role": "bot", "text": "hello"}], "Robo")
        labels = [b["chunks"][0][0] for b in blocks
                  if b.get("chunks") and b["chunks"][0][1] == "b"]
        self.assertEqual(labels, ["You", "Robo"])

    def test_nothing_new_means_nothing(self):
        self.assertEqual(markdown.conversation_blocks([], "Robo"), [])


class AvatarProfile(unittest.TestCase):
    """Should derive silhouette, expression and colour from the seed, like OpenBot."""

    def test_is_deterministic(self):
        first = avatar.avatar_profile("agent-1", None)
        second = avatar.avatar_profile("agent-1", None)
        self.assertEqual(first, second)

    def test_shape_is_supported(self):
        for seed in ("a", "b", "robo", "agent-00000000-0000-0000-0000-000000000000"):
            self.assertIn(avatar.avatar_profile(seed, None)["shape"], avatar.SUPPORTED_SHAPES)

    def test_seed_spreads_the_shapes(self):
        shapes = {avatar.avatar_profile(f"seed-{i}", None)["shape"] for i in range(24)}
        self.assertGreater(len(shapes), 1)

    def test_hue_picks_the_colour(self):
        self.assertEqual(avatar.avatar_profile("x", 100)["hex"], avatar.AVATAR_HEX["vert"])
        self.assertEqual(avatar.avatar_profile("x", 215)["hex"], avatar.AVATAR_HEX["bleu"])
        self.assertEqual(avatar.avatar_profile("x", 999)["hex"], avatar.AVATAR_HEX["gris"])

    def test_empty_seed_still_gives_a_face(self):
        profile = avatar.avatar_profile("", None)
        self.assertIn(profile["shape"], avatar.SUPPORTED_SHAPES)
        self.assertGreater(profile["bottom"], 0)

    def test_stable_index_matches_fnv1a(self):
        # FNV-1a of "a" is 0xe40c292c; at length 7 that is 4.
        self.assertEqual(avatar.stable_index("a", 7), 0xE40C292C % 7)


class ProcessCmdline(unittest.TestCase):
    """Should make the single-instance check work without /proc."""

    @unittest.skipIf(sys.platform == "win32", "Windows cannot read the command line yet")
    def test_own_process_is_a_python_commandline(self):
        self.assertIn(b"python", process_cmdline(os.getpid()).lower())

    def test_missing_process_is_empty(self):
        self.assertEqual(process_cmdline(2 ** 22 + 12345), b"")

    def test_pidfile_lives_in_the_platform_tempdir(self):
        self.assertEqual(os.path.dirname(instance.PIDFILE), tempfile.gettempdir())


class BubbleLayout(unittest.TestCase):
    """Should break lines with the toolkit's measurement; here a fixed letter width."""

    @staticmethod
    def measure(text, style, size):
        return len(text) * 7.0

    def test_a_longer_text_stays_longer_but_not_forever(self):
        from botwidget.theme import BUBBLE_LINGER, BUBBLE_LINGER_MAX
        short, long_, huge = (bubble.reading_seconds(" ".join(["woord"] * n)) for n in (3, 60, 5000))
        self.assertGreater(short, BUBBLE_LINGER)
        self.assertGreater(long_, short)
        self.assertEqual(huge, BUBBLE_LINGER_MAX)
        self.assertEqual(bubble.reading_seconds(""), BUBBLE_LINGER)

    def test_the_arrow_for_earlier_messages_sits_close_and_never_under_a_dark_panel(self):
        from botwidget.bubble import panel_rects
        for role, text in (("bot", "Hoi"), ("user", "Hoi")):
            blocks = [markdown.role_panel("more"), markdown.plain_block("more")] + \
                markdown.conversation_blocks([{"role": role, "text": text}], "Bot")
            panels = bubble_layout.bubble_panels(self.measure, blocks)
            self.assertEqual([p["role"] for p in panels], ["more", role])
            (arrow_top, arrow_h), (message_top, _h) = panel_rects(panels)
            self.assertLess(message_top, arrow_top + arrow_h, "closer than a normal gap")
            chevron_bottom = arrow_top + 2 + 6 + 3
            if role == "user":
                self.assertGreater(message_top, chevron_bottom, "the dark panel does not cover the arrow")

    def test_plain_text_drops_the_marks_and_keeps_the_shape(self):
        raw = "Dit is **vet** en `code`.\n\n- punt een\n- punt twee\n\n```\nx = 1\n```\n\n[de site](https://x.nl)!"
        self.assertEqual(markdown.plain_text(raw),
                         "Dit is vet en code.\n\n• punt een\n• punt twee\n\nx = 1\n\nde site!")

    def test_a_single_message_has_no_name_above_it(self):
        text = markdown.block_text(markdown.conversation_blocks([{"role": "bot", "text": "Hoi daar"}], "Fritsie"))
        self.assertEqual(text, "Hoi daar")

    def test_several_messages_each_get_their_name(self):
        messages = [{"role": "user", "text": "Hoi"}, {"role": "bot", "text": "Hoi daar"}]
        text = markdown.block_text(markdown.conversation_blocks(messages, "Fritsie"))
        self.assertEqual(text, "You\nHoi\nFritsie\nHoi daar")

    def test_every_message_panel_knows_its_place_and_its_own_words(self):
        from botwidget.bubble import content_height, panel_rects
        messages = [{"role": "user", "text": "Eerste"}, {"role": "bot", "text": "Tweede\n\nderde"}]
        panels = bubble_layout.bubble_panels(self.measure, markdown.conversation_blocks(messages, "Bot"))
        self.assertEqual([p["copy"] for p in panels], ["Eerste", "Tweede\n\nderde"])
        rects = panel_rects(panels)
        self.assertEqual(rects[0][0], 0)
        self.assertGreater(rects[1][0], rects[0][0] + rects[0][1], "a gap between the panels")
        self.assertEqual(rects[-1][0] + rects[-1][1], content_height(panels))

    def test_long_text_breaks_within_the_width(self):
        lines, widest = bubble_layout.md_layout(self.measure, "word " * 40, 200)
        self.assertGreater(len(lines), 1)
        self.assertLessEqual(widest, 200)

    def test_short_text_stays_on_one_line(self):
        lines, _ = bubble_layout.md_layout(self.measure, "hello world", 300)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["xs"], [0, 42])

    def test_unbreakable_word_is_split(self):
        lines, _ = bubble_layout.md_layout(self.measure, "x" * 100, 120)
        self.assertGreater(len(lines), 1)


class Settings(unittest.TestCase):
    """Should put the face on top without a widget.json, and keep only known keys."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._old = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(self._dir.name, "widget.json")
        self.addCleanup(setattr, config, "CONFIG_PATH", self._old)

    def test_default_is_always_on_top(self):
        self.assertTrue(config.always_on_top())

    def test_turning_it_off_is_remembered(self):
        config.save_widget_config(always_on_top=False)
        self.assertFalse(config.always_on_top())

    def test_unknown_keys_are_not_stored(self):
        config.save_widget_config(sound=True, secret="x")
        self.assertEqual(config.widget_config(), {"sound": True})


class Detection(unittest.TestCase):
    """Should recognise OpenBot and Grok Bot by their folder and their gbot command."""

    def test_openbot_is_found_by_its_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            old = openbot.OPENBOT_DIR
            self.addCleanup(setattr, openbot, "OPENBOT_DIR", old)
            openbot.OPENBOT_DIR = folder
            self.assertTrue(openbot.openbot_installed())
            openbot.OPENBOT_DIR = os.path.join(folder, "missing")
            self.assertFalse(openbot.openbot_installed())

    def test_gbot_is_found_by_its_command(self):
        old = openbot.GBOT
        self.addCleanup(setattr, openbot, "GBOT", old)
        openbot.GBOT = sys.executable
        self.assertTrue(openbot.gbot_installed())
        openbot.GBOT = "/nonexistent/gbot"
        self.assertFalse(openbot.gbot_installed())


class Thinking(unittest.TestCase):
    """Should move the dots in short smooth steps and keep the activity to one short line."""

    def test_the_dots_tick_short_enough_to_look_fluid(self):
        self.assertLessEqual(theme.DOTS_MS, 40, "a short timer, not a slideshow")
        step = theme.DOTS_MS / 1000 / theme.DOTS_CYCLE_S
        self.assertGreaterEqual(1 / step, 20, "at least 20 frames per wave")

    def test_the_dot_wave_slows_at_its_crest(self):
        def radius(phase):
            svg = bubble.dots_svg(0, 0, phase, "#000")
            return float(svg.split('r="')[1].split('"')[0])

        climb = abs(radius(0.25) - radius(0.20))
        crest = abs(radius(0.30) - radius(0.25))
        self.assertLess(crest, climb, "a smooth crest, not a corner")

    def test_the_activity_line_is_one_short_line(self):
        self.assertEqual(markdown.activity_line("  reading   the file\nand more "), "reading the file")
        self.assertEqual(markdown.activity_line(""), "")
        long = markdown.activity_line("working on it " * 20)
        self.assertLessEqual(len(long), markdown.ACTIVITY_CHARS)
        self.assertTrue(long.endswith("…"))


class Clouds(unittest.TestCase):
    """Should give the thinking cloud one lobed silhouette and a tail of shrinking circles."""

    def test_trail_points_toward_the_face_from_every_side(self):
        clouds = {side: bubble.cloud_body_svg(200, 100, tip=50, side=side) for side in bubble.SIDES}
        self.assertEqual(len({svg.count("<circle") for svg in clouds.values()}), 1)
        self.assertEqual(len(set(clouds.values())), 4, "four different tails")

    def test_the_tail_of_the_chat_bubble_comes_out_of_the_edge_facing_the_face(self):
        # the white area is 200 by 100 at (18, 18); a tail pointing at 50 along its edge ends in these points
        tips = {"above": "50 125", "below": "50 11", "right": "11 50", "left": "225 50"}
        for side, apex in tips.items():
            self.assertIn(apex, bubble.bubble_body_svg(200, 100, tip=50, side=side), side)

    def test_cloud_and_chat_bubble_share_a_canvas_size(self):
        cloud = bubble.cloud_body_svg(200, 100)
        chat = bubble.bubble_body_svg(200, 100)

        def canvas(svg):
            return svg.split('width="')[1].split('"')[0], svg.split('height="')[1].split('"')[0]

        self.assertEqual(canvas(cloud), canvas(chat))

    def test_the_cloud_is_one_smooth_shape_not_a_box_with_circles(self):
        svg = bubble.cloud_body_svg(200, 100)
        self.assertEqual(svg.count("<path"), 1, "one silhouette")
        self.assertNotIn("<rect", svg, "no box behind the cloud")
        self.assertEqual(svg.count("<circle"), len(bubble.CLOUD_TRAIL),
                         "only the trail toward the head is circles")

    def test_the_cloud_follows_the_nuage_profile(self):
        svg = bubble.cloud_body_svg(200, 100)
        self.assertEqual(svg, bubble.cloud_body_svg(200, 100), "the shape does not wobble")
        self.assertGreater(svg.count("C"), 40, "a smooth curve through the 64 lobes")

    def test_shadow_matches_the_body_shape(self):
        shadow = bubble.cloud_shadow_svg(200, 100)
        body = bubble.cloud_body_svg(200, 100)
        self.assertEqual(shadow.count("<path"), body.count("<path"))
        self.assertEqual(shadow.count("<circle"), body.count("<circle"))


class FrameRate(unittest.TestCase):
    """Should animate at the fast rate whenever the face is held, moving or the pointer is near."""

    def test_calm_only_when_nothing_is_happening(self):
        self.assertEqual(animation.frame_ms(held=False, moving=False, pointer_near=False), animation.IDLE_MS)

    def test_hovering_alone_is_fast(self):
        self.assertEqual(animation.frame_ms(held=False, moving=False, pointer_near=True), animation.BUSY_MS)

    def test_held_or_moving_is_fast(self):
        self.assertEqual(animation.frame_ms(held=True, moving=False, pointer_near=False), animation.BUSY_MS)
        self.assertEqual(animation.frame_ms(held=False, moving=True, pointer_near=False), animation.BUSY_MS)

    def test_fast_means_at_least_sixty_frames_per_second(self):
        self.assertLessEqual(animation.BUSY_MS, 17)


class FrameCost(unittest.TestCase):
    """Should build a face frame far inside the 16 ms budget; the limit is loose so CI does not flake."""

    def test_building_a_frame_svg_is_fast(self):
        start = time.perf_counter()
        for i in range(100):
            avatar.face_svg(dx=i % 8, dy=2.0, converge=0.5, seed="robo", happy=0.5)
        self.assertLess((time.perf_counter() - start) / 100, 0.005)


class Rendering(unittest.TestCase):
    """Should render and animate a real face window offscreen."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui import face
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.face = face
        cls.app = QApplication.instance() or QApplication([])

    def aimed(self, at):
        window = self.face.FaceWindow("t", "Test", spot=(300, 400))
        self.addCleanup(window.close_face)
        window._poll_timer.stop()
        window._pointer = lambda: (window.x() + at[0], window.y() + at[1])
        window._aim(16)
        return window.anim.target

    def test_over_the_face_it_looks_at_you(self):
        target = self.aimed((34, 34))
        self.assertEqual((target["dx"], target["dy"], target["converge"], target["scale"]), (0, 0, 0, 1))

    def test_near_the_face_it_follows_the_pointer(self):
        self.assertGreater(self.aimed((34 + 45, 34))["dx"], 0)

    def test_far_away_it_goes_back_to_its_own_cycle(self):
        self.assertEqual(self.aimed((900, 900))["dx"], avatar.POSES["idle"][0])

    def test_a_frame_renders_in_a_few_milliseconds(self):
        from botwidget.qt_ui.render import svg_pixmap
        svg = avatar.face_svg(seed="robo")
        start = time.perf_counter()
        for _ in range(50):
            svg_pixmap(svg)
        self.assertLess((time.perf_counter() - start) / 50, 0.005)

    def test_hovering_switches_the_timer_to_the_fast_rate_and_back(self):
        window = self.face.FaceWindow("t", "Test", spot=(100, 100))
        try:
            near = {"on": True}
            window._pointer = lambda: (134, 134) if near["on"] else (5000, 5000)
            window._last_tick -= 0.05
            window._animate()
            self.assertEqual(window._anim_timer.interval(), animation.BUSY_MS)
            near["on"] = False
            for _ in range(200):
                window._last_tick -= 0.03
                window._animate()
            self.assertEqual(window._anim_timer.interval(), animation.IDLE_MS)
        finally:
            window._alive = False
            window.close()


class UpdateTick(unittest.TestCase):
    """Should restart into a staged update only when no face is in use, and look again for releases now and then."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from botwidget.qt_ui import faces
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.faces = faces

    def stub(self, staged, idle, probed=0.0):
        from types import SimpleNamespace
        calls = []
        me = SimpleNamespace(staged=staged, faces={"a": SimpleNamespace(idle=lambda: idle)},
                             _probed=probed, calls=calls,
                             install_update=lambda: calls.append("install"),
                             _start_probe=lambda: calls.append("probe"))
        return me

    def test_installs_a_staged_update_when_every_face_is_idle(self):
        me = self.stub("/x.zip", idle=True)
        self.faces.Faces._update_tick(me)
        self.assertEqual(me.calls, ["install"])

    def test_waits_while_someone_is_using_a_face(self):
        me = self.stub("/x.zip", idle=False)
        self.faces.Faces._update_tick(me)
        self.assertEqual(me.calls, [])

    def test_looks_for_a_new_release_after_the_recheck_interval_only(self):
        me = self.stub(None, idle=True, probed=time.monotonic())
        self.faces.Faces._update_tick(me)
        self.assertEqual(me.calls, [])
        me = self.stub(None, idle=True, probed=time.monotonic() - self.faces.RECHECK_S - 1)
        self.faces.Faces._update_tick(me)
        self.assertEqual(me.calls, ["probe"])


class BubbleScroll(unittest.TestCase):
    """Should keep the end of a long answer in view."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui import face
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.face = face
        cls.app = QApplication.instance() or QApplication([])

    def test_the_bubble_ends_at_the_end_of_a_long_answer(self):
        from botwidget.markdown import conversation_blocks
        window = self.face.FaceWindow("t", "Test", spot=(300, 400))
        self.addCleanup(window.close_face)
        window._poll_timer.stop()
        text = "Ja.\n\n" + "Een lange regel. " * 60 + "\n\nZal ik pushen?"
        window.bubble.show_blocks(conversation_blocks([{"role": "bot", "text": text}], "Test"), "say")
        import time
        deadline = time.monotonic() + 3
        while window.bubble._growth is not None and time.monotonic() < deadline:
            self.app.processEvents()
        self.app.processEvents()
        bar = window.bubble._scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        self.assertEqual(bar.value(), bar.maximum())


class BubbleWidth(unittest.TestCase):
    """Should give a long answer a wider bubble instead of only scrolling it."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui import face
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.face = face
        cls.app = QApplication.instance() or QApplication([])

    def width(self, text, screen=(0, 0, 1600, 900)):
        from botwidget.markdown import conversation_blocks
        old = self.face.screens.rects
        self.addCleanup(setattr, self.face.screens, "rects", old)
        self.face.screens.rects = lambda: [screen]
        old_at = self.face.screens.rect_at
        self.addCleanup(setattr, self.face.screens, "rect_at", old_at)
        self.face.screens.rect_at = lambda x, y: screen
        from botwidget.qt_ui import bubble_window
        self.addCleanup(setattr, bubble_window.screens, "rect_at", bubble_window.screens.rect_at)
        bubble_window.screens.rect_at = lambda x, y: screen
        window = self.face.FaceWindow("t", "Test", spot=(300, 400))
        self.addCleanup(window.close_face)
        window._poll_timer.stop()
        window.bubble.show_blocks(conversation_blocks([{"role": "bot", "text": text}], "Test"), "say")
        return window.bubble._geom[1]

    def test_a_short_answer_keeps_its_natural_width(self):
        from botwidget.theme import BUBBLE_MAX_W
        self.assertLessEqual(self.width("Ja."), BUBBLE_MAX_W)

    def test_a_long_answer_gets_a_wider_bubble(self):
        from botwidget.theme import BUBBLE_MAX_W
        self.assertGreater(self.width("Een lange regel met woorden. " * 80), BUBBLE_MAX_W)

    def test_the_bubble_never_takes_more_than_its_share_of_a_small_screen(self):
        from botwidget.theme import BUBBLE_MAX_W
        self.assertLessEqual(self.width("Een lange regel met woorden. " * 80, screen=(0, 0, 600, 900)), BUBBLE_MAX_W + 40)


class BubbleHover(unittest.TestCase):
    """Should show the bubble when pointed at and close it a while after the pointer left."""

    MESSAGES = [{"role": "user", "text": "Klaar?"}, {"role": "bot", "text": "Ja.\n\nZal ik pushen?"}]

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui import face
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.face = face
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        for name, value in (("latest_chat", lambda thread_id, limit=8: {"messages": self.MESSAGES, "activity": ""}),
                            ("openbot_installed", lambda: True), ("gbot_installed", lambda: True)):
            old = getattr(self.face, name)
            self.addCleanup(setattr, self.face, name, old)
            setattr(self.face, name, value)
        self.window = self.face.FaceWindow("t", "Test", spot=(300, 400))
        self.window._poll_timer.stop()
        self.addCleanup(self.window.close_face)
        self.where = {"at": (5000, 5000)}
        self.window._pointer = lambda: self.where["at"]

    def hover(self):
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        self.window._animate()
        self.finish_growth()

    def finish_growth(self):
        bubble = self.window.bubble
        bubble._slide.stop()
        bubble._growth_done()

    def test_pointing_at_the_face_opens_the_bubble_with_the_latest_answer(self):
        self.window._animate()
        self.assertFalse(self.window.bubble.isVisible())
        self.hover()
        self.assertTrue(self.window.bubble.isVisible())
        self.assertIn("Zal ik pushen?", self.window.bubble.full_text)

    def test_it_closes_at_once_when_the_pointer_leaves(self):
        self.hover()
        bubble = self.window.bubble
        bubble._tick()
        self.assertTrue(bubble.kind, "the pointer is still on the face")
        self.where["at"] = (5000, 5000)
        bubble._tick()
        self.assertEqual(bubble.kind, "")

    def test_a_bubble_nobody_pointed_at_closes_after_the_time_to_read_it(self):
        import time
        from botwidget.bubble import reading_seconds
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": ""})
        bubble = self.window.bubble
        bubble._tick()
        self.assertTrue(bubble.kind)
        bubble.changed = time.monotonic() - reading_seconds(bubble.full_text) + 1
        bubble._tick()
        self.assertTrue(bubble.kind, "still being read")
        bubble.changed = time.monotonic() - reading_seconds(bubble.full_text) - 1
        bubble._tick()
        self.assertEqual(bubble.kind, "")

    def test_showing_the_same_bubble_again_does_not_build_it_again(self):
        self.hover()
        bubble = self.window.bubble
        bubble._tick()
        self.where["at"] = (5000, 5000)
        bubble._tick()
        self.assertEqual(bubble.kind, "")
        built, chrome = bubble._built, bubble._chrome_pix
        calls = []
        old = bubble._parts
        bubble._parts = lambda: calls.append(1) or old()
        self.window._hover_retry = 0.0
        self.hover()
        self.assertTrue(bubble.isVisible())
        self.assertEqual(calls, [], "no new layout")
        self.finish_growth()
        self.assertEqual(bubble._chrome_pix.size(), chrome.size())
        self.assertEqual(bubble._built, built)

    def test_the_thinking_cloud_is_not_kept_open_by_its_dots(self):
        import time
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": "reading files"}, force=True)
        bubble = self.window.bubble
        self.assertEqual(bubble.kind, "think")
        before = bubble.changed
        time.sleep(0.01)
        bubble._tick_dots()
        self.assertEqual(bubble.changed, before)

    def test_selected_words_keep_the_bubble_open_until_the_selection_goes(self):
        import time
        from botwidget.theme import BUBBLE_LINGER
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": ""})
        bubble = self.window.bubble
        bubble._doc.hasFocus = lambda: True
        bubble._doc.selectAll()
        bubble.changed = time.monotonic() - BUBBLE_LINGER - 1
        bubble._tick()
        self.assertTrue(bubble.kind, "words are selected")
        bubble._doc.textCursor().clearSelection()
        cursor = bubble._doc.textCursor()
        cursor.clearSelection()
        bubble._doc.setTextCursor(cursor)
        bubble.changed = time.monotonic() - BUBBLE_LINGER - 1
        bubble._tick()
        self.assertEqual(bubble.kind, "")

    def send_mouse(self, kind, x, y, buttons=None, button=None, modifiers=None):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        viewport = self.window.bubble._doc.viewport()
        kind = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove, "release": QEvent.MouseButtonRelease}[kind]
        buttons = Qt.NoButton if buttons is None else buttons
        button = Qt.NoButton if button is None else button
        modifiers = Qt.NoModifier if modifiers is None else modifiers
        point = QPointF(x, y)
        QApplication.sendEvent(viewport, QMouseEvent(kind, point, QPointF(viewport.mapToGlobal(point.toPoint())),
                                                     button, buttons, modifiers))

    def message_point(self, index, down=24):
        """Where in the text view the n-th message is."""
        from botwidget.bubble import panel_rects
        bubble = self.window.bubble
        top, _height = panel_rects(bubble._geom[0])[index]
        return 40, top + down - bubble._doc.y()

    def click(self, index, modifiers=None):
        from PySide6.QtCore import Qt
        x, y = self.message_point(index)
        self.send_mouse("press", x, y, Qt.LeftButton, Qt.LeftButton, modifiers)
        self.send_mouse("release", x, y, Qt.NoButton, Qt.LeftButton, modifiers)

    def clipboard(self):
        from PySide6.QtWidgets import QApplication
        return QApplication.clipboard().text()

    def test_a_hand_shows_over_a_message_and_not_over_the_dots(self):
        from PySide6.QtCore import Qt
        self.window.pin()
        self.window._outbox.add("Hallo", "c7")
        self.window._pump_outbox = lambda: None
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": ""})
        bubble = self.window.bubble
        self.finish_growth()
        panels = bubble._geom[0]
        self.assertEqual(panels[-1]["copy"], "", "the dots are not a message")
        x, y = self.message_point(len(panels) - 2)
        self.send_mouse("move", x, y)
        self.assertEqual(bubble._doc.viewport().cursor().shape(), Qt.PointingHandCursor)
        x, y = self.message_point(len(panels) - 1)
        self.send_mouse("move", x, y)
        self.assertEqual(bubble._doc.viewport().cursor().shape(), Qt.ArrowCursor)

    def test_a_click_copies_the_message_as_plain_text(self):
        self.MESSAGES = [{"role": "bot", "text": "Dit is **vet** en `code`.\n\nTweede alinea."}]
        self.hover()
        self.click(0)
        self.assertEqual(self.clipboard(), "Dit is vet en code.\n\nTweede alinea.")
        notice = self.window.bubble._notice
        self.assertTrue(notice.isVisibleTo(self.window.bubble))
        self.assertEqual(notice.text, "Copied")

    def test_shift_click_copies_the_markdown(self):
        from PySide6.QtCore import Qt
        raw = "Dit is **vet** en `code`."
        self.MESSAGES = [{"role": "bot", "text": raw}]
        self.hover()
        self.click(0, Qt.ShiftModifier)
        self.assertEqual(self.clipboard(), raw)
        self.assertEqual(self.window.bubble._notice.text, "Copied markdown")

    def test_shift_click_only_copies_and_never_extends_a_selection(self):
        from PySide6.QtCore import Qt
        raw = "Een lange regel met woorden die over meerdere regels loopt in de bubbel, " * 2
        self.MESSAGES = [{"role": "bot", "text": raw}]
        self.hover()
        x, y = self.message_point(0)
        self.click_at(30, y)  # puts the text cursor somewhere
        self.send_mouse("move", 200, y + 25)
        self.send_mouse("press", 200, y + 25, Qt.LeftButton, Qt.LeftButton, Qt.ShiftModifier)
        self.assertFalse(self.window.bubble._doc.textCursor().hasSelection(), "not even while the button is down")
        self.send_mouse("release", 200, y + 25, Qt.NoButton, Qt.LeftButton, Qt.ShiftModifier)
        self.assertFalse(self.window.bubble._doc.textCursor().hasSelection(), "shift+click selects nothing")
        self.assertEqual(self.clipboard(), raw.strip(), "just the markdown")

    def test_each_message_copies_its_own_words(self):
        self.hover()
        self.window.show_older()
        self.finish_growth()
        self.click(0)
        self.assertEqual(self.clipboard(), "Klaar?")
        self.click(1)
        self.assertEqual(self.clipboard(), "Ja.\n\nZal ik pushen?")

    def test_clicking_the_arrow_loads_the_message_before(self):
        from PySide6.QtCore import Qt
        self.hover()
        self.assertEqual(self.window._depth, 1)
        x, y = self.message_point(0, down=8)
        self.assertEqual(self.window.bubble._geom[0][0]["role"], "more")
        self.send_mouse("move", x, y)
        self.assertEqual(self.window.bubble._doc.viewport().cursor().shape(), Qt.PointingHandCursor)
        self.click_at(x, y)
        self.assertEqual(self.window._depth, 2)

    def click_at(self, x, y):
        from PySide6.QtCore import Qt
        self.send_mouse("press", x, y, Qt.LeftButton, Qt.LeftButton)
        self.send_mouse("release", x, y, Qt.NoButton, Qt.LeftButton)

    def test_a_click_neither_selects_nor_closes(self):
        self.hover()
        self.click(0)
        self.assertFalse(self.window.bubble._doc.textCursor().hasSelection())
        self.assertTrue(self.window.bubble.isVisible())

    def test_dragging_selects_with_the_text_cursor_and_copies_the_selection_on_release(self):
        from PySide6.QtCore import Qt
        self.MESSAGES = [{"role": "bot", "text": "Een lange regel met woorden die vanzelf over twee regels loopt in de bubbel."}]
        self.hover()
        bubble = self.window.bubble
        x, y = self.message_point(0)
        self.send_mouse("press", 20, y, Qt.LeftButton, Qt.LeftButton)
        self.send_mouse("move", 120, y, Qt.LeftButton, Qt.NoButton)
        self.assertEqual(bubble._doc.viewport().cursor().shape(), Qt.IBeamCursor, "selecting")
        self.send_mouse("move", 240, y, Qt.LeftButton, Qt.NoButton)
        self.send_mouse("release", 240, y, Qt.NoButton, Qt.LeftButton)
        selected = bubble._doc.textCursor().selectedText()
        self.assertTrue(selected)
        self.assertEqual(self.clipboard(), selected.replace("\u2029", "\n"))
        self.assertTrue(bubble._notice.isVisibleTo(bubble))
        self.assertEqual(bubble._notice.text, "Copied")

    def test_the_notice_fades_the_words_behind_it_and_then_goes(self):
        import time
        self.MESSAGES = [{"role": "bot", "text": "Een korte zin."}]
        self.hover()
        self.click(0)
        notice = self.window.bubble._notice
        levels, deadline = [], time.monotonic() + 4
        while notice.isVisible() and time.monotonic() < deadline:
            self.app.processEvents()
            levels.append(notice.level)
        self.assertFalse(notice.isVisible(), "gone again")
        self.assertGreater(max(levels), 0.95, "fully over the words at its strongest")
        self.assertLess(levels[0], max(levels), "fades in")
        self.assertLess(levels[-1], max(levels), "and out")

    def test_the_notice_sits_over_the_message_that_was_copied(self):
        self.hover()
        self.window.show_older()
        self.finish_growth()
        self.click(1)
        from botwidget.bubble import panel_rects
        bubble = self.window.bubble
        top, height = panel_rects(bubble._geom[0])[1]
        self.assertEqual((bubble._notice.y(), bubble._notice.height()), (top - bubble._scroll.verticalScrollBar().value(), height))

    def test_a_selection_over_wrapped_lines_copies_as_one_line(self):
        from PySide6.QtCore import Qt
        text = "Een lange regel met woorden die vanzelf over meerdere regels loopt in de bubbel, " * 2
        self.MESSAGES = [{"role": "bot", "text": text}]
        self.hover()
        bubble = self.window.bubble
        doc = bubble._doc
        cursor = doc.textCursor()
        cursor.setPosition(0)
        cursor.movePosition(cursor.MoveOperation.End, cursor.MoveMode.KeepAnchor)
        doc.setTextCursor(cursor)
        from botwidget.qt_ui.text_doc import selected_text
        copied = selected_text(doc.document(), cursor.selectionStart(), cursor.selectionEnd())
        self.assertNotIn("\n", copied, "wrapped lines are one paragraph")
        self.assertEqual(copied.split(), text.split())

    def corner_is_warning(self):
        from PySide6.QtGui import QColor
        image = self.window.grab().toImage()
        ratio = image.devicePixelRatio()
        pixel = image.pixelColor(int(61 * ratio), int(61 * ratio))
        warn = QColor(self.face.WARN_COLOR)
        return abs(pixel.red() - warn.red()) < 12 and abs(pixel.green() - warn.green()) < 12

    def test_a_waiting_message_puts_a_warning_dot_on_the_face(self):
        self.assertFalse(self.window.unsent())
        self.assertFalse(self.corner_is_warning())
        self.window._outbox.add("hallo", "c1")
        self.window._on_message_done("c1", False, True, "HTTP 503")
        self.assertTrue(self.window.unsent())
        self.assertTrue(self.corner_is_warning())
        self.window._outbox.sent("c1")
        self.window._on_message_done("c1", True, False, "")
        self.assertFalse(self.window.unsent())

    def test_a_refused_message_keeps_the_dot_until_you_look(self):
        self.window._outbox.add("hallo", "c2")
        self.window._on_message_done("c2", False, False, "HTTP 400")
        self.assertTrue(self.window.unsent())
        self.window.pin()
        self.assertFalse(self.window.unsent())

    def test_a_message_shows_at_once_with_the_thinking_dots_before_openbot_confirms(self):
        self.window.pin()
        self.window.bubble._entry.setText("Hallo daar")
        old = self.window._pump_outbox
        self.window._pump_outbox = lambda: None
        self.addCleanup(setattr, self.window, "_pump_outbox", old)
        self.window.bubble._entry.returnPressed.emit()
        self.assertIn("Hallo daar", self.window.bubble.full_text)
        self.assertTrue(self.window.bubble._dots_lines, "the dots show as soon as the message is on its way")

    def test_the_bubble_stays_open_until_the_answer_is_in(self):
        self.hover()
        bubble = self.window.bubble
        bubble._tick()
        self.window._outbox.add("Hallo", "w1")
        self.window._pump_outbox = lambda: None
        self.where["at"] = (5000, 5000)
        bubble._tick()
        self.assertTrue(bubble.kind, "pointer gone, answer not in yet")
        bubble.changed -= 100
        bubble._tick()
        self.assertTrue(bubble.kind, "waiting does not run out of patience quickly")
        self.window._outbox.sent("w1")
        self.window._sync_bubble({"messages": self.MESSAGES + [{"role": "bot", "text": "Antwoord."}], "activity": ""})
        bubble._tick()
        self.assertTrue(bubble.kind, "the answer itself gets shown before the bubble goes")

    def test_a_bot_that_never_answers_does_not_keep_the_bubble_forever(self):
        import time
        from botwidget.theme import BUBBLE_WAIT_MAX
        self.hover()
        bubble = self.window.bubble
        bubble._tick()
        self.window._outbox.add("Hallo", "w2")
        self.where["at"] = (5000, 5000)
        bubble._tick()
        bubble._wait_since = time.monotonic() - BUBBLE_WAIT_MAX - 1
        bubble.changed = time.monotonic() - 100
        bubble._tick()
        self.assertEqual(bubble.kind, "")

    def test_the_dots_move_in_a_bubble_that_was_already_open(self):
        self.window.pin()
        bubble = self.window.bubble
        self.assertFalse(bubble._dots.isActive())
        self.window._pump_outbox = lambda: None
        self.window.bubble._entry.setText("Hallo daar")
        self.window.bubble._entry.returnPressed.emit()
        self.assertTrue(bubble._dots_lines)
        self.assertTrue(bubble._dots.isActive(), "the animation timer runs as soon as there are dots")
        phase = bubble._dots_phase
        bubble._tick_dots()
        self.assertNotEqual(bubble._dots_phase, phase)

    def test_a_message_that_waits_for_openbot_shows_the_note_and_no_dots(self):
        self.window.pin()
        self.window._outbox.add("Hallo daar", "c9")
        self.window._on_message_done("c9", False, True, "HTTP 503")
        self.assertIn("Hallo daar", self.window.bubble.full_text)
        self.assertFalse(self.window.bubble._dots_lines)

    def test_a_refused_message_stays_visible_next_to_the_reason(self):
        self.window.pin()
        self.window._outbox.add("Hallo daar", "c8")
        self.window._on_message_done("c8", False, False, "HTTP 400")
        self.assertIn("I couldn't send that", self.window.bubble.full_text)
        self.window.show_older()
        self.assertIn("Hallo daar", self.window.bubble.full_text, "what you typed is one scroll up")

    def test_a_pointer_that_never_moved_still_opens_the_bubble(self):
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        bubble = self.window.bubble
        bubble.place("")
        self.window._hovered = True  # it was on the face before, as when the desktop changes under it
        self.window._animate()
        self.assertTrue(bubble.isVisible(), "no movement needed")

    def test_a_bubble_closed_on_purpose_comes_back_after_a_while_if_the_pointer_stays(self):
        import time
        self.hover()
        bubble = self.window.bubble
        self.window.unpin()
        self.assertFalse(bubble.isVisible())
        self.window._hover_retry = 0.0
        self.window._animate()
        self.assertFalse(bubble.isVisible(), "not at once: Escape or clicking away was meant")
        self.window._hover_blocked_until = time.monotonic() - 0.1
        self.window._hover_retry = 0.0
        self.window._animate()
        self.assertTrue(bubble.isVisible(), "the pointer is still on the face")

    def test_closing_with_the_pointer_elsewhere_blocks_nothing(self):
        self.hover()
        self.where["at"] = (5000, 5000)
        self.window._animate()
        self.window.unpin()
        self.assertEqual(self.window._hover_blocked_until, 0.0)

    def test_a_thrown_face_loses_its_bubble_and_does_not_get_it_back_while_flying(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        self.hover()
        self.assertTrue(self.window.bubble.isVisible())
        self.window._drag_origin = [self.window.spot()]
        self.window._press_pos = (0.0, 0.0)
        self.window._dvx, self.window._dvy = 2000.0, 0.0
        point = QPointF(5, 5)
        QApplication.sendEvent(self.window, QMouseEvent(QEvent.MouseButtonRelease, point, point, Qt.LeftButton,
                                                        Qt.NoButton, Qt.NoModifier))
        self.assertTrue(self.window._coasting)
        self.assertFalse(self.window.bubble.isVisible(), "the bubble goes when the face is thrown")
        self.window._hover_retry = 0.0
        self.window._animate()
        self.assertFalse(self.window.bubble.isVisible(), "and stays away while the face is flying")
        self.window._coasting = False

    def test_the_input_field_is_there_from_the_start(self):
        self.hover()
        self.assertTrue(self.window.bubble._entry.isVisibleTo(self.window.bubble))

    def test_a_conversation_that_has_not_started_greets_you_with_the_field(self):
        self.MESSAGES = []
        self.hover()
        self.assertTrue(self.window.bubble.isVisible())
        self.assertIn("Ask me anything", self.window.bubble.full_text)
        self.assertTrue(self.window.bubble._entry.isVisibleTo(self.window.bubble))

    def test_the_field_gets_focus_only_when_the_pointer_stays(self):
        focus = []
        old = self.face.activate_app
        self.addCleanup(setattr, self.face, "activate_app", old)
        self.face.activate_app = lambda: None
        self.window.bubble.focus_entry = lambda: focus.append(1)
        self.hover()
        self.assertEqual(focus, [], "just arrived")
        self.window._animate()
        self.assertEqual(focus, [], "not long enough")
        self.window._hover_since -= 1
        self.window._animate()
        self.assertEqual(focus, [1])
        self.window._animate()
        self.assertEqual(focus, [1], "once")

    def test_flying_past_the_face_never_takes_the_keyboard(self):
        focus = []
        self.window.bubble.focus_entry = lambda: focus.append(1)
        self.hover()
        self.where["at"] = (5000, 5000)
        self.window._animate()
        self.window._hover_since -= 1
        self.window._animate()
        self.assertEqual(focus, [])

    def test_an_empty_field_does_not_keep_the_bubble_when_the_pointer_leaves(self):
        self.hover()
        bubble = self.window.bubble
        bubble._tick()
        bubble._entry.hasFocus = lambda: True
        self.where["at"] = (5000, 5000)
        bubble._tick()
        self.assertEqual(bubble.kind, "")

    def test_typed_words_keep_the_bubble_when_the_pointer_leaves(self):
        self.hover()
        bubble = self.window.bubble
        bubble._tick()
        bubble._entry.hasFocus = lambda: True
        bubble._entry.setText("half een zin")
        self.where["at"] = (5000, 5000)
        bubble._tick()
        self.assertTrue(bubble.kind)

    def test_clicking_away_from_an_empty_field_closes_even_a_pinned_bubble(self):
        self.window.pin()
        bubble = self.window.bubble
        has = {"focus": True}
        bubble._entry.hasFocus = lambda: has["focus"]
        bubble._tick()
        has["focus"] = False
        bubble._tick()
        self.assertEqual(bubble.kind, "")
        self.assertFalse(self.window.pinned)

    def test_only_the_latest_message_shows_at_first(self):
        self.hover()
        text = self.window.bubble.full_text
        self.assertIn("Zal ik pushen?", text)
        self.assertNotIn("Klaar?", text)
        self.assertEqual(self.window.bubble._geom[0][0]["role"], "more", "an arrow on top says there is more")

    def test_scrolling_up_adds_the_message_before_and_the_hint_goes_when_there_is_no_more(self):
        self.hover()
        self.window.show_older()
        text = self.window.bubble.full_text
        self.assertIn("Klaar?", text)
        self.assertIn("Zal ik pushen?", text)
        self.assertNotEqual(self.window.bubble._geom[0][0]["role"], "more", "nothing more to scroll to")
        self.window.show_older()
        self.assertEqual(self.window._depth, 2, "nothing older to load")

    def test_a_bubble_grows_out_of_a_small_one_when_it_opens(self):
        import time
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        self.window._animate()
        bubble = self.window.bubble
        self.assertIsNotNone(bubble._growth)
        start = (bubble.width(), bubble.height())
        self.assertLess(bubble.windowOpacity(), 1.0, "it fades in")
        deadline = time.monotonic() + 3
        while bubble._growth is not None and time.monotonic() < deadline:
            self.app.processEvents()
        self.assertIsNone(bubble._growth)
        self.assertGreater(bubble.width(), start[0])
        self.assertGreater(bubble.height(), start[1])
        self.assertEqual(bubble.windowOpacity(), 1.0)

    def test_a_bubble_near_the_top_edge_picks_its_side_for_its_final_size(self):
        self.window._move_icon(300, 60)
        self.window._remember_spot()
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        old = self.face.screens.rect_at
        self.addCleanup(setattr, self.face.screens, "rect_at", old)
        self.face.screens.rect_at = lambda x, y: (0, 0, 1600, 900)
        from botwidget.qt_ui import bubble_window
        self.addCleanup(setattr, bubble_window.screens, "rect_at", bubble_window.screens.rect_at)
        bubble_window.screens.rect_at = lambda x, y: (0, 0, 1600, 900)
        self.MESSAGES = [{"role": "bot", "text": "Een lange regel met woorden. " * 25}]
        self.window._animate()
        bubble = self.window.bubble
        sides = set()
        for t in (0.0, 0.1, 0.3, 0.6, 0.9, 1.0):
            bubble._growth_step(t)
            sides.add(bubble._goal()[2][1])
        self.assertEqual(len(sides), 1, "the same side from the first frame to the last")
        self.finish_growth()

    def screen(self, rect):
        from botwidget.qt_ui import bubble_window
        for module in (self.face.screens, bubble_window.screens):
            old = module.rect_at
            self.addCleanup(setattr, module, "rect_at", old)
            module.rect_at = lambda x, y, rect=rect: rect

    def side_for(self, face_at, text, screen):
        self.screen(screen)
        self.window._move_icon(*face_at)
        self.window._remember_spot()
        self.MESSAGES = [{"role": "bot", "text": text}]
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        self.window._animate()
        self.finish_growth()
        return self.window.bubble._goal()

    LONG = "Een lange regel met woorden. " * 25

    def test_the_bubble_goes_above_the_face_when_there_is_room(self):
        _tx, _ty, (_pos, side) = self.side_for((700, 500), "Kort.", (0, 0, 1600, 900))
        self.assertEqual(side, "above")

    def test_without_room_above_it_goes_to_the_right(self):
        tx, ty, (pos, side) = self.side_for((300, 40), self.LONG, (0, 0, 1600, 900))
        self.assertEqual(side, "right")
        self.assertGreater(tx, self.window.x() + 34 - 20, "right of the face")
        self.assertLessEqual(abs(ty + pos - (self.window.y() + 34)), 1, "the tail points at the middle of the face")

    def test_without_room_above_or_to_the_right_it_goes_to_the_left(self):
        tx, ty, (pos, side) = self.side_for((1500, 40), self.LONG, (0, 0, 1600, 900))
        self.assertEqual(side, "left")
        self.assertLess(tx + self.window.bubble.width(), self.window.x() + 34 + 20, "left of the face")
        self.assertLessEqual(abs(ty + pos - (self.window.y() + 34)), 1)

    def test_below_the_face_only_when_nothing_else_fits(self):
        _tx, _ty, (_pos, side) = self.side_for((150, 40), self.LONG, (0, 0, 420, 900))
        self.assertEqual(side, "below")

    def test_the_tail_points_at_the_face_in_every_frame_of_the_growth(self):
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        self.window._animate()
        bubble = self.window.bubble
        face_x = self.window.x() + 34
        for t in (0.0, 0.15, 0.4, 0.7, 1.0):
            bubble._growth_step(t)
            tip_x = bubble.x() + bubble._tip[0]
            self.assertEqual(bubble._tip[1], "above")
            self.assertLessEqual(abs(tip_x - face_x), 1, f"at {t}: the tail is at {tip_x}, the face at {face_x}")

    def test_the_tail_is_right_after_the_bubble_shrinks_too(self):
        self.hover()
        self.window._sync_bubble({"messages": self.MESSAGES + [{"role": "bot", "text": "Een lange regel. " * 40}], "activity": ""})
        self.finish_growth()
        self.window._sync_bubble({"messages": self.MESSAGES + [{"role": "bot", "text": "Kort."}], "activity": ""})
        bubble = self.window.bubble
        for t in (0.0, 0.5, 1.0):
            bubble._growth_step(t)
            self.assertLessEqual(abs(bubble.x() + bubble._tip[0] - (self.window.x() + 34)), 1)
        self.finish_growth()

    def test_the_field_waits_until_the_bubble_has_grown_a_bit(self):
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        self.window._animate()
        bubble = self.window.bubble
        bubble._growth_step(0.1)
        self.assertFalse(bubble._entry.isVisibleTo(bubble))
        bubble._growth_step(0.6)
        self.assertTrue(bubble._entry.isVisibleTo(bubble))

    def test_growing_stays_inside_the_tail_and_the_final_size_is_the_normal_one(self):
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        self.window._animate()
        bubble = self.window.bubble
        for t in (0.0, 0.3, 0.7):
            bubble._growth_step(t)
            self.assertLessEqual(bubble.width(), 2 * 18 + 2 * 12 + 600)
        self.finish_growth()
        full = (bubble.width(), bubble.height())
        bubble.place("")
        bubble._built = None
        self.window._hover_retry = 0.0
        self.hover()
        self.assertEqual((bubble.width(), bubble.height()), full)

    def test_a_longer_answer_grows_the_open_bubble_instead_of_jumping(self):
        self.hover()
        bubble = self.window.bubble
        before = (bubble.width(), bubble.height())
        long_text = "Een lange regel met woorden. " * 30
        self.window._sync_bubble({"messages": self.MESSAGES + [{"role": "bot", "text": long_text}], "activity": ""})
        self.assertIsNotNone(bubble._growth, "growing")
        self.finish_growth()
        self.assertGreater(bubble.height(), before[1])

    def test_the_older_message_slides_in_and_the_bubble_ends_up_complete(self):
        import time
        self.hover()
        bubble = self.window.bubble
        before = bubble.height()
        self.window.show_older()
        self.assertIsNotNone(bubble._growth, "sliding in")
        self.assertLess(bubble.height(), before + 200)
        deadline = time.monotonic() + 3
        while bubble._growth is not None and time.monotonic() < deadline:
            self.app.processEvents()
        self.assertIsNone(bubble._growth)
        self.assertGreater(bubble.height(), before, "grown to hold the older message")
        self.assertEqual(bubble._scroll.verticalScrollBar().value(), 0, "the new message is at the top")

    def test_the_mouse_wheel_at_the_top_loads_the_message_before_once_per_pause(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtWidgets import QApplication
        self.hover()
        bubble = self.window.bubble
        up = lambda: QApplication.sendEvent(bubble._scroll.viewport(), QWheelEvent(
            QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
            Qt.NoScrollPhase, False))
        up()
        self.assertEqual(self.window._depth, 2)
        up()
        self.assertEqual(self.window._depth, 2, "no flood of messages from one flick")

    def test_a_new_message_brings_back_only_the_latest(self):
        self.hover()
        self.window.show_older()
        self.assertEqual(self.window._depth, 2)
        self.MESSAGES = self.MESSAGES + [{"role": "bot", "text": "Nog iets."}]
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": ""})
        self.assertEqual(self.window._depth, 1)
        self.assertNotIn("Klaar?", self.window.bubble.full_text)

    def test_pointing_at_the_face_again_starts_from_the_latest_message(self):
        self.hover()
        self.window.show_older()
        self.where["at"] = (5000, 5000)
        self.window._animate()
        self.window.bubble._tick()
        self.window.bubble.place("")
        self.window._hover_retry = 0.0
        self.hover()
        self.assertEqual(self.window._depth, 1)

    def test_clicking_on_its_own_words_to_select_them_is_not_leaving(self):
        from unittest import mock
        from PySide6.QtWidgets import QApplication
        self.window.pin()
        bubble = self.window.bubble
        has = {"focus": True}
        bubble._entry.hasFocus = lambda: has["focus"]
        bubble._tick()
        has["focus"] = False
        with mock.patch.object(QApplication, "activeWindow", return_value=bubble):
            bubble._tick()
        self.assertTrue(bubble.kind)
        self.assertTrue(self.window.pinned)

    def test_clicking_the_words_neither_opens_nor_closes_the_bubble(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        self.hover()
        bubble = self.window.bubble
        pinned = self.window.pinned
        QTest.mouseClick(bubble._doc.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(30, 30))
        self.assertTrue(bubble.isVisible())
        self.assertEqual(self.window.pinned, pinned)


    def test_a_click_on_the_face_puts_the_cursor_in_the_field(self):
        focus = []
        old = self.face.activate_app
        self.addCleanup(setattr, self.face, "activate_app", old)
        self.face.activate_app = lambda: None
        self.window.bubble.focus_entry = lambda: focus.append(1)
        self.window.open_input()
        self.assertTrue(self.window.bubble.isVisible())
        self.assertEqual(focus, [1])
        self.window.open_input()
        self.assertTrue(self.window.bubble.isVisible(), "a second click does not close it")

    def test_there_is_no_tooltip(self):
        self.assertEqual(self.window.toolTip(), "")


class LatestChat(unittest.TestCase):
    """Should hand the bubble whole messages, not the first 500 characters of them."""

    def chat(self, text):
        import sqlite3
        from botwidget import openbot
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "openbot.db")
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE projection_thread_messages (thread_id, author, item_type, message_json, created_at)")
        con.execute("INSERT INTO projection_thread_messages VALUES ('t', 'bot', 'final_answer', ?, 1)",
                    (json.dumps({"text": text}),))
        con.commit()
        con.close()
        old = openbot.DB_FILE
        self.addCleanup(setattr, openbot, "DB_FILE", old)
        openbot.DB_FILE = path
        return openbot.latest_chat("t")["messages"][-1]["text"]

    def test_a_long_answer_arrives_whole(self):
        text = "Dit is een lange zin. " * 60 + "Zal ik de 2 commits pushen?"
        self.assertGreater(len(text), 500)
        self.assertEqual(self.chat(text), text)

    def test_a_runaway_answer_is_cut_with_an_ellipsis(self):
        from botwidget import openbot
        text = self.chat("x" * (openbot.MESSAGE_CHARS + 500))
        self.assertTrue(text.endswith("…"))
        self.assertLessEqual(len(text), openbot.MESSAGE_CHARS + 1)


class ScreenChanges(unittest.TestCase):
    """Should move the face onto a screen when its screen goes, and back when the screen returns."""

    BOTH = [(0, 0, 1000, 800), (1000, 0, 1000, 800)]
    LAPTOP = [(0, 0, 1000, 800)]

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui import face
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.face = face
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.layout = list(self.BOTH)
        old = self.face.screens.rects
        self.addCleanup(setattr, self.face.screens, "rects", old)
        self.face.screens.rects = lambda: self.layout
        self.window = self.face.FaceWindow("t", "Test", spot=(1500, 300))
        self.window._poll_timer.stop()
        self.addCleanup(self.window.close_face)

    def test_it_stays_when_its_screen_stays(self):
        self.window._settle()
        self.assertEqual(self.window.spot(), (1500, 300))

    def test_it_moves_onto_the_remaining_screen_and_returns_with_the_second_one(self):
        self.layout[:] = self.LAPTOP
        self.window._settle()
        x, y = self.window.spot()
        self.assertTrue(0 <= x <= 1000 - 68 and 0 <= y <= 800 - 68, self.window.spot())
        self.layout[:] = self.BOTH
        self.window._settle()
        self.assertEqual(self.window.spot(), (1500, 300))

    def test_a_spot_chosen_by_the_user_is_the_one_to_return_to(self):
        self.window._move_icon(200, 100)
        self.window._remember_spot()
        self.layout[:] = self.LAPTOP
        self.window._settle()
        self.assertEqual(self.window.spot(), (200, 100))


class QuietHours(unittest.TestCase):
    """Should keep the answer sound off during the night, only when asked for."""

    def test_the_night_is_quiet_when_enabled(self):
        for hour in (22, 23, 0, 3, 7):
            self.assertTrue(config.quiet_now(hour, True), hour)
        for hour in (8, 12, 21):
            self.assertFalse(config.quiet_now(hour, True), hour)

    def test_never_quiet_when_not_enabled(self):
        self.assertFalse(any(config.quiet_now(hour, False) for hour in range(24)))

    def test_the_sound_follows_the_setting_and_the_clock(self):
        from unittest import mock
        from botwidget import sound
        cases = [({"sound": True}, 23, 1), ({"sound": True, "quiet_hours": True}, 23, 0),
                 ({"sound": True, "quiet_hours": True}, 12, 1), ({"sound": False}, 12, 0)]
        for settings, hour, plays in cases:
            with mock.patch.object(sound, "widget_config", return_value=settings), \
                    mock.patch.object(sound, "play_notification") as play, \
                    mock.patch.object(sound.datetime, "datetime") as now:
                now.now.return_value.hour = hour
                sound.play_sound()
                self.assertEqual(play.call_count, plays, (settings, hour))


class Hotkey(unittest.TestCase):
    """Should open the chat of the first face from the global key combination, and close it again."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui import faces
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.faces = faces
        cls.app = QApplication.instance() or QApplication([])

    def test_the_key_toggles_the_chat_of_the_first_face(self):
        from types import SimpleNamespace
        calls = []
        face = SimpleNamespace(pinned=False, pin=lambda: calls.append("pin"), unpin=lambda: calls.append("unpin"),
                               bring_here=lambda: False)
        me = SimpleNamespace(faces={"a": face})
        old = self.faces.activate_app
        self.addCleanup(setattr, self.faces, "activate_app", old)
        self.faces.activate_app = lambda: calls.append("activate")
        self.faces.Faces.hotkey(me)
        self.assertEqual(calls, ["activate", "pin"])
        face.pinned = True
        self.faces.Faces.hotkey(me)
        self.assertEqual(calls[2:], ["unpin"])

    def test_the_bubble_comes_along_with_the_face(self):
        from unittest import mock
        from botwidget.qt_ui import face as face_module
        window = face_module.FaceWindow("t", "Test", spot=(300, 400))
        self.addCleanup(window.close_face)
        window._poll_timer.stop()
        window.bubble.show_blocks(face_module.conversation_blocks([{"role": "bot", "text": "Hoi"}], "T"), "say")
        moved = []
        with mock.patch.object(face_module.desktops, "bring_here", side_effect=lambda w: moved.append(w) or True):
            self.assertTrue(window.bring_here())
        self.assertEqual(moved, [window, window.bubble])
        moved.clear()
        window.bubble.place("")
        with mock.patch.object(face_module.desktops, "bring_here", side_effect=lambda w: moved.append(w) or True):
            window.bring_here()
        self.assertEqual(moved, [window], "a closed bubble opens on the right desktop by itself")

    def test_a_bubble_that_opens_checks_which_desktop_it_is_on(self):
        from unittest import mock
        from botwidget.qt_ui import bubble_window, face as face_module
        window = face_module.FaceWindow("t", "Test", spot=(300, 400))
        self.addCleanup(window.close_face)
        window._poll_timer.stop()
        with mock.patch.object(bubble_window.desktops, "bring_here") as bring:
            window.bubble.show_blocks(face_module.conversation_blocks([{"role": "bot", "text": "Hoi"}], "T"), "say")
        bring.assert_called_with(window.bubble)

    def test_the_key_brings_a_face_from_another_desktop_and_opens_it_instead_of_closing(self):
        from types import SimpleNamespace
        calls = []
        face = SimpleNamespace(pinned=True, pin=lambda: calls.append("pin"), unpin=lambda: calls.append("unpin"),
                               bring_here=lambda: True)
        old = self.faces.activate_app
        self.addCleanup(setattr, self.faces, "activate_app", old)
        self.faces.activate_app = lambda: None
        self.faces.Faces.hotkey(SimpleNamespace(faces={"a": face}))
        self.assertEqual(calls, ["pin"], "it was pinned on the other desktop; here it must show, not close")

    def test_no_faces_no_error(self):
        from types import SimpleNamespace
        self.faces.Faces.hotkey(SimpleNamespace(faces={}))

    @unittest.skipUnless(sys.platform == "darwin", "the key combination is macOS only so far")
    def test_the_system_callback_reaches_our_function(self):
        calls = []
        handler = macos._hotkey_handler(lambda: calls.append(1))
        self.assertEqual(handler(None, None, None), 0)
        self.assertEqual(calls, [1])

    def test_other_systems_say_there_is_no_key_yet(self):
        for module in (linux, windows):
            self.assertFalse(module.register_hotkey(lambda: None))


class Desktops(unittest.TestCase):
    """Should keep the face and its bubble on every desktop, or on the one you leave them on."""

    def test_on_every_desktop_is_the_default(self):
        from unittest import mock
        with mock.patch.object(config, "widget_config", return_value={}):
            self.assertTrue(config.all_desktops())
        with mock.patch.object(config, "widget_config", return_value={"all_desktops": False}):
            self.assertFalse(config.all_desktops())

    def test_the_mac_behaviour_differs_by_whether_you_can_move_it_in_mission_control(self):
        everywhere, single = macos.desktop_behavior(True), macos.desktop_behavior(False)
        self.assertTrue(everywhere & macos.CAN_JOIN_ALL_SPACES)
        self.assertFalse(single & macos.CAN_JOIN_ALL_SPACES)
        self.assertTrue(single & macos.MANAGED)
        self.assertTrue(everywhere & single & macos.FULL_SCREEN_AUXILIARY, "over full-screen apps in both")

    def test_only_real_windows_are_told_which_desktops(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from unittest import mock
            from PySide6.QtWidgets import QApplication, QWidget
            from botwidget.qt_ui import desktops
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        app = QApplication.instance() or QApplication([])
        widget = QWidget()
        with mock.patch.object(desktops, "set_desktops") as call:
            desktops.apply(widget)
            call.assert_not_called()
            with mock.patch.object(desktops.QGuiApplication, "platformName", return_value="cocoa"):
                desktops.apply(widget)
            self.assertEqual(call.call_count, 1)
        self.assertIsNotNone(app)

    def bring(self, everywhere, here, platform="cocoa"):
        from unittest import mock
        from PySide6.QtWidgets import QApplication, QWidget
        from botwidget.qt_ui import desktops
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])
        widget = QWidget()
        with mock.patch.object(desktops, "all_desktops", return_value=everywhere), \
                mock.patch.object(desktops, "on_active_space", return_value=here), \
                mock.patch.object(desktops, "move_to_active_space") as move, \
                mock.patch.object(desktops, "apply") as apply, \
                mock.patch.object(desktops, "QTimer") as timer, \
                mock.patch.object(desktops.QGuiApplication, "platformName", return_value=platform):
            moved = desktops.bring_here(widget)
        self.assertIsNotNone(app)
        return moved, move.call_count, timer.singleShot.call_count, apply.call_count

    def test_a_face_on_another_desktop_comes_to_this_one_and_stays_here(self):
        try:
            self.assertEqual(self.bring(everywhere=False, here=False), (True, 1, 1, 0))
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")

    def test_nothing_moves_when_the_face_is_here_or_everywhere_or_the_system_has_no_desktops(self):
        try:
            self.assertEqual(self.bring(everywhere=False, here=True)[0], False)
            self.assertEqual(self.bring(everywhere=True, here=False)[0], False)
            self.assertEqual(self.bring(everywhere=False, here=False, platform="offscreen")[0], False)
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")

    def test_other_systems_have_nothing_to_choose(self):
        self.assertFalse(linux.CAN_PICK_DESKTOPS or windows.CAN_PICK_DESKTOPS)
        linux.set_desktops(0, True)
        windows.set_desktops(0, False)


class Animator(unittest.TestCase):
    """Should move the springs smoothly to the target, overshoot where it should, and then really stand still."""

    @staticmethod
    def settle(animator, seconds=3.0, fps=30):
        for _ in range(int(seconds * fps)):
            if not animator.step(1 / fps):
                return True
        return False

    def test_should_settle_on_its_target(self):
        animator = animation.FaceAnimator()
        animator.aim(dx=6.0, scale=0.22)
        self.assertTrue(self.settle(animator))
        self.assertEqual((animator.value["dx"], animator.value["scale"]), (6.0, 0.22))

    def test_should_settle_equally_fast_at_either_frame_rate(self):
        def seconds(fps):
            animator = animation.FaceAnimator()
            animator.aim(dx=6.0)
            count = 0
            while animator.step(1 / fps):
                count += 1
            return count / fps
        self.assertAlmostEqual(seconds(30), seconds(60), delta=0.1)

    def test_a_kick_wobbles_and_returns_to_rest(self):
        animator = animation.FaceAnimator()
        animator.kick("sy", -1.2)
        lowest = 1.0
        for _ in range(60):
            animator.step(1 / 60)
            lowest = min(lowest, animator.value["sy"])
        self.assertLess(lowest, 0.97)
        self.assertTrue(self.settle(animator))
        self.assertEqual(animator.value["sy"], 1.0)

    def test_an_idle_animator_reports_nothing_moving(self):
        self.assertFalse(animation.FaceAnimator().step(1 / 30))

    def test_an_unknown_target_is_an_error(self):
        with self.assertRaises(KeyError):
            animation.FaceAnimator().aim(wobble=1)


class FaceEyes(unittest.TestCase):
    """Should keep the eyes solid: no eye is transparent halfway through a transition."""

    def test_every_eye_is_fully_opaque_at_any_happy_value(self):
        for happy in (0.0, 0.25, 0.5, 0.75, 1.0):
            svg = avatar.face_svg(seed="robo", happy=happy)
            white = [chunk for chunk in svg.split("<path") if 'stroke="#f9f9f9"' in chunk]
            self.assertEqual(len(white), 2)
            self.assertTrue(all('opacity="1.0"' in chunk for chunk in white), f"happy={happy}")

    def test_happy_morphs_the_same_shape_instead_of_fading_in_a_second_one(self):
        count = lambda happy: avatar.face_svg(seed="robo", happy=happy).count('stroke="#f9f9f9"')
        self.assertEqual(count(0.0), count(0.5))
        self.assertEqual(count(0.5), count(1.0))


class IdleLook(unittest.TestCase):
    """Should make idle almost standing still: a glance up and to the right and an occasional blink, like Grok Bot."""

    def test_idle_cycle_is_dominated_by_the_still_glance(self):
        total = sum(ms for _pose, ms in avatar.FACE["idle"])
        still = sum(ms for pose, ms in avatar.FACE["idle"] if pose == "idle")
        self.assertGreater(still / total, 0.9)

    def test_the_glance_is_up_and_to_the_right(self):
        dx, dy, _scale = avatar.POSES["idle"]
        self.assertTrue(dx > 0 and dy < 0)


class FaceLook(unittest.TestCase):
    """Should use the Grok Bot palette, no light ring, depth and a tilt of its own per bot."""

    GROK_PALETTE = {"rouge": "#ff3e51", "orange": "#ff781c", "ambre": "#ffaf38", "vert": "#00c972",
                    "turquoise": "#1cc3b0", "bleu": "#2a92fe", "violet": "#a97efe", "rose": "#ff5eb1",
                    "gris": "#959595"}

    def test_palette_matches_grok_bot(self):
        for name, colour in self.GROK_PALETTE.items():
            self.assertEqual(avatar.AVATAR_HEX[name], colour)

    def test_face_has_no_outline_and_has_depth(self):
        svg = avatar.face_svg(seed="robo")
        head = svg.split("<path", 2)[1].split(">", 1)[0]
        self.assertFalse("stroke" in head, "the head must not have an outline")
        self.assertTrue("url(#hl)" in svg and "url(#sh)" in svg)

    def test_tilt_is_stable_per_bot_and_small(self):
        tilts = {seed: avatar.avatar_profile(seed, None)["tilt"] for seed in ("a", "b", "c", "d", "e", "f")}
        self.assertEqual(tilts["a"], avatar.avatar_profile("a", None)["tilt"])
        self.assertTrue(all(abs(t) <= 9.7 for t in tilts.values()))
        self.assertGreater(len(set(tilts.values())), 1)

    def test_head_follows_the_eyes_only_partly(self):
        svg = avatar.face_svg(dx=8.0, dy=0.0, seed="robo")
        self.assertIn(f"translate({8.0 * avatar.PARALLAX:.2f} 0.00)", svg)


class TestUpdates(unittest.TestCase):
    """Should treat only a really higher version number as an update; a failed request is silent."""

    def serve(self, routes):
        """Make urlopen answer from routes: the key is a part of the URL, the value the bytes."""
        class Reply(io.BytesIO):
            def __exit__(self, *args):
                return False

        def fake(request, timeout=None):
            url = request.full_url if hasattr(request, "full_url") else request
            for part, data in routes.items():
                if part in url:
                    return Reply(data)
            raise updates.urllib.error.URLError("not served: " + url)

        old = updates.urllib.request.urlopen
        self.addCleanup(setattr, updates.urllib.request, "urlopen", old)
        updates.urllib.request.urlopen = fake

    def test_versions_compare_by_number_not_by_text(self):
        self.assertTrue(updates.is_newer("v0.10.0", "0.9.0"))
        self.assertFalse(updates.is_newer("v0.1.0", "0.1.0"))
        self.assertFalse(updates.is_newer("0.0.9", "0.1.0"))

    def test_a_dev_build_sorts_below_the_release_it_precedes(self):
        self.assertTrue(updates.is_newer("v0.1.1", "0.1.1.dev3+gabc1234.d20261019"))
        self.assertFalse(updates.is_newer("v0.1.0", "0.1.1.dev3+gabc1234"), "a dev build is past 0.1.0")
        self.assertFalse(updates.is_newer("v0.1.1", "0.1.1"))

    def test_the_unknown_fallback_version_is_older_than_any_release(self):
        self.assertTrue(updates.is_newer("v0.1.0", "0.0.0+unknown"))

    def test_garbage_tags_are_never_newer(self):
        self.assertFalse(updates.is_newer("nightly", "0.1.0"))

    def test_newer_release_returns_the_version_without_v(self):
        body = b'{"tag_name": "v0.3.0", "assets": [{"name": "a.zip", "browser_download_url": "https://x/a.zip"}]}'
        self.serve({"api.github.com": body})
        release = updates.newer_release("0.1.0")
        self.assertEqual((release.version, release.assets), ("0.3.0", {"a.zip": "https://x/a.zip"}))
        self.assertIsNone(updates.newer_release("0.3.0"))

    def test_network_failure_is_silent(self):
        def fail(*args, **kwargs):
            raise updates.urllib.error.URLError("offline")
        old = updates.urllib.request.urlopen
        self.addCleanup(setattr, updates.urllib.request, "urlopen", old)
        updates.urllib.request.urlopen = fail
        self.assertIsNone(updates.newer_release("0.1.0"))


class X11Libraries(unittest.TestCase):
    """The X11 libraries Qt's plugin misses, taken from ldd."""

    def test_not_found_lines_name_the_library(self):
        ldd = ("\tlibxcb-cursor.so.0 => not found\n"
               "\tlibGL.so.1 => /usr/lib/x86_64-linux-gnu/libGL.so.1\n"
               "\tlibxkbcommon-x11.so.0 => not found\n")
        self.assertEqual(linux._libs_not_found(ldd),
                         ["libxcb-cursor.so.0", "libxkbcommon-x11.so.0"])

    def test_everything_present_gives_nothing(self):
        self.assertEqual(linux._libs_not_found("\tlibGL.so.1 => /usr/lib/libGL.so.1\n"), [])


class LaunchAtLogin(unittest.TestCase):
    """Should let every operating system put its own file or key; here the files."""

    COMMAND = ["/Applications/Bot Widget.app/Contents/MacOS/Bot Widget"]

    def test_linux_writes_and_removes_an_autostart_entry(self):
        with tempfile.TemporaryDirectory() as home:
            old = linux.data_home
            self.addCleanup(setattr, linux, "data_home", old)
            linux.data_home = lambda: home
            linux.set_launch_at_login(self.COMMAND, True)
            self.assertTrue(linux.launch_at_login())
            with open(os.path.join(home, "autostart", "botwidget.desktop")) as fh:
                self.assertIn('Exec="/Applications/Bot Widget.app/Contents/MacOS/Bot Widget"', fh.read())
            linux.set_launch_at_login(self.COMMAND, False)
            self.assertFalse(linux.launch_at_login())

    def test_macos_writes_and_removes_a_launch_agent(self):
        with tempfile.TemporaryDirectory() as home:
            path = os.path.join(home, "LaunchAgents", "agent.plist")
            for name, value in (("_launch_agent", lambda: path),
                                ("_dev_launcher", lambda: os.path.join(home, macos.DEV_LAUNCHER_NAME))):
                old = getattr(macos, name)
                self.addCleanup(setattr, macos, name, old)
                setattr(macos, name, value)
            macos.set_launch_at_login(self.COMMAND, True)
            self.assertTrue(macos.launch_at_login())
            with open(path, "rb") as fh:
                agent = plistlib.load(fh)
            self.assertTrue(agent["RunAtLoad"])
            self.assertEqual(agent["ProcessType"], "Interactive", "else launchd throttles the animation")
            launcher = agent["ProgramArguments"][0]
            self.assertEqual(os.path.basename(launcher), macos.DEV_LAUNCHER_NAME, "not shown as 'python'")
            with open(launcher) as fh:
                self.assertIn(self.COMMAND[0], fh.read())
            self.assertTrue(os.access(launcher, os.X_OK))
            macos.set_launch_at_login(self.COMMAND, False)
            self.assertFalse(macos.launch_at_login())

    def test_command_is_the_app_itself_when_bundled_and_the_package_otherwise(self):
        self.assertEqual(startup.launch_command()[:3], [sys.executable, "-m", "botwidget"])
        sys.frozen = True
        self.addCleanup(delattr, sys, "frozen")
        self.assertEqual(startup.launch_command(), [sys.executable])


class AutoUpdate(unittest.TestCase):
    """Should download, verify, stage and install at the next start."""

    PAYLOAD = b"pretend this is an app"

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        for name, value in (("STAGING", os.path.join(self.folder.name, "updates")),
                            ("UPDATE_ASSET", "app.zip")):
            old = getattr(updates, name)
            self.addCleanup(setattr, updates, name, old)
            setattr(updates, name, value)
        self.release = updates.Release("0.2.0", {"app.zip": "https://x/app.zip",
                                                  "SHA256SUMS.txt": "https://x/SHA256SUMS.txt"})

    def serve(self, payload, digest):
        TestUpdates.serve(self, {"SHA256SUMS.txt": f"{digest}  app.zip\n".encode(), "app.zip": payload})

    def test_sums_parse_both_sha256sum_layouts(self):
        sums = updates.parse_sums(f"{'a' * 64}  one.zip\n{'B' * 64} *two.exe\nnot a line\n")
        self.assertEqual(sums, {"one.zip": "a" * 64, "two.exe": "b" * 64})

    def test_a_verified_download_is_staged(self):
        import hashlib
        self.serve(self.PAYLOAD, hashlib.sha256(self.PAYLOAD).hexdigest())
        path = updates.stage(self.release)
        self.assertEqual(open(path, "rb").read(), self.PAYLOAD)
        self.assertEqual(updates.staged_update("0.1.0"), ("0.2.0", path))

    def test_a_download_with_the_wrong_checksum_is_thrown_away(self):
        self.serve(self.PAYLOAD, "0" * 64)
        self.assertIsNone(updates.stage(self.release))
        self.assertFalse(os.path.exists(os.path.join(updates.STAGING, "0.2.0")))
        self.assertIsNone(updates.staged_update("0.1.0"))

    def test_a_release_without_a_file_for_this_system_is_not_staged(self):
        self.assertIsNone(updates.stage(updates.Release("0.2.0", {"SHA256SUMS.txt": "https://x/s"})))

    def test_staged_update_installs_once_and_only_when_newer(self):
        import hashlib
        self.serve(self.PAYLOAD, hashlib.sha256(self.PAYLOAD).hexdigest())
        path = updates.stage(self.release)
        calls = []
        for name, value in (("can_install_update", lambda: True),
                            ("install_update", lambda p: calls.append(p) or True)):
            old = getattr(updates, name)
            self.addCleanup(setattr, updates, name, old)
            setattr(updates, name, value)
        self.assertFalse(updates.install_staged("0.2.0"))
        self.assertTrue(updates.install_staged("0.1.0"))
        self.assertEqual(calls, [path])
        self.assertFalse(updates.install_staged("0.1.0"), "a failed install must not retry on every start")

    def test_old_staged_updates_are_cleaned_up(self):
        for version in ("0.1.0", "0.2.0", "0.3.0"):
            os.makedirs(os.path.join(updates.STAGING, version))
        updates.clean_staging("0.2.0")
        self.assertEqual(sorted(os.listdir(updates.STAGING)), ["0.3.0"])


class MacBundleSwap(unittest.TestCase):
    """Should do the real swap of an .app on macOS, with a fake app in a temporary folder."""

    @unittest.skipUnless(sys.platform == "darwin", "only macOS has ditto and .app")
    def test_the_old_app_is_replaced_by_the_new_one(self):
        import subprocess
        import time
        with tempfile.TemporaryDirectory() as home:
            old_app = os.path.join(home, "Apps", "Bot Widget.app")
            os.makedirs(old_app)
            open(os.path.join(old_app, "version.txt"), "w").write("old")
            build = os.path.join(home, "build", "Bot Widget.app")
            os.makedirs(build)
            open(os.path.join(build, "version.txt"), "w").write("new")
            archive = os.path.join(home, "BotWidget-macOS.zip")
            subprocess.run(["ditto", "-c", "-k", "--keepParent", build, archive], check=True)
            os.environ["BOTWIDGET_NO_RELAUNCH"] = "1"
            self.addCleanup(os.environ.pop, "BOTWIDGET_NO_RELAUNCH", None)
            running = subprocess.Popen(["sleep", "0.4"])
            macos.apply_bundle_update(archive, old_app, running.pid)
            marker = os.path.join(old_app, "version.txt")
            for _ in range(60):
                time.sleep(0.1)
                running.poll()  # a closed child process otherwise stays a zombie that still "lives"
                if open(marker).read() == "new":
                    break
            self.assertEqual(open(marker).read(), "new")
            for _ in range(30):  # the cleanup follows right after the swap
                if os.listdir(os.path.join(home, "Apps")) == ["Bot Widget.app"]:
                    break
                time.sleep(0.1)
            self.assertEqual(sorted(os.listdir(os.path.join(home, "Apps"))), ["Bot Widget.app"])


class DevRunner(unittest.TestCase):
    """Should see new and changed files in dev mode, and ignore the rest."""

    def test_snapshot_changes_when_a_python_file_changes_or_appears(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "a.py")
            open(path, "w").write("x = 1")
            before = dev.snapshot(folder)
            os.utime(path, ns=(1, 1))
            self.assertNotEqual(dev.snapshot(folder), before)
            before = dev.snapshot(folder)
            open(os.path.join(folder, "b.py"), "w").write("y = 2")
            self.assertNotEqual(dev.snapshot(folder), before)

    def test_snapshot_ignores_other_files_and_bytecode(self):
        with tempfile.TemporaryDirectory() as folder:
            before = dev.snapshot(folder)
            open(os.path.join(folder, "notes.txt"), "w").write("hi")
            os.makedirs(os.path.join(folder, "__pycache__"))
            open(os.path.join(folder, "__pycache__", "a.py"), "w").write("")
            self.assertEqual(dev.snapshot(folder), before)

    def test_stopping_nothing_is_fine(self):
        dev.stop(None)


class FirstRun(unittest.TestCase):
    """Should turn on starting at login the first time; after that the user decides."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        old = config.CONFIG_PATH
        self.addCleanup(setattr, config, "CONFIG_PATH", old)
        config.CONFIG_PATH = os.path.join(self.folder.name, "widget.json")
        self.enabled = False
        for name, value in (("is_enabled", lambda: self.enabled), ("set_enabled", self.set)):
            old = getattr(startup, name)
            self.addCleanup(setattr, startup, name, old)
            setattr(startup, name, value)

    def set(self, on):
        self.enabled = on

    def test_the_first_start_turns_launch_at_login_on(self):
        self.assertTrue(startup.apply_default())
        self.assertTrue(self.enabled)

    def test_a_user_who_turned_it_off_is_not_overruled(self):
        startup.apply_default()
        self.enabled = False
        self.assertFalse(startup.apply_default())
        self.assertFalse(self.enabled)


class SingleInstance(unittest.TestCase):
    """Should recognise every way to start the widget, also the packaged app."""

    def test_every_launch_style_is_recognised(self):
        for cmdline in (b"/usr/bin/python3 /home/me/bot_widget.py",
                        b"/home/me/.local/share/uv/tools/botwidget/bin/python -m botwidget --dev",
                        b"/Applications/Bot Widget.app/Contents/MacOS/Bot Widget",
                        b"/home/me/.local/share/botwidget/app/Bot Widget"):
            self.assertTrue(instance.looks_like_widget(cmdline), cmdline)

    def test_other_programs_are_left_alone(self):
        for cmdline in (b"vim notes.txt", b"/usr/bin/python3 other_script.py", b""):
            self.assertFalse(instance.looks_like_widget(cmdline), cmdline)


class Channel(unittest.TestCase):
    """Should switch between stable and local: who is running, what the other is, and the login item."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.patch(config, "CONFIG_PATH", os.path.join(self.folder.name, "widget.json"))
        self.login = True
        self.launched = []
        self.patch(startup, "from_checkout", lambda: False)
        self.patch(startup, "is_enabled", lambda: self.login)
        self.patch(startup, "set_enabled", self.set_login)
        self.patch(channel, "stable_app_command", lambda: ["open", "/Applications/Bot Widget.app", "--args"])

    def patch(self, owner, name, value):
        old = getattr(owner, name)
        self.addCleanup(setattr, owner, name, old)
        setattr(owner, name, value)

    def set_login(self, on):
        self.login = on

    def popen(self, command, **kwargs):
        self.launched.append(command)

    def test_a_local_widget_remembers_how_it_starts(self):
        self.patch(startup, "from_checkout", lambda: True)
        channel.remember_local()
        self.assertEqual(config.widget_config()["local_command"], startup.launch_command())

    def test_the_stable_widget_only_offers_local_once_one_is_known(self):
        self.assertIsNone(channel.switch_label())
        config.save_widget_config(local_command=["/x/python", "-m", "botwidget", "--dev"])
        self.assertEqual(channel.switch_label(), "Switch to local version")

    def test_a_local_widget_offers_the_installed_stable_one(self):
        self.patch(startup, "from_checkout", lambda: True)
        self.assertEqual(channel.switch_label(), "Switch to stable version")
        self.patch(channel, "stable_app_command", lambda: None)
        self.assertIsNone(channel.switch_label())

    def test_switching_starts_the_other_one_and_hands_the_login_item_over(self):
        config.save_widget_config(local_command=["/x/python", "-m", "botwidget", "--dev"])
        self.patch(channel.subprocess, "Popen", self.popen)
        self.assertTrue(channel.switch())
        self.assertEqual(self.launched, [["/x/python", "-m", "botwidget", "--dev", "--keep-login"]])
        self.assertFalse(self.login, "this version gives up the login item; the other one takes it")

    def test_switching_without_a_login_item_does_not_ask_for_one(self):
        self.login = False
        config.save_widget_config(local_command=["/x/python", "-m", "botwidget", "--dev"])
        self.patch(channel.subprocess, "Popen", self.popen)
        channel.switch()
        self.assertEqual(self.launched, [["/x/python", "-m", "botwidget", "--dev"]])

    def test_a_failed_start_keeps_the_login_item_and_this_widget(self):
        config.save_widget_config(local_command=["/missing"])

        def broken(command, **kwargs):
            raise OSError("no such file")
        self.patch(channel.subprocess, "Popen", broken)
        self.assertFalse(channel.switch())
        self.assertTrue(self.login)

    def test_garbage_in_the_settings_file_is_not_a_command(self):
        config.save_widget_config(local_command="not a list")
        self.assertIsNone(channel.other_command())


class BubbleTextDocument(unittest.TestCase):
    """The bubble text is a real document: selectable words and clickable http links."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:  # no toolkit at all: nothing to test here
            raise unittest.SkipTest("PySide6 is not available")
        try:
            cls.app = QApplication.instance() or QApplication([])
        except Exception as err:  # no screen and no offscreen platform
            raise unittest.SkipTest(str(err))

    @staticmethod
    def measure(text, style, size):
        return len(text) * 7.0

    def document(self, messages):
        from PySide6.QtGui import QTextDocument

        from botwidget.qt_ui.text_doc import fill_document
        blocks = markdown.conversation_blocks(messages, "Robo")
        panels = bubble_layout.bubble_panels(self.measure, blocks)
        box_w = bubble.bubble_width(panels) + 2 * theme.PAD_PANEL_X
        doc = QTextDocument()
        fill_document(doc, panels, box_w)
        return doc, panels

    def test_the_words_are_in_the_document(self):
        doc, _panels = self.document([{"role": "user", "text": "hi"},
                                      {"role": "bot", "text": "hello **there**"}])
        self.assertIn("You", doc.toPlainText())
        self.assertIn("hi", doc.toPlainText())
        self.assertIn("Robo", doc.toPlainText())
        self.assertIn("hello there", doc.toPlainText())

    def test_refilling_replaces_the_old_text_instead_of_stacking_under_it(self):
        from botwidget.qt_ui.text_doc import fill_document
        doc, _panels = self.document([{"role": "user", "text": "first question"}])
        messages = [{"role": "user", "text": "first question"}, {"role": "bot", "text": "the answer"}]
        panels = bubble_layout.bubble_panels(self.measure, markdown.conversation_blocks(messages, "Robo"))
        fill_document(doc, panels, 300)
        text = doc.toPlainText()
        self.assertEqual(text.count("first question"), 1, "the old copy must not stay behind")
        self.assertEqual(text.count("You"), 1)
        self.assertIn("the answer", text)

    def _links(self, doc):
        """The anchor labels and hrefs in the document, in reading order."""
        from PySide6.QtGui import QTextCursor
        cursor = QTextCursor(doc)
        label, hrefs = "", []
        while not cursor.atEnd():
            cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
            fmt = cursor.charFormat()
            if fmt.isAnchor():
                label += doc.characterAt(cursor.position() - 1)
                hrefs.append(fmt.anchorHref())
        return label, hrefs

    def test_an_http_link_becomes_a_clickable_anchor(self):
        doc, _panels = self.document([{"role": "bot", "text": "see [docs](https://example.com/x)"}])
        label, hrefs = self._links(doc)
        self.assertEqual(set(hrefs), {"https://example.com/x"})
        self.assertEqual(label, "docs", "only the label is the link, the host stays text")

    def test_a_bare_https_url_becomes_an_anchor(self):
        doc, _panels = self.document([{"role": "bot", "text": "read https://example.com/x now"}])
        label, hrefs = self._links(doc)
        self.assertEqual(set(hrefs), {"https://example.com/x"})
        self.assertEqual(label, "https://example.com/x", "the url is its own label")

    def test_a_markdown_link_with_parentheses_is_one_anchor(self):
        url = "https://en.wikipedia.org/wiki/Foo_(bar)"
        doc, _panels = self.document([{"role": "bot", "text": f"see [page]({url})."}])
        label, hrefs = self._links(doc)
        self.assertEqual(set(hrefs), {url}, "the whole url is the href")
        self.assertEqual("".join(label.split()), "page", "only the label is the link")

    def test_a_bare_url_with_parentheses_is_one_anchor(self):
        url = "https://en.wikipedia.org/wiki/Foo_(bar)"
        doc, _panels = self.document([{"role": "bot", "text": "see " + url + "."}])
        label, hrefs = self._links(doc)
        self.assertEqual(set(hrefs), {url}, "the whole url is the anchor, the period is not in it")
        self.assertEqual("".join(label.split()), url, "the brackets belong to the url")

    def test_a_bare_url_with_another_scheme_stays_text(self):
        doc, _panels = self.document([{"role": "bot", "text": "try file:///etc/passwd or mailto:a@b.c"}])
        self.assertEqual(self._links(doc), ("", []), "only http(s) opens on a click")

    def test_another_scheme_is_text_without_an_anchor(self):
        from PySide6.QtGui import QTextCursor
        doc, _panels = self.document([{"role": "bot", "text": "see [passwd](file:///etc/passwd)"}])
        cursor = QTextCursor(doc)
        while not cursor.atEnd():
            cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
            self.assertFalse(cursor.charFormat().isAnchor())

    def test_the_text_sits_where_the_shapes_are(self):
        doc, panels = self.document([{"role": "user", "text": "hi"},
                                     {"role": "bot", "text": "hello"}])
        layout = doc.documentLayout()
        first_of_second = doc.findBlockByNumber(len(panels[0]["lines"]))
        expected = sum(bubble.line_height(line) for line in panels[0]["lines"])
        expected += theme.PAD_PANEL_Y + theme.GAP_PANEL + theme.PAD_PANEL_Y
        self.assertAlmostEqual(layout.blockBoundingRect(first_of_second).y(), expected, delta=1)


class Sending(unittest.TestCase):
    """A POST that can fail: a blip is retried with the same clientMessageId, a refusal is said."""

    def test_a_retry_keeps_the_message_and_its_id(self):
        box = delivery.Outbox()
        box.add("hello", "abc")
        self.assertEqual(box.current()["cid"], "abc")
        self.assertEqual(box.failed("abc", True), 1)
        self.assertEqual(box.current()["cid"], "abc", "a retry uses the id it started with")
        self.assertEqual(box.failed("abc", True), 2, "the wait grows")
        self.assertEqual(len(box.items), 1, "the message is not lost")

    def test_a_refusal_drops_the_message(self):
        box = delivery.Outbox()
        box.add("hello", "abc")
        self.assertIsNone(box.failed("abc", False))
        self.assertIsNone(box.current())

    def test_a_sent_message_leaves_the_box(self):
        box = delivery.Outbox()
        box.add("hello", "abc")
        self.assertEqual(box.sent("abc")["text"], "hello")
        self.assertIsNone(box.current())

    def test_a_live_post_that_fails_is_retryable_and_recovers_with_the_same_id(self):
        with _FlakyApi([500, 200]) as server:
            cid = "deadbeef"
            path = "/v1/agents/me/messages"
            first = openbot.api_post(path, {"text": "hi", "clientMessageId": cid})
            self.assertFalse(first.ok)
            self.assertTrue(first.retryable, "a server error may heal by itself")
            box = delivery.Outbox()
            box.add("hi", cid)
            self.assertEqual(box.failed(cid, first.retryable), 1)
            second = openbot.api_post(path, {"text": "hi", "clientMessageId": cid})
            self.assertTrue(second.ok, "the retry goes through")
            box.sent(cid)
            self.assertIsNone(box.current())
            self.assertEqual(server.seen[0]["clientMessageId"], server.seen[1]["clientMessageId"])
            self.assertEqual(server.seen[0]["text"], "hi")

    def test_a_200_with_a_body_that_is_not_json_is_retried_with_the_same_id(self):
        with _FlakyApi([200, 200], bodies=[b"<html>not json</html>"]) as server:
            cid = "deadbeef"
            path = "/v1/agents/me/messages"
            first = openbot.api_post(path, {"text": "hi", "clientMessageId": cid})
            self.assertFalse(first.ok)
            self.assertEqual(first.status, 200, "the answer arrived, we just could not read it")
            self.assertTrue(first.retryable, "an unreadable answer is a blip, not a refusal")
            box = delivery.Outbox()
            box.add("hi", cid)
            self.assertEqual(box.failed(cid, first.retryable), 1)
            self.assertEqual(box.current()["cid"], cid, "the message is kept, not dropped")
            second = openbot.api_post(path, {"text": "hi", "clientMessageId": cid})
            self.assertTrue(second.ok, "the retry goes through")
            box.sent(cid)
            self.assertIsNone(box.current())
            self.assertEqual(server.seen[0]["clientMessageId"], server.seen[1]["clientMessageId"])

    def test_a_200_with_an_empty_body_is_a_refusal(self):
        for body in (b"", b"   \n"):
            with self.subTest(body=body):
                with _FlakyApi([200], bodies=[body]):
                    result = openbot.api_post("/v1/agents/me/messages",
                                              {"text": "hi", "clientMessageId": "abc"})
                    self.assertFalse(result.ok)
                    self.assertEqual(result.status, 200)
                    self.assertEqual(result.error, "empty answer")
                    self.assertFalse(result.retryable, "an empty body will not become JSON")
                    box = delivery.Outbox()
                    box.add("hi", "abc")
                    self.assertIsNone(box.failed("abc", result.retryable), "the message is dropped")
                    self.assertIsNone(box.current())

    def test_a_200_body_of_only_a_byte_order_mark_is_a_refusal(self):
        for body in (b"\xef\xbb\xbf", b"\xef\xbb\xbf \n", b" \xef\xbb\xbf\t"):
            with self.subTest(body=body):
                with _FlakyApi([200], bodies=[body]):
                    result = openbot.api_post("/v1/agents/me/messages",
                                              {"text": "hi", "clientMessageId": "abc"})
                    self.assertFalse(result.ok)
                    self.assertEqual(result.status, 200)
                    self.assertEqual(result.error, "empty answer")
                    self.assertFalse(result.retryable, "a byte-order mark is not content")
                    box = delivery.Outbox()
                    box.add("hi", "abc")
                    self.assertIsNone(box.failed("abc", result.retryable), "the message is dropped")
                    self.assertIsNone(box.current())

    def test_a_200_body_that_is_not_an_object_is_a_refusal(self):
        for body in (b"null", b"[]", b"3", b'"hoi"'):
            with self.subTest(body=body):
                with _FlakyApi([200], bodies=[body]):
                    result = openbot.api_post("/v1/agents/me/messages",
                                              {"text": "hi", "clientMessageId": "abc"})
                    self.assertFalse(result.ok)
                    self.assertEqual(result.status, 200)
                    self.assertEqual(result.error, "unexpected answer")
                    self.assertFalse(result.retryable, "a body we cannot use will not get better")
                    box = delivery.Outbox()
                    box.add("hi", "abc")
                    self.assertIsNone(box.failed("abc", result.retryable), "the message is dropped")
                    self.assertIsNone(box.current())

    def test_a_refusal_from_the_api_is_not_retried(self):
        with _FlakyApi([401]) as server:
            result = openbot.api_post("/v1/agents/me/messages",
                                      {"text": "hi", "clientMessageId": "x"})
            self.assertEqual(len(server.seen), 1)
        self.assertFalse(result.ok)
        self.assertFalse(result.retryable)
        self.assertEqual(result.status, 401)

    def test_no_answer_at_all_is_retryable(self):
        old_url, old_headers = openbot.api_url, openbot.HEADERS_FILE
        self.addCleanup(setattr, openbot, "api_url", old_url)
        self.addCleanup(setattr, openbot, "HEADERS_FILE", old_headers)
        with tempfile.TemporaryDirectory() as folder:
            headers = os.path.join(folder, "headers")
            with open(headers, "w") as f:
                f.write("Authorization: Bearer test\n")
            openbot.HEADERS_FILE = headers
            closed = _closed_address()
            openbot.api_url = lambda: closed
            result = openbot.api_post("/v1/agents/me/messages", {"text": "hi"})
        self.assertFalse(result.ok)
        self.assertTrue(result.retryable, "a dropped link looks like a stopped OpenBot, but retries")
        self.assertIsNone(result.status)


def _closed_address() -> str:
    """A local URL where nothing listens."""
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}"


class _FlakyApi:
    """A local API that answers with the given status codes in order, as a context manager."""

    def __init__(self, replies: list, bodies: list | None = None):
        import http.server
        import threading

        self.replies = replies
        self.bodies = bodies or []
        self.seen = []
        self._tmp = tempfile.TemporaryDirectory()
        self._headers = os.path.join(self._tmp.name, "headers")
        with open(self._headers, "w") as f:
            f.write("Authorization: Bearer test\n")

        parent = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                parent.seen.append(json.loads(body or b"{}"))
                self.send_response(parent.replies.pop(0) if parent.replies else 200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(parent.bodies.pop(0) if parent.bodies else b'{"ok": true}')

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def __enter__(self):
        self._old = (openbot.HEADERS_FILE, openbot.api_url)
        openbot.HEADERS_FILE = self._headers
        address = f"http://127.0.0.1:{self.server.server_port}"
        openbot.api_url = lambda: address
        return self

    def __exit__(self, *exc):
        openbot.HEADERS_FILE, openbot.api_url = self._old
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()
        return False


class OpenBotAutomation(unittest.TestCase):
    """Should find OpenBot's local API when it appears, even after the widget started."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        for name, file in (("URL_FILE", "url"), ("HEADERS_FILE", "headers")):
            old = getattr(config, name)
            self.addCleanup(setattr, config, name, old)
            setattr(config, name, os.path.join(self.folder.name, file))

    def write(self, name, text):
        with open(os.path.join(self.folder.name, name), "w") as fh:
            fh.write(text)

    def test_the_default_address_is_used_until_openbot_writes_one(self):
        self.assertEqual(config.api_url(), "http://127.0.0.1:41673")

    def test_the_address_is_read_again_on_every_call(self):
        self.assertEqual(config.api_url(), "http://127.0.0.1:41673")
        self.write("url", "http://127.0.0.1:50123\n")
        self.assertEqual(config.api_url(), "http://127.0.0.1:50123")
        self.write("url", "http://127.0.0.1:50999")
        self.assertEqual(config.api_url(), "http://127.0.0.1:50999", "a restarted OpenBot picks a new port")

    def test_automation_is_ready_only_with_both_the_address_and_the_token(self):
        self.assertFalse(config.automation_ready(), "the switch is off: no files yet")
        self.write("url", "http://127.0.0.1:50123")
        self.assertFalse(config.automation_ready())
        self.write("headers", "Authorization: Bearer secret")
        self.assertTrue(config.automation_ready())

    def test_empty_files_do_not_count(self):
        self.write("url", "")
        self.write("headers", "\n")
        self.assertFalse(config.automation_ready())


if __name__ == "__main__":
    unittest.main()
