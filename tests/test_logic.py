"""Logic without a screen: eye_aim, markdown and the face from the bot definition.

No window or toolkit: only calculating and parsing, so this also runs on a CI
machine without a display.
"""

import contextlib
import io
import json
import math
import os
import plistlib
import random
import re
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from botwidget import (
    animation,
    avatar,
    body3d,
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
from botwidget.qt_ui.native import native_id
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
        self.assertEqual(avatar.avatar_profile("grok:General", None, {"shape": "zigzag"}), seeded,
                         "a shape the widget cannot draw leaves the seed's face alone")
        self.assertEqual(avatar.avatar_profile("grok:General", None, {"color": "chartreuse"}), seeded,
                         "no colour is invented")
        body = avatar.face_svg(seed="grok:General", avatar={"shape": "blob", "color": "black"})
        self.assertIn('fill="#000000"', body)
        self.assertNotIn(seeded["hex"], body)

    def test_stable_index_matches_fnv1a(self):
        # FNV-1a of "a" is 0xe40c292c; at length 7 that is 4.
        self.assertEqual(avatar.stable_index("a", 7), 0xE40C292C % 7)


def eye_paths(svg: str) -> list:
    """The points of every eye in a face: the light filled paths."""
    found = re.findall(r'<path d="M([^"]+)Z" fill="' + re.escape(avatar.EYE_FILL) + '"', svg)
    return [[tuple(map(float, xy.split())) for xy in d.split("L")] for d in found]


def body_d(svg: str) -> str:
    return re.search(r'<path d="([^"]+)" fill="#', svg).group(1)


class GrokMarks(unittest.TestCase):
    """Should draw every Grok Bot avatar shape as Grok Bot draws it, with the widget's own animation."""

    def test_every_grok_bot_shape_has_a_mark_that_fits_the_face(self):
        from botwidget.grok_marks import GROK_MARKS
        for name in ("blob", "hex", "clover", "cloud", "sparkle", "house", "square", "squircle", "star"):
            self.assertIn(name, GROK_MARKS)
        for name, (body, eyes) in GROK_MARKS.items():
            self.assertGreaterEqual(len(body), 20, name)
            reach = max((x * x + y * y) ** 0.5 for x, y in body)
            self.assertLessEqual(reach, 1.1501, f"{name} stays on the canvas")
            self.assertEqual(len(eyes), 2, name)
            self.assertLess(eyes[0][0], eyes[1][0], f"{name}: the first eye is the left one")

    def test_a_grok_bot_shape_is_drawn_with_its_own_outline_and_eyes(self):
        profile = avatar.avatar_profile("grok:Builder", None, {"shape": "house", "color": "brown"})
        self.assertEqual((profile["shape"], profile["hex"], profile["tilt"]), ("house", "#936439", 0.0))
        self.assertEqual((profile["top"], profile["bottom"]), avatar.mark_extent("house"))
        svg = avatar.face_svg(*[0, 0], seed="grok:Builder", avatar={"shape": "house", "color": "brown"},
                              pitch=avatar.GROK_STILL[0], yaw=avatar.GROK_STILL[1], roll=avatar.GROK_STILL[2])
        self.assertEqual(len(eye_paths(svg)), 2, "two eyes, flat like Grok Bot's")
        self.assertNotIn("stroke=", svg, "no shadow, no outline")

    def test_a_grok_bot_mark_blinks_and_follows_like_the_other_faces(self):
        shape = {"shape": "sparkle", "color": "orange"}
        rest = avatar.face_svg(seed="grok:Admin", avatar=shape)
        self.assertNotEqual(avatar.face_svg(dx=4, seed="grok:Admin", avatar=shape), rest)
        self.assertNotEqual(avatar.face_svg(scale=0.1, seed="grok:Admin", avatar=shape), rest)
        self.assertIn('stroke-width="2.6"', avatar.face_svg(seed="grok:Admin", avatar=shape, muted=True),
                      "a muted mark gets the cross too")
        self.assertNotIn('stroke-width="2.6"', rest)

    def test_the_blob_has_grok_bots_two_pill_eyes_on_its_own_outline(self):
        blob = {"shape": "blob", "color": "black"}
        svg = avatar.face_svg(seed="grok:General", avatar=blob)
        self.assertEqual(len(eye_paths(svg)), 2, "two flat light eyes on the black ball, no highlights")
        self.assertNotIn(" A", svg, "no crescent any more")
        self.assertEqual(avatar.avatar_profile("grok:General", None, blob)["top"], avatar.GROK_BLOB[48])
        self.assertNotEqual(avatar.face_svg(seed="grok:General", avatar=blob, scale=0.0), svg, "it blinks")
        self.assertNotEqual(avatar.face_svg(seed="grok:General", avatar=blob, happy=1.0), svg, "it smiles")
        self.assertNotEqual(avatar.face_svg(seed="grok:General", avatar=blob, dx=-4), svg, "it looks around")

    def test_openbot_faces_are_untouched(self):
        for seed in (f"seed-{i}" for i in range(40)):
            profile = avatar.avatar_profile(seed, None)
            self.assertFalse(profile["grok"], "a shared shape name is not a Grok Bot mark")
            self.assertEqual(len(eye_paths(avatar.face_svg(seed=seed))), 2, seed)
        for seed in ("a", "b", "robo"):
            self.assertIn(avatar.avatar_profile(seed, None)["shape"], avatar.SUPPORTED_SHAPES)
            self.assertIn(avatar.avatar_profile(seed, 215)["shape"], avatar.SUPPORTED_SHAPES)


class GrokAvatarFallback(unittest.TestCase):
    """Should keep the Grok Bot face right when Grok Bot cannot be asked: widget.json, then the last answer."""

    def pick(self, live, cached=None, config=None):
        from unittest import mock
        with mock.patch.object(grokbot, "widget_config", return_value=config or {}):
            return grokbot.pick_avatar(live, "General", cached)

    def test_what_grok_bot_says_now_wins(self):
        self.assertEqual(self.pick({"shape": "blob", "color": "black"},
                                   cached={"General": {"shape": "hex"}},
                                   config={"grokbot_avatars": {"General": {"shape": "cloud"}}}),
                         {"shape": "blob", "color": "black"})

    def test_without_an_answer_widget_json_names_the_face(self):
        self.assertEqual(self.pick(None, cached={"General": {"shape": "hex"}},
                                   config={"grokbot_avatars": {"general": {"shape": "blob", "color": "black"}}}),
                         {"shape": "blob", "color": "black"})

    def test_then_the_last_answer_by_name(self):
        self.assertEqual(self.pick(None, cached={"General": {"shape": "blob", "color": "black"}}),
                         {"shape": "blob", "color": "black"})

    def test_nothing_known_keeps_the_seed_face_and_junk_is_ignored(self):
        self.assertIsNone(self.pick(None))
        self.assertIsNone(self.pick(None, cached={"General": "blob"}, config={"grokbot_avatars": ["x"]}))
        self.assertEqual(self.pick({"shape": " hex ", "color": "", "extra": 1}), {"shape": "hex"})

    def test_the_faces_keep_what_grok_bot_said_for_the_next_start(self):
        from unittest import mock

        from botwidget.qt_ui.faces import Faces
        faces = Faces.__new__(Faces)
        faces.faces, faces.grok_avatars = {}, {}
        faces.live_avatar = {"shape": "blob", "color": "black"}
        saved = []
        faces._save = lambda: saved.append(dict(faces.grok_avatars))
        with mock.patch.object(grokbot, "widget_config", return_value={}):
            faces._take_grok_avatar()
            self.assertEqual(faces.avatar, {"shape": "blob", "color": "black"})
            self.assertEqual(saved, [{"General": {"shape": "blob", "color": "black"}}])
            faces.live_avatar = None  # no route this time: the face keeps the last answer
            faces._take_grok_avatar()
        self.assertEqual(faces.avatar, {"shape": "blob", "color": "black"})
        self.assertEqual(len(saved), 1, "nothing new to save")

    def test_semicircle_hangs_under_the_top_middle(self):
        """Should put every face on the lower half of the circle, under the top edge."""
        from botwidget.qt_ui.faces import Faces
        faces = Faces.__new__(Faces)
        faces.faces = {"a": None, "b": None, "c": None}
        faces._hotspot = lambda: (800.0, 0.0)
        pos = faces._semicircle_positions()
        self.assertEqual(set(pos), {"a", "b", "c"})
        for sx, sy in pos.values():
            self.assertGreater(sy, 0)
            self.assertLessEqual((sx - 800) ** 2 + sy ** 2, 120 ** 2 + 1)

    def test_the_pointer_opens_the_arc_from_the_top_middle(self):
        """Should open just under the top edge, not below the shallow catch strip."""
        from botwidget.qt_ui.faces import Faces
        faces = Faces.__new__(Faces)
        faces._hotspot = lambda: (800.0, 0.0)
        self.assertTrue(faces._pointer_over_arc(800, 60))
        self.assertFalse(faces._pointer_over_arc(800, 80))
        self.assertFalse(faces._pointer_over_arc(800, 150))
        self.assertFalse(faces._pointer_over_arc(800, 400))
        self.assertFalse(faces._in_hotspot(800, 150))

    def test_the_top_catch_is_a_quarter_of_the_old_area(self):
        """Stefan's half circle: a 200x70 strip on the top edge, not the old 560x200 one."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication, QWidget
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        from botwidget.qt_ui.faces import ARC_CATCH_X, ARC_CATCH_Y, Faces
        self.assertEqual((ARC_CATCH_X, ARC_CATCH_Y), (100, 70), "plain constants, not derived from the radius")
        app = QApplication.instance() or QApplication([])
        faces = Faces.__new__(Faces)
        faces._hotspot = lambda: (800.0, 0.0)
        faces._catcher = QWidget()
        faces._place_catcher()
        geo = faces._catcher.geometry()
        self.assertEqual((geo.width(), geo.height()), (200, 70))
        self.assertEqual((geo.x(), geo.y()), (700, 0))
        self.assertIsNotNone(app)
        self.assertTrue(faces._pointer_over_arc(800 + 99, 69), "the near corner still catches")
        self.assertFalse(faces._pointer_over_arc(800 + 101, 50), "2px wider than the catch")
        self.assertFalse(faces._pointer_over_arc(800, 71), "2px deeper than the catch")
        self.assertFalse(faces._pointer_over_arc(800 + 200, 150))

    def test_a_bot_of_the_arc_let_go_inside_the_arc_glides_back_to_its_slot(self):
        """Dragging a hidden bot around inside the arc and letting go: it snaps back like a drag-in does."""
        from unittest import mock
        from botwidget.qt_ui import faces as faces_module
        from botwidget.qt_ui.faces import ARC_MOVE_S, Faces

        class Timer:
            active = False
            def start(self): self.active = True
            def stop(self): self.active = False

        class Guest:
            agent_id, _arc_guest = "g", True
            def __init__(self): self.at, self.seen = (790, 30), []
            def x(self): return self.at[0]
            def y(self): return self.at[1]
            def width(self): return 48
            def height(self): return 48
            def _set_semicircle(self, semicircle): self.seen.append((semicircle["g"]["x"], semicircle["g"]["y"]))

        faces = Faces.__new__(Faces)
        guest = Guest()
        faces.faces, faces._arc_guests = {"a": None, "b": None}, {"g": guest}
        faces._hotspot = lambda: (800.0, 0.0)
        faces._semicircle_phase, faces._semicircle_timer = "visible", Timer()
        faces._semicircle = {"g": {"x": 700.0, "y": 70.0, "slot_x": 700.0, "slot_y": 70.0, "visible": True,
                                   "rank": None, "size": 48}}
        faces._emit_semicircle = lambda: guest._set_semicircle(faces._semicircle)
        self.assertTrue(faces.drop_arc(guest), "the drop is handled: the bot does not stay where it was let go")
        self.assertTrue(faces._semicircle_timer.active)
        self.assertEqual(guest.seen[-1], (814.0, 54.0), "it starts where it was let go")
        start = time.monotonic()
        with mock.patch.object(faces_module.time, "monotonic", return_value=start + ARC_MOVE_S / 2):
            faces._semicircle_tick()
        mid = guest.seen[-1]
        self.assertTrue(700 < mid[0] < 814, "on its way, not a jump")
        with mock.patch.object(faces_module.time, "monotonic", return_value=start + ARC_MOVE_S + 0.01):
            faces._semicircle_tick()
            self.assertEqual(guest.seen[-1], (700.0, 70.0), "home in its slot")
            faces._semicircle_tick()
        self.assertFalse(faces._semicircle_timer.active, "nothing left to move")

    def test_arc_bots_leave_the_centre_one_at_a_time_and_return_last_first(self):
        """Should hold later bots until the one before them has started, and reverse that on the way back."""
        from botwidget.qt_ui.faces import ARC_MOVE_S, ARC_STEP_S, arc_drop, arc_progress
        self.assertEqual(arc_drop(True, False, 2), "off")
        self.assertEqual(arc_drop(True, False, 1), "snap")
        self.assertEqual(arc_drop(False, True, 1), "on")
        self.assertEqual(arc_drop(False, False, 2), "out")
        from botwidget.qt_ui.faces import arc_drag_size
        self.assertEqual(arc_drag_size(True, False, 2, 68), 48)
        self.assertEqual(arc_drag_size(False, False, 2, 68), 68)
        self.assertEqual(arc_drag_size(True, False, 1, 68), 68, "the last face stays full")
        self.assertEqual(arc_progress(0, 0), 0.0)
        self.assertGreater(arc_progress(ARC_MOVE_S * 0.5, 0), 0)
        self.assertEqual(arc_progress(ARC_STEP_S * 0.5, 1), 0.0)
        self.assertEqual(arc_progress(ARC_STEP_S + ARC_MOVE_S, 1), 1.0)
        # The way back hands rank 0 to the last arrival, so that one moves first.
        self.assertEqual(arc_progress(0.01, 0) > 0, True)
        self.assertEqual(arc_progress(0.01, 2), 0.0)


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

    def test_the_blur_leaves_the_margin_clear(self):
        """Should keep the area outside the shadow transparent, not black."""
        from PySide6.QtGui import QColor, QImage, QPixmap
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from botwidget.qt_ui.render import blurred
        QApplication.instance() or QApplication([])
        image = QImage(24, 24, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        image.setPixelColor(12, 12, QColor(0, 0, 0, 90))
        out = blurred(QPixmap.fromImage(image), 2).toImage()
        self.assertEqual(out.pixelColor(0, 0).alpha(), 0)

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

    def test_bubble_height_cap_is_four_face_heights_plus_chrome(self):
        from botwidget.avatar import AVATAR_SIZE
        from botwidget.theme import PAD_SVG, TAIL_ROOM
        self.assertEqual(bubble.bubble_height_cap(AVATAR_SIZE), PAD_SVG + TAIL_ROOM + 4 * AVATAR_SIZE + 16)
        self.assertEqual(bubble.bubble_height_cap(40), PAD_SVG + TAIL_ROOM + 4 * AVATAR_SIZE + 16)
        self.assertEqual(bubble.bubble_height_cap(120), PAD_SVG + TAIL_ROOM + 496)
        self.assertLess(bubble.bubble_height_cap(AVATAR_SIZE), int(1080 * 0.5))

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

    def test_a_grok_blob_has_eyes_and_no_mouth_unless_muted(self):
        from botwidget.avatar import face_svg
        ball = face_svg(seed="General", avatar={"shape": "blob", "color": "black"})
        self.assertEqual(len(eye_paths(ball)), 2, "Grok Bot's two eyes")
        self.assertNotIn('stroke-width="2.6"', ball, "no cross for a mouth")
        self.assertEqual(face_svg(seed="x").count(" A"), 0, "no crescent on other faces")
        self.assertEqual(len(eye_paths(face_svg(seed="x"))), 2, "others keep two eyes")

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

    def test_still_only_when_nothing_is_happening(self):
        self.assertEqual(animation.frame_ms(held=False, moving=False, pointer_near=False), animation.STILL_MS)
        self.assertGreaterEqual(animation.STILL_MS, 100, "ten frames a second at most while it holds still")

    def test_a_playing_clip_is_calm_not_fast(self):
        self.assertEqual(animation.frame_ms(held=False, moving=True, pointer_near=False, playing=True), animation.IDLE_MS)
        self.assertEqual(animation.frame_ms(held=False, moving=False, pointer_near=False, playing=True), animation.IDLE_MS)
        self.assertEqual(animation.frame_ms(held=False, moving=True, pointer_near=True, playing=True), animation.BUSY_MS)

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

    def test_far_away_it_goes_back_to_grok_bots_still_pose(self):
        from botwidget.motion import STILL
        target = self.aimed((900, 900))
        self.assertEqual((target["dx"], target["dy"]), (0.0, 0.0))
        self.assertEqual((target["pitch"], target["yaw"], target["roll"]), STILL)
        self.assertEqual(target["zoom"], 1.0, "no breathing")

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
            # Back to the still rate once the face has settled: idle, it only waits for its next blink.
            for _ in range(400):
                window._last_tick -= 0.03
                window._animate()
                if window._anim_timer.interval() == animation.STILL_MS:
                    break
            self.assertEqual(window._anim_timer.interval(), animation.STILL_MS)
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
                            ("openbot_installed", lambda: True), ("gbot_installed", lambda: True),
                            # The local API of OpenBot is on, as for a bot that works: whether it is on
                            # this computer must not add a note that changes the bubble's size.
                            ("automation_ready", lambda: True)):
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
        self.window._seeded = True
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

    def test_an_open_wait_does_not_hide_a_new_message_behind_the_cloud(self):
        import time
        from botwidget.bubble import reading_seconds
        self.window._seeded = True
        chat = {"messages": self.MESSAGES, "activity": "", "waiting": "Waiting: build"}
        self.window._sync_bubble(chat)
        bubble = self.window.bubble
        self.assertNotEqual(bubble.kind, "think")
        self.assertEqual(self.window._motion_mood(), "thinking")
        bubble._tick()
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
        self.window._seeded = True
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

    def load_older(self):
        self.window.bubble._load_older()
        self.finish_growth()

    def click_at(self, x, y):
        from PySide6.QtCore import Qt
        self.send_mouse("press", x, y, Qt.LeftButton, Qt.LeftButton)
        self.send_mouse("release", x, y, Qt.NoButton, Qt.LeftButton)

    def test_a_click_neither_selects_nor_closes(self):
        self.hover()
        self.click(0)
        self.assertFalse(self.window.bubble._doc.textCursor().hasSelection())
        self.assertTrue(self.window.bubble.isVisible())

    def test_dragging_selects_with_the_text_cursor_and_does_not_copy(self):
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
        self.assertNotEqual(self.clipboard(), selected.replace("\u2029", "\n"), "selecting leaves the copying to you")
        self.assertFalse(bubble._notice.isVisibleTo(bubble))

    def test_up_and_down_walk_through_earlier_prompts_and_back_to_the_draft(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        self.hover()
        entry = self.window.bubble._entry
        entry.history = lambda: ["een", "twee", "drie"]

        def press(key):
            entry.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))

        entry.setText("concept")
        press(Qt.Key_Up)
        self.assertEqual(entry.text(), "drie")
        press(Qt.Key_Up)
        self.assertEqual(entry.text(), "twee")
        press(Qt.Key_Down)
        self.assertEqual(entry.text(), "drie")
        press(Qt.Key_Down)
        self.assertEqual(entry.text(), "concept", "past the newest prompt is the draft again")
        press(Qt.Key_Up)
        press(Qt.Key_Up)
        press(Qt.Key_Up)
        press(Qt.Key_Up)
        self.assertEqual(entry.text(), "een", "the oldest stays")

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
        self.assertEqual(self.window.bubble.kind, "think")
        self.assertFalse(self.window.bubble._input)
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

    def test_asking_shows_dots_at_once_and_hover_brings_the_thought_back(self):
        """Should open a dots cloud before the bot is thinking, close it, and expand it on hover."""
        import time
        from botwidget.bubble import reading_seconds
        self.window._pump_outbox = lambda: None
        self.window._seeded = True
        self.window.on_user_message("Hallo")
        bubble = self.window.bubble
        self.assertEqual(bubble.kind, "think")
        self.assertFalse(bubble._input)
        self.assertNotIn("reading", bubble.full_text)
        # The send already finished and the bot is not thinking yet: the cloud stays.
        self.window._outbox.items.clear()
        self.window._sending = False
        self.window._asked = True
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": ""})
        self.assertEqual(bubble.kind, "think")
        # A pause while the question is still the latest line keeps the cloud.
        asked = self.MESSAGES + [{"role": "user", "text": "Hallo"}]
        self.window._sync_bubble({"messages": asked, "activity": "reading"})
        self.window._sync_bubble({"messages": asked, "activity": ""})
        self.assertEqual(bubble.kind, "think")
        self.window._sync_bubble({"messages": asked + [{"role": "bot", "text": "Klaar."}], "activity": ""})
        self.assertNotEqual(bubble.kind, "think")
        bubble.changed = time.monotonic() - reading_seconds(bubble.full_text) - 1
        bubble._tick()
        self.assertEqual(bubble.kind, "")
        self.window._pointer_on_head = lambda: True
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": "reading files"}, force=True)
        self.assertIn("reading files", bubble.full_text)
        self.assertTrue(bubble._input)
        self.window._pointer_on_head = lambda: False
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": "reading files"}, force=True)
        self.assertNotIn("reading files", bubble.full_text)
        self.assertFalse(bubble._input)
        self.assertEqual(bubble.kind, "think")
        bubble._tick()
        self.assertEqual(bubble.kind, "think", "leaving starts the wait again")
        bubble.changed = time.monotonic() - reading_seconds(bubble.full_text) - 1
        bubble._tick()
        self.assertEqual(bubble.kind, "")
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": "reading files"})
        self.assertEqual(bubble.kind, "", "a new thought does not bring the chat bubble")

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

    def test_clicking_into_the_field_gives_it_the_keys_but_a_bubble_that_opens_by_itself_takes_none(self):
        """X: the window manager hands the keyboard only to a window that accepts focus (WM_HINTS input), and
        Qt refuses to even ask for one that does not. A bubble that opens by itself must not take the keys."""
        from PySide6.QtCore import QPoint, Qt, qInstallMessageHandler
        from PySide6.QtTest import QTest
        said = []
        old = qInstallMessageHandler(lambda _kind, _context, text: said.append(text))
        self.addCleanup(qInstallMessageHandler, old)
        bubble = self.window.bubble
        del bubble.focus_entry  # the real one: this test is about focus
        self.hover()
        self.assertTrue(bubble.isVisible())
        self.assertTrue(bubble.testAttribute(Qt.WA_ShowWithoutActivating), "opening by itself takes no focus")
        entry = bubble._entry
        QTest.mouseClick(entry.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(10, 5))
        self.click_face()
        self.assertFalse(bubble.windowFlags() & Qt.WindowDoesNotAcceptFocus,
                         "a bubble that never accepts focus can never be typed in")
        self.assertFalse([text for text in said if "DoesNotAcceptFocus" in text])

    def test_a_left_click_on_the_face_puts_the_cursor_in_the_field_once_the_field_shows(self):
        """The field only shows once the bubble has grown a bit: asking for the cursor before that must not
        get lost, or the keys go nowhere."""
        bubble = self.window.bubble
        del bubble.focus_entry  # the real one: this test is about focus
        self.assertFalse(bubble.isVisible())
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        self.click_face()
        self.assertTrue(bubble.isVisible())
        self.finish_growth()
        self.assertTrue(bubble._entry.isVisible())
        self.assertIs(bubble.focusWidget(), bubble._entry)

    def test_clicking_the_face_from_a_page_of_the_menu_opens_the_chat_again(self):
        bubble = self.open_settings()
        self.assertIsNotNone(self.window._menu_page)
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        self.window.open_input()  # what a click on the face does
        self.finish_growth()
        self.assertIsNone(self.window._menu_page)
        self.assertIn("Ja.", bubble.full_text)
        self.assertNotIn("Settings", bubble.full_text)

    def test_clicking_the_face_from_the_command_list_opens_the_chat_again(self):
        self.window.open_commands()
        bubble = self.window.bubble
        self.assertTrue(bubble._list_only)
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        self.click_face()
        self.finish_growth()
        self.assertFalse(bubble._list_only)
        self.assertIn("Ja.", bubble.full_text)

    def test_a_conversation_that_has_not_started_greets_you_with_the_field(self):
        self.MESSAGES = []
        self.hover()
        self.assertTrue(self.window.bubble.isVisible())
        self.assertIn("Ask me anything", self.window.bubble.full_text)
        self.assertTrue(self.window.bubble._entry.isVisibleTo(self.window.bubble))

    def test_a_dragged_face_shrinks_smoothly_around_the_pointer(self):
        """Into the arc the face gets small over a moment, not in one jump, and stays centred on the pointer."""
        window = self.window
        window._drag_center = (window.x() + 34.0, window.y() + 34.0)
        window._resize_to(48)
        self.assertEqual(window.width(), 68, "no jump on the first move")
        # The animation is stepped by hand: waiting for real time made the test flaky on a busy machine.
        anim = window._size_anim
        anim.setCurrentTime(self.face.DRAG_RESIZE_MS // 2)
        self.assertTrue(48 < window.width() < 68, "half way")
        anim.setCurrentTime(self.face.DRAG_RESIZE_MS)
        self.assertEqual(window.width(), 48)
        self.assertEqual((window.x() + 24, window.y() + 24), tuple(int(v) for v in window._drag_center))
        window._resize_to(68)
        window._finish_resize()
        self.assertEqual(window.width(), 68, "letting go settles at once on the size it was heading for")

    def test_the_arc_does_not_ask_hermes_on_every_drag(self):
        """`hermes --version` costs 0.2 s; asked once, the answer is kept."""
        from unittest import mock
        from botwidget import hermesbot
        old = hermesbot._installed_cache
        self.addCleanup(setattr, hermesbot, "_installed_cache", old)
        hermesbot._installed_cache = None
        with mock.patch.object(hermesbot.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            self.assertTrue(hermesbot.is_hermes_installed())
            self.assertTrue(hermesbot.is_hermes_installed())
        self.assertEqual(run.call_count, 1)

    def test_the_field_gets_focus_only_when_the_pointer_stays(self):
        focus = []
        old_hover = self.face.FOCUS_ON_HOVER
        self.addCleanup(setattr, self.face, "FOCUS_ON_HOVER", old_hover)
        self.face.FOCUS_ON_HOVER = True
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

    def test_where_hover_must_not_take_focus_resting_on_the_face_does_not_activate_the_bubble(self):
        """GNOME shows "Bot Widget is ready" for a window that asks for focus without a click."""
        focus = []
        old_hover = self.face.FOCUS_ON_HOVER
        self.addCleanup(setattr, self.face, "FOCUS_ON_HOVER", old_hover)
        self.face.FOCUS_ON_HOVER = False
        self.window.bubble.focus_entry = lambda: focus.append(1)
        self.hover()
        self.window._hover_since -= 1
        self.window._animate()
        self.assertEqual(focus, [], "only a click puts the cursor in the field")
        self.click_face()
        self.assertEqual(focus, [1])

    def test_every_show_of_the_bubble_marks_it_before_it_is_mapped(self):
        """GNOME says "Bot Widget is ready" for a window that is mapped without skip-taskbar."""
        from unittest import mock
        bubble = self.window.bubble
        with mock.patch("botwidget.qt_ui.bubble_window.before_show") as marked:
            self.hover()
            self.assertTrue(bubble.isVisible())
            self.assertEqual(marked.call_count, 1)
            bubble.place("")
            bubble.hide()
            bubble.show()
            self.assertEqual(marked.call_count, 2, "a second map needs it again")
            bubble.show()
            self.assertEqual(marked.call_count, 2, "already shown: nothing to mark")

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

    def test_an_empty_pinned_field_closes_when_the_pointer_leaves(self):
        self.hover()
        self.window.pin()
        bubble = self.window.bubble
        bubble._tick()
        self.where["at"] = (5000, 5000)
        bubble._tick()
        self.assertEqual(bubble.kind, "")
        self.assertFalse(self.window.pinned)

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
        self.assertTrue(self.window.bubble._has_older)
        self.assertNotEqual(self.window.bubble._geom[0][0]["role"], "more", "the arrow takes no room until asked for")

    def test_scrolling_up_adds_the_message_before_and_the_hint_goes_when_there_is_no_more(self):
        self.hover()
        self.window.show_older()
        text = self.window.bubble.full_text
        self.assertIn("Klaar?", text)
        self.assertIn("Zal ik pushen?", text)
        self.assertNotEqual(self.window.bubble._geom[0][0]["role"], "more", "nothing more to scroll to")
        self.window.show_older()
        self.assertEqual(self.window._depth, 2, "nothing older to load")

    def test_a_bubble_opens_at_its_full_size_fading_in_and_sliding_out_from_the_face(self):
        import time
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        self.window._animate()
        bubble = self.window.bubble
        self.assertIsNotNone(bubble._growth)
        full = (bubble.width(), bubble.height())
        self.assertLess(bubble.windowOpacity(), 1.0, "it fades in")
        bubble._growth_step(0.0)
        near_face = (bubble.x(), bubble.y())
        self.assertEqual((bubble.width(), bubble.height()), full, "the text does not wrap again while it opens")
        self.assertTrue(bubble._entry.isVisibleTo(bubble), "the field is there from the first frame")
        deadline = time.monotonic() + 3
        while bubble._growth is not None and time.monotonic() < deadline:
            self.app.processEvents()
        self.assertIsNone(bubble._growth)
        self.assertEqual((bubble.width(), bubble.height()), full)
        self.assertNotEqual((bubble.x(), bubble.y()), near_face, "it came from the face")
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

    def wheel_up(self, bubble, phase=None, delta=120):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtWidgets import QApplication
        QApplication.sendEvent(bubble._scroll.viewport(), QWheelEvent(
            QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
            Qt.NoScrollPhase if phase is None else phase, False))

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

    def test_a_copied_notice_stays_on_its_message_when_an_older_one_loads_above(self):
        self.hover()
        bubble = self.window.bubble
        self.click(0)
        self.window.show_older()
        self.finish_growth()
        from botwidget.bubble import panel_rects
        top, height = panel_rects(bubble._geom[0])[-1]
        top -= bubble._scroll.verticalScrollBar().value()
        view = bubble._scroll.viewport().height()
        self.assertEqual((bubble._notice.y(), bubble._notice.height()), (top, min(view, top + height) - top))

    def test_a_new_message_takes_the_notice_away(self):
        self.hover()
        self.click(0)
        self.assertTrue(self.window.bubble._notice.isVisible())
        self.window._sync_bubble({"messages": self.MESSAGES + [{"role": "bot", "text": "Nog iets."}], "activity": ""})
        self.assertFalse(self.window.bubble._notice.isVisible())

    @unittest.skipIf(sys.platform == "win32", "Cmd+Backspace is a Mac key; Windows Qt deletes a word on Ctrl+Backspace first")
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
        self.window._pointer_on_head = lambda: True
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": "reading"}, force=True)
        self.finish_growth()
        bubble = self.window.bubble
        self.assertEqual(bubble.kind, "think")
        self.assertTrue(bubble._entry.isVisibleTo(bubble))
        self.assertEqual(bubble._entry.placeholderText(), "Queue a message…")

    def test_a_thinking_cloud_shrinks_to_its_dots_when_the_pointer_leaves(self):
        """Busy bot, cloud open by itself: point at it, then leave (also straight onto another app)."""
        import time
        from unittest import mock
        from botwidget.bubble import reading_seconds
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        active = mock.patch.object(QGuiApplication, "applicationState", return_value=Qt.ApplicationActive)
        active.start()
        self.addCleanup(active.stop)
        for leave_onto_other_app in (False, True):
            self.start_working()
            self.window._working = True
            bubble = self.window.bubble
            self.assertEqual(bubble.kind, "think")
            bubble._was_near = False
            self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
            bubble._tick()
            self.assertEqual(bubble.kind, "think", "the pointer is on it")
            self.window._pointer_on_head = lambda: False
            if leave_onto_other_app:
                with mock.patch("botwidget.qt_ui.face.global_pointer", return_value=False), \
                        mock.patch.object(type(self.window), "underMouse", return_value=True), \
                        mock.patch.object(type(bubble), "underMouse", return_value=True), \
                        mock.patch("botwidget.qt_ui.bubble_window.pointer_window", return_value=0):
                    bubble._tick()
            else:
                self.where["at"] = (5000, 5000)
                bubble._tick()
            self.assertEqual(bubble.kind, "think", "back to the dots")
            self.assertFalse(bubble._input)
            self.assertNotIn("reading", bubble.full_text)
            self.where["at"] = (5000, 5000)
            bubble.changed = time.monotonic() - reading_seconds(bubble.full_text) - 1
            bubble._tick()
            self.assertEqual(bubble.kind, "", "and they go after a while")
            self.window._think_quiet = False

    def start_working(self):
        self.state = {"activity": "reading"}
        self.face.latest_chat = lambda thread_id, limit=8: {"messages": self.MESSAGES, "activity": self.state["activity"]}
        self.window._pump_outbox = lambda: None
        self.window._pointer_on_head = lambda: True
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

    def settings_state(self):
        return {"sound": True, "quiet_hours": False, "always_on_top": True, "all_desktops": False, "login": False,
                "check_updates": True, "auto_update": False, "channel": "local", "version": "0.2.0",
                "can_pick_desktops": True, "can_install_updates": False, "hotkey": "", "switch_label": None,
                "update": "", "staged_update": "", "bots": []}

    def open_settings(self):
        from botwidget import menu_pages
        self.window.faces = type("Faces", (), {"menu_state": lambda _self: self.settings_state(),
                                               "menu_command": lambda _self, command, page: page,
                                               "close_bubbles_except": lambda _self, _id: None,
                                               "hold_arc": lambda _self: None,
                                               "raise_bubbles": lambda _self: None})()
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

    def test_the_arrow_on_a_page_leads_back_to_the_list_of_commands_only(self):
        bubble = self.open_settings()
        self.assertEqual(bubble._geom[0][0]["back"], "page/commands")
        bubble.command.emit("page/commands")
        self.finish_growth()
        self.assertIsNone(self.window._menu_page)
        self.assertTrue(bubble._list_only, "the command list on its own, as a first right-click")
        self.assertTrue(bubble._slash.isVisibleTo(bubble))
        self.assertNotIn("Ja.", bubble.full_text, "no conversation")

    def test_a_page_has_the_arrow_up_instead_of_a_menu_link_and_it_goes_back(self):
        bubble = self.open_settings()
        self.assertNotIn("Menu", bubble.full_text)
        self.assertEqual(bubble._geom[0][0]["role"], "more")
        sent = []
        bubble.command.connect(sent.append)
        _x, y = self.message_point(0, down=4)
        self.click_at(bubble._shown_w(bubble._geom[1]) // 2, y)
        self.assertEqual(sent, ["page/commands"])

    def test_pulling_the_line_of_a_page_far_enough_goes_back_too(self):
        bubble = self.open_settings()
        sent = []
        bubble.command.connect(sent.append)
        self.wheel_up(bubble)
        self.assertEqual(sent, [], "one notch only pulls the line")
        self.assertGreater(bubble._pull_px, 0)
        self.wheel_up(bubble)
        self.wheel_up(bubble)
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

    def test_no_timer_closes_a_bubble_the_pointer_is_on_and_leaving_the_margin_closes_it_at_once(self):
        from unittest import mock as _mock
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtGui import QGuiApplication as _App
        active = _mock.patch.object(_App, "applicationState", return_value=_Qt.ApplicationActive)
        active.start()
        self.addCleanup(active.stop)
        from unittest import mock
        self.hover()
        bubble = self.window.bubble
        later = time.monotonic() + 600
        near = (bubble.frameGeometry().right() + 10, bubble.frameGeometry().center().y())
        with mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=later):
            self.where["at"] = near
            bubble._tick()
            self.assertTrue(bubble.isVisible(), "just outside, in the margin: still on it, however long")
            self.where["at"] = (bubble.frameGeometry().right() + 200, bubble.frameGeometry().center().y())
            bubble._tick()
        self.assertFalse(bubble.isVisible(), "out of the margin: closed at once")

    def test_a_right_click_menu_closes_the_moment_the_pointer_leaves_not_seconds_later(self):
        from unittest import mock as _mock
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtGui import QGuiApplication as _App
        active = _mock.patch.object(_App, "applicationState", return_value=_Qt.ApplicationActive)
        active.start()
        self.addCleanup(active.stop)
        self.stub_faces()
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        self.window.open_command_menu()
        bubble = self.window.bubble
        bubble._tick()
        self.assertTrue(bubble.isVisible())
        self.where["at"] = (5000, 5000)
        bubble._tick()
        self.assertFalse(bubble.isVisible(), "no keep-open timer from the moment it opened")

    def back_arrow_leaves_the_pointer_outside(self):
        """Settings open, the pointer low on the page (scrolling up past the top goes back too); the back arrow
        shrinks the bubble to the list."""
        from PySide6.QtCore import QPoint
        bubble = self.open_settings()
        page = bubble.frameGeometry()
        self.where["at"] = (page.center().x(), page.bottom() - 30)
        bubble._tick()
        bubble.command.emit("page/commands")
        self.finish_growth()
        self.assertFalse(bubble.card().contains(QPoint(*self.where["at"])), "the list is smaller")
        return bubble, page

    def test_the_area_of_the_bigger_bubble_stays_hover_area_after_the_back_arrow(self):
        from unittest import mock
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        with mock.patch.object(QGuiApplication, "applicationState", return_value=Qt.ApplicationActive):
            bubble, page = self.back_arrow_leaves_the_pointer_outside()
            bubble._tick()
            self.assertTrue(bubble.isVisible(), "still in the area the settings page covered")
            self.where["at"] = (page.center().x(), page.bottom() - 10)
            bubble._tick()
            self.assertTrue(bubble.isVisible(), "moving inside that area")
            self.where["at"] = (page.right() + 200, page.top() + 60)
            bubble._tick()
            self.assertFalse(bubble.isVisible(), "out of it: closed at once, the pointer had been on the bubble")

    def test_on_xwayland_the_window_keeps_the_page_area_so_x_names_the_bubble_until_the_pointer_leaves(self):
        """XWayland only knows the pointer over X windows: after the back arrow the bubble's own window keeps
        the area of the page, see-through around the smaller card, so the X server names the bubble there."""
        from unittest import mock
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QGuiApplication
        window = self.window
        window.show()
        with self.x_pointer(), \
                mock.patch.object(QGuiApplication, "applicationState", return_value=Qt.ApplicationInactive):
            bubble, page = self.back_arrow_leaves_the_pointer_outside()
            self.assertTrue(bubble.frameGeometry().contains(page), "the window still covers the page")
            self.assertTrue(bubble.frameGeometry().contains(bubble.card()))
            from botwidget.qt_ui import bubble_window as bubble_module
            self.assertEqual(bubble_module.pointer_window(), native_id(bubble), "X names the bubble there")
            bubble._tick()
            self.assertTrue(bubble.isVisible(), "the pointer is on the bubble's window")
            self.where["at"] = (page.right() + 200, page.top() + 60)
            bubble._tick()
            self.assertFalse(bubble.isVisible(), "left it: closed at once")
            self.assertIsNone(bubble.holding_area(), "and the window holds nothing any more")

    def test_nothing_that_happens_by_itself_closes_a_bubble_the_pointer_is_on(self):
        """Focus taken by another window, the time to read it, a poll with an empty chat: none of them may take
        a bubble the pointer is still on. Things the user does (Escape, another face) still close it at once."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from unittest import mock
        window = self.window
        window.show()
        bubble = window.bubble
        with mock.patch.object(QGuiApplication, "applicationState", return_value=Qt.ApplicationActive):
            self.hover()
            window.open_input()
            self.finish_growth()
            centre = bubble.frameGeometry().center()
            self.where["at"] = (centre.x(), centre.y())
            bubble._had_focus = True  # the field had the focus; now another window took it
            with mock.patch("botwidget.qt_ui.bubble_window.QApplication.activeWindow", return_value=None):
                bubble._tick()
            self.assertTrue(bubble.isVisible(), "focus went elsewhere, the pointer did not")
            bubble.changed = 1.0  # long past the time to read it
            bubble._tick()
            self.assertTrue(bubble.isVisible())
            for reason in bubble.CLOSE_UNLESS_ENGAGED:
                self.assertFalse(bubble.close_bubble(reason), reason)
            self.assertTrue(bubble.isVisible() and bubble.consistent())
            self.assertTrue(bubble.close_bubble("unpin"), "Escape closes it, pointer or not")
            self.assertFalse(bubble.isVisible())
            self.assertEqual(bubble.state(), "closed")
            self.assertTrue(bubble.consistent())

    def test_random_use_never_breaks_the_rules_of_opening_and_closing(self):
        """Random sequences of what Stefan does (hover, leave, clicks, every menu command, the back arrow, a
        refresh, a new answer, focus elsewhere, the face in every corner and edge), with the pointer as X reports it.
        After every step:
        - the bubble's state matches its window (closed, open, yielding);
        - a bubble the pointer is engaged with is still open after anything that happens by itself;
        - a page change never takes the bubble from under the pointer: it stays engaged;
        - the window that holds a bigger bubble's area never covers the bubble;
        - a closed bubble never leaves the face unresponsive: pointing at the face opens it again."""
        import random
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QGuiApplication
        from botwidget.qt_ui import bubble_window as bubble_module
        from unittest import mock
        from botwidget.qt_ui import face as face_module
        state = dict(self.settings_state())
        state["bots"] = [{"id": f"b{i}", "name": f"Bot {i}", "source": "OpenBot", "on": True} for i in range(3)]
        state.update({"openbot": True, "automation_ready": True, "gbot": False, "grok": "not found"})
        chat = {"messages": [], "activity": ""}
        self.face.latest_chat = lambda thread_id, limit=8: chat
        window = self.window
        window.show()
        bubble = window.bubble
        window.faces = type("Faces", (), {"menu_state": lambda _self: state,
                                          "menu_command": lambda _self, command, page: page,
                                          "close_bubbles_except": lambda _self, _id: None,
                                          "hold_arc": lambda _self: None,
                                          "raise_bubbles": lambda _self: None})()
        clock = [1000.0]
        screen = QGuiApplication.primaryScreen().geometry()
        right, bottom = screen.right() - 72, screen.bottom() - 72
        spots = [(4, 4), (right, 4), (4, bottom), (right, bottom), (right // 2, 4), (4, bottom // 2),
                 (right, bottom // 2), (right // 2, bottom), (26, 62), (27, 139), (right // 2, bottom // 2)]
        answers = ["Ja.", "Dit is een lang antwoord. " * 30, "Kort.\n\n- een\n- twee\n- drie"]

        def frames(count=6, held=None):
            for _ in range(count):
                self.one_content(bubble, "on a frame")
                if held is not None:
                    self.assertTrue(bubble.isVisible() and bubble.engaged(),
                                    f"the pointer is not on the bubble while it changes, after {held[-6:]}")
                # A frame as it comes: the bubble as it is drawn now is what the pointer is on or not.
                inside = bubble.isVisible() and bubble_module.pointer_window() == native_id(bubble)
                if bubble._physics.isActive():
                    bubble._tick()
                if inside:
                    self.assertTrue(bubble.isVisible(), f"closed with the pointer in its window, after {held or ''}")
                self.window_holds(bubble, "on a frame")
                window._animate()
                clock[0] += 0.016
                if bubble._growth is not None:
                    bubble._slide.setCurrentTime(min(bubble._slide.currentTime() + 16, bubble._slide.duration()))

        def pointer():
            return QPoint(*[int(v) for v in self.where["at"]])

        def check(step, log):
            self.assertTrue(bubble.consistent(), f"state {bubble.state()} vs window, after {log[-6:]}")
            self.one_content(bubble, f"after {log[-6:]}")
            self.window_holds(bubble, f"after {log[-6:]}")

        def responsive(log):
            """Point at the face for long enough: the bubble opens."""
            self.where["at"] = (window.x() + 34, window.y() + 34)
            clock[0] += face_module.REOPEN_AFTER_S + face_module.HOVER_RETRY_S + 0.1
            frames(3)
            self.assertTrue(bubble.isVisible(), f"pointing at the face opened nothing, after {log[-6:]}")

        ops = ["hover", "on_bubble", "edge", "leave", "left_click", "right_click", "choose", "back", "refresh",
               "answer", "poll", "new_chat", "focus_elsewhere", "move_face", "wait", "escape"]
        automatic = {"poll", "answer", "new_chat", "wait", "focus_elsewhere"}
        with self.x_pointer(), mock.patch("time.monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(QGuiApplication, "applicationState", return_value=Qt.ApplicationInactive), \
                mock.patch.object(face_module, "api_get", side_effect=OSError("no network in tests"), create=True), \
                mock.patch("PySide6.QtGui.QDesktopServices.openUrl", return_value=True):
            for seed in range(10):
                rnd = random.Random(seed)
                log = []
                bubble.close_bubble("refresh")
                window.move(*rnd.choice(spots))
                window._home = (window.x(), window.y())
                for step in range(50):
                    op = rnd.choice(ops)
                    log.append(op)
                    engaged_before = bubble.isVisible() and bubble.engaged()
                    if op == "hover":
                        self.where["at"] = (window.x() + 34, window.y() + 34)
                    elif op == "on_bubble" and bubble.isVisible():
                        centre = bubble.card().center()
                        self.where["at"] = (centre.x(), centre.y())
                    elif op == "edge" and bubble.isVisible():
                        frame = bubble.card()
                        self.where["at"] = (frame.left() + 2, frame.bottom() - 2)
                    elif op == "leave":
                        self.where["at"] = (5000, 5000)
                    elif op == "left_click":
                        self.where["at"] = (window.x() + 34, window.y() + 34)
                        window.open_input()
                    elif op == "right_click":
                        self.where["at"] = (window.x() + 34, window.y() + 34)
                        window.open_command_menu()
                    elif op == "choose":
                        if not (bubble.isVisible() and bubble._list_only and bubble._slash.rows):
                            self.where["at"] = (window.x() + 34, window.y() + 34)  # right-click first
                            window.open_command_menu()
                            frames()
                        index = rnd.randrange(len(bubble._slash.rows))
                        command = bubble._slash.rows[index][0]
                        log[-1] = "choose " + command
                        row = bubble._slash.mapToGlobal(QPoint(bubble._slash.width() // 2,
                                                               4 + bubble._slash.ROW_H * index + 18))
                        self.where["at"] = (row.x(), row.y())
                        frames(1)
                        engaged_before = bubble.isVisible() and bubble.engaged()
                        bubble._run_command(command)
                    elif op == "back":
                        if not (bubble.isVisible() and window._menu_page is not None):
                            window.open_menu(rnd.choice(["settings", "bots", "connections"]))  # a page first
                            frames()
                        # The pointer somewhere on the page, often low on it, where the list will not be.
                        frame = bubble.card()
                        self.where["at"] = (rnd.randint(frame.left() + 10, frame.right() - 10),
                                            rnd.randint(frame.center().y(), frame.bottom() - 10))
                        frames(1)
                        engaged_before = bubble.isVisible() and bubble.engaged()
                        bubble.command.emit("page/commands")
                    elif op == "refresh":
                        window.on_user_message("/refresh")
                    elif op == "answer":
                        chat = {"messages": [{"role": "user", "text": "Vraag?"},
                                             {"role": "bot", "text": rnd.choice(answers) + f" ({step})"}],
                                "activity": ""}
                        window._sync_bubble(window._latest())
                    elif op == "poll":
                        window._sync_bubble(window._latest())
                    elif op == "new_chat":
                        chat = {"messages": [], "activity": ""}
                        window._sync_bubble(window._latest())
                    elif op == "focus_elsewhere":
                        bubble._had_focus = bubble._input
                        with mock.patch("botwidget.qt_ui.bubble_window.QApplication.activeWindow",
                                        return_value=None):
                            frames(2)
                    elif op == "move_face":
                        window.move(*rnd.choice(spots))
                        window._home = (window.x(), window.y())
                        self.where["at"] = (window.x() + 34, window.y() + 34)
                    elif op == "wait":
                        clock[0] += rnd.choice([0.5, 3.0, 30.0, 120.0])
                    elif op == "escape":
                        window.unpin()
                    op = log[-1]
                    swap = (op.startswith("choose /") and op not in ("choose /refresh", "choose /feedback")
                            or op == "back")
                    frames(held=log if swap and engaged_before else None)
                    check(step, log)
                    if op in automatic and engaged_before:
                        here = bubble.frameGeometry().contains(pointer()) \
                            or window.geometry().contains(pointer())
                        if here:
                            self.assertTrue(bubble.isVisible(), f"closed under the pointer, after {log[-6:]}")
                    if op.startswith("choose /") and op != "choose /refresh" and engaged_before \
                            and op != "choose /feedback":
                        self.assertTrue(bubble.isVisible() and bubble.engaged(),
                                        f"the page left the pointer, after {log[-6:]}")
                    if op == "back" and engaged_before:
                        self.assertTrue(bubble.isVisible() and bubble.engaged(),
                                        f"the list left the pointer, after {log[-6:]}")
                    if not bubble.isVisible() and rnd.random() < 0.4:
                        log.append("probe")
                        responsive(log)
                        check(step, log)

    def x_pointer(self):
        """XWayland as on Stefan's desktop: X says which of our windows is under the pointer (no hover margin),
        the bubble lies over its face, and a window mask lets the pointer through."""
        from unittest import mock
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication
        window = self.window

        def under_pointer():
            x, y = self.where["at"]
            point = QPoint(int(x), int(y))
            for widget in (window.bubble, window):
                if not widget.isVisible() or not widget.geometry().contains(point):
                    continue
                mask = widget.mask()
                if mask.isEmpty() or mask.contains(point - widget.pos()):
                    return native_id(widget)
            return 0

        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(QGuiApplication, "platformName", return_value="xcb"))
        stack.enter_context(mock.patch("botwidget.qt_ui.face.global_pointer", return_value=False))
        stack.enter_context(mock.patch("botwidget.qt_ui.bubble_window.pointer_window", side_effect=under_pointer))
        return stack

    def test_the_back_arrow_keeps_the_page_area_in_the_bubbles_own_window_on_every_frame(self):
        """Stefan, after the back arrow with the pointer low on the page: the bubble just disappears. A second,
        see-through window that held the page's area had to be mapped and stacked by the window manager on its own
        (late, or under another app), and until then X named no window of ours under the pointer. Now the
        bubble's own window keeps the page's area on every frame while the card shrinks inside it: X names the
        bubble there from the first frame on, and leaving that window still closes it at once."""
        from unittest import mock
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QGuiApplication
        from botwidget.qt_ui import bubble_window as bubble_module
        window = self.window
        window.show()
        with self.x_pointer(), \
                mock.patch.object(QGuiApplication, "applicationState", return_value=Qt.ApplicationInactive):
            bubble = self.open_settings()
            page = bubble.frameGeometry()
            self.where["at"] = (page.center().x(), page.bottom() - 30)
            bubble._tick()
            self.assertTrue(bubble.isVisible())
            bubble.command.emit("page/commands")
            for ms in range(0, 400, 16):
                if bubble._growth is not None:
                    bubble._slide.setCurrentTime(min(ms, bubble._slide.duration()))
                self.assertTrue(bubble.frameGeometry().contains(page), f"the window let go of the page at {ms} ms")
                self.assertTrue(bubble.frameGeometry().contains(bubble.card()), f"the card sticks out at {ms} ms")
                self.assertEqual(bubble_module.pointer_window(), native_id(bubble), f"X lost the bubble at {ms} ms")
                bubble._tick()
                self.assertTrue(bubble.isVisible(), f"closed {ms} ms after the back arrow")
            self.assertTrue(bubble._list_only)
            self.assertFalse(bubble.card().contains(QPoint(*self.where["at"])), "the card is the smaller list")
            self.where["at"] = (page.right() + 200, page.top() + 60)
            bubble._tick()
            self.assertFalse(bubble.isVisible(), "leaving the window still closes it")

    def choose_from_the_menu(self, command):
        """Right-click the face, point at the command's row and click it; the page grows in frame by frame."""
        from PySide6.QtCore import QPoint
        window, bubble = self.window, self.window.bubble
        self.where["at"] = (window.x() + 34, window.y() + 34)
        window.open_command_menu()
        self.finish_growth()
        index = [row[0] for row in bubble._slash.rows].index(command)
        row = bubble._slash.mapToGlobal(QPoint(bubble._slash.width() // 2,
                                               4 + bubble._slash.ROW_H * index + bubble._slash.ROW_H // 2))
        self.where["at"] = (row.x(), row.y())
        bubble._tick()
        menu = bubble.frameGeometry()
        bubble._run_command(command)
        frames = []
        for ms in range(0, 400, 16):
            if bubble._growth is not None:
                bubble._slide.setCurrentTime(min(ms, bubble._slide.duration()))
            bubble._tick()
            frames.append(bubble.frameGeometry())
            if not bubble.isVisible():
                break
        return menu, frames

    def one_content(self, bubble, when=""):
        """Never two contents at once: the command list on its own, or a page/chat without that list."""
        listing = bubble._slash.isVisibleTo(bubble)
        page = bubble._scroll.isVisibleTo(bubble) or bubble._entry.isVisibleTo(bubble)
        if bubble._list_only:
            self.assertFalse(page, f"the list shows with a page under it {when}")
        else:
            self.assertFalse(listing and not bubble._input, f"the old command list shows over the page {when}")

    def test_after_choosing_a_command_or_going_back_only_one_content_shows_on_every_frame(self):
        """/bots from the right-click list drew the page with the list still on top of it: the list was kept to
        keep the bubble's size, and its rows with it. Only the size carries over, never the rows."""
        from botwidget import menu_pages
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from unittest import mock
        state = dict(self.settings_state())
        state["bots"] = [{"id": f"b{i}", "name": f"Bot {i}", "source": "OpenBot", "on": True} for i in range(3)]
        state.update({"openbot": True, "automation_ready": True, "gbot": False, "grok": "not found"})
        window = self.window
        window.show()
        window.faces = type("Faces", (), {"menu_state": lambda _self: state,
                                          "menu_command": lambda _self, command, page: page,
                                          "close_bubbles_except": lambda _self, _id: None,
                                          "hold_arc": lambda _self: None,
                                          "raise_bubbles": lambda _self: None})()
        bubble = window.bubble
        window.move(26, 62)
        window._home = (26, 62)
        with self.x_pointer(), mock.patch.object(QGuiApplication, "applicationState",
                                                 return_value=Qt.ApplicationInactive), \
                mock.patch("PySide6.QtGui.QDesktopServices.openUrl", return_value=True), \
                mock.patch("botwidget.qt_ui.face.api_get", side_effect=OSError("no network in tests")):
            for command, _note in menu_pages.COMMANDS:
                with self.subTest(command=command):
                    menu, frames = self.choose_from_the_menu(command)
                    self.one_content(bubble, f"after {command}")
                    for _ in range(25):  # and on every frame of the growth
                        if bubble._growth is not None:
                            bubble._slide.setCurrentTime(min(bubble._slide.currentTime() + 16,
                                                             bubble._slide.duration()))
                        self.one_content(bubble, f"while {command} grows")
                    if window._menu_page is not None:
                        bubble.command.emit("page/commands")
                        self.assertTrue(bubble._list_only)
                        for _ in range(25):
                            if bubble._growth is not None:
                                bubble._slide.setCurrentTime(min(bubble._slide.currentTime() + 16,
                                                                 bubble._slide.duration()))
                            self.one_content(bubble, f"back from {command}")
                    bubble.close_bubble("refresh")

    def window_holds(self, bubble, when=""):
        """While a shrink is pending the window still covers the old area (and the card); else it is the card."""
        held = bubble.holding_area()
        if held is None:
            if bubble.isVisible():
                self.assertEqual(bubble.frameGeometry(), bubble.card(), f"a window bigger than its card {when}")
            return
        self.assertEqual(bubble.state(), "open", f"an area held for a bubble that is not open {when}")
        self.assertTrue(bubble.frameGeometry().contains(held), f"the window let go of the old area {when}")
        self.assertTrue(bubble.frameGeometry().contains(bubble.card()), f"the card sticks out {when}")

    def test_the_held_area_of_a_bigger_bubble_goes_once_the_pointer_is_on_the_card_or_with_a_yield(self):
        """After the back arrow the window holds the page's area. Once the pointer is on the smaller card, or the
        bubble gives way to another one or closes, the window is the card again: no see-through area is left on
        the screen that still counts as the bubble."""
        from unittest import mock
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        window = self.window
        window.show()
        with self.x_pointer(), mock.patch.object(QGuiApplication, "applicationState",
                                                 return_value=Qt.ApplicationInactive):
            bubble, page = self.back_arrow_leaves_the_pointer_outside()
            self.assertIsNotNone(bubble.holding_area())
            self.window_holds(bubble, "after the back arrow")
            centre = bubble.card().center()
            self.where["at"] = (centre.x(), centre.y())  # onto the list itself
            bubble._tick()
            self.assertTrue(bubble.isVisible())
            self.assertIsNone(bubble.holding_area(), "on the card: nothing to hold any more")
            self.assertEqual(bubble.frameGeometry(), bubble.card())
            window.open_command_menu()  # the content changes again, the pointer on it
            self.window_holds(bubble, "after a second change")
            # Again, and now the bubble gives way to another one.
            self.where["at"] = (page.center().x(), page.bottom() - 30)
            bubble2, _page = self.back_arrow_leaves_the_pointer_outside()
            self.assertIsNotNone(bubble.holding_area())
            with mock.patch.object(type(bubble), "_must_yield", return_value=True):
                bubble._tick()
            self.assertEqual(bubble.state(), "yielding")
            self.assertIsNone(bubble.holding_area(), "nothing held while yielding")
            bubble.close_bubble("refresh")
            self.assertIsNone(bubble.holding_area(), "nor once closed")

    def test_a_held_area_over_a_face_leaves_that_face_clickable(self):
        """The window that keeps a page's area must not take the clicks meant for a face under it: the face's
        spot is cut out of the window's shape (and so of its input) for as long as the area is held."""
        from unittest import mock
        from PySide6.QtCore import QPoint, QRect, Qt
        from PySide6.QtGui import QGuiApplication
        window = self.window
        window.show()
        with self.x_pointer(), mock.patch.object(QGuiApplication, "applicationState",
                                                 return_value=Qt.ApplicationInactive):
            bubble, page = self.back_arrow_leaves_the_pointer_outside()
            self.assertIsNotNone(bubble.holding_area())
            # The area held reaches over the face (as when a tall page sat beside it).
            bubble._held = bubble.holding_area().united(window.frameGeometry())
            bubble._fit_window()
            self.window_holds(bubble, "over the face")
            face = window.frameGeometry()
            self.assertTrue(bubble.frameGeometry().contains(face))
            from botwidget.qt_ui import bubble_window as bubble_module
            self.where["at"] = (face.center().x(), face.center().y())
            self.assertEqual(bubble_module.pointer_window(), native_id(window), "a click there reaches the face")
            self.where["at"] = (page.center().x(), page.bottom() - 30)
            self.assertEqual(bubble_module.pointer_window(), native_id(bubble), "the rest is still the bubble")
            centre = bubble.card().center() - bubble.pos()
            self.assertTrue(bubble.mask().contains(centre), "the card itself is never cut")

    def test_choosing_bots_from_the_menu_keeps_the_bubble_whatever_the_place_of_the_face(self):
        """/bots from the right-click list of the top faces closed the bubble at once: the page started its
        growth from a sliver (the list's height was forgotten first), which left the pointer outside. Further down
        a page too tall to fit above the face moves to the side, away from the pointer."""
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QGuiApplication
        from unittest import mock
        state = dict(self.settings_state())
        state["bots"] = [{"id": f"b{i}", "name": f"Bot {i}", "source": "OpenBot", "on": True} for i in range(3)]
        window = self.window
        window.show()
        window.faces = type("Faces", (), {"menu_state": lambda _self: state,
                                          "menu_command": lambda _self, command, page: page,
                                          "close_bubbles_except": lambda _self, _id: None,
                                          "hold_arc": lambda _self: None,
                                          "raise_bubbles": lambda _self: None})()
        bubble = window.bubble
        for spot in ((26, 62), (27, 139), (25, 210), (300, 400)):
            with self.subTest(spot=spot), self.x_pointer(), \
                    mock.patch.object(QGuiApplication, "applicationState", return_value=Qt.ApplicationInactive):
                window.move(*spot)
                window._home = spot
                menu, frames = self.choose_from_the_menu("/bots")
                self.assertTrue(bubble.isVisible(), f"the /bots page stays: {menu} then {frames[:3]}")
                self.assertEqual(window._menu_page, "bots")
                pointer = QPoint(*self.where["at"])
                for frame in frames:
                    self.assertTrue(frame.contains(pointer), f"pointer let go in {frame}")
                self.where["at"] = (5000, 5000)
                bubble._tick()
                self.assertFalse(bubble.isVisible(), "leaving closes it at once")

    def test_a_bot_without_a_conversation_keeps_its_greeting_while_the_pointer_is_on_it(self):
        """Hermes with an empty chat: hover (or a click) opened the greeting, and the next poll found no
        conversation and closed it within a tenth of a second. It stays while the pointer is there, like any
        bubble, and goes the moment the pointer leaves. The command list of such a bot stays too."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from unittest import mock
        self.face.latest_chat = lambda thread_id, limit=8: {"messages": [], "activity": ""}
        window = self.window
        window.show()
        bubble = window.bubble
        with mock.patch.object(QGuiApplication, "applicationState", return_value=Qt.ApplicationActive):
            self.hover()
            self.assertTrue(bubble.isVisible())
            self.assertIn("Ask me anything", bubble.full_text)
            window._sync_bubble(window._latest())  # the poll that follows
            self.assertTrue(bubble.isVisible(), "the pointer is on it: the greeting stays")
            bubble._tick()
            self.assertTrue(bubble.isVisible())
            window.open_input()
            window._sync_bubble(window._latest())
            self.assertTrue(bubble.isVisible(), "a click on the face keeps it too")
            self.where["at"] = (5000, 5000)
            bubble._tick()
            self.assertFalse(bubble.isVisible(), "the pointer left: it goes at once")
            self.where["at"] = (window.x() + 34, window.y() + 34)
            window.open_command_menu()
            window._sync_bubble(window._latest())
            self.assertTrue(bubble.isVisible() and bubble._list_only, "the command list stays as well")

    def test_a_right_click_after_a_left_click_lets_the_command_list_be_clicked_on_x(self):
        """Left-click opens the chat, right-click swaps it for the smaller command list. A separate window that
        held the chat's area once lay on top of the list and took every click: the list looked stuck. The
        bubble's own window holds that area now, so a click on a command always reaches the list."""
        from unittest import mock
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QGuiApplication
        long = "Dit is een lang antwoord over van alles en nog wat. " * 40
        self.face.latest_chat = lambda thread_id, limit=8: {"messages": [{"role": "bot", "text": long}], "activity": ""}
        window = self.window
        window.show()
        bubble = window.bubble

        def under_pointer():
            x, y = self.where["at"]
            point = QPoint(int(x), int(y))
            for widget in (bubble, window):
                if not widget.isVisible() or not widget.geometry().contains(point):
                    continue
                mask = widget.mask()
                if mask.isEmpty() or mask.contains(point - widget.pos()):
                    return native_id(widget)
            return 0

        with mock.patch.object(QGuiApplication, "applicationState", return_value=Qt.ApplicationInactive), \
                mock.patch.object(QGuiApplication, "platformName", return_value="xcb"), \
                mock.patch("botwidget.qt_ui.face.global_pointer", return_value=False), \
                mock.patch("botwidget.qt_ui.bubble_window.pointer_window", side_effect=under_pointer):
            self.where["at"] = (window.x() + 34, window.y() + 34)
            window.open_input()
            if bubble._growth is not None:
                bubble._slide.stop()
                bubble._growth_done()
            chat = bubble.frameGeometry()
            window.open_command_menu()
            menu = bubble.card()
            self.assertTrue(bubble._list_only)
            self.assertFalse(menu.width() >= chat.width() and menu.height() >= chat.height(), "the list is smaller")
            row = bubble._slash.mapToGlobal(QPoint(bubble._slash.width() // 2, bubble._slash.ROW_H + 10))
            self.where["at"] = (row.x(), row.y())
            self.assertEqual(under_pointer(), native_id(bubble), "a click on a command reaches the bubble")
            outside = next((QPoint(x, y) for x in range(chat.left(), chat.right(), 4)
                            for y in range(chat.top(), chat.bottom(), 4)
                            if not menu.contains(QPoint(x, y)) and not window.frameGeometry().contains(QPoint(x, y))),
                           None)
            if bubble.holding_area() is not None and outside is not None:
                self.where["at"] = (outside.x(), outside.y())
                self.assertEqual(under_pointer(), native_id(bubble), "the rest of the chat's area is still the bubble")
            card = bubble.card()
            bubble._put(card.x() + 7, card.y() + 5)  # the spring moves the card on
            moved = bubble.card().center()
            self.where["at"] = (moved.x(), moved.y())
            self.assertEqual(under_pointer(), native_id(bubble), "also where the card went")
            self.window_holds(bubble, "after the spring moved it")

    def test_on_x_a_closed_bubble_leaves_no_window_the_window_manager_could_still_map(self):
        """Opened and closed again before the window manager mapped it: Mutter maps it anyway, after Qt's
        unmap. That invisible window sat on the face, took hover and right-click, and the bot looked stuck."""
        from unittest import mock
        from PySide6.QtGui import QGuiApplication
        window = self.window
        window.show()
        bubble = window.bubble
        with mock.patch.object(QGuiApplication, "platformName", return_value="xcb"):
            window.open_command_menu()
            self.assertTrue(bubble.isVisible())
            self.assertIsNotNone(bubble.windowHandle())
            bubble.place("")
            self.assertIsNone(bubble.windowHandle(), "closed: no X window left that a late map could show")
            window.open_command_menu()
            self.assertTrue(bubble.isVisible(), "and it opens again on a new window")
            self.assertIsNotNone(bubble.windowHandle())

    def test_a_bubble_whose_state_lost_step_with_its_window_opens_again_on_hover_and_right_click(self):
        """Backstop: the bubble thinks it is closed but its window is up (or the other way round). Pointing at
        the face or a right-click must still open it, not leave the bot stuck until a restart."""
        window = self.window
        window.show()
        bubble = window.bubble
        self.hover()
        self.assertTrue(bubble.isVisible())
        bubble.kind = ""  # closed in name only
        bubble._physics.stop()
        self.where["at"] = (5000, 5000)
        window._animate()
        window._hover_retry = window._hover_blocked_until = 0.0
        self.hover()
        self.assertTrue(bubble.isVisible())
        self.assertNotEqual(bubble.kind, "", "pointing at the face opened it for real")
        self.assertTrue(bubble._physics.isActive())
        bubble.hide()  # open in name only: the window is gone
        window.open_command_menu()
        self.assertTrue(bubble.isVisible(), "a right-click shows the command list")

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

    def test_a_page_button_fits_its_line_and_does_not_cover_the_switch_below(self):
        """The old button had a 36px min-height plus padding: it spilled over the next row."""
        from botwidget.qt_ui.controls import ActionButton
        from botwidget.theme import CONTROL_H
        bubble = self.open_settings()
        buttons = [w for w in bubble._control_widgets if isinstance(w, ActionButton)]
        self.assertTrue(buttons)
        self.assertLessEqual(ActionButton("Switch to stable version").minimumSizeHint().height(), CONTROL_H)
        for button in buttons:
            self.assertLessEqual(button.height(), CONTROL_H)
        rows = sorted((w.y(), w.y() + w.height()) for w in bubble._control_widgets)
        for (_top, bottom), (next_top, _b) in zip(rows, rows[1:]):
            self.assertLessEqual(bottom, next_top, "no control overlaps the next one")

    def test_a_menu_page_grows_to_its_content_before_it_scrolls(self):
        """Settings is taller than the chat band of a face: it gets the room, up to most of the screen."""
        from botwidget.bubble import MENU_SCREEN_SHARE, bubble_height_cap
        from botwidget.qt_ui import screens
        bubble = self.open_settings()
        _x, _y, _w, screen_h = screens.rect_at(self.window.x() + 34, self.window.y() + 34)
        chat_cap = bubble_height_cap(self.window.height())
        panels, _box_w, inner = bubble._geom
        self.assertGreater(bubble.height(), chat_cap, "more than the chat band of the face")
        self.assertLessEqual(bubble.height(), max(chat_cap, screen_h * MENU_SCREEN_SHARE) + bubble._extras() + 1)
        bar = bubble._scroll.verticalScrollBar()
        if inner + 2 * 12 < screen_h * MENU_SCREEN_SHARE - 80:
            self.assertEqual(bar.maximum(), 0, "it all fits: nothing to scroll")

    def test_on_wayland_a_bubble_closes_at_once_when_the_pointer_leaves(self):
        """No close grace: off the bubble for one frame and it goes. Only the face-to-bubble move is kept."""
        from contextlib import ExitStack
        from unittest import mock
        bubble = self.open_settings()
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
        tick(start + 0.05, over=False)
        self.assertFalse(bubble.isVisible(), "one frame away, no grace delay")

    def test_on_wayland_crossing_from_the_face_onto_the_bubble_does_not_close_it(self):
        """The gap between face and bubble is not a leave: the bubble stays when the pointer lands on it."""
        from contextlib import ExitStack
        from unittest import mock
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import Qt

        bubble = self.open_settings()
        start = time.monotonic()
        window = self.window

        def tick(at: float, face_over: bool, bubble_over: bool):
            with ExitStack() as stack:
                stack.enter_context(mock.patch("botwidget.qt_ui.face.global_pointer", return_value=False))
                stack.enter_context(mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=at))
                stack.enter_context(
                    mock.patch.object(type(window), "underMouse", return_value=face_over))
                stack.enter_context(
                    mock.patch.object(type(bubble), "underMouse", return_value=bubble_over))
                stack.enter_context(
                    mock.patch.object(QGuiApplication, "applicationState",
                                      return_value=Qt.ApplicationState.ApplicationActive))
                bubble._tick()

        # Pointer on the face: marks the pointer as near.
        tick(start, face_over=True, bubble_over=False)
        self.assertTrue(bubble.isVisible(), "face hover opened the bubble")

        # Straight off the face onto its own bubble: one move, not a leave. The read bubble stays.
        window.leaveEvent(None)
        bubble.changed = start - 1000
        tick(start + 0.01, face_over=False, bubble_over=True)
        self.assertTrue(bubble.isVisible(), "landing on its own bubble is the same hover, not a leave")

    def test_on_wayland_the_bubble_closes_when_the_pointer_is_far_and_the_app_stays_active(self):
        """XWayland keeps the app active and underMouse() stuck true after the pointer has left both windows."""
        from unittest import mock
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        self.hover()
        bubble = self.window.bubble
        self.assertTrue(bubble.isVisible())
        start = time.monotonic()
        # The pointer leaves both windows and Qt keeps reporting underMouse() true (stale on XWayland).
        # The next frame must close it: there is no grace to wait out.
        with mock.patch("botwidget.qt_ui.face.global_pointer", return_value=False), \
                mock.patch.object(QGuiApplication, "applicationState", return_value=Qt.ApplicationActive), \
                mock.patch.object(type(self.window), "underMouse", return_value=True), \
                mock.patch.object(type(bubble), "underMouse", return_value=True):
            self.window.leaveEvent(None)
            bubble.leaveEvent(None)
            with mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=start + 0.05):
                bubble._tick()
        self.assertFalse(bubble.isVisible(), "a stuck underMouse must not hold the bubble after both windows were left")


    def test_on_xwayland_the_bubble_closes_when_the_pointer_goes_onto_another_app_without_a_leave(self):
        """Straight from the bubble onto a Wayland window: no leave event arrives and underMouse() stays true,
        but X says the pointer is over no X window any more."""
        from unittest import mock
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        self.hover()
        bubble = self.window.bubble
        start = time.monotonic()
        with mock.patch("botwidget.qt_ui.face.global_pointer", return_value=False), \
                mock.patch.object(QGuiApplication, "applicationState", return_value=Qt.ApplicationActive), \
                mock.patch.object(type(self.window), "underMouse", return_value=True), \
                mock.patch.object(type(bubble), "underMouse", return_value=True):
            bubble.enterEvent(None)
            with mock.patch("botwidget.qt_ui.bubble_window.pointer_window", return_value=native_id(bubble)), \
                    mock.patch.object(QGuiApplication, "platformName", return_value="xcb"):
                bubble._tick()
            self.assertTrue(bubble.isVisible(), "the pointer is on one of our X windows")
            with mock.patch("botwidget.qt_ui.bubble_window.pointer_window", return_value=0), \
                    mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=start + 0.05):
                bubble._tick()
        self.assertFalse(bubble.isVisible(), "over no X window means over another app")

    def test_on_xwayland_a_bubble_the_pointer_left_without_a_leave_is_not_held_by_a_stuck_enter(self):
        """The back arrow shrinks the page to the chat: the pointer is suddenly off the bubble, on another X
        window, and no leave comes. A bubble that thought it was pointed at forever stayed up (also behind
        other apps) and every other bubble, a right-click menu too, gave way to it."""
        from unittest import mock
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        self.hover()
        bubble = self.window.bubble
        with mock.patch("botwidget.qt_ui.face.global_pointer", return_value=False), \
                mock.patch.object(QGuiApplication, "applicationState", return_value=Qt.ApplicationActive), \
                mock.patch.object(QGuiApplication, "platformName", return_value="xcb"), \
                mock.patch.object(type(self.window), "underMouse", return_value=True), \
                mock.patch.object(type(bubble), "underMouse", return_value=True):
            bubble.enterEvent(None)
            with mock.patch("botwidget.qt_ui.bubble_window.pointer_window", return_value=native_id(bubble)):
                self.assertTrue(bubble.pointer_over())
                bubble._tick()
            self.assertTrue(bubble.isVisible())
            with mock.patch("botwidget.qt_ui.bubble_window.pointer_window", return_value=0x5400004):
                self.assertFalse(bubble.user_owned(), "the pointer is on another app's X window")
                bubble._tick()
        self.assertFalse(bubble.isVisible())

    def test_on_xwayland_hover_opens_and_keeps_the_bubble_while_another_app_has_the_focus(self):
        """GNOME: the Grok Bot app or a terminal has the focus, so our app is inactive. X still says the pointer
        is on the face: the bubble opens and stays, instead of closing at once (and a click-opened one too)."""
        from unittest import mock
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QGuiApplication
        window, bubble = self.window, self.window.bubble
        window.show()

        def under_pointer():
            x, y = self.where["at"]
            for widget in (bubble, window):
                if widget.isVisible() and widget.geometry().contains(QPoint(int(x), int(y))):
                    return native_id(widget)
            return 0

        with mock.patch.object(QGuiApplication, "applicationState", return_value=Qt.ApplicationInactive), \
                mock.patch.object(QGuiApplication, "platformName", return_value="xcb"), \
                mock.patch("botwidget.qt_ui.face.global_pointer", return_value=False), \
                mock.patch("botwidget.qt_ui.bubble_window.pointer_window", side_effect=under_pointer):
            self.where["at"] = (window.x() + 34, window.y() + 34)
            for _ in range(5):
                window._animate()
                bubble._tick()
                self.finish_growth()
            self.assertTrue(bubble.isVisible(), "hover opened it and it stayed")
            window.pin()
            bubble._tick()
            self.assertTrue(bubble.isVisible(), "a click keeps it too")
            self.where["at"] = (5000, 5000)
            bubble._tick()
            self.assertFalse(bubble.isVisible(), "the pointer went away: it closes")
            window._hover_retry = 0.0  # the retry pause is about time, not about this
            self.where["at"] = (window.x() + 34, window.y() + 34)
            for _ in range(3):
                window._animate()
                bubble._tick()
                self.finish_growth()
            self.assertTrue(bubble.isVisible(), "and hovering opens it again")

    def test_refresh_reloads_every_bot_and_unsticks_them(self):
        from unittest import mock
        other = self.second_face()
        other.pinned = True
        other._think_quiet = True
        other._hover_blocked_until = time.monotonic() + 100
        with mock.patch.object(type(self.window.faces), "_probe_grok") as probe:
            self.window.on_user_message("/refresh")
            for _ in range(20):
                if probe.called:
                    break
                time.sleep(0.01)
        self.assertTrue(probe.called, "Grok Bot is asked again")
        self.assertTrue(other._poll_timer.isActive(), "the other bot reloads too")
        self.assertEqual((other.pinned, other._think_quiet, other._hover_blocked_until), (False, False, 0.0))
        self.assertFalse(other.bubble.isVisible(), "quietly: only the bot it was typed into talks")
        self.assertTrue(self.window.bubble.isVisible())
        self.assertIn("Refreshing", self.window.bubble.full_text)

    def test_a_see_through_bubble_does_not_push_the_others_aside(self):
        other = self.second_face()
        other._sync_bubble(other._latest(), force=True)
        other.bubble._slide.stop()
        other.bubble._growth_done()
        self.assertIn(other.bubble, self.window.bubble._others())
        other.bubble.setWindowOpacity(0.0)
        other.bubble.windowOpacity = lambda: 0.0  # offscreen keeps no opacity
        self.assertNotIn(other.bubble, self.window.bubble._others())
        other.bubble._growth = object()
        self.assertIn(other.bubble, self.window.bubble._others(), "fading in is on its way to be seen")
        other.bubble._growth = None

    def test_a_right_click_closes_the_other_bubbles_instead_of_giving_way(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        other = self.second_face()
        other.move(self.window.x() + 20, self.window.y() + 10)
        other.pinned = True
        other._sync_bubble(other._latest(), force=True)
        other.bubble._slide.stop()
        other.bubble._growth_done()
        self.assertTrue(other.bubble.isVisible())
        point = QPointF(5, 5)
        QApplication.sendEvent(self.window, QMouseEvent(QEvent.MouseButtonPress, point, point, Qt.RightButton,
                                                        Qt.RightButton, Qt.NoModifier))
        self.assertTrue(self.window.bubble.isVisible(), "the menu is up")
        self.assertFalse(other.bubble.isVisible())

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
                         "Kijk even\n\nAttached local files:\n- twee.pdf: " + str(Path("/x/twee.pdf")))

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

    def test_the_own_words_twin_of_a_question_does_not_hold_the_answer_back(self):
        calls = self.posts()
        prompt = {"requestId": "r3", "requiresOpenBot": False, "questions": [
            {"id": "q0", "header": "", "question": "Betaalmethode?", "options": [{"label": "Ideal"}]},
            {"id": "q0_custom", "header": "", "question": "Type your own answer", "options": None}]}
        self.start_working()
        self.window._set_attention(self.attention(prompts=[prompt]))
        self.window.on_user_message("iDeal")
        self.wait_for(calls)
        self.assertEqual(calls, [("/v1/agents/t/prompts/r3/answer", {"answers": {"q0_custom": ["iDeal"]}})])

    def test_clicking_an_option_settles_the_own_words_twin(self):
        calls = self.posts()
        prompt = {"requestId": "r3", "requiresOpenBot": False, "questions": [
            {"id": "q0", "header": "", "question": "Betaalmethode?", "options": [{"label": "Ideal"}]},
            {"id": "q0_custom", "header": "", "question": "Type your own answer", "options": None}]}
        self.start_working()
        self.window._set_attention(self.attention(prompts=[prompt]))
        self.window._menu_command("answer/r3/q0/0")
        self.wait_for(calls)
        self.assertEqual(calls, [("/v1/agents/t/prompts/r3/answer", {"answers": {"q0": ["Ideal"]}})])

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
        self.window._pointer_on_head = lambda: True
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

    def test_the_thought_stays_hidden_until_the_pointer_is_on_the_bot(self):
        """Should show only the dots until the pointer is on the bot, then the thought."""
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": "reading files"}, force=True)
        self.assertNotIn("reading files", self.window.bubble.full_text)
        self.window._pointer_on_head = lambda: True
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": "reading files"}, force=True)
        self.assertIn("reading files", self.window.bubble.full_text)

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
                                               "close_bubbles_except": lambda _self, _id: None,
                                               "hold_arc": lambda _self: None,
                                               "raise_bubbles": lambda _self: None})()

    def test_a_slash_at_the_start_opens_a_list_of_commands_above_the_field(self):
        self.hover()
        bubble = self.window.bubble
        height = bubble.height()
        bubble._entry.setText("/")
        self.app.processEvents()
        self.assertTrue(bubble._slash.isVisibleTo(bubble))
        self.assertEqual([c for c, _n in bubble._slash.rows],
                         ["/settings", "/bots", "/connections", "/refresh", "/feedback"])
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
        self.assertEqual(self.window._menu_page, "bots", "the second row since /home is gone")
        self.assertEqual(bubble._entry.text(), "")

    def test_tab_completes_the_command_without_running_it_and_escape_closes_the_list_with_what_was_typed(self):
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
        self.assertEqual((bubble._entry.text(), dismissed), ("", []), "the bubble itself stays")

    def test_escape_keeps_a_message_that_was_already_in_the_field_when_the_list_was_opened_by_right_click(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.hover()
        self.stub_faces()
        bubble = self.window.bubble
        bubble.type_text("een bericht")
        bubble.open_command_list()
        QTest.keyClick(bubble._entry, Qt.Key_Escape)
        self.assertEqual(bubble._entry.text(), "een bericht")

    def test_a_page_opened_on_another_face_replaces_the_one_before_and_escape_closes_it(self):
        from unittest import mock
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        other = self.second_face()
        registry = self.window.faces
        registry.menu_state = self.settings_state
        registry.menu_command = lambda command, page: page
        self.window.open_menu("settings")
        self.finish_growth()
        self.assertTrue(self.window.bubble.isVisible())
        other.open_commands()
        other.open_menu("settings")
        other.bubble._slide.stop()
        other.bubble._growth_done()
        self.assertFalse(self.window.bubble.isVisible(), "one page at a time")
        self.assertTrue(other.bubble.isVisible())
        QTest.keyClick(other, Qt.Key_Escape)
        self.assertFalse(other.bubble.isVisible(), "Escape works on the face too")

    def test_turning_on_a_connection_that_is_not_found_opens_its_page_and_stays_on_until_turned_off(self):
        from unittest import mock
        from botwidget.qt_ui.faces import Faces
        faces = Faces.__new__(Faces)
        faces.wanted = set()
        faces.menu_state = lambda: {"openbot": False, "gbot": True, "wanted": sorted(faces.wanted)}
        with mock.patch("botwidget.qt_ui.faces.QDesktopServices.openUrl") as opened:
            Faces.menu_command(faces, "connect/openbot", "connections")
            self.assertEqual(opened.call_count, 1)
            self.assertEqual(faces.wanted, {"openbot"})
            Faces.menu_command(faces, "connect/openbot", "connections")
            self.assertEqual((opened.call_count, faces.wanted), (1, set()), "off again, nothing opened")
            Faces.menu_command(faces, "connect/grokbot", "connections")
            self.assertEqual((opened.call_count, faces.wanted), (1, set()), "a found one has nothing to open")

    def test_words_left_in_the_field_keep_the_bubble_when_the_pointer_leaves(self):
        self.hover()
        bubble = self.window.bubble
        bubble.type_text("nog niet verstuurd")
        self.where["at"] = (5000, 5000)
        bubble._tick()
        self.assertTrue(bubble.kind, "the words in the field would be lost")

    def test_a_bubble_waiting_on_an_answer_stays_when_the_pointer_leaves(self):
        from unittest import mock
        self.hover()
        bubble = self.window.bubble
        with mock.patch.object(self.window, "awaiting", lambda: True):
            self.where["at"] = (5000, 5000)
            bubble._tick()
        self.assertEqual(bubble.kind, "", "waiting does not keep the bubble up")

    def test_a_field_emptied_again_lets_the_bubble_go_when_the_pointer_leaves(self):
        self.hover()
        bubble = self.window.bubble
        bubble.type_text("a")
        bubble._entry.clear()
        self.where["at"] = (5000, 5000)
        bubble._tick()
        self.assertEqual(bubble.kind, "", "an empty field is no reason to stay")

    def test_the_conversation_as_it_was_at_the_start_does_not_open_the_bubble_but_a_new_message_does(self):
        chat = {"messages": self.MESSAGES, "activity": ""}
        self.window._sync_bubble(chat)
        self.assertFalse(self.window.bubble.isVisible(), "old news after a restart")
        newer = {"messages": self.MESSAGES + [{"role": "bot", "text": "Nieuw"}], "activity": ""}
        self.window._sync_bubble(newer)
        self.assertTrue(self.window.bubble.isVisible())

    def test_dragging_a_face_over_another_does_not_open_the_bubble_of_that_one(self):
        other = self.second_face()
        self.hover()
        mine = self.window.bubble
        self.assertTrue(mine.isVisible())
        self.window._drag_origin = [self.window.spot()]
        self.window.move(other.x(), other.y())
        self.where["at"] = (other.x() + 34, other.y() + 34)
        other._check_hover()
        self.assertFalse(other.bubble.isVisible(), "the pointer is dragging a face, it is not pointing at this one")
        self.window._drag_origin = None
        self.window.move(other.x() + 400, other.y())
        self.where["at"] = (5000, 5000)
        other._check_hover()
        other.bubble._tick()
        self.assertFalse(other.bubble.isVisible())

    def test_two_faces_on_top_of_each_other_do_not_take_the_bubble_from_one_another(self):
        other = self.second_face()
        other.move(self.window.x(), self.window.y())
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        owners = set()
        for _ in range(6):
            for face in (self.window, other):
                face._hover_retry = 0.0
                face._check_hover()
                for bubble in (self.window.bubble, other.bubble):
                    bubble._slide.stop()
                    bubble._growth_done()
            owners.add((self.window.bubble.isVisible(), other.bubble.isVisible()))
        self.assertEqual(len(owners), 1, "one of them keeps it")
        self.assertEqual(sum(next(iter(owners))), 1)

    def test_turning_off_the_bot_whose_bubble_holds_the_page_moves_the_page_to_another_bot(self):
        from unittest import mock
        from botwidget.qt_ui.faces import Faces
        other = self.second_face()
        registry = self.window.faces
        registry.menu_state = self.settings_state
        registry._open = mock.Mock()
        registry._save = mock.Mock()
        self.window.open_menu("bots")
        Faces.toggle(registry, "t", False)
        self.assertEqual(other._menu_page, "bots")
        self.assertTrue(other.bubble.isVisible() or other.bubble._growth is not None)

    def test_a_message_sent_from_the_chat_swaps_it_for_the_dots_cloud_that_opens_like_a_new_bubble(self):
        from botwidget.qt_ui.face import conversation_blocks, role_panel, plain_block
        bubble = self.window.bubble
        bubble.show_blocks(conversation_blocks([{"role": "bot", "text": "Klaar?"}], "T"), "say", input=True)
        self.finish_growth()
        bubble.show_blocks([role_panel("bot"), plain_block("dots")], "think")
        self.assertEqual(bubble.kind, "think")
        self.assertTrue(bubble._growth is not None and bubble._growth.opening, "not a speech bubble that shrinks")
        self.assertLess(bubble.windowOpacity(), 1.0)

    def test_a_thought_that_grows_the_cloud_is_read_from_the_top_until_it_has_grown(self):
        from botwidget.qt_ui.face import role_panel, plain_block, thought_blocks
        bubble = self.window.bubble
        bubble.show_blocks([role_panel("bot"), plain_block("dots")], "think")
        self.finish_growth()
        long = [role_panel("bot")] + thought_blocks("Een lange gedachte over de bestanden. " * 30) + [role_panel("bot"), plain_block("dots")]
        bubble.show_blocks(long, "think", input=True)
        self.assertIsNotNone(bubble._growth)
        bubble._growth_step(0.5)
        self.assertEqual(bubble._scroll.verticalScrollBar().value(), 0, "no flying past the text while it grows")

    def test_the_field_keeps_the_cursor_in_view_when_a_wrapped_paragraph_passes_the_fifth_line(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from botwidget.qt_ui.face import conversation_blocks
        bubble = self.window.bubble
        bubble.show_blocks(conversation_blocks([{"role": "bot", "text": "Ja"}], "T"), "say", input=True)
        self.finish_growth()
        entry = bubble._entry
        for i in range(400):
            QTest.keyClick(entry, " " if i % 9 == 0 else "x")
            QApplication.processEvents()
            if entry.line_count() > 5:
                self.assertLessEqual(entry.cursorRect().bottom(), entry.viewport().height(), f"after {i} letters")
        self.assertGreater(entry.line_count(), 6)
        self.assertEqual(entry.document().blockCount(), 1, "one paragraph, many lines")

    def test_the_cloud_after_a_message_stays_when_the_pointer_was_on_the_bubble_and_then_leaves(self):
        self.window._pump_outbox = lambda: None
        self.window._pointer_on_head = lambda: False
        self.hover()
        self.window.pin()
        self.finish_growth()
        bubble = self.window.bubble
        bubble._tick()
        bubble.type_text("Hallo")
        bubble._send()
        self.assertEqual(bubble.kind, "think")
        bubble._tick()
        self.where["at"] = (5000, 5000)
        for _ in range(5):
            bubble._tick()
            self.window._check_hover()
        self.assertEqual(bubble.kind, "think", "the mouse went back to the work: only the dots are left")
        self.assertFalse(bubble._input)

    def wheel_up_at(self, bubble, moment, phase=None, delta=120):
        from unittest import mock
        with mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=moment):
            self.wheel_up(bubble, phase, delta)

    def test_the_arrow_for_the_message_before_takes_no_room_until_you_scroll_up(self):
        self.hover()
        bubble = self.window.bubble
        before = bubble.height()
        self.assertTrue(bubble._has_older)
        self.assertNotEqual(bubble._geom[0][0]["role"], "more")
        self.wheel_up(bubble)
        self.assertEqual(bubble._geom[0][0]["role"], "more", "the arrow is there, the content below it")
        self.assertIsNotNone(bubble._growth, "the bubble grows by the arrow")
        self.finish_growth()
        self.assertGreater(bubble.height(), before)
        self.assertEqual(self.window._depth, 1, "showing the arrow loads nothing")

    def test_pointing_at_the_top_of_the_bubble_shows_the_line_and_it_stays(self):
        from unittest import mock
        self.hover()
        bubble = self.window.bubble
        card = bubble.card()
        with mock.patch("botwidget.qt_ui.face.global_pointer", return_value=True):
            self.where["at"] = (card.center().x(), card.top() + 8)
            bubble._tick()
            self.assertEqual(bubble._geom[0][0]["role"], "more")
            self.finish_growth()
            card = bubble.card()
            self.where["at"] = (card.center().x(), card.bottom() - 4)
            for _ in range(5):
                bubble._tick()
            self.assertTrue(bubble._more_open, "once it showed, it stays")
            self.assertEqual(bubble._geom[0][0]["role"], "more")

    def test_a_click_on_the_arrow_loads_the_message_before_at_once(self):
        self.hover()
        bubble = self.window.bubble
        self.wheel_up(bubble)
        self.finish_growth()
        self.assertEqual(bubble._geom[0][0]["role"], "more")
        _x, y = self.message_point(0, down=4)
        self.click_at(40, y)
        self.assertEqual(self.window._depth, 2)
        self.finish_growth()
        self.assertIn("Klaar?", bubble.full_text)
        self.assertFalse(bubble._more_open, "the arrow went with the loading")

    def test_the_line_is_pulled_by_the_distance_scrolled_and_far_enough_loads_the_message_before(self):
        self.hover()
        bubble = self.window.bubble
        self.wheel_up_at(bubble, 100.0)
        self.finish_growth()
        self.assertTrue(bubble._more_open)
        self.assertEqual(self.window._depth, 1, "a flick only shows the line")
        first = bubble._more_progress
        self.wheel_up_at(bubble, 105.0)
        self.assertGreater(bubble._more_progress, first, "the further, the more it swells, however slowly")
        self.assertEqual(self.window._depth, 1, "not far enough yet")
        self.wheel_up_at(bubble, 110.0)
        self.assertEqual(self.window._depth, 1)
        self.wheel_up_at(bubble, 115.0)
        self.assertEqual(self.window._depth, 2, "scrolled far enough, however slowly")

    def test_after_a_message_came_in_the_scrolling_that_goes_on_pulls_nothing_until_a_new_scroll(self):
        self.MESSAGES = [{"role": "user", "text": "Eerst?"}, {"role": "bot", "text": "Ja."}, *self.MESSAGES]
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": ""})
        self.hover()
        bubble = self.window.bubble
        self.wheel_up_at(bubble, 100.0)
        self.finish_growth()
        for step in range(4):
            self.wheel_up_at(bubble, 100.1 + step * 0.01)
        self.assertEqual(self.window._depth, 2)
        self.finish_growth()
        self.assertFalse(bubble._more_open, "the line went with the message")
        for step in range(30):
            self.wheel_up_at(bubble, 100.2 + step * 0.02)
        self.assertEqual(self.window._depth, 2, "the same scroll does not load the next message")
        self.assertFalse(bubble._more_open, "and does not bring the line back")
        self.wheel_up_at(bubble, 101.5)
        self.assertTrue(bubble._more_open, "a new scroll does")
        self.assertEqual(self.window._depth, 2)

    def test_a_message_that_came_in_above_is_read_from_its_end(self):
        self.MESSAGES = [{"role": "bot", "text": "Een lange regel met woorden. " * 120}, self.MESSAGES[-1]]
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": ""})
        self.hover()
        bubble = self.window.bubble
        self.wheel_up_at(bubble, 100.0)
        self.finish_growth()
        for step in range(4):
            self.wheel_up_at(bubble, 100.1 + step * 0.01)
        self.assertEqual(self.window._depth, 2)
        self.finish_growth()
        bar = bubble._scroll.verticalScrollBar()
        self.assertGreater(bar.value(), bar.maximum() // 2, "at the end of the message that came in, not its top")

    def test_the_field_for_a_message_only_shows_while_the_pointer_is_with_the_bubble(self):
        from unittest import mock
        from botwidget.qt_ui.face import conversation_blocks
        bubble = self.window.bubble
        blocks = conversation_blocks(self.MESSAGES, "Test")
        self.where["at"] = (-5000, -5000)
        bubble.show_blocks(blocks, "say", input=True, hover_field=True)
        self.finish_growth()
        self.assertTrue(bubble.isVisible())
        self.assertFalse(bubble._input, "opened by itself: no field")
        self.assertFalse(bubble._entry.isVisible())
        self.hover()
        bubble._tick()
        self.finish_growth()
        self.assertTrue(bubble._input, "the pointer is on the face: the field shows")
        bubble._entry.setPlainText("een halve zin")
        self.where["at"] = (-5000, -5000)
        for _ in range(3):
            bubble._tick()
        self.assertTrue(bubble._input, "words you typed keep it")

    def test_the_field_goes_a_moment_after_the_pointer_left(self):
        from unittest import mock
        self.hover()
        bubble = self.window.bubble
        self.assertTrue(bubble._input)
        self.where["at"] = (-5000, -5000)
        with mock.patch.object(self.window, "pointer_near", return_value=False):
            bubble._sync_field(100.0)
            self.assertTrue(bubble._input, "not at once")
            bubble._sync_field(100.5)
            self.assertTrue(bubble._input)
            bubble._sync_field(101.0)
        self.assertFalse(bubble._input)

    def test_a_bubble_that_was_prepared_opens_without_laying_the_text_out_again(self):
        from unittest import mock
        from botwidget.qt_ui.face import conversation_blocks
        bubble = self.window.bubble
        blocks = conversation_blocks(self.MESSAGES, "Test")
        self.assertTrue(bubble.prepare(blocks, "say", True))
        self.assertFalse(bubble.isVisible(), "prepared, not shown")
        self.assertEqual(bubble.kind, "", "it is still closed")
        self.assertFalse(bubble.prepare(blocks, "say", True), "once is enough")
        with mock.patch.object(bubble, "_parts", side_effect=AssertionError("laid out again")):
            bubble.show_blocks(blocks, "say", input=True)
        self.assertEqual(bubble.kind, "say")
        self.assertTrue(bubble.isVisible())
        self.assertIn("Ja.", bubble.full_text)

    def test_a_bubble_is_not_prepared_while_it_is_open(self):
        from botwidget.qt_ui.face import conversation_blocks
        self.hover()
        bubble = self.window.bubble
        self.assertTrue(bubble.isVisible())
        self.assertFalse(bubble.prepare(conversation_blocks([{"role": "bot", "text": "Nieuw."}], "Test"), "say", True))
        self.assertNotIn("Nieuw", bubble.full_text)

    def test_scrolling_back_down_shrinks_the_line_again(self):
        self.hover()
        bubble = self.window.bubble
        self.wheel_up_at(bubble, 100.0)
        self.finish_growth()
        self.wheel_up_at(bubble, 100.1)
        pulled = bubble._pull_px
        self.wheel_up_at(bubble, 100.2, delta=-120)
        self.assertLess(bubble._pull_px, pulled)
        self.wheel_up_at(bubble, 100.3, delta=-1200)
        self.assertEqual(bubble._pull_px, 0.0)
        self.assertEqual(self.window._depth, 1)

    def test_letting_go_shoots_the_line_back_up_without_loading(self):
        from unittest import mock
        self.hover()
        bubble = self.window.bubble
        self.wheel_up_at(bubble, 100.0)
        self.finish_growth()
        self.wheel_up_at(bubble, 100.1)
        self.assertGreater(bubble._pull_px, 0)
        with mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=100.15):
            bubble._watch_arrow(100.15)
        self.assertGreater(bubble._pull_px, 0, "the wheel has only just stopped")
        now = 100.3
        for step in range(30):
            now += 0.016
            with mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=now):
                bubble._watch_arrow(now)
        self.assertEqual(bubble._pull_px, 0.0)
        self.assertEqual(self.window._depth, 1, "letting go loads nothing")

    def test_a_finger_that_stays_on_the_pad_holds_the_line_where_it_is(self):
        from unittest import mock
        from PySide6.QtCore import Qt
        self.hover()
        bubble = self.window.bubble
        self.wheel_up_at(bubble, 100.0, Qt.ScrollBegin)
        self.finish_growth()
        self.wheel_up_at(bubble, 100.1, Qt.ScrollUpdate)
        pulled = bubble._pull_px
        for now in (101.0, 102.0, 103.0):
            with mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=now):
                bubble._watch_arrow(now)
        self.assertEqual(bubble._pull_px, pulled)

    def test_the_momentum_after_a_lifted_finger_shows_the_arrow_but_never_loads(self):
        from PySide6.QtCore import Qt
        self.hover()
        bubble = self.window.bubble
        for step in range(12):
            self.wheel_up_at(bubble, 100.0 + step * 0.1, Qt.ScrollMomentum)
        self.assertTrue(bubble._more_open)
        self.assertEqual(self.window._depth, 1)

    def test_the_pull_shows_as_a_swell_in_the_line(self):
        from botwidget.bubble import bubble_deco_svg
        self.hover()
        bubble = self.window.bubble
        self.wheel_up_at(bubble, 100.0)
        self.finish_growth()
        plain = bubble_deco_svg(*bubble._geom[:2])
        bubble._set_progress(0.5)
        self.assertNotEqual(bubble_deco_svg(*bubble._geom[:2]), plain)

    def test_a_new_message_takes_the_arrow_away(self):
        self.hover()
        bubble = self.window.bubble
        self.wheel_up(bubble)
        self.finish_growth()
        self.window._sync_bubble({"messages": self.MESSAGES + [{"role": "bot", "text": "Nog iets."}], "activity": ""})
        self.assertFalse(bubble._more_open)
        self.assertEqual(self.window._depth, 1)

    def test_pointing_at_another_face_that_lies_under_the_border_of_an_open_bubble_opens_its_bubble(self):
        from unittest import mock
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        active = mock.patch.object(QGuiApplication, "applicationState", return_value=Qt.ApplicationActive)
        active.start()
        self.addCleanup(active.stop)
        other = self.second_face()
        self.hover()
        mine = self.window.bubble
        self.assertTrue(mine.isVisible())
        card = mine.card()
        other.move(card.right() + 10 - 34, card.center().y() - 34)
        self.where["at"] = (other.x() + 34, other.y() + 34)
        self.assertFalse(card.contains(self.where["at"][0], self.where["at"][1]), "outside the card, inside the border")
        self.assertTrue(self.window.pointer_near(mine), "the border of the open bubble")
        # A screen so cramped that the bubble of the other face would lie on this one wherever it goes.
        other.bubble._covering = lambda *_spot: [mine] if mine.isVisible() else []
        other._check_hover()
        for _ in range(3):
            other.bubble._tick()
            mine._tick()
        other.bubble._slide.stop()
        other.bubble._growth_done()
        self.assertTrue(other.bubble.isVisible(), "the face under the border is pointed at")
        self.assertFalse(mine.isVisible(), "one at a time")

    def test_after_sending_the_cloud_stays_at_its_dots_until_the_pointer_leaves_and_comes_back(self):
        self.window._pump_outbox = lambda: None
        self.hover()
        self.window.pin()
        self.finish_growth()
        bubble = self.window.bubble
        bubble.type_text("Hallo")
        bubble._send()
        self.window._sync_bubble(self.window._latest(), force=True)
        self.assertEqual(bubble.kind, "think")
        self.assertFalse(bubble._input, "the pointer is still on it, but you just sent: no field")
        self.assertTrue(self.window._think_held)
        self.window._sync_bubble(self.window._latest(), force=True)
        self.assertFalse(bubble._input)
        self.where["at"] = (5000, 5000)
        self.window._think_expanded()
        self.assertFalse(self.window._think_held, "the pointer left")
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        self.assertTrue(self.window._think_expanded(), "back on it: the thought and the field open")

    def test_clicking_the_face_after_sending_opens_the_chat_again(self):
        self.window._think_held = True
        self.window.pin()
        self.assertFalse(self.window._think_held)

    def test_spaces_at_the_end_of_a_line_do_not_push_the_text_sideways(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from botwidget.qt_ui.face import conversation_blocks
        bubble = self.window.bubble
        bubble.show_blocks(conversation_blocks([{"role": "bot", "text": "Ja"}], "T"), "say", input=True)
        self.finish_growth()
        entry = bubble._entry
        for pattern in ("abcdefgh  ", "mmmmmm   ", "ii   "):
            entry.clear()
            for i in range(160):
                QTest.keyClick(entry, pattern[i % len(pattern)])
                QApplication.processEvents()
                self.assertEqual(entry.horizontalScrollBar().value(), 0, f"{pattern!r} after {i} letters")

    def test_a_bubble_opens_on_the_desktop_you_are_on_and_a_face_stays_where_it_lives(self):
        from botwidget.system import macos
        from botwidget.qt_ui.faces import ArcCatcher
        stays = macos.desktop_behavior(False)
        travels = macos.desktop_behavior(False, travels=True)
        self.assertTrue(stays & macos.MANAGED and not stays & macos.MOVE_TO_ACTIVE_SPACE)
        self.assertTrue(travels & macos.MOVE_TO_ACTIVE_SPACE and not travels & macos.MANAGED)
        everywhere = macos.desktop_behavior(True, travels=True)
        self.assertTrue(everywhere & macos.CAN_JOIN_ALL_SPACES and not everywhere & macos.MOVE_TO_ACTIVE_SPACE)
        self.assertTrue(self.window.bubble.travels and ArcCatcher.travels)
        self.assertFalse(getattr(self.window, "travels", False))

    def test_apply_tells_the_system_whether_a_window_travels(self):
        from unittest import mock
        from botwidget.qt_ui import desktops
        with mock.patch.object(desktops, "_real", return_value=True), \
                mock.patch.object(desktops, "all_desktops", return_value=False), \
                mock.patch.object(desktops, "set_desktops") as call:
            desktops.apply(self.window.bubble)
            desktops.apply(self.window)
        self.assertEqual([c.args[1:] for c in call.call_args_list], [(False, True), (False, False)])

    def test_a_bubble_gets_its_desktop_before_it_shows(self):
        from unittest import mock
        from botwidget.qt_ui import bubble_window
        bubble = self.window.bubble
        order = []
        with mock.patch.object(bubble_window.desktops, "apply", side_effect=lambda w: order.append("apply")), \
                mock.patch.object(type(bubble), "show", lambda _self: order.append("show")):
            bubble._show_at(10, 10)
        self.assertEqual(order, ["apply", "show", "apply"], "shown first, it would take you to its last desktop")

    def test_the_bubble_is_glass_and_its_mask_is_only_the_shape(self):
        from botwidget import bubble
        from botwidget.theme import GLASS_ALPHA
        body = bubble.bubble_body_svg(200, 100, alpha=GLASS_ALPHA)
        self.assertIn(f'opacity="{GLASS_ALPHA}"', body)
        self.assertIn("linearGradient", body)
        mask = bubble.bubble_body_svg(200, 100, mask=True)
        self.assertNotIn("stroke", mask)
        self.assertNotIn("Gradient", mask)
        cloud = bubble.cloud_body_svg(200, 100, alpha=GLASS_ALPHA)
        self.assertEqual(cloud.count("<path"), 1, "the silhouette is drawn once and used twice")
        self.assertEqual(cloud.count("<use"), 2)

    def test_a_shadow_does_not_show_through_the_glass(self):
        from botwidget import bubble
        from botwidget.qt_ui.render import blurred, cut_out, svg_pixmap
        shadow = blurred(svg_pixmap(bubble.bubble_shadow_svg(200, 100)), 12)
        shape = svg_pixmap(bubble.bubble_body_svg(200, 100, mask=True))
        ratio = shadow.devicePixelRatio()
        centre = (int(120 * ratio), int(70 * ratio))
        self.assertGreater(shadow.toImage().pixelColor(*centre).alpha(), 0)
        self.assertEqual(cut_out(shadow, shape).toImage().pixelColor(*centre).alpha(), 0)

    def test_the_glass_is_less_paint_where_it_can_blur(self):
        from unittest import mock
        from botwidget.qt_ui import glass
        from botwidget.theme import GLASS_ALPHA, GLASS_ALPHA_FLAT
        # Non-blur platform at default: the glass starts more transparent so the gradient and grain show.
        # (The user's glass_clear may be slightly above 40, so alpha is a touch under GLASS_ALPHA_FLAT.)
        self.assertLessEqual(glass.alpha(), GLASS_ALPHA_FLAT, "offscreen: glass is clearer so paint and grain are visible")
        with mock.patch.object(glass, "blurs", return_value=True):
            self.assertEqual(glass.alpha(), GLASS_ALPHA, "over a blur it can be much clearer")

    def test_text_fades_at_the_edge_where_it_goes_on_and_not_where_it_starts(self):
        from botwidget.qt_ui.face import conversation_blocks
        bubble = self.window.bubble
        long = [{"role": "bot", "text": "Een lange regel met woorden. " * 80}]
        bubble.show_blocks(conversation_blocks(long, "T"), "say", input=True)
        self.finish_growth()
        bar = bubble._scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)

        def ends():
            stops = bubble._fade.opacityMask().gradient().stops()
            return stops[0][1].alpha(), stops[-1][1].alpha()

        bar.setValue(0)
        self.assertEqual(ends(), (255, 0), "the top is where it starts, the bottom is where it goes on")
        bar.setValue(bar.maximum() // 2)
        self.assertEqual(ends(), (0, 0))
        bar.setValue(bar.maximum())
        self.assertEqual(ends(), (0, 255))

    def test_the_settings_offer_the_glass_slider_wherever_the_glass_is_painted(self):
        from botwidget import menu_pages
        from botwidget.qt_ui import glass
        self.assertTrue(glass.available(), "the glass is painted here, so the setting for it belongs in the menu")
        state = {**self.settings_state(), "glass_clear": 40}
        self.assertNotIn("slider/glass", self.window_commands(menu_pages.settings(state)),
                         "a state without glass has no slider")
        blocks = menu_pages.settings({**state, "can_glass": True})
        self.assertIn("slider/glass", self.window_commands(blocks))
        slider = next(block for block in blocks if block.get("control") == "slider")
        self.assertEqual(slider["on"], 40)

    def test_the_glass_slider_sets_how_much_paint_the_glass_has(self):
        from unittest import mock
        from botwidget.qt_ui import glass
        from botwidget.theme import GLASS_ALPHA
        with mock.patch.object(glass, "blurs", return_value=True), \
                mock.patch.object(glass, "widget_config", return_value={}):
            self.assertEqual(glass.alpha(), GLASS_ALPHA, "the default is where it started")
        with mock.patch.object(glass, "blurs", return_value=True):
            values = []
            for percent in (0, 50, 100, 250, -5):
                with mock.patch.object(glass, "widget_config", return_value={"glass_clear": percent}):
                    values.append(glass.alpha())
        self.assertEqual(values[0], 1.0)
        self.assertEqual(values[2], 0.2, "at 100 hardly any paint is left")
        self.assertGreater(values[0], values[1])
        self.assertGreater(values[1], values[2])
        self.assertEqual(values[3], values[2], "more than 100 is 100")
        self.assertEqual(values[4], values[0], "less than 0 is 0")
        # Where nothing behind the window can be blurred the glass starts more solid, but the slider still takes
        # paint away: that is the frost.
        from botwidget.theme import GLASS_ALPHA_FLAT, GLASS_ALPHA_FLAT_CLEAR
        with mock.patch.object(glass, "blurs", return_value=False), \
                mock.patch.object(glass, "widget_config", return_value={}):
            self.assertEqual(glass.alpha(), GLASS_ALPHA_FLAT)
        with mock.patch.object(glass, "blurs", return_value=False), \
                mock.patch.object(glass, "widget_config", return_value={"glass_clear": 100}):
            self.assertEqual(glass.alpha(), GLASS_ALPHA_FLAT_CLEAR)

    def test_moving_the_glass_slider_saves_it_and_draws_the_bubbles_again_without_a_new_page(self):
        from unittest import mock
        from botwidget.qt_ui.faces import Faces
        faces = Faces.__new__(Faces)
        faces.faces, faces._arc_guests = {"t": self.window}, {}
        with mock.patch("botwidget.qt_ui.faces.save_widget_config") as save, \
                mock.patch.object(self.window.bubble, "restyle") as restyle:
            self.assertIsNone(faces.menu_command("slider/glass/65", "settings"))
        save.assert_called_once_with(glass_clear=65)
        restyle.assert_called()

    def window_commands(self, blocks):
        return [block["command"] for block in blocks if block.get("kind") == "control"]

    def test_a_menu_page_is_not_pinned_and_escape_closes_it(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.window.pin()
        self.open_settings()
        self.assertFalse(self.window.pinned, "it goes away by itself like any bubble")
        QTest.keyClick(self.window.bubble, Qt.Key_Escape)
        self.assertEqual(self.window.bubble.kind, "")

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
            if command in ("/refresh", "/feedback"):
                continue
            self.assertIn(command, menu_pages.SLASH)
        self.assertNotIn("/home", [command for command, _note in menu_pages.COMMANDS],
                         "gone: the back arrow and a right-click show the list")
        self.assertNotIn("/refresh", menu_pages.SLASH, "reload, not a menu page")
        self.assertNotIn("/feedback", menu_pages.SLASH, "a browser page, not a menu page")

    def second_face(self):
        from botwidget.qt_ui.faces import Faces
        other = self.face.FaceWindow("u", "Other", spot=(900, 400))
        self.addCleanup(other.close_face)
        other._poll_timer.stop()
        other._pointer = lambda: self.where["at"]
        other.bubble.focus_entry = lambda: None
        registry = Faces.__new__(Faces)
        registry.faces = {"t": self.window, "u": other}
        registry._arc_guests = {}
        registry.hold_arc = lambda: None
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
                mock.patch.object(desktops, "bring_here") as pull:
            self.window._keep_bubble_here()
        pull.assert_called_once_with(bubble)
        self.assertFalse(bubble.isVisible(), "gone, so that the next hover opens it where you are")
        self.window._hover_retry = 0.0
        self.hover()
        self.assertTrue(bubble.isVisible())
    def test_the_thinking_dots_pulse_in_bursts_and_rest_in_between(self):
        from unittest import mock
        from botwidget.theme import DOTS_BURST_CYCLES, DOTS_CYCLE_S, DOTS_MS
        self.hover()
        bubble = self.window.bubble
        bubble._dots_lines = [{"phase": 0.0}]
        bubble._dots_on = True
        bubble._dots.start()
        with mock.patch("botwidget.qt_ui.bubble_window.QTimer.singleShot") as later:
            for _ in range(round(DOTS_BURST_CYCLES * DOTS_CYCLE_S * 1000 / DOTS_MS) + 2):
                bubble._tick_dots()
        self.assertFalse(bubble._dots.isActive(), "no timer runs while the dots rest")
        later.assert_called_once()
        bubble._resume_dots()
        self.assertTrue(bubble._dots.isActive(), "and they pulse again after the rest")
        bubble._dots.stop()

    def test_a_mood_clip_plays_once_and_then_rests(self):
        from botwidget import motion
        move = motion.Motion(seed=1)
        move.set_mood("thinking")
        played = 0
        for _ in range(20 * 60):  # twenty seconds at sixty frames
            move.step(1 / 60)
            played += move.playing is not None
        self.assertLess(played / 60, 20 * 0.6, "it holds still for part of the time")
        self.assertGreater(played, 0)

    def test_the_app_is_not_activated_while_its_bubble_sits_on_another_desktop(self):
        from unittest import mock
        from botwidget.qt_ui import desktops, face
        self.hover()
        with mock.patch.object(desktops, "shown_here", return_value=False), \
                mock.patch.object(desktops, "bring_here"), mock.patch.object(face, "activate_app") as activate:
            self.window._activate_here()
        activate.assert_not_called()
        self.window._hover_retry = 0.0
        self.hover()
        with mock.patch.object(desktops, "shown_here", return_value=True), \
                mock.patch.object(face, "activate_app") as activate:
            self.window._activate_here()
        activate.assert_called_once()

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

    def test_application_inactive_closes_the_bubble(self):
        """When the pointer leaves to another app on XWayland, underMouse() can stay True
        but the app is inactive — the bubble must close after the cross-gap."""
        import time
        from unittest import mock
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        self.hover()
        bubble = self.window.bubble
        self.finish_growth()
        # global_pointer() is False on this platform (offscreen), so pointer_near()
        # falls back to underMouse(). Patch underMouse to stay False (pointer not on us),
        # but report the app as inactive (user switched away).
        with mock.patch.object(type(bubble), "underMouse", return_value=False), \
             mock.patch.object(type(self.window), "underMouse", return_value=False), \
             mock.patch.object(QGuiApplication, "applicationState",
                               return_value=Qt.ApplicationInactive):
            # Advance time past CROSS_GAP_S so the leave path should fire
            bubble._was_near = True
            bubble._near_at = time.monotonic() - 1.0
            bubble._tick()
            self.assertTrue(bubble.kind, "a moment inactive is a switch of desktop, not the user leaving")
            self.window._inactive_since = time.monotonic() - 5
            bubble._tick()
        self.assertEqual(bubble.kind, "")


class BubbleScrollMemory(unittest.TestCase):
    """Should open where you left off: the same page shown again keeps the place you scrolled to."""

    LONG = "\n\n".join(f"Regel {i} van een antwoord dat veel langer is dan de bubbel." for i in range(60))
    MESSAGES = [{"role": "user", "text": "Leg uit."}, {"role": "bot", "text": LONG}]

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
                            ("openbot_installed", lambda: True), ("gbot_installed", lambda: True),
                            ("automation_ready", lambda: True)):
            old = getattr(self.face, name)
            self.addCleanup(setattr, self.face, name, old)
            setattr(self.face, name, value)
        self.window = self.face.FaceWindow("t", "Test", spot=(300, 400))
        self.window._poll_timer.stop()
        self.addCleanup(self.window.close_face)
        self.where = {"at": (5000, 5000)}
        self.window._pointer = lambda: self.where["at"]
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        old_path = config.CONFIG_PATH
        self.addCleanup(setattr, config, "CONFIG_PATH", old_path)
        config.CONFIG_PATH = os.path.join(folder, "widget.json")
        old_activate = self.face.activate_app
        self.addCleanup(setattr, self.face, "activate_app", old_activate)
        self.face.activate_app = lambda: None
        self.window.bubble.focus_entry = lambda: None

    def open_bubble(self):
        """Point at the face until the chat fills the bubble."""
        self.window._animate()
        self.where["at"] = (self.window.x() + 34, self.window.y() + 34)
        self.window._animate()
        bubble = self.window.bubble
        self.finish_growth()
        return bubble

    def finish_growth(self):
        bubble = self.window.bubble
        bubble._slide.stop()
        bubble._growth_done()

    def scroll_to(self, bubble, share):
        """Scroll to a share of the way down the answer, and hand back where that is."""
        bar = bubble._scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0, "the answer must be longer than the bubble")
        bar.setValue(round(bar.maximum() * share))
        self.assertGreater(bar.value(), 0, "the bubble must be scrolled away from the start")
        return bar.value()

    def pulse(self):
        """Let Qt lay out what just changed: a hidden scroll area is pinned to its top only then, as in the widget."""
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

    def test_the_field_coming_and_going_keeps_the_place_you_scrolled_to(self):
        bubble = self.open_bubble()
        bubble.show_blocks(bubble.blocks, "say", input=False, hover_field=True)
        self.finish_growth()
        place = self.scroll_to(bubble, 0.3)
        bubble.show_blocks(bubble.blocks, "say", input=True, hover_field=True)
        self.finish_growth()
        self.pulse()
        self.assertEqual(bubble._scroll.verticalScrollBar().value(), place)

    def test_closing_the_bubble_keeps_the_place_you_left(self):
        bubble = self.open_bubble()
        place = self.scroll_to(bubble, 0.4)
        self.where["at"] = (5000, 5000)
        bubble._tick()
        self.pulse()
        self.assertFalse(bubble.isVisible(), "the pointer left, so the bubble went")
        self.assertEqual(bubble._scroll.verticalScrollBar().value(), 0, "Qt pins a hidden scroll area to its top")
        self.assertEqual(bubble._scroll_place, place, "but the bubble kept the place aside")

    def test_reopening_the_bubble_starts_where_you_left_it(self):
        bubble = self.open_bubble()
        place = self.scroll_to(bubble, 0.5)
        self.where["at"] = (5000, 5000)
        bubble._tick()
        self.pulse()
        self.assertFalse(bubble.isVisible(), "the pointer left, so the bubble went")
        # Opening it again lays the same page out, as the face does when you point at it.
        bubble.show_blocks(bubble.blocks, "say", input=True, hover_field=True)
        self.finish_growth()
        self.pulse()
        self.assertEqual(bubble._scroll.verticalScrollBar().value(), place)

    def test_a_poll_while_it_is_closed_does_not_lose_the_place(self):
        bubble = self.open_bubble()
        place = self.scroll_to(bubble, 0.6)
        self.where["at"] = (5000, 5000)
        bubble._tick()
        self.pulse()
        # The poll runs while the bubble is closed, laying the same page out again for the next opening.
        self.window._sync_bubble({"messages": self.MESSAGES, "activity": ""})
        self.pulse()
        bubble.show_blocks(bubble.blocks, "say", input=True, hover_field=True)
        self.finish_growth()
        self.pulse()
        self.assertEqual(bubble._scroll.verticalScrollBar().value(), place)


class FrostLook(unittest.TestCase):
    """Should look frosted where the system cannot blur what is behind the window, without a per-frame blur."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.app = QApplication.instance() or QApplication([])

    def parts(self):
        """A plain glass card the size of a bubble, and its shape as a mask."""
        from botwidget import bubble
        from botwidget.qt_ui.render import svg_pixmap
        body = svg_pixmap(bubble.bubble_body_svg(240, 160, None, "above", 0.9))
        shape = svg_pixmap(bubble.bubble_body_svg(240, 160, None, "above", mask=True))
        return body, shape

    def test_the_grain_stays_inside_the_shape(self):
        from botwidget.qt_ui import glass
        body, shape = self.parts()
        out = glass.frost(body, shape)
        self.assertEqual(out.size(), body.size())
        inside = body.rect().center()
        corner = body.rect().topLeft()
        self.assertNotEqual(out.toImage().pixelColor(inside), body.toImage().pixelColor(inside),
                            "the glass is grained")
        self.assertEqual(out.toImage().pixelColor(corner).alpha(), 0, "outside the shape stays empty")

    def test_every_platform_that_cannot_blur_gets_the_grain(self):
        """Not just Linux: Windows ignores blur behind a window since Windows 8, so it gets the same frost."""
        from unittest import mock
        from PySide6.QtGui import QGuiApplication
        from botwidget.qt_ui import glass
        for platform in ("windows", "xcb", "wayland"):
            with mock.patch.object(QGuiApplication, "platformName", return_value=platform), \
                    mock.patch.object(glass, "CAN_BLUR", False):
                self.assertFalse(glass.blurs(), f"{platform} cannot blur behind the window, so it is painted")
        with mock.patch.object(QGuiApplication, "platformName", return_value="cocoa"), \
                mock.patch.object(glass, "CAN_BLUR", True):
            self.assertTrue(glass.blurs(), "macOS blurs for real, so it is not painted")

    def test_the_same_size_gets_the_same_grain_every_time(self):
        from botwidget.qt_ui import glass
        body, shape = self.parts()
        plain = body.toImage()
        self.assertEqual(glass.frost(body, shape).toImage(), glass.frost(body, shape).toImage(),
                         "a redraw must not shift the grain")
        self.assertEqual(body.toImage(), plain, "the glass handed in is left alone")


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


class FailedTurn(unittest.TestCase):
    """A turn OpenBot gave up on (a spent provider) is not thinking: the face says why."""

    def store(self, status, active=None, error=None):
        import sqlite3
        from botwidget import openbot
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "openbot.db")
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE projection_thread_messages (thread_id, author, item_type, message_json, created_at)")
        con.execute("CREATE TABLE projection_threads (thread_id, active_turn_id)")
        con.execute("CREATE TABLE projection_turns (turn_id, thread_id, status, completed_at)")
        con.execute("CREATE TABLE projection_deliveries (turn_id, error)")
        con.execute("INSERT INTO projection_thread_messages VALUES ('t', 'user', 'message', ?, '2026-01-01T10:00')",
                    (json.dumps({"text": "Are you alive?"}),))
        con.execute("INSERT INTO projection_thread_messages VALUES ('t', 'bot', 'commentary', ?, '2026-01-01T10:01')",
                    (json.dumps({"text": "Looking at it"}),))
        con.execute("INSERT INTO projection_threads VALUES ('t', ?)", (active,))
        con.execute("INSERT INTO projection_turns VALUES ('u1', 't', ?, '2026-10-27T15:24:25.734Z')", (status,))
        con.execute("INSERT INTO projection_deliveries VALUES ('u1', ?)", (error,))
        con.commit()
        con.close()
        old = openbot.DB_FILE
        self.addCleanup(setattr, openbot, "DB_FILE", old)
        openbot.DB_FILE = path
        return openbot.latest_chat("t")

    def test_a_spent_provider_is_out_of_tokens_not_thinking(self):
        chat = self.store("failed", error="RequestError: Internal error: Free usage limit reached. Connect a provider")
        self.assertEqual(chat["activity"], "", "no thinking for a turn that is over")
        self.assertTrue(chat["failed"].startswith("Out of tokens"))

    def test_another_failure_says_the_turn_failed(self):
        self.assertEqual(self.store("failed", error="boom")["failed"], "The last turn failed: boom")

    def test_a_running_turn_still_thinks(self):
        chat = self.store("running", active="u1")
        self.assertEqual(chat["activity"], "Looking at it")
        self.assertEqual(chat["failed"], "")

    def test_the_face_shows_offline_with_the_reason(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from botwidget.qt_ui import face
        QApplication.instance() or QApplication([])
        window = face.FaceWindow("t", "Test", spot=(300, 400))
        window._poll_timer.stop()
        self.addCleanup(window.close_face)
        # What is installed on this computer must not matter: OpenBot is there, its local API is on.
        for name in ("automation_ready", "openbot_installed", "gbot_installed"):
            self.addCleanup(setattr, face, name, getattr(face, name))
            setattr(face, name, lambda: True)
        chat = {"messages": [{"role": "user", "text": "Are you alive?"}], "activity": "",
                "failed": "Out of tokens: Free usage limit reached."}
        window._sync_bubble(chat, force=True)
        self.assertFalse(window._working)
        self.assertEqual(window._motion_mood(), "offline")
        self.assertIn("Out of tokens", window.bubble.full_text)


    def failed_face(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from botwidget.qt_ui import face
        QApplication.instance() or QApplication([])
        window = face.FaceWindow("t", "Test", spot=(300, 400))
        window._poll_timer.stop()
        self.addCleanup(window.close_face)
        for name in ("automation_ready", "openbot_installed", "gbot_installed"):
            self.addCleanup(setattr, face, name, getattr(face, name))
            setattr(face, name, lambda: True)
        return window

    def test_a_turn_that_failed_after_you_asked_ends_the_thinking(self):
        import time
        window = self.failed_face()
        window._asked, window._asked_at = True, time.time() - 30
        ended = time.strftime("%Y-%m-%dT%H:%M:%S.000+00:00", time.gmtime(time.time() - 5))
        chat = {"messages": [{"role": "user", "text": "Ping"}], "activity": "",
                "failed": "The last turn failed: no sign-in", "failed_at": ended}
        window._sync_bubble(chat, force=True)
        self.assertFalse(window._asked, "no answer is coming")
        self.assertIn("no sign-in", window.bubble.full_text)
        self.assertEqual(window.bubble.kind, "say", "not the thinking cloud")

    def test_an_older_failure_does_not_end_the_thinking_of_a_new_question(self):
        import time
        window = self.failed_face()
        window._asked, window._asked_at = True, time.time()
        old = time.strftime("%Y-%m-%dT%H:%M:%S.000+00:00", time.gmtime(time.time() - 600))
        chat = {"messages": [{"role": "user", "text": "Ping"}], "activity": "",
                "failed": "The last turn failed: old", "failed_at": old}
        window._sync_bubble(chat, force=True)
        self.assertTrue(window._asked, "this question has not been answered, or failed, yet")


class Tables(unittest.TestCase):
    TEXT = "Voor\n\n| Naam | Waarde |\n|---|:--:|\n| a | **1** |\n| lange naam hier | `2` |\n\nNa"

    def test_markdown_tables_become_a_table_block(self):
        from botwidget.markdown import md_blocks
        blocks = md_blocks(self.TEXT)
        self.assertEqual([block["kind"] for block in blocks], ["text", "gap", "table", "gap", "text"])
        rows = blocks[2]["rows"]
        self.assertEqual(len(rows), 3, "the line of dashes is not a row")
        self.assertEqual(rows[0][0], [("Naam", "")])
        self.assertEqual(rows[1][1], [("1", "b")])

    def test_a_line_with_a_bar_and_no_dashes_under_it_is_no_table(self):
        from botwidget.markdown import md_blocks
        self.assertEqual([block["kind"] for block in md_blocks("a | b\nc | d")], ["text", "text"])

    def test_a_table_is_a_line_per_row_with_tabs_between_the_cells_and_a_rule_under_the_header(self):
        from botwidget.bubble_layout import md_layout
        laid, widest = md_layout(lambda text, style, size: 7.0 * len(text), self.TEXT, 400)
        rows = [line for line in laid if line.get("tabs")]
        self.assertEqual(len(rows), 3)
        self.assertEqual([line["kind"] for line in laid].count("rule"), 1)
        self.assertEqual("".join(word for word, _style, _lead in rows[0]["words"]), "Naam\tWaarde")
        self.assertEqual(rows[0]["tabs"], rows[2]["tabs"], "the columns line up")
        self.assertGreaterEqual(rows[0]["tabs"][0], 7 * len("lange naam hier"), "wide enough for the longest cell")

    def test_a_table_wider_than_the_bubble_wraps_its_words_and_says_it_is_cramped(self):
        from botwidget.bubble_layout import md_layout
        text = "| A | B |\n|--|--|\n| " + "woord " * 30 + "| kort |"
        laid, widest = md_layout(lambda text, style, size: 7.0 * len(text), text, 300)
        rows = [line for line in laid if line.get("tabs")][1:]
        said = "".join(word for row in rows for word, _style, _lead in row["words"] if word != "\t")
        self.assertGreater(len(rows), 1, "the long cell goes over more lines")
        self.assertNotIn("…", said)
        self.assertEqual(said.count("woord"), 30)
        self.assertGreater(rows[0]["natural"], rows[0]["width"])
        self.assertLessEqual(widest, 300)


class NewFlagsNewWindow(unittest.TestCase):
    """Switching always-on-top gives the windows new flags. Qt used to swap the native window only after the
    show, so skip-taskbar and send-behind went to the old one: a taskbar entry per bot, a bubble above other
    apps while its face stayed behind them."""

    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])

    def test_new_flags_drop_the_old_native_window(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QWidget
        from botwidget.qt_ui.native import set_flags
        widget = QWidget()
        self.addCleanup(widget.deleteLater)
        widget.show()
        self.assertTrue(widget.testAttribute(Qt.WA_WState_Created))
        set_flags(widget, Qt.FramelessWindowHint | Qt.WindowStaysOnBottomHint)
        self.assertFalse(widget.testAttribute(Qt.WA_WState_Created), "made again, with the new flags, at the show")

    def test_restack_marks_the_window_that_is_shown(self):
        from botwidget.qt_ui import bubble_window, face
        from botwidget.qt_ui.native import native_id
        window = face.FaceWindow("t", "Test", spot=(300, 400))
        window._poll_timer.stop()
        self.addCleanup(window.close_face)
        window.show()
        marked = []
        old = bubble_window.before_show
        self.addCleanup(setattr, bubble_window, "before_show", old)
        bubble_window.before_show = lambda wid, layer="": marked.append(wid)
        window.restack()
        self.assertIn(native_id(window), marked)


class NoTaskbarButton(unittest.TestCase):
    """Faces and bubbles never get a button in the Windows taskbar."""

    def test_the_windows_helper_turns_tool_window_on_and_app_window_off(self):
        from unittest import mock
        from botwidget.system import windows
        user32 = mock.Mock()
        user32.GetWindowLongPtrW.return_value = windows.WS_EX_APPWINDOW | 0x8
        windows.hide_from_taskbar(0x1234, user32=user32)
        (_hwnd, index, style), _ = user32.SetWindowLongPtrW.call_args
        self.assertEqual(index, windows.GWL_EXSTYLE)
        self.assertEqual(style, windows.WS_EX_TOOLWINDOW | 0x8)

    def test_the_windows_helper_leaves_a_tool_window_alone_and_does_nothing_elsewhere(self):
        from unittest import mock
        from botwidget.system import windows
        user32 = mock.Mock()
        user32.GetWindowLongPtrW.return_value = windows.WS_EX_TOOLWINDOW
        windows.hide_from_taskbar(0x1234, user32=user32)
        user32.SetWindowLongPtrW.assert_not_called()
        if sys.platform != "win32":
            windows.hide_from_taskbar(0x1234)  # no user32 here: nothing happens, nothing breaks

    def test_every_top_level_window_is_a_tool_window_on_windows(self):
        from unittest import mock
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from botwidget.qt_ui import face, faces
        QApplication.instance() or QApplication([])
        with mock.patch.object(face, "FACE_IS_TOOL", True):
            window = face.FaceWindow("t", "Test", spot=(300, 400))
            window._poll_timer.stop()
            self.addCleanup(window.close_face)
            catcher = faces.ArcCatcher(None)
            self.addCleanup(catcher.deleteLater)
            for widget in (window, window.bubble, catcher):
                self.assertTrue(widget.windowFlags() & Qt.Tool, type(widget).__name__)
            window.restack()
            self.assertTrue(window.windowFlags() & Qt.Tool, "still a tool window after always-on-top switched")
            self.assertTrue(window.bubble.windowFlags() & Qt.Tool)
        import inspect
        self.assertIn("Qt.Tool", inspect.getsource(faces.Faces._spawn_guest), "arc guests")

    def test_linux_faces_stay_normal_windows(self):
        from botwidget.system import linux
        self.assertFalse(linux.FACE_IS_TOOL, "a utility window rises above other apps under mutter")


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
        me = SimpleNamespace(faces={"a": face}, _catcher=object())
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

    def test_a_bubble_waits_out_of_sight_while_its_face_is_on_another_desktop_and_opens_when_you_get_there(self):
        from unittest import mock
        from botwidget.qt_ui import bubble_window, face as face_module
        window = face_module.FaceWindow("t", "Test", spot=(300, 400))
        self.addCleanup(window.close_face)
        window._poll_timer.stop()
        blocks = face_module.conversation_blocks([{"role": "bot", "text": "Hoi"}], "T")
        with mock.patch.object(bubble_window.desktops, "face_here", return_value=False):
            window.bubble.show_blocks(blocks, "say")
            window.bubble._tick()
            self.assertFalse(window.bubble.isVisible())
        window.bubble._tick()
        self.assertTrue(window.bubble.isVisible(), "you went to the desktop of the face")

    def test_the_key_brings_a_face_from_another_desktop_and_opens_it_instead_of_closing(self):
        from types import SimpleNamespace
        calls = []
        face = SimpleNamespace(pinned=True, pin=lambda: calls.append("pin"), unpin=lambda: calls.append("unpin"),
                               bring_here=lambda: True)
        old = self.faces.activate_app
        self.addCleanup(setattr, self.faces, "activate_app", old)
        self.faces.activate_app = lambda: None
        self.faces.Faces.hotkey(SimpleNamespace(faces={"a": face}, _catcher=object()))
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

    def test_windows_has_nothing_to_choose_and_linux_does(self):
        from unittest import mock
        self.assertTrue(linux.CAN_PICK_DESKTOPS, "the X11 desktop property works on the XWayland window")
        self.assertFalse(windows.CAN_PICK_DESKTOPS)
        windows.set_desktops(0, False)
        sent = []
        fake = mock.Mock(set_desktop=lambda win, everywhere: sent.append((win, everywhere)))
        with mock.patch.object(linux, "_xlib", return_value=fake):
            linux.set_desktops(7, True)
            linux.set_desktops(8, True, travels=True)  # a bubble opens on the desktop you are on
        self.assertEqual(sent, [(7, True)], "only the face is put on every desktop")


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
        self.assertIn("Arrow at the top goes back to commands.", self.text(blocks))
        self.assertIn("☑ Fritsie", self.text(blocks))
        self.assertIn("☐ Robo", self.text(blocks))
        self.assertIn("No bots found yet", self.text(menu_pages.bots({**self.STATE, "bots": []})))

    def test_the_connections_page_has_a_switch_per_connection_that_says_what_was_found(self):
        blocks = menu_pages.connections(self.STATE)
        text = self.text(blocks)
        self.assertEqual(self.commands(blocks), ["page/commands", "connect/openbot", "connect/grokbot"])
        self.assertIn("☑ OpenBot", text)
        self.assertIn("local API is off", text)
        self.assertIn("☐ Grok Bot", text)
        self.assertIn("Not found", text)
        ready = self.text(menu_pages.connections({**self.STATE, "automation_ready": True, "gbot": True}))
        self.assertIn("local API ready", ready)
        self.assertIn("☑ Grok Bot", ready)

    def test_a_connection_that_was_turned_on_but_not_found_stays_on_and_says_it_waits(self):
        text = self.text(menu_pages.connections({**self.STATE, "wanted": ["grokbot"]}))
        self.assertIn("☑ Grok Bot", text)
        self.assertIn("Waiting for Grok Bot", text)

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


class BotSources(unittest.TestCase):
    """The /bots page says where each bot lives."""

    def test_each_bot_shows_its_source(self):
        from botwidget import grokbot, hermesbot
        try:
            from botwidget.qt_ui.faces import bot_source
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        grok, hermes = grokbot.face_id("General"), hermesbot.face_id()
        self.assertEqual([bot_source(i) for i in ("agent-1", grok, hermes)], ["OpenBot", "Grok Bot", "Hermes"])
        state = {"bots": [{"id": "agent-1", "name": "Grumpy", "on": True, "source": "OpenBot"},
                          {"id": grok, "name": "General", "on": True, "source": "Grok Bot"}]}
        text = " ".join(str(block) for block in menu_pages.bots(state))
        self.assertIn("Grumpy · OpenBot", text)
        self.assertIn("General · Grok Bot", text)


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
                            ("openbot_installed", lambda: True), ("gbot_installed", lambda: True),
                            ("automation_ready", lambda: True)):
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

            def hold_arc(self):
                pass

            def raise_bubbles(self):
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
        self.assertEqual(bubble._entry.text(), "")
        self.assertTrue(bubble._slash.isVisibleTo(bubble))
        self.assertEqual(bubble._slash.rows, list(menu_pages.COMMANDS))
        self.assertEqual(self.text(), "")
        self.assertFalse(bubble._entry.isVisibleTo(bubble))

    def test_the_command_list_closes_when_the_bubble_goes(self):
        self.right_click()
        bubble = self.window.bubble
        self.assertTrue(bubble._slash.rows)
        bubble.place("")
        self.assertEqual(bubble._slash.rows, [])
        self.right_click()
        self.window._sync_bubble(self.window._latest(), force=True)
        self.assertTrue(bubble.isVisible())
        self.assertTrue(bubble.windowOpacity() == 1.0 or bubble._growth is not None,
                        "a cancelled open must not leave the bubble invisible")

    def test_a_right_click_on_a_busy_bot_keeps_the_command_list_open(self):
        """A bot that works refreshes its thinking cloud all the time; that must not replace the menu."""
        self.window._pump_outbox = lambda: None
        busy = {"messages": [{"role": "user", "text": "Klaar?"}], "activity": "reading"}
        self.face.latest_chat = lambda thread_id, limit=8: busy
        self.window._sync_bubble(busy, force=True)
        self.window._working = True
        self.window._asked = True
        self.right_click()
        bubble = self.window.bubble
        for _ in range(3):
            self.window._sync_bubble(busy, force=True)
            self.window._sync_bubble(busy)
            self.window._check_hover()
        self.assertTrue(bubble._list_only, "the menu stays")
        bubble._tick_dots()  # the dots of the thought before must not trip over a bubble without text
        self.assertEqual(bubble._slash.rows, list(menu_pages.COMMANDS))
        self.window.on_user_message("/settings")
        self.assertIn("Sound on a new answer", self.text())

    def test_typing_a_slash_command_opens_its_page_and_sends_nothing(self):
        self.window._pump_outbox = lambda: None
        for typed, expected in (("/settings", "Sound on a new answer"), ("/bots", "Fritsie"),
                                ("/connections", "☑ OpenBot")):
            self.window.on_user_message(typed)
            self.assertIn(expected, self.text(), typed)
        self.assertEqual(self.window._outbox.items, [], "a slash command is not a message to the bot")

    def test_refresh_reloads_this_bot_and_sends_nothing(self):
        calls = []
        self.window._poll_timer.timeout.disconnect()
        self.window._poll_timer.timeout.connect(lambda: calls.append("polled"))
        self.window.on_user_message("/refresh")
        self.app.processEvents()
        self.assertEqual(calls, ["polled"])
        self.assertEqual(self.window._outbox.items, [])

    def test_refresh_says_it_is_busy_and_then_how_it_went(self):
        """Never an empty white bubble: 'Refreshing…' at once, then the chat with one line on the result."""
        from unittest import mock
        self.window._poll_timer.timeout.disconnect()
        self.right_click()
        self.window.bubble._run_command("/refresh")
        self.assertIn("Refreshing", self.text())
        self.assertTrue(self.window.bubble.isVisible())
        with mock.patch.object(self.face, "api_get", return_value={"prompts": [], "approvals": []}):
            self.window._poll_pending()
        self.assertIn("Refreshed.", self.text())
        self.assertIn("Hoi.", self.text())
        self.right_click()
        self.window.bubble._run_command("/refresh")
        with mock.patch.object(self.face, "api_get", side_effect=OSError("down")):
            self.window._poll_pending()
        self.assertIn("Could not reach OpenBot.", self.text())

    def test_back_from_a_page_shows_the_commands_and_leaves_nothing_stuck(self):
        """Settings, then the arrow back: the list shows, it closes once the pointer is gone, and right-click
        and the chat work as before."""
        from unittest import mock
        window, bubble = self.window, self.window.bubble
        self.right_click()
        bubble._run_command("/settings")
        self.assertIn("Settings", self.text())
        window._menu_command("page/commands")
        self.assertFalse(window.pinned, "the arrow back does not pin")
        self.assertEqual(bubble._slash.rows, list(menu_pages.COMMANDS))
        with mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=time.monotonic() + 60):
            bubble._tick()
        self.assertFalse(bubble.isVisible(), "the pointer is not on it: it goes")
        self.right_click()
        self.assertTrue(bubble.isVisible() and bubble._list_only, "right-click works again")
        bubble.place("")
        window._sync_bubble(window._latest(), force=True)
        self.assertIn("Hoi.", self.text(), "and the chat shows again")

    def test_feedback_says_what_happened_instead_of_an_empty_bubble(self):
        from unittest import mock
        from PySide6.QtGui import QDesktopServices
        bubble = self.window.bubble
        for opened, expected in ((True, "Opened in your browser"), (False, "Could not open the browser")):
            self.right_click()
            with mock.patch.object(QDesktopServices, "openUrl", return_value=opened) as open_url:
                bubble._run_command("/feedback")
            self.assertEqual(open_url.call_count, 1)
            self.assertTrue(bubble.isVisible())
            self.assertFalse(bubble._list_only)
            self.assertIn(expected, self.text())
        with mock.patch("botwidget.qt_ui.bubble_window.time.monotonic", return_value=time.monotonic() + 60):
            bubble._tick()
        self.assertFalse(bubble.isVisible(), "it goes by itself")

    def test_the_right_click_menu_is_flat_rows_in_the_bubble_with_nothing_cut(self):
        """One outline, the bubble's: the list draws no box of its own, and every note fits."""
        from PySide6.QtGui import QColor, QImage
        self.right_click()
        bubble = self.window.bubble
        slash = bubble._slash
        # As wide as the notes need, up to the cap; wider fonts (Windows) get their notes elided, never cut.
        from botwidget.qt_ui.bubble_window import BUBBLE_MAX_W
        cap = BUBBLE_MAX_W + 60
        self.assertGreaterEqual(bubble._geom[1], min(slash.wanted_width(), cap), "the bubble is wide enough for the notes")
        image = QImage(slash.width(), slash.height(), QImage.Format_ARGB32)
        image.fill(QColor("#ffffff"))
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QRegion
        from PySide6.QtWidgets import QWidget
        slash.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
        mid = slash.height() // 2
        self.assertEqual(image.pixelColor(0, mid).name(), "#ffffff", "no outline on the left edge")
        self.assertEqual(image.pixelColor(slash.width() - 1, mid).name(), "#ffffff", "nor on the right")

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
        self.assertEqual(self.window.bubble._entry.text(), "")
        self.assertTrue(self.window.bubble._slash.isVisibleTo(self.window.bubble))

    def test_back_from_a_page_shows_only_the_command_list_like_a_first_right_click(self):
        self.right_click()
        first = (self.window.bubble._list_only, self.window.bubble.full_text, list(self.window.bubble._slash.rows),
                 self.window.bubble._geom[1])
        self.window.on_user_message("/settings")
        self.window.bubble.command.emit("page/commands")
        bubble = self.window.bubble
        self.assertTrue(bubble.isVisible())
        self.assertEqual((bubble._list_only, bubble.full_text, list(bubble._slash.rows), bubble._geom[1]), first)
        self.assertNotIn("Hoi.", bubble.full_text, "no answer text, only the commands")

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
        index = [command for command, _note in slash.rows].index("/bots")
        row = index * slash.ROW_H + slash.ROW_H // 2 + 4
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
            white = [chunk for chunk in svg.split("<path") if f'fill="{avatar.EYE_FILL}"' in chunk]
            self.assertEqual(len(white), 2)
            self.assertTrue(all("opacity" not in chunk for chunk in white), f"happy={happy}")

    def test_happy_morphs_the_same_shape_instead_of_fading_in_a_second_one(self):
        count = lambda happy: avatar.face_svg(seed="robo", happy=happy).count('stroke="#f9f9f9"')
        self.assertEqual(count(0.0), count(0.5))
        self.assertEqual(count(0.5), count(1.0))


class IdleLook(unittest.TestCase):
    """Should idle calmly: Grok Bot's still pose, and only after a long random wait a blink or a look."""

    def motion(self, seed=1):
        from botwidget import motion
        return motion, motion.Motion(random.Random(seed))

    def run_for(self, m, seconds, dt=0.05):
        poses = []
        for _ in range(round(seconds / dt)):
            poses.append(m.step(dt))
        return poses

    def test_idle_holds_grok_bots_still_pose(self):
        motion, m = self.motion()
        pose = m.step(0.05)
        self.assertEqual((pose["pitch"], pose["yaw"], pose["roll"]), motion.STILL)
        self.assertEqual((pose["zoom"], pose["lids"], pose["face"]), (1.0, 0.0, "neutral"), "no breathing, eyes open")
        self.assertFalse(m.active, "nothing plays: the face can draw at the still rate")

    def test_nothing_happens_for_at_least_eight_seconds_between_blinks_and_looks(self):
        motion, _m = self.motion()
        for seed in range(20):
            _motion, m = self.motion(seed)
            m.wait = 0.01
            m.step(0.05)  # the first blink or look
            self.assertEqual(len(m.history), 1)
            poses = self.run_for(m, motion.IDLE_GAP_S[0] - 0.1)
            self.assertEqual(len(m.history), 1, seed)
            self.assertTrue(all((p["pitch"], p["yaw"], p["lids"]) == (*motion.STILL[:2], 0.0)
                                for p in poses[round((6 / (1 - motion.RATE_JITTER) + 0.1) / 0.05):]), seed)

    def test_the_waits_are_random_and_between_eight_and_thirty_seconds(self):
        motion, _m = self.motion()
        waits = {round(self.motion(seed)[1]._gap(), 3) for seed in range(30)}
        self.assertGreater(len(waits), 20, "random")
        self.assertTrue(all(motion.IDLE_GAP_S[0] <= w <= motion.IDLE_GAP_S[1] for w in waits))

    def test_after_the_wait_it_blinks_or_looks_around_with_a_grok_idle_clip(self):
        motion, m = self.motion()
        self.run_for(m, 10 * 60)
        self.assertGreater(len(m.history), 10 * 60 / motion.IDLE_GAP_S[1])
        self.assertLess(len(m.history), 10 * 60 / motion.IDLE_GAP_S[0] + 1)
        self.assertIn("blink", m.history)
        self.assertTrue(set(m.history) - {"blink"} <= set(motion.IDLE_LOOKS))
        self.assertGreater(m.history.count("blink"), len(m.history) / 3, "mostly blinks")

    def test_a_blink_shuts_and_opens_the_lids_like_grok_bots(self):
        motion, _m = self.motion()
        self.assertEqual(motion.blink_at(0.0), 0.0)
        self.assertAlmostEqual(motion.blink_at(motion.BLINK_SHUT), 1.0)
        self.assertEqual(motion.blink_at(motion.BLINK_OPEN), 0.0)
        self.assertGreater(motion.blink_at(0.06), 0.3)

    def test_clips_are_sampled_on_their_own_eases(self):
        motion, _m = self.motion()
        self.assertAlmostEqual(motion.ease(0.5, motion.STANDARD_EASE), 0.5, places=4)
        self.assertLess(motion.ease(0.2, motion.STANDARD_EASE), 0.2, "eases in")
        keys = ((0.0, (0.0,), (0, 0, 1, 1)), (1.0, (10.0,), (0, 0, 1, 1)))
        self.assertEqual(motion.at(keys, -1), (0.0,))
        self.assertEqual(motion.at(keys, 5), (10.0,), "held after the last key")
        self.assertAlmostEqual(motion.at(keys, 0.5)[0], 5.0, places=3)
        b = motion.clip_at("Idle_B", 1.62)
        self.assertAlmostEqual(b["pitch"] if "pitch" in b else b["rotation"][0], 0.1, places=1)
        self.assertAlmostEqual(b["zoom"], 0.64 / 0.6, places=2, msg="Idle_B swells, only while it plays")

    def test_idle_a_spins_once_and_ends_facing_front(self):
        motion, _m = self.motion()
        self.assertGreater(motion.clip_at("Idle_A", 5.5)["rotation"][1], 180)
        self.assertEqual(motion.clip_at("Idle_A", 6.0)["rotation"][1], 0)


class Moods(unittest.TestCase):
    """Should show what happens: every event and mood has its own Grok Bot clip and face."""

    def setUp(self):
        from botwidget import motion
        self.motion = motion
        self.m = motion.Motion(random.Random(3))

    def faces_while(self, seconds, dt=0.05):
        return [self.m.step(dt) for _ in range(round(seconds / dt))]

    def test_every_event_maps_to_its_grok_clip_and_face(self):
        expected = {"reply": ("Done_A", "happy"), "new_message": ("Idle_B", "surprised"), "sent": ("nod", None),
                    "error": ("Blocked_B", "sad"), "no_route": ("Blocked_A", "confused"), "click": ("bounce", "happy")}
        self.assertEqual({name: event[:2] for name, event in self.motion.EVENTS.items()}, expected)
        self.assertEqual(self.motion.MOODS["thinking"], ("Working_B", "inspecting"))
        self.assertEqual(self.motion.MOODS["ask"], ("Idle_D", "neutral"))
        self.assertEqual(self.motion.MOODS["offline"], (None, "sleepy"))
        for clip, _face, *_rest in self.motion.EVENTS.values():
            self.assertTrue(clip in self.motion.CLIPS or clip in self.motion.POKES, clip)

    def test_a_reply_hops_with_happy_eyes_and_then_settles(self):
        self.m.event("reply")
        self.faces_while(self.motion.EVENT_DELAY_S)
        poses = self.faces_while(self.motion.CLIPS["Done_A"]["duration"])
        self.assertTrue(all(p["face"] == "happy" for p in poses[: -round(self.motion.EVENT_DELAY_S / 0.05) - 2]))
        self.assertGreater(max(p["y"] for p in poses), 0.2, "it hops")
        after = self.faces_while(0.1)[-1]
        self.assertEqual((after["face"], after["yaw"]), ("neutral", self.motion.STILL[1]))
        self.assertFalse(self.m.active)

    def test_a_message_nobody_asked_for_surprises(self):
        self.m.event("new_message")
        self.assertEqual(self.faces_while(0.5)[-1]["face"], "surprised")

    def test_sending_nods(self):
        self.m.event("sent")
        poses = self.faces_while(self.motion.POKES["nod"] * 1.2 + self.motion.EVENT_DELAY_S)
        self.assertAlmostEqual(max(p["pitch"] for p in poses), self.motion.STILL[0] + 16, delta=0.5)

    def test_a_refusal_is_sad_and_stays_sad_a_moment(self):
        self.m.event("error")
        self.faces_while(self.motion.CLIPS["Blocked_B"]["duration"] + 0.5)
        self.assertEqual(self.m.step(0.05)["face"], "sad")
        self.faces_while(2.0)
        self.assertEqual(self.m.step(0.05)["face"], "neutral")

    def test_thinking_inspects_and_loops_until_the_answer(self):
        self.m.set_mood("thinking")
        poses = self.faces_while(12)
        self.assertTrue(all(p["face"] in ("inspecting", "surprised") for p in poses), "Working_B's own faces")
        self.assertTrue(self.m.active)
        self.m.set_mood("idle")
        self.assertEqual(self.m.step(0.05)["yaw"], self.motion.STILL[1])
        self.assertFalse(self.m.active)

    def test_no_route_is_confused_then_sleepy_and_still(self):
        self.m.event("no_route")
        self.m.set_mood("offline")
        self.assertEqual(self.faces_while(1.0)[-1]["face"], "confused")
        self.faces_while(self.motion.CLIPS["Blocked_A"]["duration"])
        poses = self.faces_while(40)
        self.assertTrue(all(p["face"] == "sleepy" and p["yaw"] == self.motion.STILL[1] for p in poses))
        self.assertFalse(self.m.active, "asleep, the face is drawn at the still rate")

    def test_an_event_finishes_before_the_mood_loop_takes_over(self):
        self.m.event("sent")
        self.m.set_mood("thinking")
        self.assertEqual(self.m.playing[0], "nod")
        self.faces_while(self.motion.POKES["nod"] / (1 - self.motion.RATE_JITTER) + self.motion.EVENT_DELAY_S + 0.1)
        self.assertEqual(self.m.playing[0], "Working_B")

    def test_a_question_listens_with_idle_d(self):
        self.m.set_mood("ask")
        self.assertEqual(self.m.playing[0], "Idle_D")

    def test_every_grok_face_draws_for_every_kind_of_face(self):
        for face in avatar.GROK_FACES:
            for kw in ({"seed": "robo"}, {"seed": "grok:A", "avatar": {"shape": "house", "color": "red"}},
                       {"seed": "grok:B", "avatar": {"shape": "blob", "color": "blue"}}):
                svg = avatar.face_svg(expression=("neutral", face, 0.5), **kw)
                eyes = eye_paths(svg)
                self.assertEqual(len(eyes), 2, (face, kw))
                self.assertEqual(len(eyes[0]), len(eye_paths(avatar.face_svg(**kw))[0]), "morphs point for point")

    def test_inspecting_has_one_big_and_one_small_eye(self):
        svg = avatar.face_svg(seed="grok:B", avatar={"shape": "blob", "color": "blue"},
                              expression=("neutral", "inspecting", 1.0))
        left, right = sorted(eye_paths(svg), key=lambda eye: min(x for x, _ in eye))
        width = lambda eye: max(x for x, _ in eye) - min(x for x, _ in eye)
        self.assertAlmostEqual(width(left) / width(right), 2.0, delta=0.2)


def _polygon(d: str) -> list:
    return [tuple(map(float, xy.split())) for xy in d[1:].rstrip("Z").split("L")]


def _outside_by(point, polygon) -> float:
    """0 for a point inside the polygon, else how far it is from it."""
    x, y = point
    inside = False
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    if inside:
        return 0.0
    best = math.inf
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
        dx, dy = x1 - x0, y1 - y0
        t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / ((dx * dx + dy * dy) or 1.0)))
        best = min(best, math.hypot(x - x0 - t * dx, y - y0 - t * dy))
    return best


def _every_face() -> dict:
    """A face for every OpenBot shape and every Grok Bot shape."""
    faces, seed = {}, 0
    while len(faces) < len(avatar.SUPPORTED_SHAPES) and seed < 5000:
        shape = avatar.avatar_profile(f"s{seed}", None, None)["shape"]
        faces.setdefault(f"openbot {shape}", {"seed": f"s{seed}"})
        seed += 1
    for shape in avatar.GROK_MARKS:
        faces[f"grok {shape}"] = {"seed": "grok:X", "avatar": {"shape": shape, "color": "blue"}}
    return faces


def _clip_poses(step: float):
    """Every pose of Grok Bot's clips and pokes, step seconds apart; the head's turn on a 5 degree grid,
    so that the turned outlines are shared and the tests stay quick."""
    from botwidget import motion
    lengths = {name: clip["duration"] for name, clip in motion.CLIPS.items()} | dict(motion.POKES)
    for name, length in lengths.items():
        for i in range(int(length / step) + 1):
            m = motion.Motion(random.Random(0))
            m.playing, m.rate = (name, i * step, False, None), 1.0
            pose = m.step(0.0)
            pose["pitch"], pose["yaw"] = (round(pose[key] / 5) * 5 for key in ("pitch", "yaw"))
            yield name, pose


class EyesOnTheBody(unittest.TestCase):
    """Should keep both eyes on the body, inside its outline, however it turns and whatever its face."""

    def test_the_eyes_stay_inside_the_silhouette_in_every_turn_and_clip(self):
        turns = [(p, y, 0.0) for p in range(-30, 31, 30) for y in range(-60, 61, 15)]
        turns += [(pose["pitch"], pose["yaw"], pose["roll"]) for _n, pose in _clip_poses(1.0)]
        for name, kw in _every_face().items():
            for face in ("neutral", "surprised"):
                for pitch, yaw, roll in turns:
                    svg = avatar.face_svg(pitch=pitch, yaw=yaw, roll=roll, expression=("neutral", face, 1.0), **kw)
                    body = _polygon(body_d(svg))
                    for eye in eye_paths(svg):
                        worst = max(_outside_by(point, body) for point in eye)
                        self.assertLess(worst, 0.1, f"{name} {face} at {pitch}, {yaw}, {roll}")

    def test_openbot_eyes_lie_on_the_front_of_their_own_body(self):
        flat = avatar.openbot_surface("triangle", 0.3, 0.0)
        self.assertEqual(flat, (avatar.EXTRUDE[0], (0.0, 0.0, 1.0)), "an extruded body: its flat front")
        z, _normal = avatar.openbot_surface("galet", 0.0, 0.0)
        self.assertAlmostEqual(z, avatar.LOFT_DEPTH, places=3)
        self.assertLess(avatar.openbot_surface("galet", 0.6, 0.0)[0], z, "a loft is lower towards its edge")
        ball, normal = avatar.openbot_surface("cercle", 0.6, 0.0)
        self.assertAlmostEqual(ball, 0.8, places=3, msg="the circle is a ball")
        self.assertEqual(normal, (0.6, 0.0, ball))


class InTheWindow(unittest.TestCase):
    """Should keep the whole face inside its window in every frame of every hop, squash and swell."""

    TRANSFORM = re.compile(r'translate\(([-\d.]+) ([-\d.]+)\) rotate\(([-\d.]+) [\d.]+ [\d.]+\) '
                           r'translate\([\d.]+ [\d.]+\) scale\(([-\d.]+) ([-\d.]+)\)')

    def drawn(self, svg: str) -> list:
        """The body's outline in window px, after the face's own transform."""
        tx, ty, angle, sx, sy = map(float, self.TRANSFORM.search(svg).groups())
        c = avatar.AVATAR_SIZE / 2
        cos, sin = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        out = []
        for x, y in _polygon(body_d(svg)):
            x, y = (x - c) * sx, (y - c) * sy
            out.append((c + x * cos - y * sin + tx, c + x * sin + y * cos + ty))
        return out

    def test_every_clip_frame_stays_inside_the_window(self):
        from botwidget import motion
        # Every half second, and each clip's highest hop, deepest squash, widest stretch and biggest swell.
        everything = list(_clip_poses(0.05))
        frames = everything[::10]
        for clip in {name for name, _pose in everything}:
            poses = [pose for name, pose in everything if name == clip]
            for key in ("y", "sy", "sx", "zoom", "x"):
                frames += [(clip, max(poses, key=lambda pose: pose[key])), (clip, min(poses, key=lambda pose: pose[key]))]
        for name, kw in _every_face().items():
            for clip, pose in frames:
                lift, shift = motion.offsets(pose, avatar.CIRCLE_R)
                svg = avatar.face_svg(pitch=pose["pitch"], yaw=pose["yaw"], roll=pose["roll"], lift=lift,
                                      shift=shift, zoom=pose["zoom"], squash=(pose["sx"], pose["sy"]), **kw)
                points = self.drawn(svg)
                self.assertGreaterEqual(min(min(x, y) for x, y in points), 0.0, f"{name} in {clip}")
                self.assertLessEqual(max(max(x, y) for x, y in points), avatar.AVATAR_SIZE, f"{name} in {clip}")

    def test_a_hop_still_hops(self):
        rest = avatar.fit_in_window(avatar.grok_body_points("blob", 0, 0), 1.0, 1.0, 0.0, 0.0, 0.0)
        self.assertEqual(rest, (1.0, 0.0, 0.0), "nothing changes at rest")
        k, lift, _shift = avatar.fit_in_window(avatar.grok_body_points("blob", 0, 0), 1.0, 1.0, 0.0, 7.8, 0.0)
        self.assertGreater(lift, 3.0)
        self.assertGreaterEqual(k, avatar.MIN_FIT)


class NotInStep(unittest.TestCase):
    """Should never move faces in lockstep: every face has its own seed, first wait, pace and phase."""

    def test_faces_started_together_wait_differently_and_keep_their_own_pace(self):
        from botwidget import motion
        faces = [motion.Motion(seed=f"face{i}") for i in range(6)]
        self.assertEqual(len({round(m.wait, 3) for m in faces}), 6, "a different first wait each")
        self.assertTrue(all(motion.FIRST_WAIT_S[0] <= m.wait <= motion.FIRST_WAIT_S[1] for m in faces))
        self.assertEqual(len({round(m.rate, 4) for m in faces}), 6, "a different pace each")
        self.assertTrue(all(abs(m.rate - 1) <= motion.RATE_JITTER for m in faces))
        firsts = []
        for m in faces:
            t = 0.0
            while not m.history:
                m.step(0.05)
                t += 0.05
            firsts.append(round(t, 2))
        self.assertEqual(len(set(firsts)), 6, "nobody blinks or looks at the same moment")

    def test_a_mood_loop_starts_anywhere_in_its_clip(self):
        from botwidget import motion
        phases = set()
        for i in range(6):
            m = motion.Motion(seed=f"face{i}")
            m.set_mood("thinking")
            phases.add(round(m.playing[1], 3))
        self.assertEqual(len(phases), 6)

    def test_an_event_reaches_the_faces_a_little_apart(self):
        from botwidget import motion
        delays = set()
        for i in range(6):
            m = motion.Motion(seed=f"face{i}")
            m.event("no_route")
            self.assertLessEqual(-m.playing[1], motion.EVENT_DELAY_S)
            delays.add(round(m.playing[1], 3))
        self.assertGreater(len(delays), 4)

    def test_every_face_window_gets_its_own_seed(self):
        try:
            from PySide6.QtWidgets import QApplication

            from botwidget.qt_ui import face
        except ImportError as error:
            self.skipTest(f"no Qt: {error}")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        QApplication.instance() or QApplication([])
        windows = [face.FaceWindow(agent, agent, spot=(100 + 90 * i, 100)) for i, agent in enumerate(("a", "b", "c"))]
        try:
            self.assertEqual(len({round(w.motion.wait, 4) for w in windows}), 3)
        finally:
            for w in windows:
                w.close_face()


class GrokEyes(unittest.TestCase):
    """Should blink and smile with the eyes Grok Bot's engine draws."""

    def test_a_blink_presses_the_pill_to_a_lying_one(self):
        self.assertEqual(avatar.eye_length(16, 8, 1.0), 16)
        self.assertAlmostEqual(avatar.eye_length(16, 8, 0.0), avatar.LID_SHUT * 8)
        self.assertLess(avatar.eye_length(16, 8, 0.0), 8, "shut, the pill lies down")
        self.assertGreater(avatar.eye_length(16, 8, 0.5), avatar.eye_length(16, 8, 0.0))

    def test_a_happy_eye_is_an_arc_as_thick_as_the_eye(self):
        svg = avatar.face_svg(seed="grok:Admin", avatar={"shape": "sparkle", "color": "orange"}, happy=1.0)
        arcs = eye_paths(svg)
        self.assertEqual(len(arcs), 2)
        eyes = avatar.GROK_MARKS["sparkle"][1]
        widest = max(eye[2] for eye in eyes) * avatar.CIRCLE_R
        for arc in arcs:
            ys = [y for _, y in arc]
            self.assertGreater(max(ys) - min(ys), 0.5 * widest, "thick, not a thin line")
        left, right = sorted(arcs, key=lambda arc: min(x for x, _ in arc))
        self.assertLess(max(x for x, _ in left), min(x for x, _ in right) + 0.5, "the two arcs never touch")

    def test_at_rest_every_grok_shape_shows_its_eyes_where_grok_bot_draws_them(self):
        pitch, yaw, roll = avatar.GROK_STILL
        centre = avatar.AVATAR_SIZE / 2
        for shape, (_outline, marks) in avatar.GROK_MARKS.items():
            if shape == "blob":
                continue
            svg = avatar.face_svg(seed="grok:Builder", avatar={"shape": shape, "color": "brown"},
                                  pitch=pitch, yaw=yaw, roll=roll)
            drawn = sorted(eye_paths(svg), key=lambda eye: min(x for x, _ in eye))
            self.assertEqual(len(drawn), 2, shape)
            for eye, (x, y, _w, _length, _tilt) in zip(drawn, marks):
                mx = (min(p[0] for p in eye) + max(p[0] for p in eye)) / 2
                my = (min(p[1] for p in eye) + max(p[1] for p in eye)) / 2
                self.assertAlmostEqual(mx, centre + x * avatar.CIRCLE_R, delta=1.0, msg=shape)
                self.assertAlmostEqual(my, centre + y * avatar.CIRCLE_R, delta=1.0, msg=shape)

    def test_at_rest_every_grok_body_is_grok_bots_own_art(self):
        def box(points):
            return (min(x for x, _ in points), max(x for x, _ in points),
                    min(y for _, y in points), max(y for _, y in points))
        for shape, (outline, _eyes) in avatar.GROK_MARKS.items():
            if shape == "blob":
                continue
            drawn = box(avatar.grok_body_points(shape, *avatar.GROK_STILL))
            for got, art in zip(drawn, box(outline)):
                self.assertAlmostEqual(got, art, delta=0.04, msg=shape)


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

    def test_a_turn_turns_the_body_its_shading_and_its_eyes(self):
        front = avatar.face_svg(seed="robo")
        right = avatar.face_svg(dx=8.0, dy=0.0, seed="robo")
        self.assertNotEqual(body_d(front), body_d(right), "the outline of a 3D body changes when it turns")
        light = lambda svg: float(re.search(r'id="hl" cx="([\d.]+)"', svg).group(1))
        self.assertGreater(light(right), light(front), "its shading turns with it")
        mid = lambda svg: sum(sum(x for x, _ in e) / len(e) for e in eye_paths(svg)) / 2
        # On the flat front of a slab, a little in front of the middle, as Grok Bot seats them.
        self.assertGreater(mid(right), mid(front) + 1.5, "the eyes go with the front of the head")


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
                try:
                    if open(marker).read() == "new":
                        break
                except FileNotFoundError:
                    pass  # the folder is between the old app and the new one
            self.assertEqual(open(marker).read(), "new")
            for _ in range(30):  # the cleanup follows right after the swap
                if os.listdir(os.path.join(home, "Apps")) == ["Bot Widget.app"]:
                    break
                time.sleep(0.1)
            self.assertEqual(sorted(os.listdir(os.path.join(home, "Apps"))), ["Bot Widget.app"])


class SpawnScript(unittest.TestCase):
    """The update script must still be there when /bin/sh opens it; it cleans itself up."""

    @unittest.skipIf(sys.platform == "win32", "no /bin/sh")
    def test_the_script_runs_and_removes_its_own_file(self):
        import subprocess
        from unittest import mock
        from botwidget.system import posix
        with tempfile.TemporaryDirectory() as folder:
            out = os.path.join(folder, "ran")
            with mock.patch.object(posix.subprocess, "Popen") as popen:
                posix.spawn_script('#!/bin/sh\necho ok > "$1"\n', out)
            script = popen.call_args[0][0][1]
            self.assertTrue(os.path.exists(script), "still there for a shell that starts late")
            subprocess.run(["/bin/sh", *popen.call_args[0][0][1:]], check=True)
            with open(out) as fh:
                self.assertEqual(fh.read().strip(), "ok")
            self.assertFalse(os.path.exists(script), "the script removed its own file")


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

    def test_a_200_body_with_leading_bom_and_real_json_is_not_empty(self):
        # A BOM before real JSON bytes must NOT be treated as empty answer.
        body = b"\xef\xbb\xbf{\"text\":\"hi\"}"
        with self.subTest(body=body):
            with _FlakyApi([200], bodies=[body]):
                result = openbot.api_post("/v1/agents/me/messages",
                                          {"text": "hi", "clientMessageId": "abc"})
                self.assertTrue(result.ok, f"body={body!r} should parse as JSON, got error={result.error!r}")
                self.assertEqual(result.status, 200)
                self.assertNotEqual(result.error, "empty answer",
                                    f"body={body!r} should not be refused as empty answer")

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


class CheckoutPull(unittest.TestCase):
    def git(self, folder, *args):
        import subprocess
        subprocess.run(["git", "-C", folder, "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True,
                       capture_output=True)

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.origin, self.mine, self.other = (os.path.join(root, name) for name in ("origin", "mine", "other"))
        self.git(root, "init", "-q", "--bare", "-b", "main", self.origin)
        self.git(root, "clone", "-q", self.origin, self.mine)
        self.git(root, "clone", "-q", self.origin, self.other)
        self.commit(self.mine, "a.txt", "one")
        self.git(self.mine, "push", "-q", "origin", "main")
        self.git(self.other, "pull", "-q", "origin", "main")

    def commit(self, folder, name, text):
        with open(os.path.join(folder, name), "w") as fh:
            fh.write(text)
        self.git(folder, "add", name)
        self.git(folder, "commit", "-q", "-m", text)

    def publish(self, text="two"):
        self.commit(self.other, "a.txt", text)
        self.git(self.other, "push", "-q", "origin", "main")

    def read(self):
        with open(os.path.join(self.mine, "a.txt")) as fh:
            return fh.read()

    def test_new_commits_on_main_are_pulled(self):
        from botwidget import checkout
        self.publish()
        self.assertTrue(checkout.pull(self.mine))
        self.assertEqual(self.read(), "two")
        self.assertFalse(checkout.pull(self.mine), "nothing new")

    def test_a_checkout_with_changes_of_its_own_is_left_alone(self):
        from botwidget import checkout
        self.publish()
        with open(os.path.join(self.mine, "a.txt"), "w") as fh:
            fh.write("mine")
        self.assertFalse(checkout.pull(self.mine))
        self.assertEqual(self.read(), "mine")

    def test_another_branch_and_commits_not_pushed_are_left_alone(self):
        from botwidget import checkout
        self.publish()
        self.commit(self.mine, "b.txt", "local")
        self.assertFalse(checkout.pull(self.mine), "cannot fast-forward")
        self.git(self.mine, "reset", "-q", "--hard", "HEAD~1")
        self.git(self.mine, "checkout", "-q", "-b", "feature")
        self.assertFalse(checkout.pull(self.mine))
        self.assertEqual(self.read(), "one")

    def test_a_missing_remote_is_silent(self):
        from botwidget import checkout
        self.git(self.mine, "remote", "set-url", "origin", os.path.join(self.tmp.name, "nowhere"))
        self.assertFalse(checkout.pull(self.mine))


if __name__ == "__main__":
    unittest.main()


class Body3D(unittest.TestCase):
    """Should draw every face as Grok Bot draws its avatars: a turned 3D body with its eyes on it."""

    def test_an_unturned_body_is_its_own_outline(self):
        points = body3d.radii_points(avatar.silhouette_radii("hexagone"))
        self.assertEqual(body3d.outline(points, 0.0, 0.0), points)
        art = avatar.GROK_MARKS["house"][0]
        self.assertEqual(body3d.outline(art, *avatar.MARK_REST, avatar.MARK_REST), tuple(art),
                         "Grok Bot's still art is the body in its still pose")

    def test_a_turned_body_changes_its_outline_but_not_its_size(self):
        points = body3d.radii_points(avatar.silhouette_radii("hexagone"))
        turned = body3d.outline(points, -10.0, 30.0)
        self.assertNotEqual(turned, points)
        widest = max(math.hypot(x, y) for x, y in points)
        self.assertLess(max(math.hypot(x, y) for x, y in turned), widest * 1.1)
        self.assertGreater(max(math.hypot(x, y) for x, y in turned), widest * 0.85)

    def test_turn_from_undoes_the_rest_turn(self):
        rot = body3d.turn_from((-15.9, 33.3), -15.9, 33.3)
        for p in ((0.3, -0.2, 0.9), (0.0, 0.0, 1.0)):
            for a, b in zip(rot(*p), p):
                self.assertAlmostEqual(a, b, places=9)

    def eye_size(self, svg):
        widths = [max(x for x, _ in e) - min(x for x, _ in e) for e in eye_paths(svg)]
        return sorted(widths)

    def test_eyes_foreshorten_when_the_head_turns_away(self):
        for kw in ({"seed": "zeta"}, {"seed": "grok:General", "avatar": {"shape": "blob", "color": "black"}}):
            front = self.eye_size(avatar.face_svg(**kw))
            turned = self.eye_size(avatar.face_svg(dx=14, **kw))
            self.assertLess(turned[0], front[0] - 0.5, kw)

    def test_eyes_bend_with_the_surface(self):
        rot = body3d.turn(0.0, 35.0)
        line = [(0.0, v / 8 - 0.5) for v in range(9)]
        laid = body3d.eye_on_surface((0.4, 0.0, math.sqrt(1 - 0.16)), [(0.0, v) for _, v in line], rot)
        (x0, y0), (x1, y1) = laid[0], laid[-1]
        bend = max(abs((x1 - x0) * (y0 - y) - (x0 - x) * (y1 - y0)) / math.dist(laid[0], laid[-1])
                   for x, y in laid)
        self.assertGreater(bend, 0.01, "a straight eye curves on a turned ball")

    def test_eyes_that_turned_away_are_not_drawn_and_eyes_stay_on_the_body(self):
        self.assertIsNone(body3d.eye_on_surface((0.0, 0.0, 1.0), [(0.0, 0.0), (0.01, 0.0)], body3d.turn(0.0, 120.0)))
        svg = avatar.face_svg(dx=14, seed="robo")
        self.assertIn('clip-path="url(#body)"', svg)

    def test_openbot_and_grok_bot_faces_share_one_eye_system(self):
        for kw in ({"seed": "agent-7"}, {"seed": "grok:Admin", "avatar": {"shape": "sparkle", "color": "orange"}}):
            self.assertEqual(len(eye_paths(avatar.face_svg(**kw))), 2)
            self.assertEqual(len(eye_paths(avatar.face_svg(scale=0.0, **kw))), 2, "blinking")
            self.assertEqual(len(eye_paths(avatar.face_svg(happy=1.0, **kw))), 2, "happy")
            self.assertNotIn("stroke=", avatar.face_svg(dx=-9, **kw))

    def test_zoom_sizes_the_face(self):
        big = avatar.face_svg(seed="zeta", zoom=1.05)
        self.assertIn("scale(1.0500 1.0500)", big)

    def test_turns_follow_grok_bots_order_and_directions(self):
        from botwidget import body3d
        right = body3d.turn(0, 90)(0.0, 0.0, 1.0)
        self.assertAlmostEqual(right[0], 1.0, msg="a positive yaw turns the front to the right")
        down = body3d.turn(30, 0)(0.0, 0.0, 1.0)
        self.assertGreater(down[1], 0.4, "a positive pitch turns it down")
        # Grok Bot turns by roll after pitch after yaw.
        both = body3d.turn(20, 30, 10)(0.0, 0.0, 1.0)
        yawed = body3d.turn(0, 30)(0.0, 0.0, 1.0)
        pitched = body3d.turn(20, 0)(*yawed)
        rolled = body3d.turn(0, 0, 10)(*pitched)
        for got, want in zip(both, rolled):
            self.assertAlmostEqual(got, want)

    def test_every_grok_body_turns_in_3d_and_stays_on_the_canvas(self):
        from botwidget.grok_bodies import GROK_BODIES
        for shape in GROK_BODIES:
            rest = avatar.grok_body_points(shape, 0, 0)
            turns = [avatar.grok_body_points(shape, pitch, yaw) for pitch, yaw in ((0, 45), (-30, 0), (20, -60))]
            if shape != "blob":  # a ball looks the same from everywhere
                self.assertTrue(any(turned != rest for turned in turns), shape)
            for turned in turns:
                self.assertLessEqual(max(math.hypot(x, y) for x, y in turned), 1.17, shape)

    def test_a_cube_seen_from_the_side_shows_its_depth(self):
        width = lambda points: max(x for x, _ in points) - min(x for x, _ in points)
        front, side = (width(avatar.grok_body_points("square", 0, yaw)) for yaw in (0, 90))
        self.assertLess(side, front * 0.4, "from the side Grok Bot's square is a thin slab")
        self.assertGreater(side, 0.5, "with its own thickness")
        pebble = [width(avatar.grok_body_points("pebble", 0, yaw)) for yaw in (0, 90)]
        self.assertAlmostEqual(pebble[0], pebble[1], places=2, msg="a pebble is turned on a lathe")
