"""Logic without a screen: eye_aim, markdown and the face from the bot definition.

No window or toolkit: only calculating and parsing, so this also runs on a CI
machine without a display.
"""

import io
import json
import os
import plistlib
import sys
import tempfile
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
from botwidget.system import linux, macos
from botwidget.system.current import process_cmdline


class EyeAim(unittest.TestCase):
    """Should aim the gaze: far away is rest, nearby follows, right on the nose squints."""

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


class Clouds(unittest.TestCase):
    """Should give the thinking cloud circles around the area and a tail of shrinking circles."""

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
            from PySide6.QtGui import QGuiApplication
        except ImportError:  # no toolkit at all: nothing to test here
            raise unittest.SkipTest("PySide6 is not available")
        try:
            cls.app = QGuiApplication.instance() or QGuiApplication([])
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

    def test_an_http_link_becomes_a_clickable_anchor(self):
        from PySide6.QtGui import QTextCursor
        doc, _panels = self.document([{"role": "bot", "text": "see [docs](https://example.com/x)"}])
        cursor = QTextCursor(doc)
        label, hrefs = "", []
        while not cursor.atEnd():
            cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
            fmt = cursor.charFormat()
            if fmt.isAnchor():
                label += doc.characterAt(cursor.position() - 1)
                hrefs.append(fmt.anchorHref())
        self.assertEqual(set(hrefs), {"https://example.com/x"})
        self.assertEqual(label, "docs", "only the label is the link, the host stays text")

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

    def test_a_refusal_from_the_api_is_not_retried(self):
        with _FlakyApi([401]) as server:
            result = openbot.api_post("/v1/agents/me/messages",
                                      {"text": "hi", "clientMessageId": "x"})
            self.assertEqual(len(server.seen), 1)
        self.assertFalse(result.ok)
        self.assertFalse(result.retryable)
        self.assertEqual(result.status, 401)

    def test_no_answer_at_all_is_retryable(self):
        old_url, old_headers = openbot.API_URL, openbot.HEADERS_FILE
        self.addCleanup(setattr, openbot, "API_URL", old_url)
        self.addCleanup(setattr, openbot, "HEADERS_FILE", old_headers)
        with tempfile.TemporaryDirectory() as folder:
            headers = os.path.join(folder, "headers")
            with open(headers, "w") as f:
                f.write("Authorization: Bearer test\n")
            openbot.HEADERS_FILE = headers
            openbot.API_URL = _closed_address()
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

    def __init__(self, replies: list):
        import http.server
        import threading

        self.replies = replies
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
                self.wfile.write(b'{"ok": true}')

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def __enter__(self):
        self._old = (openbot.HEADERS_FILE, openbot.API_URL)
        openbot.HEADERS_FILE = self._headers
        openbot.API_URL = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def __exit__(self, *exc):
        openbot.HEADERS_FILE, openbot.API_URL = self._old
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()
        return False


if __name__ == "__main__":
    unittest.main()
