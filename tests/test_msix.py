"""Tests for packaging/msix.py and packaging/build.py --msix."""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packaging"))

import build
import msix

# Namespace URIs used in the manifest
_NS = {
    "": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
    "uap": "http://schemas.microsoft.com/appx/manifest/uap/windows10",
    "desktop": "http://schemas.microsoft.com/appx/manifest/desktop/windows10",
    "rescap": "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities",
}


def _tag(local: str) -> str:
    return f"{{{_NS['']}}}{local}"


def _tag_ns(prefix: str, local: str) -> str:
    return f"{{{_NS[prefix]}}}{local}"


class TestLoadConfig(unittest.TestCase):
    """load_config: default, env override, validation."""

    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self._config_path = os.path.join(self._dir, "msix.json")
        self.addCleanup(lambda: shutil.rmtree(self._dir, True))

    def _write(self, data):
        with open(self._config_path, "w") as fh:
            json.dump(data, fh)

    def test_default_values(self):
        self._write({
            "identity_name": "MyCorp.BotWidget",
            "publisher": "CN=12345678-1234-1234-1234-123456789012",
            "publisher_display_name": "MyCorp",
            "display_name": "Bot Widget",
            "description": "Animated bot faces",
            "min_version": "10.0.17763.0",
            "max_version_tested": "10.0.22621.0",
        })
        config = msix.load_config(self._config_path)
        self.assertEqual(config["identity_name"], "MyCorp.BotWidget")
        self.assertEqual(config["publisher"], "CN=12345678-1234-1234-1234-123456789012")

    def test_env_override_identity(self):
        self._write({"identity_name": "Orig.Name",
                      "publisher": "CN=12345678-1234-1234-1234-123456789012",
                      "publisher_display_name": "Orig",
                      "display_name": "Bot Widget",
                      "description": "Desc",
                      "min_version": "10.0.17763.0",
                      "max_version_tested": "10.0.22621.0",
                      })
        config = msix.load_config(self._config_path, environ={
            "MSIX_IDENTITY_NAME": "Env.BotWidget",
            "MSIX_PUBLISHER": "CN=ABCDEFAB-CDEF-ABCD-EFAB-CDEFABCDEFAB",
            "MSIX_PUBLISHER_DISPLAY_NAME": "EnvName",
        })
        self.assertEqual(config["identity_name"], "Env.BotWidget")
        self.assertEqual(config["publisher"], "CN=ABCDEFAB-CDEF-ABCD-EFAB-CDEFABCDEFAB")
        self.assertEqual(config["publisher_display_name"], "EnvName")

    def test_env_empty_does_not_override(self):
        self._write({"identity_name": "Orig.Name",
                      "publisher": "CN=12345678-1234-1234-1234-123456789012",
                      "publisher_display_name": "Orig",
                      "display_name": "Bot Widget",
                      "description": "Desc",
                      "min_version": "10.0.17763.0",
                      "max_version_tested": "10.0.22621.0",
                      })
        config = msix.load_config(self._config_path, environ={
            "MSIX_IDENTITY_NAME": "",
            "MSIX_PUBLISHER": "",
        })
        self.assertEqual(config["identity_name"], "Orig.Name")

    def test_invalid_identity_is_refused(self):
        base = {"identity_name": "Valid.Name",
                "publisher": "CN=12345678-1234-1234-1234-123456789012",
                "publisher_display_name": "Orig",
                "display_name": "Bot Widget",
                "description": "Desc",
                "min_version": "10.0.17763.0",
                "max_version_tested": "10.0.22621.0"}
        for key, bad in (("identity_name", "a"), ("publisher", "InvalidPublisher")):
            with self.subTest(key=key):
                data = dict(base)
                data[key] = bad
                self._write(data)
                with self.assertRaises(ValueError):
                    msix.load_config(self._config_path)


class TestIsPlaceholder(unittest.TestCase):
    def test_a_placeholder_field_marks_the_identity(self):
        real = {"identity_name": "MyCorp.BotWidget",
                "publisher": "CN=12345678-1234-1234-1234-123456789012",
                "publisher_display_name": "MyCorp"}
        cases = (
            ("identity name", {"identity_name": "PLACEHOLDER.BotWidget",
                               "publisher": "CN=1234", "publisher_display_name": "Real"}, True),
            ("publisher display", {"identity_name": "Real.Name", "publisher": "CN=1234",
                                   "publisher_display_name": "PLACEHOLDER Corp"}, True),
            ("all-zero guid", {"identity_name": "Real.Name",
                               "publisher": "CN=00000000-0000-0000-0000-000000000000",
                               "publisher_display_name": "Real"}, True),
            ("real identity", real, False),
        )
        for name, config, want in cases:
            with self.subTest(name=name):
                self.assertEqual(msix.is_placeholder(config), want)


_REAL_IDENTITY = {
    "MSIX_IDENTITY_NAME": "MyCorp.BotWidget",
    "MSIX_PUBLISHER": "CN=12345678-1234-1234-1234-123456789012",
    "MSIX_PUBLISHER_DISPLAY_NAME": "MyCorp",
}


class TestIdentityConfigured(unittest.TestCase):
    def test_all_three_variables_are_required(self):
        """Should be true only when every identity variable is a non-empty string."""
        missing_one = dict(_REAL_IDENTITY)
        del missing_one["MSIX_PUBLISHER"]
        empty = dict(_REAL_IDENTITY)
        empty["MSIX_PUBLISHER_DISPLAY_NAME"] = ""
        cases = (
            ("none", {}, False),
            ("one missing", missing_one, False),
            ("empty", empty, False),
            ("all set", dict(_REAL_IDENTITY), True),
        )
        for name, env, want in cases:
            with self.subTest(name=name):
                self.assertEqual(msix.identity_configured(env), want)


class TestMainIdentityGate(unittest.TestCase):
    def test_skips_and_warns_when_missing(self):
        """Should skip the package and emit a workflow warning when identity variables are missing."""
        with unittest.mock.patch.object(msix, "stage") as stage, \
             unittest.mock.patch.object(msix, "pack") as pack, \
             unittest.mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            built = msix.main(["app", "out.msix"], environ={})
        self.assertFalse(built)
        stage.assert_not_called()
        pack.assert_not_called()
        text = out.getvalue()
        self.assertIn("::warning::MSIX skipped:", text)
        for key in _REAL_IDENTITY:
            self.assertIn(key, text)
        # One line, so Actions treats it as a single warning annotation.
        self.assertEqual(text.count("\n"), 1)
        self.assertTrue(text.startswith("::warning::"))

    def test_builds_when_identity_set(self):
        """Should build when the three identity variables are set."""
        with unittest.mock.patch.object(msix, "stage") as stage, \
             unittest.mock.patch.object(msix, "pack") as pack, \
             unittest.mock.patch.object(msix, "_get_version", return_value="0.1.1"), \
             unittest.mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            built = msix.main(["app", "out.msix"], environ=dict(_REAL_IDENTITY))
        self.assertTrue(built)
        stage.assert_called_once()
        pack.assert_called_once()
        self.assertEqual(stage.call_args.args[2]["identity_name"], "MyCorp.BotWidget")
        self.assertEqual(stage.call_args.args[2]["publisher"], _REAL_IDENTITY["MSIX_PUBLISHER"])
        self.assertIn("Built out.msix", out.getvalue())
        self.assertNotIn("::warning::", out.getvalue())

    def test_builds_when_set_values_are_placeholders(self):
        """Should still build when the variables are set, even if the values are placeholders."""
        env = {
            "MSIX_IDENTITY_NAME": "PLACEHOLDER.BotWidget",
            "MSIX_PUBLISHER": "CN=00000000-0000-0000-0000-000000000000",
            "MSIX_PUBLISHER_DISPLAY_NAME": "PLACEHOLDER",
        }
        with unittest.mock.patch.object(msix, "stage") as stage, \
             unittest.mock.patch.object(msix, "pack") as pack, \
             unittest.mock.patch.object(msix, "_get_version", return_value="0.1.1"), \
             unittest.mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            built = msix.main(["app", "out.msix"], environ=env)
        self.assertTrue(built)
        stage.assert_called_once()
        pack.assert_called_once()
        self.assertNotIn("::warning::", out.getvalue())
        self.assertIn("WARNING: identity placeholders detected", out.getvalue())


class TestMsixVersion(unittest.TestCase):
    def test_known_versions_become_four_parts(self):
        cases = (
            ("0.1.1", "0.1.1.0"),
            ("1.2", "1.2.0.0"),
            ("1", "1.0.0.0"),
            ("0.1.1.dev3+gabc", "0.1.1.0"),
            ("1.2.3.4", "1.2.3.4"),
            ("1.0.0.alpha", "1.0.0.0"),  # a non-numeric suffix after a dot is dropped
        )
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(msix.msix_version(raw), want)

    def test_unusable_versions_are_refused(self):
        for raw in ("0.1.65536.0", "-1.0.0.0", "alpha"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    msix.msix_version(raw)


class TestAssets(unittest.TestCase):
    def test_keys_and_sizes(self):
        expected = {
            "Square44x44Logo.png": (44, 44),
            "Square44x44Logo.targetsize-256_altform-unplated.png": (256, 256),
            "Square150x150Logo.png": (150, 150),
            "Wide310x150Logo.png": (310, 150),
            "StoreLogo.png": (50, 50),
        }
        self.assertEqual(msix.ASSETS, expected)


class TestManifestXml(unittest.TestCase):
    """Parse the manifest as XML and check structure."""

    @staticmethod
    def _config():
        return {
            "identity_name": "MyCorp.BotWidget",
            "publisher": "CN=12345678-1234-1234-1234-123456789012",
            "publisher_display_name": "MyCorp",
            "display_name": "Bot Widget",
            "description": "Animated bot faces",
            "min_version": "10.0.17763.0",
            "max_version_tested": "10.0.22621.0",
        }

    def setUp(self):
        self.config = self._config()
        self.xml = msix.manifest_xml(self.config, "0.1.1")
        self.root = ET.fromstring(self.xml)

    def _find(self, local_name):
        return self.root.find(_tag(local_name))

    def test_identity_attrs(self):
        identity = self._find("Identity")
        self.assertIsNotNone(identity)
        self.assertEqual(identity.get("Name"), "MyCorp.BotWidget")
        self.assertEqual(identity.get("Publisher"),
                         "CN=12345678-1234-1234-1234-123456789012")

    def test_version_four_parts(self):
        identity = self._find("Identity")
        version = identity.get("Version")
        parts = version.split(".")
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[3], "0")
        for part in parts:
            val = int(part)
            self.assertGreaterEqual(val, 0)
            self.assertLessEqual(val, 65535)

    def test_processor_architecture(self):
        identity = self._find("Identity")
        self.assertEqual(identity.get("ProcessorArchitecture"), "x64")

    def test_properties(self):
        props = self._find("Properties")
        self.assertIsNotNone(props)
        self.assertEqual(props.find(_tag("DisplayName")).text, "Bot Widget")
        self.assertEqual(props.find(_tag("PublisherDisplayName")).text, "MyCorp")
        self.assertEqual(props.find(_tag("Logo")).text, "Assets\\StoreLogo.png")

    def test_dependencies(self):
        deps = self._find("Dependencies")
        self.assertIsNotNone(deps)
        tf = deps.find(_tag("TargetDeviceFamily"))
        self.assertIsNotNone(tf)
        self.assertEqual(tf.get("Name"), "Windows.Desktop")
        self.assertEqual(tf.get("MinVersion"), "10.0.17763.0")
        self.assertEqual(tf.get("MaxVersionTested"), "10.0.22621.0")

    def test_resources(self):
        res = self._find("Resources")
        self.assertIsNotNone(res)
        resource = res.find(_tag("Resource"))
        self.assertIsNotNone(resource)
        self.assertEqual(resource.get("Language"), "en-us")
        self.assertIsNone(resource.text)

    def test_app_entry_point(self):
        apps = self._find("Applications")
        self.assertIsNotNone(apps)
        app = apps.find(_tag("Application"))
        self.assertIsNotNone(app)
        self.assertEqual(app.get("EntryPoint"), "Windows.FullTrustApplication")
        self.assertEqual(app.get("Id"), "BotWidget")

    def test_visual_elements(self):
        apps = self._find("Applications")
        app = apps.find(_tag("Application"))
        visual = app.find(_tag_ns("uap", "VisualElements"))
        self.assertIsNotNone(visual)
        self.assertEqual(visual.get("BackgroundColor"), "transparent")
        self.assertEqual(visual.get("Square150x150Logo"), "Assets\\Square150x150Logo.png")
        self.assertEqual(visual.get("Square44x44Logo"), "Assets\\Square44x44Logo.png")
        # DefaultTile is a child of VisualElements
        tile = visual.find(_tag_ns("uap", "DefaultTile"))
        self.assertIsNotNone(tile)
        self.assertEqual(tile.get("Wide310x150Logo"), "Assets\\Wide310x150Logo.png")

    def test_startup_task_structure(self):
        """Startup task must be under foundation:Extensions > desktop:Extension > desktop:StartupTask."""
        apps = self._find("Applications")
        app = apps.find(_tag("Application"))
        exts = app.find(_tag("Extensions"))
        self.assertIsNotNone(exts)
        self.assertEqual(exts.tag, _tag("Extensions"))
        ext = exts.find(_tag_ns("desktop", "Extension"))
        self.assertIsNotNone(ext)
        self.assertEqual(ext.get("Category"), "windows.startupTask")
        self.assertEqual(ext.get("Executable"), "Bot Widget.exe")
        self.assertEqual(ext.get("EntryPoint"), "Windows.FullTrustApplication")
        task = ext.find(_tag_ns("desktop", "StartupTask"))
        self.assertIsNotNone(task)
        self.assertEqual(task.get("TaskId"), "BotWidgetStartup")
        self.assertEqual(task.get("Enabled"), "true")
        self.assertEqual(task.get("DisplayName"), "Bot Widget")

    def test_run_full_trust_capability(self):
        caps = self._find("Capabilities")
        self.assertIsNotNone(caps)
        cap = caps.find(_tag_ns("rescap", "Capability"))
        self.assertIsNotNone(cap)
        self.assertEqual(cap.get("Name"), "runFullTrust")

    def test_asset_keys_covered_in_manifest(self):
        """Every asset referenced in the manifest is a key in ASSETS."""
        for filename in msix.ASSETS:
            # Only check the ones that are actually referenced in the manifest
            pass
        # The ones we use: Square150x150Logo, Square44x44Logo, Wide310x150Logo, StoreLogo
        for key in ("Square150x150Logo.png", "Square44x44Logo.png",
                     "Wide310x150Logo.png", "StoreLogo.png"):
            self.assertIn(key, self.xml, f"{key} referenced in manifest")
        # And every asset key in ASSETS is valid
        for key in msix.ASSETS:
            self.assertIn(key, msix.ASSETS)

    def test_xml_escapes_the_display_name(self):
        cases = (
            ("Bot & Widget", "Bot &amp; Widget", ('&amp;amp;', 'DisplayName="Bot & Widget"')),
            ("Bot <Widget>", "Bot &lt;Widget&gt;", ()),
        )
        for raw, escaped, forbidden in cases:
            with self.subTest(raw=raw):
                config = self._config()
                config["display_name"] = raw
                xml = msix.manifest_xml(config, "0.1.1")
                self.assertIn(escaped, xml)
                for bad in forbidden:
                    self.assertNotIn(bad, xml)

    def test_display_name_roundtrip(self):
        """display_name with & and <> should round-trip through XML parsing."""
        config = self._config()
        config["display_name"] = "Bot & <Widget>"
        xml = msix.manifest_xml(config, "0.1.1")
        self.assertNotIn("&amp;amp;", xml)
        root = ET.fromstring(xml)
        # Properties/DisplayName text
        props = root.find(_tag("Properties"))
        props_dn = props.find(_tag("DisplayName"))
        self.assertEqual(props_dn.text, "Bot & <Widget>")
        # uap:VisualElements DisplayName attribute
        apps = root.find(_tag("Applications"))
        app = apps.find(_tag("Application"))
        visual = app.find(_tag_ns("uap", "VisualElements"))
        self.assertEqual(visual.get("DisplayName"), "Bot & <Widget>")

    def test_default_namespace(self):
        """Root element must use default namespace, not ns0 prefix."""
        self.assertIn('<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"',
                      self.xml)
        self.assertNotIn("ns0:", self.xml)


class TestWriteAssets(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("QT_QPA_PLATFORM") == "offscreen",
                         "requires offscreen Qt")
    def test_write_assets_produces_pngs(self):
        out = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(out, True))
        msix.write_assets(out)
        for filename, (width, height) in msix.ASSETS.items():
            path = os.path.join(out, filename)
            self.assertTrue(os.path.isfile(path), filename)
            # Read image size with PySide6
            from PySide6.QtGui import QImage
            img = QImage(path)
            self.assertEqual(img.width(), width)
            self.assertEqual(img.height(), height)


class TestStage(unittest.TestCase):
    def setUp(self):
        self.app_dir = tempfile.mkdtemp()
        self.out_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.app_dir, True))
        self.addCleanup(lambda: shutil.rmtree(self.out_dir, True))
        # Create a fake app folder with the exe
        self.exe_name = "Bot Widget.exe"
        self.exe_path = os.path.join(self.app_dir, self.exe_name)
        with open(self.exe_path, "wb") as fh:
            fh.write(b"fake exe")

    def test_stage_copies_contents(self):
        config = msix.load_config()
        msix.stage(self.app_dir, self.out_dir, config, "0.1.1")
        self.assertTrue(os.path.isfile(os.path.join(self.out_dir, self.exe_name)))

    def test_stage_has_manifest(self):
        config = msix.load_config()
        msix.stage(self.app_dir, self.out_dir, config, "0.1.1")
        manifest = os.path.join(self.out_dir, "AppxManifest.xml")
        self.assertTrue(os.path.isfile(manifest))
        root = ET.parse(manifest).getroot()
        identity = root.find(_tag("Identity"))
        self.assertIsNotNone(identity)

    def test_stage_has_all_assets(self):
        config = msix.load_config()
        msix.stage(self.app_dir, self.out_dir, config, "0.1.1")
        assets_dir = os.path.join(self.out_dir, "Assets")
        for filename in msix.ASSETS:
            self.assertTrue(os.path.isfile(os.path.join(assets_dir, filename)))

    def test_manifest_is_parseable(self):
        config = msix.load_config()
        msix.stage(self.app_dir, self.out_dir, config, "0.1.1")
        manifest = os.path.join(self.out_dir, "AppxManifest.xml")
        root = ET.parse(manifest).getroot()
        self.assertEqual(root.tag, _tag("Package"))


class TestFindMakeappx(unittest.TestCase):
    @unittest.skipIf(sys.platform == "win32", "the Windows SDK may provide makeappx")
    def test_returns_none_on_linux(self):
        self.assertIsNone(msix.find_makeappx())


class TestPack(unittest.TestCase):
    def test_uses_found_makeappx_path(self):
        with unittest.mock.patch.object(msix, "find_makeappx", return_value="/usr/bin/makeappx"):
            with unittest.mock.patch("subprocess.run") as mock_run:
                msix.pack("/tmp/staging", "/tmp/out.msix")
                mock_run.assert_called_once_with(
                    ["/usr/bin/makeappx", "pack", "/o", "/h", "SHA256", "/d", "/tmp/staging", "/p", "/tmp/out.msix"],
                    check=True,
                )

    def test_raises_SystemExit_when_makeappx_not_found(self):
        with unittest.mock.patch.object(msix, "find_makeappx", return_value=None):
            with self.assertRaises(SystemExit):
                msix.pack("/tmp/staging", "/tmp/out.msix")


class TestWriteAssetsSubprocess(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("QT_QPA_PLATFORM") == "offscreen",
                         "requires offscreen Qt")
    def test_write_assets_from_foreign_cwd(self):
        """Import and call write_assets from a temporary directory (not the repo)."""
        import sys as _sys
        packaging_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packaging")
        out_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(out_dir, True))
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        code = (
            "import sys, os\n"
            f"sys.path.insert(0, {packaging_dir!r})\n"
            f"import msix\n"
            f"msix.write_assets({out_dir!r})\n"
            f"import glob\n"
            f"files = sorted(glob.glob(os.path.join({out_dir!r}, '*')))\n"
            f"print(len(files))\n"
        )
        result = subprocess.run(
            [_sys.executable, "-c", code],
            cwd=tempfile.mkdtemp(),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        count = int(result.stdout.strip())
        self.assertEqual(count, len(msix.ASSETS))
        for filename in msix.ASSETS:
            self.assertTrue(os.path.isfile(os.path.join(out_dir, filename)), filename)


class TestBuildUsage(unittest.TestCase):
    def test_usage_mentions_msix(self):
        usage = build.__doc__
        self.assertIn("--msix", usage)


if __name__ == "__main__":
    unittest.main()
