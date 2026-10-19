"""Logica zonder scherm: eye_aim, markdown en het gezicht uit de botdefinitie.

Geen Gtk-venster: alleen rekenen en parsen, zodat dit ook op een CI-machine
zonder beeldscherm draait.
"""

import io
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
    config,
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


class Animator(unittest.TestCase):
    """De veren: soepel naar het doel, doorveren waar dat hoort, en daarna echt stil."""

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
    """De ogen zijn altijd massief: ook halverwege een overgang is geen oog doorzichtig."""

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
    """Rust is bijna stilstaan: schuin omhoog kijken en af en toe knipperen, zoals Grok Bot."""

    def test_idle_cycle_is_dominated_by_the_still_glance(self):
        total = sum(ms for _pose, ms in avatar.FACE["idle"])
        still = sum(ms for pose, ms in avatar.FACE["idle"] if pose == "idle")
        self.assertGreater(still / total, 0.9)

    def test_the_glance_is_up_and_to_the_right(self):
        dx, dy, _scale = avatar.POSES["idle"]
        self.assertTrue(dx > 0 and dy < 0)


class FaceLook(unittest.TestCase):
    """Grok Bot-palet, geen lichte ring, diepte en een eigen kanteling per bot."""

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
    """Alleen een echt hoger versienummer is een update; een mislukte vraag is stil."""

    def serve(self, routes):
        """Laat urlopen antwoorden uit routes: sleutel is een stuk van de url, waarde de bytes."""
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


class LaunchAtLogin(unittest.TestCase):
    """Elk besturingssysteem zet zijn eigen bestand of sleutel; hier de bestanden."""

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
            old = macos._launch_agent
            self.addCleanup(setattr, macos, "_launch_agent", old)
            macos._launch_agent = lambda: path
            macos.set_launch_at_login(self.COMMAND, True)
            self.assertTrue(macos.launch_at_login())
            with open(path, "rb") as fh:
                agent = plistlib.load(fh)
            self.assertEqual(agent["ProgramArguments"], self.COMMAND)
            self.assertTrue(agent["RunAtLoad"])
            self.assertEqual(agent["AssociatedBundleIdentifiers"], [macos.BUNDLE_ID])
            macos.set_launch_at_login(self.COMMAND, False)
            self.assertFalse(macos.launch_at_login())

    def test_command_is_the_app_itself_when_bundled_and_the_package_otherwise(self):
        self.assertEqual(startup.launch_command()[:3], [sys.executable, "-m", "botwidget"])
        sys.frozen = True
        self.addCleanup(delattr, sys, "frozen")
        self.assertEqual(startup.launch_command(), [sys.executable])


class AutoUpdate(unittest.TestCase):
    """Downloaden, controleren, klaarzetten en bij de volgende start installeren."""

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
    """De echte wissel van een .app op macOS, met een nepapp in een tijdelijke map."""

    @unittest.skipUnless(sys.platform == "darwin", "alleen macOS heeft ditto en .app")
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
                running.poll()  # een afgesloten kindproces blijft anders een zombie die nog "leeft"
                if open(marker).read() == "new":
                    break
            self.assertEqual(open(marker).read(), "new")
            self.assertEqual(sorted(os.listdir(os.path.join(home, "Apps"))), ["Bot Widget.app"])


class DevRunner(unittest.TestCase):
    """De ontwikkelmodus ziet nieuwe en gewijzigde bestanden, en negeert de rest."""

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
    """Meestarten staat de eerste keer aan; daarna beslist de gebruiker."""

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


if __name__ == "__main__":
    unittest.main()
