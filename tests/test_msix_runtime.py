"""Under MSIX (Store policy 10.2.2): no self-updater, and the manifest's startupTask instead of a Run entry."""

import sys
import types
import unittest
import unittest.mock

from botwidget import updates
from botwidget.system import windows


class FakeKernel:
    """GetCurrentPackageFullName: 15700 (APPMODEL_ERROR_NO_PACKAGE) when unpackaged, else 0 / 122."""

    def __init__(self, code):
        self.code = code
        self.GetCurrentPackageFullName = self._call

    def _call(self, length, buffer):
        return self.code


class IsMsixTest(unittest.TestCase):
    def test_packaged_only_when_the_kernel_says_so(self):
        for code, expected in ((15700, False), (122, True)):
            with self.subTest(code=code):
                self.assertEqual(windows.is_msix(FakeKernel(code)), expected)
        self.assertFalse(windows.is_msix(None))


class UpdaterOffTest(unittest.TestCase):
    def test_install_only_outside_msix(self):
        for packaged, expected in ((True, False), (False, True)):
            with self.subTest(packaged=packaged):
                with unittest.mock.patch.object(windows, "is_msix", return_value=packaged), \
                        unittest.mock.patch.object(sys, "frozen", True, create=True):
                    self.assertEqual(windows.can_install_update(), expected)

    def test_staged_update_not_installed_under_msix(self):
        with unittest.mock.patch.object(updates, "staged_update", return_value=("9.9.9", "x")), \
                unittest.mock.patch.object(updates, "can_install_update", windows.can_install_update), \
                unittest.mock.patch.object(windows, "is_msix", return_value=True), \
                unittest.mock.patch.object(sys, "frozen", True, create=True), \
                unittest.mock.patch.object(updates, "install_update") as install:
            self.assertFalse(updates.install_staged())
            install.assert_not_called()


class StartupTaskTest(unittest.TestCase):
    def test_no_run_entry_written_under_msix(self):
        winreg = types.SimpleNamespace(OpenKey=unittest.mock.Mock(), SetValueEx=unittest.mock.Mock())
        with unittest.mock.patch.object(windows, "is_msix", return_value=True), \
                unittest.mock.patch.dict(sys.modules, {"winreg": winreg}):
            windows.set_launch_at_login(["x.exe"], True)
        winreg.OpenKey.assert_not_called()
        winreg.SetValueEx.assert_not_called()

    def test_login_reads_manifest_startup_task_under_msix(self):
        winreg = types.SimpleNamespace(OpenKey=unittest.mock.Mock())
        with unittest.mock.patch.object(windows, "is_msix", return_value=True), \
                unittest.mock.patch.dict(sys.modules, {"winreg": winreg}):
            self.assertTrue(windows.launch_at_login())
        winreg.OpenKey.assert_not_called()


if __name__ == "__main__":
    unittest.main()
