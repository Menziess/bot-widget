"""Logica zonder scherm: eye_aim, markdown en het gezicht uit de botdefinitie.

Geen Gtk-venster: alleen rekenen en parsen, zodat dit ook op een CI-machine
zonder beeldscherm draait.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from botwidget import avatar, bubble, bubble_layout, config, instance, markdown, openbot, theme
from botwidget.system.current import process_cmdline


class EyeAim(unittest.TestCase):
    """De blik: ver weg is rust, dichtbij volgen, op de neus samenknijpen."""

    def test_far_away_is_rest(self):
        self.assertEqual(avatar.eye_aim(400, 0), (0.0, 0.0, 0.0, 1.0))
        self.assertEqual(avatar.eye_aim(0, 900), (0.0, 0.0, 0.0, 1.0))
        self.assertEqual(avatar.eye_aim(avatar.GAZE_NEAR, 0), (0.0, 0.0, 0.0, 1.0))

    def test_on_the_nose_squeezes(self):
        self.assertEqual(avatar.eye_aim(0, 0), (0.0, 0.0, 6.0, 0.6))

    def test_close_follows_the_pointer(self):
        dx, dy, conv, scale = avatar.eye_aim(10, 0)
        self.assertGreater(dx, 0)
        self.assertEqual(dy, 0)
        self.assertGreater(conv, 0)
        self.assertLess(conv, 6)
        self.assertLess(scale, 1.0)

    def test_direction_is_kept(self):
        right = avatar.eye_aim(10, 0)
        left = avatar.eye_aim(-10, 0)
        self.assertEqual(round(right[0], 6), round(-left[0], 6))
        up = avatar.eye_aim(0, -10)
        self.assertLess(up[1], 0)

    def test_shift_is_capped(self):
        for vx, vy in ((1, 1), (5, 5), (40, 40), (-40, 3)):
            dx, dy = avatar.eye_aim(vx, vy)[:2]
            self.assertLessEqual(abs(dx), 8.0)
            self.assertLessEqual(abs(dy), 8.0)


class Markdown(unittest.TestCase):
    """Markdown naar blokken: koppen, lijsten, code, links."""

    def test_inline_styles(self):
        self.assertEqual(markdown.md_inline("gewoon"), [("gewoon", "")])
        self.assertEqual(markdown.md_inline("**vet**"), [("vet", "b")])
        self.assertEqual(markdown.md_inline("*schuin*"), [("schuin", "i")])
        self.assertEqual(markdown.md_inline("`code`"), [("code", "code")])

    def test_link_is_label_plus_host(self):
        chunks = markdown.md_inline("[docs](https://example.com/pad?x=1)")
        self.assertEqual(chunks[0], ("docs", "link"))
        self.assertEqual(chunks[1], (" (example.com)", "dim"))

    def test_blocks(self):
        blocks = markdown.md_blocks("# Kop\n\ntekst\n\n- een\n- twee")
        kinds = [b["kind"] for b in blocks]
        self.assertEqual(kinds[0], "text")
        self.assertTrue(blocks[0]["head"])
        self.assertEqual(theme.MD_HEAD_SIZE[1], blocks[0]["size"])
        bullets = [b for b in blocks if b.get("prefix") == "\u2022 "]
        self.assertEqual(len(bullets), 2)

    def test_code_block_keeps_lines(self):
        blocks = markdown.md_blocks("```\nregel een\nregel twee\n```")
        self.assertEqual([b["kind"] for b in blocks], ["code"])
        self.assertEqual(blocks[0]["lines"], ["regel een", "regel twee"])

    def test_code_block_is_cut_off(self):
        body = "\n".join(f"r{i}" for i in range(theme.BUBBLE_CODE_LINES + 3))
        lines = markdown.md_blocks("```\n" + body + "\n```")[0]["lines"]
        self.assertEqual(len(lines), theme.BUBBLE_CODE_LINES + 1)
        self.assertEqual(lines[-1], "\u2026")

    def test_block_text_is_plain(self):
        self.assertEqual(markdown.block_text(markdown.md_blocks("**vet** en *schuin*")), "vet en schuin")
        self.assertEqual(markdown.block_text(markdown.md_blocks("# Kop")), "Kop")
        self.assertEqual(markdown.block_text(markdown.md_blocks("- een\n- twee")), "\u2022 een\n\u2022 twee")

    def test_conversation_labels(self):
        blocks = markdown.conversation_blocks(
            [{"role": "user", "text": "hoi"}, {"role": "bot", "text": "hallo"}], "Robo")
        labels = [b["chunks"][0][0] for b in blocks
                  if b.get("chunks") and b["chunks"][0][1] == "b"]
        self.assertEqual(labels, ["You", "Robo"])

    def test_nothing_new_means_nothing(self):
        self.assertEqual(markdown.conversation_blocks([], "Robo"), [])


class AvatarProfile(unittest.TestCase):
    """Silhouet, uitdrukking en kleur uit de seed, net als OpenBot."""

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
        # FNV-1a over "a" is 0xe40c292c; op lengte 7 is dat 4.
        self.assertEqual(avatar.stable_index("a", 7), 0xE40C292C % 7)


class ProcessCmdline(unittest.TestCase):
    """De single-instance check moet ook zonder /proc werken."""

    @unittest.skipIf(sys.platform == "win32", "Windows kan de commandoregel nog niet lezen")
    def test_own_process_is_a_python_commandline(self):
        self.assertIn(b"python", process_cmdline(os.getpid()).lower())

    def test_missing_process_is_empty(self):
        self.assertEqual(process_cmdline(2 ** 22 + 12345), b"")

    def test_pidfile_lives_in_the_platform_tempdir(self):
        self.assertEqual(os.path.dirname(instance.PIDFILE), tempfile.gettempdir())


class BubbleLayout(unittest.TestCase):
    """De wolk breekt regels met de meting van de toolkit; hier een vaste letterbreedte."""

    @staticmethod
    def measure(text, style, size):
        return len(text) * 7.0

    def test_long_text_breaks_within_the_width(self):
        lines, widest = bubble_layout.md_layout(self.measure, "woord " * 40, 200)
        self.assertGreater(len(lines), 1)
        self.assertLessEqual(widest, 200)

    def test_short_text_stays_on_one_line(self):
        lines, _ = bubble_layout.md_layout(self.measure, "hallo wereld", 300)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["xs"], [0, 42])

    def test_unbreakable_word_is_split(self):
        lines, _ = bubble_layout.md_layout(self.measure, "x" * 100, 120)
        self.assertGreater(len(lines), 1)


class Settings(unittest.TestCase):
    """widget.json: zonder bestand staat het gezicht boven, en alleen bekende sleutels worden bewaard."""

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
    """OpenBot en Grok Bot worden herkend aan hun map en hun gbot-opdracht."""

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


class Clouds(unittest.TestCase):
    """De denkwolk heeft bolletjes rond het vlak en een staart van kleiner wordende bolletjes."""

    def test_trail_points_down_or_up(self):
        down = bubble.cloud_body_svg(200, 100, tip_x=100, tip_up=False)
        up = bubble.cloud_body_svg(200, 100, tip_x=100, tip_up=True)
        self.assertEqual(down.count("<circle"), up.count("<circle"))
        self.assertNotEqual(down, up)

    def test_cloud_and_chat_bubble_share_a_canvas_size(self):
        cloud = bubble.cloud_body_svg(200, 100)
        chat = bubble.bubble_body_svg(200, 100)

        def canvas(svg):
            return svg.split('width="')[1].split('"')[0], svg.split('height="')[1].split('"')[0]

        self.assertEqual(canvas(cloud), canvas(chat))

    def test_shadow_matches_body_circles(self):
        self.assertEqual(bubble.cloud_shadow_svg(200, 100).count("<circle"),
                         bubble.cloud_body_svg(200, 100).count("<circle") // 2)


if __name__ == "__main__":
    unittest.main()
