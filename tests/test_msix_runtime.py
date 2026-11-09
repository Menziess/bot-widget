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
    def test_not_packaged(self):
        self.assertFalse(windows.is_msix(FakeKernel(15700)))

    def test_packaged(self):
        self.assertTrue(windows.is_msix(FakeKernel(122)))

    def test_no_kernel(self):
        self.assertFalse(windows.is_msix(None))


class UpdaterOffTest(unittest.TestCase):
    def test_no_install_under_msix(self):
        with unittest.mock.patch.object(windows, "is_msix", return_value=True), \
                unittest.mock.patch.object(sys, "frozen", True, create=True):
            self.assertFalse(windows.can_install_update())

    def test_install_outside_msix(self):
        with unittest.mock.patch.object(windows, "is_msix", return_value=False), \
                unittest.mock.patch.object(sys, "frozen", True, create=True):
            self.assertTrue(windows.can_install_update())

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
