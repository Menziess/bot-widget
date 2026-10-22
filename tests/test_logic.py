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
    grokbot,
    instance,
    markdown,
    menu_pages,
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

    def test_a_grok_bot_wears_the_shape_and_colour_grok_bot_draws_for_it(self):
        profile = avatar.avatar_profile("grok:General", None, {"shape": "blob", "color": "black"})
        self.assertEqual(profile["shape"], "blob")
        self.assertEqual(profile["hex"], "#000000", "black, as Grok Bot names it")
        self.assertEqual(profile["tilt"], 0.0, "the blob is drawn the way Grok Bot draws it")
        self.assertEqual(profile["top"], avatar.GROK_BLOB[48])

    def test_a_grok_bot_only_takes_what_grok_bot_actually_sends(self):
        seeded = avatar.avatar_profile("grok:General", None)
        self.assertEqual(avatar.avatar_profile("grok:General", None, {"shape": "cloud"}), seeded,
                         "a shape the widget cannot draw leaves the seed's face alone")
        self.assertEqual(avatar.avatar_profile("grok:General", None, {"color": "chartreuse"}), seeded,
                         "no colour is invented")
        body = avatar.face_svg(seed="grok:General", avatar={"shape": "blob", "color": "black"})
        self.assertIn('fill="#000000"', body)
        self.assertNotIn(seeded["hex"], body)

    def test_stable_index_matches_fnv1a(self):
        # FNV-1a of "a" is 0xe40c292c; at length 7 that is 4.
        self.assertEqual(avatar.stable_index("a", 7), 0xE40C292C % 7)


class GrokAvatar(unittest.TestCase):
    """The face of a Grok Bot bot comes from Grok Bot's own roster, not from a seed."""

    ROSTER = [{"name": "Critic", "avatarShape": "hex"},
              {"name": "General", "avatarShape": "blob", "avatarColor": "black"}]

    def test_the_bot_named_in_full_wins_over_a_prefix(self):
        self.assertEqual(grokbot.avatar_of(self.ROSTER, "General"), {"shape": "blob", "color": "black"})
        self.assertEqual(grokbot.avatar_of(self.ROSTER, "general"), {"shape": "blob", "color": "black"})
        self.assertEqual(grokbot.avatar_of(self.ROSTER, "Critic"), {"shape": "hex"},
                         "only what the roster has")

    def test_a_bot_that_is_not_there_says_nothing(self):
        self.assertIsNone(grokbot.avatar_of(self.ROSTER, "Nobody"))
        self.assertIsNone(grokbot.avatar_of(None, "General"))
        self.assertIsNone(grokbot.avatar_of([{"name": "General"}], "General"))


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
    """Should move the dots in short smooth steps and show the whole activity."""

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

    def test_a_thought_is_rendered_markdown_in_the_muted_ink_and_never_cut_off(self):
        thought = "Checking `_check_hover` first.\n\n" + "A long thought. " * 100
        blocks = markdown.thought_blocks(thought)
        text = markdown.block_text(blocks)
        self.assertIn("_check_hover", text)
        self.assertNotIn("`", text, "the code span is rendered, not shown raw")
        self.assertIn("A long thought.", text[-30:], "all of it")
        self.assertTrue(all(block["grey"] for block in blocks if block["kind"] == "text"))
        self.assertEqual(markdown.thought_blocks(""), [])


class RefusedMessages(unittest.TestCase):
    """Should say why OpenBot refused a message, and what to do about a bot that has local scripts off."""

    def refused(self, code, body):
        import urllib.error
        from unittest import mock
        from botwidget import openbot
        error = urllib.error.HTTPError("http://x/v1", code, "no", {}, io.BytesIO(body))
        with mock.patch.object(openbot.urllib.request, "urlopen", side_effect=error), \
                mock.patch.object(openbot, "api_url", return_value="http://x"), \
                mock.patch.object(openbot, "read_auth_token", return_value="t"):
            return openbot.api_post("/v1/agents/a/messages", {"text": "hoi"})

    def test_a_bot_with_local_scripts_off_says_what_to_turn_on(self):
        result = self.refused(403, b'{"error":"This agent does not allow local scripts."}')
        self.assertEqual(result.status, 403)
        self.assertIn("This agent does not allow local scripts", result.error)
        self.assertIn('turn on "Local scripts"', result.error)
        self.assertFalse(result.retryable)

    def test_a_403_without_a_reason_still_names_local_scripts(self):
        self.assertIn('turn on "Local scripts"', self.refused(403, b"").error)

    def test_other_refusals_keep_what_openbot_said_or_the_status(self):
        self.assertEqual(self.refused(400, b'{"error":"text too long."}').error, "text too long")
        self.assertEqual(self.refused(404, b"not json").error, "HTTP 404")


class MutedFace(unittest.TestCase):
    """Should draw a muted bot with a cross for a mouth, and sleepy bots with their eyes open."""

    def test_a_muted_face_has_a_cross_the_others_do_not(self):
        from botwidget.avatar import face_svg
        self.assertNotIn(" L", face_svg(seed="x"))
        self.assertIn(" L", face_svg(seed="x", muted=True))

    def test_the_cross_stays_inside_even_the_flattest_head(self):
        from botwidget.avatar import AVATAR_SIZE, CIRCLE_R, MOUTH_DROP, MOUTH_SIZE, SILHOUETTES
        for name, radii in SILHOUETTES.items():
            drop = min(MOUTH_DROP, 0.6 * radii[16]) * CIRCLE_R
            self.assertLess(drop + MOUTH_SIZE + 1.3, radii[16] * CIRCLE_R, name)

    def test_the_sleepy_expression_keeps_its_eyes_open(self):
        from botwidget.avatar import EXPRESSIONS
        for eye in EXPRESSIONS["somnolent"][1:]:
            self.assertEqual(eye[3], 1)


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

    def test_the_balls_between_cloud_and_face_follow_an_arc_inside_the_canvas(self):
        for side in bubble.SIDES:
            _path, trail = bubble._cloud_parts(200, 100, 60, side)
            width, height = 200 + 2 * bubble.PAD_SVG, 100 + bubble.PAD_SVG + bubble.TAIL_ROOM
            for cx, cy, r in trail:
                self.assertGreaterEqual(min(cx, cy) - r, 0, side)
                self.assertLessEqual(max(cx + r - width, cy + r - height), 0, side)
            (x1, y1, _), (x2, y2, _), (x3, y3, _) = trail
            bend = abs((x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1))
            self.assertGreater(bend, 20, f"{side}: not on a straight line")

    def test_a_bigger_cloud_has_more_puffs_and_the_same_text_always_the_same_cloud(self):
        small, large = bubble.cloud_body_svg(120, 60), bubble.cloud_body_svg(320, 160)
        self.assertEqual(small, bubble.cloud_body_svg(120, 60), "the shape does not wobble")
        self.assertGreater(large.count("A"), small.count("A"), "the puffs follow the size, they do not stretch")

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

    def test_a_grok_bot_face_switches_to_the_avatar_grok_bot_sent(self):
        window = self.face.FaceWindow("grok:General", "General", spot=(300, 400),
                                      avatar={"shape": "blob", "color": "black"})
        try:
            window._poll_timer.stop()
            self.assertEqual(window._avatar, {"shape": "blob", "color": "black"})
            self.assertEqual(window.head_top, avatar.AVATAR_SIZE / 2 - avatar.GROK_BLOB[48] * avatar.CIRCLE_R)
            window.set_avatar({"shape": "blob", "color": "blue"})
            self.assertEqual(window._avatar["color"], "blue", "the roster moved on")
        finally:
            window.close_face()

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
        self.assertEqual(bar.value(), 0, "a new message is read from its top")


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
        # What a test saves (a muted bot) must not end up in the real widget.json.
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        old_path = config.CONFIG_PATH
        self.addCleanup(setattr, config, "CONFIG_PATH", old_path)
        config.CONFIG_PATH = os.path.join(folder, "widget.json")
        # Whether a window is active depends on what the earlier tests left behind; no test is about that.
        old_activate = self.face.activate_app
        self.addCleanup(setattr, self.face, "activate_app", old_activate)
        self.face.activate_app = lambda: None
        self.window.bubble.focus_entry = lambda: None

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
        _x, y = self.message_point(0, down=4)
        x = self.window.bubble._shown_w(self.window.bubble._geom[1]) // 2
        self.assertEqual(self.window.bubble._geom[0][0]["role"], "more")
        self.send_mouse("move", 40, y)
        self.assertEqual(self.window.bubble._doc.viewport().cursor().shape(), Qt.ArrowCursor, "beside the arrow")
        self.click_at(40, y)
        self.assertEqual(self.window._depth, 1)
        self.send_mouse("move", x, y)
        self.assertEqual(self.window.bubble._doc.viewport().cursor().shape(), Qt.PointingHandCursor)
        self.click_at(x, y)
        self.assertEqual(self.window._depth, 1, "it loads first")
        self.load_older()
        self.assertEqual(self.window._depth, 2)

    def load_older(self):
        import time
        bubble = self.window.bubble
        bubble._load_older()
        deadline = time.monotonic() + 3
        while bubble._scroll.loading and time.monotonic() < deadline:
            self.app.processEvents()

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

    def test_the_notice_of_a_message_taller_than_the_bubble_stays_inside_the_bubble(self):
        self.MESSAGES = [{"role": "bot", "text": "Een lange regel. " * 200}]
        self.hover()
        bubble = self.window.bubble
        view = bubble._scroll.viewport().height()
        self.assertGreater(bubble._doc.height(), view, "taller than what is in view")
        self.click(0)
        self.assertGreaterEqual(bubble._notice.y(), 0)
        self.assertLessEqual(bubble._notice.y() + bubble._notice.height(), view)

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

    def answer_sounds(self, visible):
        from unittest import mock
        self.window.visible_to_user = lambda: visible
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": ""})
        with mock.patch.object(self.face, "play_sound") as sound:
            self.window._sync_bubble({"messages": self.MESSAGES + [{"role": "bot", "text": "Nieuw."}], "activity": ""})
        return sound.call_count

    def test_a_new_answer_makes_no_sound_while_the_face_is_in_view(self):
        self.assertEqual(self.answer_sounds(visible=True), 0)

    def test_a_new_answer_sounds_when_the_face_is_out_of_view(self):
        self.assertEqual(self.answer_sounds(visible=False), 1)

    def test_nothing_sounds_while_the_bot_is_still_working_and_one_beep_when_it_is_done(self):
        from unittest import mock
        self.window.visible_to_user = lambda: False
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": ""})
        with mock.patch.object(self.face, "play_sound") as sound:
            step = self.MESSAGES + [{"role": "bot", "text": "Ik lees het bestand."}]
            self.window._sync_bubble({"messages": step, "activity": "reading"})
            self.assertEqual(sound.call_count, 0)
            self.window._sync_bubble({"messages": step + [{"role": "bot", "text": "Klaar."}], "activity": ""})
            self.assertEqual(sound.call_count, 1)
            self.window._sync_bubble({"messages": step + [{"role": "bot", "text": "Klaar."}], "activity": ""})
            self.assertEqual(sound.call_count, 1)

    def test_a_window_that_is_not_shown_is_not_in_view(self):
        self.assertFalse(self.window.visible_to_user())
        self.window.show()
        self.app.processEvents()
        self.assertTrue(self.window.visible_to_user())
        self.window.hide()

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

    def think_side(self, face_at, screen):
        self.screen(screen)
        self.window._move_icon(*face_at)
        self.window._remember_spot()
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": "reading"}, force=True)
        self.finish_growth()
        self.assertEqual(self.window.bubble.kind, "think")
        return self.window.bubble._goal()[2][1]

    def test_the_thinking_cloud_goes_beside_the_face_even_with_room_above(self):
        self.assertEqual(self.think_side((700, 500), (0, 0, 1600, 900)), "right")

    def test_the_thinking_cloud_goes_to_the_left_when_the_right_is_full_and_above_only_when_neither_fits(self):
        self.assertEqual(self.think_side((1500, 500), (0, 0, 1600, 900)), "left")
        self.assertEqual(self.think_side((100, 500), (0, 0, 230, 900)), "above")

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
        self.load_older()
        self.assertEqual(self.window._depth, 2)
        up()
        self.load_older()
        self.assertEqual(self.window._depth, 2, "no flood of messages from one flick")

    def wheel_up(self, bubble, phase=None, delta=120):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtWidgets import QApplication
        QApplication.sendEvent(bubble._scroll.viewport(), QWheelEvent(
            QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
            Qt.NoScrollPhase if phase is None else phase, False))

    def test_the_momentum_after_a_lifted_finger_never_loads_but_a_light_pull_at_the_top_does(self):
        from unittest import mock
        from PySide6.QtCore import Qt
        self.MESSAGES = [{"role": "user", "text": "Klaar?"}, {"role": "bot", "text": "Ja."}]
        self.hover()
        bubble = self.window.bubble
        with mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=100.0):
            for _ in range(10):
                self.wheel_up(bubble, Qt.ScrollMomentum)
        self.assertFalse(bubble._scroll.loading)
        with mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=101.0):
            self.wheel_up(bubble, Qt.ScrollUpdate, delta=15)
            self.assertFalse(bubble._scroll.loading, "not pulled far enough yet")
            self.wheel_up(bubble, Qt.ScrollUpdate, delta=30)
        self.assertTrue(bubble._scroll.loading, "a light pull from the top is enough")

    def test_the_pulsing_dots_do_not_pull_the_text_back_to_the_top_while_you_scroll(self):
        self.MESSAGES = [{"role": "user", "text": "Klaar?"}, {"role": "bot", "text": "Een lange regel. " * 200}]
        from botwidget.markdown import conversation_blocks, plain_block, role_panel
        bubble = self.window.bubble
        blocks = conversation_blocks(self.MESSAGES, "Test") + [role_panel("bot"), plain_block("dots")]
        bubble.show_blocks(blocks, "say", input=True)
        self.finish_growth()
        self.assertTrue(bubble._dots_lines)
        bar = bubble._scroll.verticalScrollBar()
        bar.setValue(40)
        bubble._tick_dots()
        self.assertEqual(bar.value(), 40)

    def test_scrolling_up_pauses_at_the_top_of_the_message_and_a_new_flick_loads_the_one_before(self):
        from unittest import mock
        self.MESSAGES = [{"role": "user", "text": "Klaar?"}, {"role": "bot", "text": "Een lange regel. " * 200}]
        self.hover()
        bubble = self.window.bubble
        bar = bubble._scroll.verticalScrollBar()
        bar.setValue(30)
        with mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=100.0):
            self.wheel_up(bubble)
        bar.setValue(0)
        with mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=100.05):
            self.wheel_up(bubble)
            self.assertEqual(self.window._depth, 1, "the same flick only bounces at the top")
        with mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=101.0):
            self.wheel_up(bubble)
            self.load_older()
            self.assertEqual(self.window._depth, 2, "a new flick asks for the message before")

    def test_while_the_message_before_loads_the_arrow_is_dots_the_text_hangs_lower_and_scrolling_is_ignored(self):
        self.hover()
        bubble = self.window.bubble
        self.wheel_up(bubble)
        self.assertTrue(bubble._scroll.loading)
        self.assertTrue(all(line.get("loading") for line in bubble._loading_lines) and bubble._loading_lines)
        self.assertIn("<circle", __import__("botwidget.bubble", fromlist=["x"]).bubble_deco_svg(*bubble._geom[:2]),
                      "dots where the arrow was")
        bubble._scroll._pull.setCurrentTime(bubble._scroll._pull.duration())
        self.assertGreater(bubble._scroll.widget().y(), 0, "the text hangs a little lower")
        self.wheel_up(bubble)
        self.wheel_up(bubble)
        self.assertEqual(self.window._depth, 1, "scroll events do nothing while loading")
        self.load_older()
        self.assertFalse(bubble._scroll.loading)
        self.assertEqual(self.window._depth, 2)
        self.assertEqual(bubble._scroll.widget().y(), 0)

    def test_a_new_message_ends_the_loading_of_the_message_before(self):
        self.hover()
        bubble = self.window.bubble
        self.wheel_up(bubble)
        self.window._sync_bubble({"messages": self.MESSAGES + [{"role": "bot", "text": "Nog iets."}], "activity": ""})
        self.assertFalse(bubble._scroll.loading)
        self.load_older()
        self.assertEqual(self.window._depth, 1)

    def test_a_flick_that_runs_into_the_top_bounces_once(self):
        from unittest import mock
        self.MESSAGES = [{"role": "user", "text": "Klaar?"}, {"role": "bot", "text": "Een lange regel. " * 200}]
        self.hover()
        bubble = self.window.bubble
        bubble._scroll.verticalScrollBar().setValue(30)
        with mock.patch.object(bubble._scroll._bounce, "start") as bounce:
            for step in range(8):
                with mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=100.0 + step * 0.1):
                    self.wheel_up(bubble)
                    bubble._scroll.verticalScrollBar().setValue(0)
        self.assertEqual(bounce.call_count, 1)

    def test_a_copied_notice_stays_on_its_message_when_an_older_one_loads_above(self):
        self.hover()
        bubble = self.window.bubble
        self.click(1)
        self.window.show_older()
        self.finish_growth()
        from botwidget.bubble import panel_rects
        top, height = panel_rects(bubble._geom[0])[-1]
        top -= bubble._scroll.verticalScrollBar().value()
        view = bubble._scroll.viewport().height()
        self.assertEqual((bubble._notice.y(), bubble._notice.height()), (top, min(view, top + height) - top))

    def test_a_new_message_takes_the_notice_away(self):
        self.hover()
        self.click(1)
        self.assertTrue(self.window.bubble._notice.isVisible())
        self.window._sync_bubble({"messages": self.MESSAGES + [{"role": "bot", "text": "Nog iets."}], "activity": ""})
        self.assertFalse(self.window.bubble._notice.isVisible())

    def test_cmd_backspace_deletes_the_line_before_the_cursor(self):
        from unittest import mock
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from botwidget.qt_ui import bubble_window
        self.hover()
        entry = self.window.bubble._entry
        entry.setText("Eerste zin.\nTweede zin die weg moet")
        cursor = entry.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        entry.setTextCursor(cursor)
        with mock.patch.object(bubble_window.sys, "platform", "darwin"):
            QTest.keyClick(entry, Qt.Key_Backspace, Qt.ControlModifier)
            self.assertEqual(entry.text(), "Eerste zin.\n")
            QTest.keyClick(entry, Qt.Key_Backspace, Qt.ControlModifier)
            self.assertEqual(entry.text(), "Eerste zin.", "at the start of a line it takes the line break")

    def test_the_notice_moves_along_with_its_message_when_the_bubble_scrolls(self):
        self.MESSAGES = [{"role": "bot", "text": "Ja.\n\n" + "Een lange regel. " * 200}]
        self.hover()
        bubble = self.window.bubble
        bar = bubble._scroll.verticalScrollBar()
        self.click(0)
        before = (bubble._notice.y(), bubble._notice.height())
        bar.setValue(bar.value() + 10)
        self.assertEqual(bubble._notice.y(), max(0, before[0] - 10) if before[0] > 0 else 0)
        bar.setValue(bar.maximum())
        self.assertLessEqual(bubble._notice.y() + bubble._notice.height(), bubble._scroll.viewport().height())

    def test_shift_enter_starts_a_new_line_and_enter_sends(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.hover()
        bubble = self.window.bubble
        sent = []
        self.window.on_user_message = lambda text, files=(): sent.append(text)
        QTest.keyClicks(bubble._entry, "eerste")
        QTest.keyClick(bubble._entry, Qt.Key_Return, Qt.ShiftModifier)
        QTest.keyClicks(bubble._entry, "tweede")
        self.assertEqual(bubble._entry.text(), "eerste\ntweede")
        self.assertEqual(sent, [])
        QTest.keyClick(bubble._entry, Qt.Key_Return)
        self.assertEqual(sent, ["eerste\ntweede"])

    def test_the_field_and_the_bubble_grow_with_its_lines(self):
        self.hover()
        bubble = self.window.bubble
        height, field = bubble.height(), bubble._entry.height()
        bubble._entry.setText("een\ntwee\ndrie")
        self.app.processEvents()
        self.assertGreater(bubble._entry.height(), field)
        self.assertEqual(bubble.height() - height, bubble._entry.height() - field, "the bubble makes room for it")
        bubble._entry.clear()
        self.app.processEvents()
        self.assertEqual(bubble._entry.height(), field)

    def test_the_field_shows_a_scrollbar_only_when_its_lines_no_longer_fit(self):
        from PySide6.QtCore import Qt
        self.hover()
        entry = self.window.bubble._entry
        entry.setText("x" * 70)
        self.app.processEvents()
        self.assertEqual(entry.verticalScrollBarPolicy(), Qt.ScrollBarAlwaysOff, "a wrapped long word grows the field")
        entry.setText("\n".join(["regel"] * 8))
        self.app.processEvents()
        self.assertEqual(entry.verticalScrollBarPolicy(), Qt.ScrollBarAsNeeded)
        entry.clear()
        self.app.processEvents()
        self.assertEqual(entry.verticalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)

    def test_the_thinking_cloud_has_the_field_so_you_can_write_ahead(self):
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": "reading"}, force=True)
        self.finish_growth()
        bubble = self.window.bubble
        self.assertEqual(bubble.kind, "think")
        self.assertTrue(bubble._entry.isVisibleTo(bubble))
        self.assertEqual(bubble._entry.placeholderText(), "Queue a message…")

    def start_working(self):
        self.state = {"activity": "reading"}
        self.face.latest_chat = lambda thread_id, limit=8: {"messages": self.MESSAGES, "activity": self.state["activity"]}
        self.window._pump_outbox = lambda: None
        self.window._sync_bubble(self.face.latest_chat("t"), force=True)

    def type_while_working(self, text):
        self.start_working()
        self.window.on_user_message(text)

    def test_a_message_typed_while_the_bot_works_waits_in_the_queue_and_shows_in_the_cloud(self):
        self.type_while_working("Daarna dit")
        self.assertEqual([item["text"] for item in self.window._queue], ["Daarna dit"])
        self.assertEqual(self.window._outbox.items, [], "not sent yet")
        self.assertIn("Daarna dit", self.window.bubble.full_text)
        self.assertIn("Queued", self.window.bubble.full_text)

    def test_the_queue_goes_out_one_message_per_finished_turn(self):
        self.start_working()
        self.window.on_user_message("Eerste")
        self.window.on_user_message("Tweede")
        texts = lambda items: [i["text"] for i in items]
        self.window._sync_bubble(self.face.latest_chat("t"))
        self.assertEqual(self.window._outbox.items, [], "the turn is still running")
        self.state["activity"] = ""
        self.window._sync_bubble(self.face.latest_chat("t"))
        self.assertEqual((texts(self.window._outbox.items), texts(self.window._queue)), (["Eerste"], ["Tweede"]))
        self.window._outbox.items.clear()
        self.window._sync_bubble(self.face.latest_chat("t"))
        self.assertEqual(texts(self.window._queue), ["Tweede"], "waits until the bot has started on the first")
        self.state["activity"] = "reading"
        self.window._sync_bubble(self.face.latest_chat("t"))
        self.state["activity"] = ""
        self.window._sync_bubble(self.face.latest_chat("t"))
        self.assertEqual(self.window._queue, [])
        self.assertEqual(texts(self.window._outbox.items), ["Tweede"])

    def test_clicking_a_queued_message_puts_it_back_in_the_field_to_edit(self):
        self.type_while_working("Pas mij aan")
        bubble = self.window.bubble
        self.finish_growth()
        self.window.bubble.focus_entry = lambda: None
        old = self.face.activate_app
        self.addCleanup(setattr, self.face, "activate_app", old)
        self.face.activate_app = lambda: None
        queued = next(panel for panel in bubble._geom[0] if panel.get("queued"))
        bubble.edit_queued.emit(queued["queued"])
        self.assertEqual(self.window._queue, [])
        self.assertEqual(bubble._entry.text(), "Pas mij aan")
        self.assertNotIn("Queued", bubble.full_text)

    def test_the_arrow_cursor_turns_into_a_hand_over_a_queued_message_in_the_cloud(self):
        self.type_while_working("Pas mij aan")
        self.finish_growth()
        bubble = self.window.bubble
        index = next(i for i, panel in enumerate(bubble._geom[0]) if panel.get("queued"))
        from botwidget.bubble import panel_rects
        top, height = panel_rects(bubble._geom[0])[index]
        self.assertIsNotNone(bubble._message_at(40, top + height / 2))
        self.assertIsNone(bubble._message_at(40, 3), "the thought itself is not clickable")

    def test_the_field_stays_put_when_a_new_thought_makes_the_cloud_grow(self):
        self.start_working()
        self.finish_growth()
        bubble = self.window.bubble
        self.assertTrue(bubble._entry.isVisibleTo(bubble))
        self.state["activity"] = "A much longer thought. " * 15
        self.window._sync_bubble(self.face.latest_chat("t"))
        self.assertIsNotNone(bubble._growth, "the cloud is growing again")
        self.assertEqual(bubble._growth.progress, 0.0)
        self.assertTrue(bubble._entry.isVisibleTo(bubble), "hiding the field would take the cursor away")

    def test_the_text_does_not_twitch_back_while_it_hangs_lower_during_loading(self):
        self.hover()
        bubble = self.window.bubble
        self.wheel_up(bubble)
        self.assertTrue(bubble._scroll.loading)
        bubble._scroll._pull.setCurrentTime(bubble._scroll._pull.duration())
        hanging = bubble._scroll.widget().y()
        self.assertGreater(hanging, 0)
        for _ in range(5):
            bubble._tick_dots()
            self.assertEqual(bubble._scroll.widget().y(), hanging)

    def test_the_text_is_back_in_place_before_the_older_message_slides_in(self):
        self.hover()
        bubble = self.window.bubble
        self.wheel_up(bubble)
        bubble._scroll._pull.setCurrentTime(bubble._scroll._pull.duration())
        self.assertGreater(bubble._scroll.widget().y(), 0)
        seen = []
        bubble.older.connect(lambda: seen.append(bubble._scroll.widget().y()))
        self.load_older()
        self.assertEqual(seen, [0], "no jump when the message slides in")

    def settings_state(self):
        return {"sound": True, "quiet_hours": False, "always_on_top": True, "all_desktops": False, "login": False,
                "check_updates": True, "auto_update": False, "channel": "local", "version": "0.2.0",
                "can_pick_desktops": True, "can_install_updates": False, "hotkey": "", "switch_label": None,
                "update": "", "staged_update": "", "bots": []}

    def open_settings(self):
        from botwidget import menu_pages
        self.window.faces = type("Faces", (), {"menu_state": lambda _self: self.settings_state(),
                                               "menu_command": lambda _self, command, page: page,
                                               "close_bubbles_except": lambda _self, _id: None})()
        self.window.open_menu("settings")
        self.finish_growth()
        self.app.processEvents()
        return self.window.bubble

    def test_the_settings_are_real_switches_and_buttons_in_their_rows(self):
        from botwidget.qt_ui.controls import ActionButton, Switch
        bubble = self.open_settings()
        switches = [w for w in bubble._control_widgets if isinstance(w, Switch)]
        buttons = [w for w in bubble._control_widgets if isinstance(w, ActionButton)]
        self.assertEqual(len(switches), 6)
        self.assertEqual([w.text() for w in buttons], ["Quit Bot Widget"])
        self.assertEqual([w.isChecked() for w in switches], [True, False, True, False, False, True])
        rows = [w.geometry().top() for w in switches]
        self.assertEqual(rows, sorted(rows), "in the order of the page")
        self.assertEqual(len(set(rows)), len(rows), "each in a row of its own")

    def test_clicking_a_switch_runs_its_command(self):
        from botwidget.qt_ui.controls import Switch
        bubble = self.open_settings()
        sent = []
        bubble.command.connect(sent.append)
        next(w for w in bubble._control_widgets if isinstance(w, Switch)).click()
        self.assertEqual(sent, ["toggle/sound"])

    def test_the_arrow_on_a_page_leads_back_to_the_field_with_the_list_of_commands(self):
        bubble = self.open_settings()
        self.assertEqual(bubble._geom[0][0]["back"], "page/commands")
        bubble.command.emit("page/commands")
        self.finish_growth()
        self.assertIsNone(self.window._menu_page)
        self.assertEqual(bubble._entry.text(), "/")
        self.assertTrue(bubble._slash.isVisibleTo(bubble))
        self.assertIn("Ja.", bubble.full_text, "above the conversation")

    def test_a_page_has_the_arrow_up_instead_of_a_menu_link_and_it_goes_back(self):
        bubble = self.open_settings()
        self.assertNotIn("Menu", bubble.full_text)
        self.assertEqual(bubble._geom[0][0]["role"], "more")
        sent = []
        bubble.command.connect(sent.append)
        _x, y = self.message_point(0, down=4)
        self.click_at(bubble._shown_w(bubble._geom[1]) // 2, y)
        self.assertEqual(sent, ["page/commands"])

    def test_scrolling_past_the_top_of_a_page_goes_back_too(self):
        bubble = self.open_settings()
        sent = []
        bubble.command.connect(sent.append)
        self.wheel_up(bubble)
        self.assertEqual(sent, ["page/commands"])

    def test_a_page_stays_a_while_when_the_pointer_is_outside_it_and_a_margin_counts_as_on_it(self):
        from unittest import mock
        bubble = self.open_settings()
        self.where["at"] = (-5000, -5000)
        bubble._tick()
        self.assertTrue(bubble.isVisible(), "the page just opened")
        near = bubble.frameGeometry().right() + 10
        self.where["at"] = (near, bubble.frameGeometry().center().y())
        self.assertTrue(self.window.pointer_near(bubble), "a margin around the bubble")
        with mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=time.monotonic() + 60):
            self.where["at"] = (-5000, -5000)
            bubble._tick()
        self.assertFalse(bubble.isVisible(), "gone once the pointer has been away past the delay")

    def test_on_wayland_only_our_own_windows_count_as_the_pointer_being_there(self):
        from unittest import mock
        bubble = self.open_settings()
        # A Wayland client that has not had the pointer keeps QCursor.pos() where it was, or at 0,0,
        # which used to read as a pointer parked on the face and held every bubble open.
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        with mock.patch("botwidget.qt_ui.face.global_pointer", return_value=False):
            self.assertFalse(self.window.pointer_near(bubble), "0,0 is not the pointer")
            self.assertFalse(self.window._pointer_on_head())
            with mock.patch.object(type(self.window), "underMouse", return_value=True):
                self.assertTrue(self.window.pointer_near(bubble), "the pointer is on the face")
                self.assertTrue(self.window._pointer_on_head())
            with mock.patch.object(type(bubble), "underMouse", return_value=True):
                self.assertTrue(self.window.pointer_near(bubble), "the pointer is on the bubble")

    def test_on_wayland_the_gap_between_face_and_bubble_is_a_moment_and_not_a_leave(self):
        from contextlib import ExitStack
        from unittest import mock
        from botwidget.qt_ui import bubble_window
        bubble = self.open_settings()
        bubble._kept_until = 0.0
        start = time.monotonic()

        def tick(at: float, over: bool):
            with ExitStack() as stack:
                stack.enter_context(mock.patch("botwidget.qt_ui.face.global_pointer", return_value=False))
                stack.enter_context(mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=at))
                if over:
                    stack.enter_context(mock.patch.object(type(bubble), "underMouse", return_value=True))
                bubble._tick()

        tick(start, over=True)
        self.assertTrue(bubble.isVisible(), "the pointer was on it")
        tick(start + 0.2, over=False)
        self.assertTrue(bubble.isVisible(), "off the window: that may be the gap on the way to the face")
        tick(start + 0.5, over=False)
        self.assertTrue(bubble.isVisible(), "still within the crossing")
        tick(start + 0.55, over=True)
        tick(start + 0.95, over=False)
        self.assertTrue(bubble.isVisible(), "back on the bubble: the moment starts over")
        tick(start + 1.3, over=False)
        self.assertFalse(bubble.isVisible(), "away for longer than a crossing: gone")

    def test_on_wayland_a_bubble_closes_when_the_pointer_never_came_near_it(self):
        from unittest import mock
        bubble = self.open_settings()
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        with mock.patch("botwidget.qt_ui.face.global_pointer", return_value=False), \
                mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=time.monotonic() + 60):
            bubble._tick()
        self.assertFalse(bubble.isVisible(), "a stuck cursor must not keep it open")

    def temporary_transfers(self):
        from botwidget import attachments
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        old = attachments.TRANSFERS
        self.addCleanup(setattr, attachments, "TRANSFERS", old)
        attachments.TRANSFERS = __import__("pathlib").Path(folder) / "Transfers"
        return folder

    def test_a_pasted_file_is_copied_under_the_shared_folder_and_shows_as_a_chip(self):
        from PySide6.QtCore import QMimeData, QUrl
        folder = self.temporary_transfers()
        original = os.path.join(folder, "notitie.txt")
        with open(original, "w") as handle:
            handle.write("hoi")
        self.hover()
        bubble = self.window.bubble
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(original)])
        height = bubble.height()
        bubble._entry.insertFromMimeData(data)
        self.assertEqual(bubble._entry.text(), "", "the path is not typed into the field")
        self.assertEqual([p.name for p in bubble._attachments], ["notitie.txt"])
        self.assertTrue(str(bubble._attachments[0]).startswith(os.path.join(folder, "Transfers")))
        self.assertTrue(bubble._attachments[0].read_text() == "hoi")
        self.assertTrue(bubble._attachment_row.isVisibleTo(bubble))
        self.assertIn("notitie.txt", bubble._attachment_row.text())
        self.assertGreater(bubble.height(), height, "the bubble makes room for the chip")

    def test_a_pasted_picture_becomes_a_png(self):
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QColor, QImage
        self.temporary_transfers()
        self.hover()
        bubble = self.window.bubble
        image = QImage(4, 4, QImage.Format_RGB32)
        image.fill(QColor("red"))
        data = QMimeData()
        data.setImageData(image)
        bubble._entry.insertFromMimeData(data)
        self.assertEqual([p.name for p in bubble._attachments], ["image.png"])
        self.assertFalse(QImage(str(bubble._attachments[0])).isNull())

    def test_pasting_plain_text_still_types_it(self):
        from PySide6.QtCore import QMimeData
        self.hover()
        entry = self.window.bubble._entry
        data = QMimeData()
        data.setText("gewoon tekst")
        entry.insertFromMimeData(data)
        self.assertEqual(entry.text(), "gewoon tekst")
        self.assertEqual(self.window.bubble._attachments, [])

    def test_a_chip_can_be_removed_and_a_message_goes_out_with_the_list_of_its_files(self):
        from pathlib import Path
        self.temporary_transfers()
        self.hover()
        bubble = self.window.bubble
        bubble._attach([Path("/x/een.png"), Path("/x/twee.pdf")])
        bubble._unattach("0")
        self.assertEqual([p.name for p in bubble._attachments], ["twee.pdf"])
        bubble._entry.setText("Kijk even")
        self.window._pump_outbox = lambda: None
        bubble._send()
        self.assertEqual(bubble._attachments, [])
        self.assertFalse(bubble._attachment_row.isVisibleTo(bubble))
        self.assertEqual(self.window._outbox.items[0]["text"],
                         "Kijk even\n\nAttached local files:\n- twee.pdf: /x/twee.pdf")

    def test_a_file_alone_is_a_message_and_a_queued_one_keeps_its_file_for_editing(self):
        from pathlib import Path
        self.hover()
        bubble = self.window.bubble
        self.start_working()
        bubble._attach([Path("/x/een.png")])
        bubble._send()
        self.assertEqual(self.window._outbox.items, [], "queued while the bot works")
        item = self.window._queue[0]
        self.assertEqual((item["text"], [p.name for p in item["files"]]), ("", ["een.png"]))
        self.assertIn("een.png", bubble.full_text)
        self.window.bubble.focus_entry = lambda: None
        self.window._edit_queued(item["id"])
        self.assertEqual([p.name for p in bubble._attachments], ["een.png"])
        self.assertEqual(self.window._queue, [])

    def click_face(self, shift=False):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        point = QPointF(5, 5)
        self.window._press_pos = (point.x(), point.y())
        QApplication.sendEvent(self.window, QMouseEvent(QEvent.MouseButtonRelease, point, point, Qt.LeftButton,
                                                        Qt.NoButton, Qt.ShiftModifier if shift else Qt.NoModifier))

    def test_shift_clicking_a_thinking_face_mutes_its_thinking_and_shift_clicking_again_brings_it_back(self):
        self.start_working()
        self.assertEqual(self.window.bubble.kind, "think")
        self.click_face(shift=True)
        self.assertTrue(self.window._muted)
        self.assertFalse(self.window.bubble.isVisible(), "no cloud while muted")
        self.window._sync_bubble(self.face.latest_chat("t"))
        self.assertFalse(self.window.bubble.isVisible(), "and it does not come back by itself")
        self.click_face(shift=True)
        self.assertFalse(self.window._muted)
        self.assertEqual(self.window.bubble.kind, "think")

    def test_a_plain_click_never_mutes_not_even_while_thinking(self):
        focus = []
        self.window.bubble.focus_entry = lambda: focus.append(1)
        self.start_working()
        self.click_face()
        self.assertFalse(self.window._muted)
        self.assertEqual(focus, [1], "it opens the field as ever")

    def test_the_mute_is_kept_and_a_new_window_for_the_same_bot_starts_muted(self):
        self.window.toggle_muted()
        self.assertEqual(config.muted_bots(), ["t"])
        again = self.face.FaceWindow("t", "Test", spot=(500, 400))
        self.addCleanup(again.close_face)
        again._poll_timer.stop()
        self.assertTrue(again._muted)
        self.assertIn(" L", __import__("botwidget.avatar", fromlist=["x"]).face_svg(seed="t", muted=again._muted))
        self.window.toggle_muted()
        self.assertEqual(config.muted_bots(), [])

    def test_shift_click_mutes_or_unmutes_at_any_moment(self):
        self.click_face(shift=True)
        self.assertTrue(self.window._muted, "also when the bot is idle")
        self.click_face(shift=True)
        self.assertFalse(self.window._muted)

    def test_the_bots_page_says_how_to_mute(self):
        from botwidget import menu_pages
        self.assertIn("Shift+click", markdown.block_text(menu_pages.bots(self.settings_state())))

    def test_the_bots_page_has_a_mute_switch_per_bot_that_works_for_a_bot_without_a_face(self):
        from botwidget.qt_ui.faces import Faces
        faces = Faces.__new__(Faces)
        faces.faces = {}
        self.assertEqual(faces.menu_command("mute/zz", "bots"), "bots")
        self.assertEqual(config.muted_bots(), ["zz"])
        faces.menu_command("mute/zz", "bots")
        self.assertEqual(config.muted_bots(), [])

    def test_a_click_on_a_face_that_is_not_thinking_still_opens_the_chat(self):
        focus = []
        self.window.bubble.focus_entry = lambda: focus.append(1)
        self.click_face()
        self.assertFalse(self.window._muted)
        self.assertEqual(focus, [1])

    def attention(self, **extra):
        return {"prompts": [], "approvals": [], "browserTakeovers": [], **extra}

    QUESTION = {"requestId": "r1", "requiresOpenBot": False, "questions": [
        {"id": "q1", "header": "Kleur", "question": "Welke **kleur** wil je?",
         "options": [{"label": "Rood", "description": ""}, {"label": "Blauw", "description": ""}]}]}

    def posts(self):
        calls = []

        def post(path, body):
            calls.append((path, body))
            return self.face.ApiResult({"ok": True}, 200, "")
        old = self.face.api_post
        self.addCleanup(setattr, self.face, "api_post", old)
        self.face.api_post = post
        return calls

    def wait_for(self, calls):
        for _ in range(300):
            if calls:
                return
            time.sleep(0.01)
            self.app.processEvents()

    def test_a_question_from_the_bot_shows_with_a_button_per_option_even_when_thinking_is_muted(self):
        self.start_working()
        self.window._muted = True
        self.window._set_attention(self.attention(prompts=[self.QUESTION]))
        self.window._sync_bubble(self.face.latest_chat("t"), force=True)
        bubble = self.window.bubble
        self.assertEqual(bubble.kind, "think")
        self.assertIn("Welke kleur wil je?", bubble.full_text)
        self.assertEqual([w.text() for w in bubble._control_widgets], ["Rood", "Blauw"])
        self.assertEqual(bubble._entry.placeholderText(), "Type your answer…")

    def test_a_question_alone_makes_the_bot_count_as_working_and_shows_the_cloud(self):
        self.window._set_attention(self.attention(prompts=[self.QUESTION]))
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": ""}, force=True)
        self.assertEqual(self.window.bubble.kind, "think")

    def test_clicking_an_option_answers_the_question(self):
        calls = self.posts()
        self.start_working()
        self.window._set_attention(self.attention(prompts=[self.QUESTION]))
        self.window._sync_bubble(self.face.latest_chat("t"), force=True)
        self.window.bubble._control_widgets[1].click()
        self.wait_for(calls)
        self.assertEqual(calls, [("/v1/agents/t/prompts/r1/answer", {"answers": {"q1": ["Blauw"]}})])
        self.assertNotIn("Welke kleur", self.window.bubble.full_text, "gone while the answer goes out")

    def test_typing_in_the_field_answers_the_open_question_in_your_own_words(self):
        calls = self.posts()
        self.start_working()
        self.window._set_attention(self.attention(prompts=[self.QUESTION]))
        self.window.on_user_message("Paars")
        self.wait_for(calls)
        self.assertEqual(calls, [("/v1/agents/t/prompts/r1/answer", {"answers": {"q1": ["Paars"]}})])
        self.assertEqual(self.window._queue, [], "an answer, not a message in the queue")

    def test_a_prompt_with_several_questions_goes_out_once_all_are_answered(self):
        calls = self.posts()
        prompt = {"requestId": "r2", "requiresOpenBot": False, "questions": [
            {"id": "a", "header": "", "question": "Eerste?", "options": [{"label": "Ja"}, {"label": "Nee"}]},
            {"id": "b", "header": "", "question": "Tweede?", "options": [{"label": "Oke"}]}]}
        self.start_working()
        self.window._set_attention(self.attention(prompts=[prompt]))
        self.window._menu_command("answer/r2/a/1")
        self.assertEqual(calls, [])
        self.assertIn("✓ Nee", self.window.bubble.full_text)
        self.window._menu_command("answer/r2/b/0")
        self.wait_for(calls)
        self.assertEqual(calls[0][1], {"answers": {"a": ["Nee"], "b": ["Oke"]}})

    def test_an_approval_has_accept_and_decline_buttons(self):
        calls = self.posts()
        approval = {"requestId": "p1", "kind": "command", "command": "rm -rf build", "cwd": "/tmp/x",
                    "reason": "Clean up", "grantRoot": None, "permissions": None}
        self.start_working()
        self.window._set_attention(self.attention(approvals=[approval]))
        self.window._sync_bubble(self.face.latest_chat("t"), force=True)
        bubble = self.window.bubble
        self.assertIn("Run a command?", bubble.full_text)
        self.assertIn("rm -rf build", bubble.full_text)
        self.assertEqual([w.text() for w in bubble._control_widgets], ["Accept", "Decline"])
        bubble._control_widgets[1].click()
        self.wait_for(calls)
        self.assertEqual(calls, [("/v1/agents/t/approvals/p1/respond", {"decision": "decline"})])

    def test_a_question_that_needs_openbot_itself_says_so_and_has_no_buttons(self):
        prompt = {"requestId": "r3", "requiresOpenBot": True, "questions": []}
        self.start_working()
        self.window._set_attention(self.attention(prompts=[prompt]))
        self.window._sync_bubble(self.face.latest_chat("t"), force=True)
        self.assertIn("open OpenBot", self.window.bubble.full_text)
        self.assertEqual(self.window.bubble._control_widgets, [])
        self.assertIsNone(self.window._open_question())

    def test_a_refused_answer_says_so_and_the_question_comes_back(self):
        self.window._set_attention(self.attention(prompts=[self.QUESTION]))
        self.window._answering.add("r1")
        self.window._answers["r1"] = {"q1": ["Rood"]}
        self.window._on_attention_done(False, "HTTP 409")
        self.assertEqual(self.window._answering, set())
        self.assertIn("HTTP 409", "".join(c for b in self.window._attention_blocks() for c, _s in b.get("chunks", [])))

    LONG_THOUGHT = "A thought that goes on. " * 60

    def think(self, text):
        self.state["activity"] = text
        self.window._sync_bubble(self.face.latest_chat("t"))
        self.finish_growth()
        self.app.processEvents()
        return self.window.bubble, self.window.bubble._scroll.verticalScrollBar()

    def test_the_cloud_follows_a_thought_down_as_it_grows(self):
        self.start_working()
        bubble, bar = self.think(self.LONG_THOUGHT)
        self.assertGreater(bar.maximum(), 0)
        self.assertEqual(bar.value(), bar.maximum(), "at the end of the thought")
        bubble, bar = self.think(self.LONG_THOUGHT + "And on it goes, a little further. " * 20)
        self.assertEqual(bar.value(), bar.maximum(), "and still at the end")

    def test_the_cloud_stays_where_you_scrolled_to_in_a_thought(self):
        self.start_working()
        bubble, bar = self.think(self.LONG_THOUGHT)
        bar.setValue(20)
        bubble, bar = self.think(self.LONG_THOUGHT + "More. " * 40)
        self.assertEqual(bar.value(), 20)
        bar.setValue(bar.maximum())
        bubble, bar = self.think(self.LONG_THOUGHT + "More. " * 80)
        self.assertEqual(bar.value(), bar.maximum(), "back at the end it follows again")

    def test_the_dots_sit_at_the_end_of_the_cloud(self):
        self.start_working()
        bubble, _bar = self.think("reading")
        panels = bubble._geom[0]
        self.assertEqual(panels[-1]["lines"][-1]["kind"], "dots")
        self.assertNotIn("dots", [line["kind"] for line in panels[0]["lines"]])

    def test_a_message_is_still_read_from_its_top(self):
        self.MESSAGES = [{"role": "bot", "text": "Een lange regel. " * 200}]
        self.hover()
        self.assertEqual(self.window.bubble._scroll.verticalScrollBar().value(), 0)

    def stub_faces(self):
        self.window.faces = type("Faces", (), {"menu_state": lambda _self: self.settings_state(),
                                               "menu_command": lambda _self, command, page: page,
                                               "close_bubbles_except": lambda _self, _id: None})()

    def test_a_slash_at_the_start_opens_a_list_of_commands_above_the_field(self):
        self.hover()
        bubble = self.window.bubble
        height = bubble.height()
        bubble._entry.setText("/")
        self.app.processEvents()
        self.assertTrue(bubble._slash.isVisibleTo(bubble))
        self.assertEqual([c for c, _n in bubble._slash.rows], ["/settings", "/bots", "/connections"])
        self.assertLess(bubble._slash.geometry().bottom(), bubble._entry.geometry().top(), "above the field")
        self.assertGreater(bubble.height(), height, "the bubble makes room for the list")
        bubble._entry.setText("/b")
        self.assertEqual([c for c, _n in bubble._slash.rows], ["/bots"])
        bubble._entry.setText("/zzz")
        self.assertFalse(bubble._slash.isVisibleTo(bubble))
        bubble._entry.setText("hallo /bots")
        self.assertFalse(bubble._slash.isVisibleTo(bubble), "only at the start of the message")
        bubble._entry.clear()
        self.app.processEvents()
        self.assertEqual(bubble.height(), height, "and the room is given back")

    def test_arrows_and_return_pick_a_command_and_it_opens_its_page(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.hover()
        self.stub_faces()
        bubble = self.window.bubble
        bubble._entry.setText("/")
        QTest.keyClick(bubble._entry, Qt.Key_Down)
        QTest.keyClick(bubble._entry, Qt.Key_Return)
        self.assertEqual(self.window._menu_page, "bots")
        self.assertEqual(bubble._entry.text(), "")

    def test_tab_completes_the_command_without_running_it_and_escape_only_closes_the_list(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.hover()
        self.stub_faces()
        bubble = self.window.bubble
        bubble._entry.setText("/c")
        QTest.keyClick(bubble._entry, Qt.Key_Tab)
        self.assertEqual(bubble._entry.text(), "/connections")
        self.assertIsNone(self.window._menu_page)
        bubble._entry.setText("/")
        dismissed = []
        bubble._entry.dismissed.connect(lambda: dismissed.append(1))
        QTest.keyClick(bubble._entry, Qt.Key_Escape)
        self.assertFalse(bubble._slash.isVisibleTo(bubble))
        self.assertEqual((bubble._entry.text(), dismissed), ("/", []), "the bubble itself stays")

    def test_clicking_a_command_in_the_list_runs_it(self):
        self.hover()
        self.stub_faces()
        bubble = self.window.bubble
        bubble._entry.setText("/")
        bubble._slash.chosen.emit("/settings")
        self.assertEqual(self.window._menu_page, "settings")

    def test_every_command_in_the_list_opens_a_page(self):
        from botwidget import menu_pages
        for command, _note in menu_pages.COMMANDS:
            self.assertIn(command, menu_pages.SLASH)

    def second_face(self):
        from botwidget.qt_ui.faces import Faces
        other = self.face.FaceWindow("u", "Other", spot=(900, 400))
        self.addCleanup(other.close_face)
        other._poll_timer.stop()
        other._pointer = lambda: self.where["at"]
        other.bubble.focus_entry = lambda: None
        registry = Faces.__new__(Faces)
        registry.faces = {"t": self.window, "u": other}
        self.window.faces = other.faces = registry
        return other

    def test_when_one_bubble_opens_on_hover_the_bubble_of_the_other_face_closes(self):
        other = self.second_face()
        self.hover()
        self.assertTrue(self.window.bubble.isVisible())
        self.where["at"] = (other.x() + 34, other.y() + 34)
        other._animate()
        self.finish_growth()
        other.bubble._slide.stop()
        other.bubble._growth_done()
        self.assertTrue(other.bubble.isVisible())
        self.assertFalse(self.window.bubble.isVisible(), "one at a time")

    def test_a_short_message_sent_with_the_pointer_away_keeps_the_bubble_open_for_a_while(self):
        self.window.pin()
        self.finish_growth()
        bubble = self.window.bubble
        self.window.unpin()
        self.where["at"] = (5000, 5000)
        bubble._was_near = True
        bubble.type_text("ok")
        bubble._entry.clearFocus()
        bubble._kept_until = 0.0
        bubble._send()
        bubble._tick()
        self.assertTrue(bubble.kind, "a message that was just sent keeps it for a moment")

    def test_a_bubble_that_opens_by_itself_steps_aside_for_the_one_the_user_is_busy_with_and_returns(self):
        from botwidget.qt_ui.face import conversation_blocks
        other = self.second_face()
        other.move(self.window.x(), self.window.y())
        # A screen so cramped that no side is free.
        other.bubble._covering = lambda *_spot: [self.window.bubble] if self.window.bubble.isVisible() else []
        self.window.pin()
        self.finish_growth()
        mine = self.window.bubble
        other.bubble.show_blocks(conversation_blocks([{"role": "bot", "text": "Klaar"}], "Other"), "say")
        self.assertTrue(mine.isVisible())
        self.assertTrue(other.bubble._yielding, "no room beside it: the user's bubble wins")
        self.assertFalse(other.bubble.isVisible())
        self.window.unpin()
        mine.place("")
        other.bubble._tick()
        self.assertTrue(other.bubble.isVisible(), "it returns when the user's bubble is gone")

    def test_a_bubble_that_opens_by_itself_takes_a_free_side_instead_of_covering_the_other(self):
        from botwidget.qt_ui.face import conversation_blocks
        other = self.second_face()
        other.move(self.window.x() + 60, self.window.y())
        self.window.pin()
        self.finish_growth()
        other.bubble.show_blocks(conversation_blocks([{"role": "bot", "text": "Klaar"}], "Other"), "say")
        self.assertFalse(other.bubble._covering(*other.bubble._spot[:2], other.bubble.width(), other.bubble.height()))
        states = set()
        for _ in range(6):
            other.bubble._tick()
            states.add((other.bubble.isVisible(), other.bubble._yielding))
        self.assertEqual(len(states), 1, "it does not flip between shown and waiting")

    def test_a_bubble_that_waits_for_room_stays_out_of_sight_and_does_not_try_to_open_again_and_again(self):
        from botwidget.qt_ui.face import conversation_blocks
        other = self.second_face()
        other.move(self.window.x(), self.window.y())
        # A screen so cramped that no side is free.
        other.bubble._covering = lambda *_spot: [self.window.bubble] if self.window.bubble.isVisible() else []
        self.window.pin()
        self.finish_growth()
        blocks = conversation_blocks([{"role": "bot", "text": "Klaar"}], "Other")
        other.bubble.show_blocks(blocks, "say")
        for _ in range(3):
            other.bubble.show_blocks(blocks, "say")
            other.bubble._tick()
        self.assertFalse(other.bubble.isVisible())
        self.assertIsNone(other.bubble._growth, "no opening animation runs out of sight")
        self.window.unpin()
        self.window.bubble.place("")
        other.bubble._tick()
        self.assertTrue(other.bubble.isVisible())
        self.assertIsNotNone(other.bubble._growth, "it opens the way a new bubble does")

    def test_the_field_shows_its_cursor_after_a_line_wraps(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from botwidget.qt_ui.face import conversation_blocks
        bubble = self.window.bubble
        bubble.show_blocks(conversation_blocks([{"role": "bot", "text": "Ja"}], "T"), "say", input=True)
        self.finish_growth()
        entry = bubble._entry
        for _ in range(70):
            QTest.keyClick(entry, Qt.Key_X)
            QApplication.processEvents()
        self.assertLessEqual(entry.cursorRect().bottom(), entry.viewport().height())
        self.assertEqual(entry.verticalScrollBar().value(), 0)

    def test_a_pinned_bubble_closes_when_another_face_is_clicked_open(self):
        other = self.second_face()
        self.window.pin()
        self.assertTrue(self.window.bubble.isVisible())
        other.open_input()
        self.assertTrue(other.bubble.isVisible())
        self.assertFalse(self.window.bubble.isVisible())
        self.assertFalse(self.window.pinned)

    def test_a_face_without_a_bubble_of_its_own_does_not_close_the_others(self):
        other = self.second_face()
        self.hover()
        other.MESSAGES = []
        other._claim_bubble()
        self.assertTrue(self.window.bubble.isVisible(), "nothing opened, nothing closes")

    def test_a_bubble_that_macos_took_off_the_screen_is_taken_away_so_it_opens_again(self):
        from unittest import mock
        from botwidget.qt_ui import desktops
        self.hover()
        bubble = self.window.bubble
        self.assertTrue(bubble.isVisible())
        with mock.patch.object(desktops, "shown_here", return_value=False), \
                mock.patch.object(desktops, "apply") as apply:
            self.window._keep_bubble_here()
        apply.assert_called_once_with(bubble)
        self.assertFalse(bubble.isVisible(), "gone, so that the next hover opens it where you are")
        self.window._hover_retry = 0.0
        self.hover()
        self.assertTrue(bubble.isVisible())

    def test_a_bubble_that_is_where_you_are_is_left_alone(self):
        from unittest import mock
        from botwidget.qt_ui import desktops
        self.hover()
        with mock.patch.object(desktops, "shown_here", return_value=True):
            self.window._keep_bubble_here()
        self.assertTrue(self.window.bubble.isVisible())

    def test_the_field_never_has_a_horizontal_scrollbar(self):
        from PySide6.QtCore import Qt
        self.hover()
        self.assertEqual(self.window.bubble._entry.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)

    def test_hovering_over_a_thinking_bubble_never_takes_the_keyboard(self):
        activated = []
        old = self.face.activate_app
        self.addCleanup(setattr, self.face, "activate_app", old)
        self.face.activate_app = lambda: activated.append(1)
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": "reading"}, force=True)
        self.assertEqual(self.window.bubble.kind, "think")
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        self.window._animate()
        self.window._hover_since = 1.0
        self.window._animate()
        self.assertEqual(activated, [])

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


class MenuPages(unittest.TestCase):
    """Should build the menu pages from what the widget knows, with clickable rows nobody else can make."""

    STATE = {"version": "0.2.0", "channel": "local", "switch_label": "Switch to stable version", "hotkey": "⌃⌥Space",
             "update": "", "staged_update": "", "sound": True, "quiet_hours": False, "always_on_top": True,
             "can_pick_desktops": True, "all_desktops": True, "login": False, "check_updates": True,
             "can_install_updates": False, "auto_update": True,
             "bots": [{"id": "a", "name": "Fritsie", "on": True}, {"id": "b", "name": "Robo", "on": False}],
             "openbot": True, "automation_ready": False, "gbot": False, "grok": "no route"}

    @staticmethod
    def commands(blocks):
        found = []
        for block in blocks:
            found += [style[4:] for _text, style in block.get("chunks", []) if style.startswith("cmd:")]
            found += [block["command"]] if block.get("kind") == "control" else []
            found += [block["back"]] if block.get("back") else []
        return found

    @staticmethod
    def text(blocks):
        return markdown.block_text(blocks)

    def test_the_settings_page_shows_every_switch_as_it_stands(self):
        text = self.text(menu_pages.settings(self.STATE))
        self.assertIn("☑ Sound on a new answer", text)
        self.assertIn("☐ Start at login", text)
        self.assertIn("☑ Show on all desktops", text)
        self.assertIn("Running the local version, v0.2.0", text)
        self.assertIn("Switch to stable version", text)
        self.assertIn("⌃⌥Space", text)
        self.assertNotIn("Install updates automatically", text, "only where the app can install them")

    def test_the_settings_page_adapts_to_the_system(self):
        state = {**self.STATE, "can_pick_desktops": False, "can_install_updates": True, "hotkey": "", "switch_label": None}
        text = self.text(menu_pages.settings(state))
        self.assertNotIn("Show on all desktops", text)
        self.assertIn("Install updates automatically", text)
        self.assertNotIn("any app", text)

    def test_an_update_shows_on_the_settings_page(self):
        self.assertIn("Update available: v0.3.0", self.text(menu_pages.settings({**self.STATE, "update": "0.3.0"})))
        staged = menu_pages.settings({**self.STATE, "update": "0.3.0", "staged_update": "0.3.0"})
        self.assertIn("action/update", self.commands(staged))

    def test_the_bots_page_has_a_switch_per_bot(self):
        blocks = menu_pages.bots(self.STATE)
        self.assertEqual(self.commands(blocks), ["page/commands", "bot/a", "mute/a", "bot/b", "mute/b"])
        self.assertIn("☑ Fritsie", self.text(blocks))
        self.assertIn("☐ Robo", self.text(blocks))
        self.assertIn("No bots found yet", self.text(menu_pages.bots({**self.STATE, "bots": []})))

    def test_the_connections_page_says_what_was_found_and_what_is_missing(self):
        text = self.text(menu_pages.connections(self.STATE))
        self.assertIn("OpenBot detected", text)
        self.assertIn("local API is off", text)
        self.assertIn("Grok Bot not found", text)
        ready = self.text(menu_pages.connections({**self.STATE, "automation_ready": True, "gbot": True}))
        self.assertIn("Local API ready", ready)
        self.assertIn("Grok Bot no route", ready)
        self.assertIn("open/openbot", self.commands(menu_pages.connections({**self.STATE, "openbot": False})))

    def test_every_page_leads_back_to_the_commands(self):
        for page in menu_pages.PAGES:
            self.assertEqual(self.commands(menu_pages.page_blocks(page, self.STATE))[0], "page/commands")
        self.assertEqual(self.commands(menu_pages.page_blocks("nonsense", self.STATE)),
                         self.commands(menu_pages.settings(self.STATE)))

    def test_the_slash_commands_that_open_a_page(self):
        self.assertEqual(menu_pages.SLASH["/settings"], "settings")
        self.assertEqual(menu_pages.SLASH["/bots"], "bots")
        self.assertEqual(menu_pages.SLASH["/connections"], "connections")
        self.assertNotIn("/", menu_pages.SLASH, "a lone slash only shows the list")

    def test_a_message_can_never_make_a_menu_row(self):
        for text in ("[Quit](bw:action/quit)", "[x](cmd:action/quit)", "[x](bw://action/quit)", "<bw:action/quit>"):
            styles = {style for block in markdown.md_blocks(text) for _t, style in block.get("chunks", [])}
            self.assertFalse(any(style.startswith("cmd:") for style in styles), text)
            self.assertEqual(markdown.anchor_url("link:bw:action/quit"), "", "not a clickable address either")

    def test_only_the_menu_style_turns_into_a_command_address(self):
        self.assertEqual(markdown.command_href("cmd:page/bots"), "bw:page/bots")
        self.assertEqual(markdown.command_href("link:https://x.nl"), "")
        self.assertEqual(markdown.command_href("b"), "")


class MenuInBubble(unittest.TestCase):
    """Should open the menu in the bubble on a right-click or a slash command, and act on its rows."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui import face, faces
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.face, cls.faces = face, faces
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        for name, value in (("latest_chat", lambda thread_id, limit=20: {"messages": [{"role": "bot", "text": "Hoi."}], "activity": ""}),
                            ("openbot_installed", lambda: True), ("gbot_installed", lambda: True)):
            old = getattr(self.face, name)
            self.addCleanup(setattr, self.face, name, old)
            setattr(self.face, name, value)
        test = self
        state = dict(MenuPages.STATE)
        self.calls = []

        class FakeFaces:
            TOGGLES = {name: (lambda faces, on, name=name: test.calls.append((name, on)) or state.update({name: on}))
                       for name in ("sound", "login")}
            LINKS = test.faces.Faces.LINKS
            faces = {}

            def menu_state(self):
                return dict(state)

            def toggle(self, agent_id, on):
                test.calls.append(("bot", agent_id, on))

            menu_command = test.faces.Faces.menu_command

            def close_bubbles_except(self, agent_id):
                pass

            def install_update(self):
                test.calls.append("update")

        self.state = state
        self.window = self.face.FaceWindow("t", "Test", spot=(300, 400), faces=FakeFaces())
        self.window._poll_timer.stop()
        self.addCleanup(self.window.close_face)

    def text(self):
        return self.window.bubble.full_text

    def right_click(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        point = QPointF(5, 5)
        QApplication.sendEvent(self.window, QMouseEvent(QEvent.MouseButtonPress, point, point, Qt.RightButton,
                                                        Qt.RightButton, Qt.NoModifier))

    def test_a_right_click_opens_the_bubble_with_a_slash_and_the_list_of_commands(self):
        self.right_click()
        bubble = self.window.bubble
        self.assertTrue(bubble.isVisible())
        self.assertEqual(bubble._entry.text(), "/")
        self.assertTrue(bubble._slash.isVisibleTo(bubble))
        self.assertEqual(bubble._slash.rows, list(menu_pages.COMMANDS))
        self.assertNotIn("Looking for settings", self.text())

    def test_typing_a_slash_command_opens_its_page_and_sends_nothing(self):
        self.window._pump_outbox = lambda: None
        for typed, expected in (("/settings", "Sound on a new answer"), ("/bots", "Fritsie"),
                                ("/connections", "OpenBot detected")):
            self.window.on_user_message(typed)
            self.assertIn(expected, self.text(), typed)
        self.assertEqual(self.window._outbox.items, [], "a slash command is not a message to the bot")

    def test_a_right_click_never_takes_away_what_you_typed(self):
        self.window.pin()
        bubble = self.window.bubble
        bubble._entry.setText("Een bericht dat bijna af is")
        self.right_click()
        self.assertEqual(bubble._entry.text(), "Een bericht dat bijna af is")
        self.assertTrue(bubble._slash.isVisibleTo(bubble))
        self.assertEqual(bubble._slash.rows, list(menu_pages.COMMANDS), "the whole list, the text is no filter")

    def test_picking_a_command_leaves_the_message_in_the_field_also_after_coming_back(self):
        self.window.pin()
        bubble = self.window.bubble
        bubble._entry.setText("Een bericht dat bijna af is")
        self.right_click()
        bubble._slash.chosen.emit("/bots")
        self.assertIn("Fritsie", self.text())
        self.assertEqual(bubble._entry.text(), "Een bericht dat bijna af is")
        bubble.command.emit("page/commands")
        self.assertEqual(bubble._entry.text(), "Een bericht dat bijna af is")
        self.assertTrue(bubble._slash.isVisibleTo(bubble))

    def test_typing_on_after_a_right_click_closes_the_list_and_enter_sends_as_ever(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.window.pin()
        bubble = self.window.bubble
        bubble.type_text("Hoi")
        self.right_click()
        QTest.keyClicks(bubble._entry, "!")
        self.assertFalse(bubble._slash.isVisibleTo(bubble))
        self.assertEqual(bubble._entry.text(), "Hoi!")

    def test_a_slash_being_typed_is_the_command_and_picking_it_clears_it(self):
        self.window.pin()
        bubble = self.window.bubble
        bubble._entry.setText("/b")
        self.right_click()
        self.assertEqual(bubble._entry.text(), "/b")
        bubble._slash.chosen.emit("/bots")
        self.assertEqual(bubble._entry.text(), "")

    def test_a_command_opens_its_page_in_the_same_bubble_and_the_arrow_comes_back(self):
        self.right_click()
        self.window.on_user_message("/settings")
        self.assertIn("Sound on a new answer", self.text())
        self.window.bubble.command.emit("page/commands")
        self.assertEqual(self.window.bubble._entry.text(), "/")
        self.assertTrue(self.window.bubble._slash.isVisibleTo(self.window.bubble))

    def test_a_link_in_the_bubble_runs_its_command(self):
        from PySide6.QtCore import QUrl
        self.window.open_menu("settings")
        self.window.bubble._doc._open(QUrl("bw:page/bots"))
        self.assertIn("Fritsie", self.text())

    def test_a_real_click_on_a_command_in_the_list_opens_its_page(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        self.right_click()
        slash = self.window.bubble._slash
        row = slash.ROW_H + slash.ROW_H // 2 + 4
        QTest.mouseClick(slash, Qt.LeftButton, Qt.NoModifier, QPoint(20, row))
        self.assertIn("Fritsie", self.text(), "the click on /bots opened the bots page")

    def test_a_switch_flips_and_the_page_shows_the_new_state(self):
        self.window.open_menu("settings")
        self.assertIn("☑ Sound on a new answer", self.text())
        self.window.bubble.command.emit("toggle/sound")
        self.assertEqual(self.calls, [("sound", False)])
        self.assertIn("☐ Sound on a new answer", self.text(), "the page redraws with the new state")

    def test_a_bot_row_switches_that_bots_face(self):
        self.window.open_menu("bots")
        self.window.bubble.command.emit("bot/b")
        self.assertEqual(self.calls, [("bot", "b", True)])

    def test_the_menu_is_not_replaced_by_the_conversation_while_it_is_open(self):
        self.window.open_menu("settings")
        self.window._sync_bubble({"messages": [{"role": "bot", "text": "Nieuw antwoord."}], "activity": ""})
        self.assertIn("Sound on a new answer", self.text())
        self.assertNotIn("Nieuw antwoord", self.text())

    def test_after_the_menu_closes_the_conversation_is_back(self):
        self.window.open_menu("settings")
        self.window.bubble.place("")
        self.window._sync_bubble({"messages": [{"role": "bot", "text": "Nieuw antwoord."}], "activity": ""}, force=True)
        self.assertIn("Nieuw antwoord", self.text())

    def test_a_menu_page_starts_at_its_top_where_the_way_back_is(self):
        import time
        self.window.open_menu("settings")
        bubble = self.window.bubble
        deadline = time.monotonic() + 3
        while bubble._growth is not None and time.monotonic() < deadline:
            self.app.processEvents()
        self.app.processEvents()
        self.assertEqual(bubble._scroll.verticalScrollBar().value(), 0)

    def test_opening_the_chat_takes_over_from_the_menu(self):
        self.window.open_menu("settings")
        self.window.pin()
        self.assertIsNone(self.window._menu_page)
        self.assertNotIn("Sound on a new answer", self.text())

    def test_the_menu_has_no_input_field_and_no_copying(self):
        self.window.open_menu("settings")
        self.assertFalse(self.window.bubble._entry.isVisibleTo(self.window.bubble))
        self.assertIsNone(self.window.bubble._message_at(0, 20))

    def test_without_faces_there_is_no_menu_and_no_error(self):
        bare = self.face.FaceWindow("t2", "Bare", spot=(100, 100))
        self.addCleanup(bare.close_face)
        bare._poll_timer.stop()
        bare.open_menu("settings")
        bare._menu_command("page/bots")
        self.assertFalse(bare.bubble.isVisible())


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

    def test_a_200_body_of_only_byte_order_marks_is_a_refusal(self):
        one, two = b"\xef\xbb\xbf", b"\xef\xbb\xbf\xef\xbb\xbf"
        for body in (one, one + b" \n", b" " + one + b"\t", two, two + b" \n",
                     one + b" " + one, two + one + b"\n"):
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
