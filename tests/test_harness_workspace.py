"""H3 workspace-scoped tools: containment, secrets, search, git, shell, edit/undo, context rules."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from harness.agent.workspace import (
    EditStore,
    PERMISSION_MODES,
    load_workspace_rules,
    resolve_workspace,
    search_files,
    shell_run,
    workspace_builtins,
    _check_inside,
    _git_run,
    _is_secret_path,
    _is_secret_dir,
    _is_secret_name,
    _safe_walk,
    _ws_diff,
    _ws_list,
    _ws_read,
    _ws_write,
)

# ── Helpers ───────────────────────────────────────────────────────────

def _mktmp(*subdirs):
    """Create a temp dir and return its path."""
    return os.path.join(tempfile.mkdtemp(), *subdirs)


def _write(path, content="x"):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)


# ── Containment ───────────────────────────────────────────────────────

class Containment(unittest.TestCase):
    def test_resolve_workspace_returns_realpath(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        resolved = resolve_workspace(folder)
        self.assertIsInstance(resolved, str)
        self.assertEqual(resolved, os.path.realpath(folder))

    def test_resolve_workspace_empty_returns_none(self):
        self.assertIsNone(resolve_workspace(""))
        self.assertIsNone(resolve_workspace(None))
        self.assertIsNone(resolve_workspace("   "))

    def test_resolve_workspace_not_a_dir_returns_none(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        self.addCleanup(os.unlink, path)
        self.assertIsNone(resolve_workspace(path))

    def test_check_inside_passes_for_path_inside(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        target = os.path.join(folder, "sub", "a.txt")
        _write(target, "hi")
        result = _check_inside(folder, "sub/a.txt")
        self.assertEqual(result, os.path.realpath(target))

    def test_check_inside_rejects_path_outside(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        other = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, other, True)
        target = os.path.join(other, "x.txt")
        _write(target)
        with self.assertRaises(Exception) as caught:
            _check_inside(folder, target)
        self.assertIn("outside", str(caught.exception).lower())

    def test_path_traversal_dotdot_is_refused(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        inside = os.path.join(folder, "sub")
        os.makedirs(inside)
        outside_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside_dir, True)
        outside = os.path.join(outside_dir, "secret.txt")
        _write(outside)
        with self.assertRaises(Exception):
            _check_inside(folder, os.path.join(inside, "..", os.pardir, "secret.txt"))


# ── Symlink escape ────────────────────────────────────────────────────

class SymlinkEscape(unittest.TestCase):
    def test_symlink_outside_is_refused(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        _write(os.path.join(outside, "secret.txt"))
        # Create a symlink inside the workspace pointing outside.
        link = os.path.join(folder, "link")
        os.symlink(outside, link)
        # Accessing through the symlink should still fail containment.
        with self.assertRaises(Exception):
            _check_inside(folder, "link/secret.txt")


# ── Secrets ───────────────────────────────────────────────────────────

class Secrets(unittest.TestCase):
    def test_env_files_are_secret(self):
        self.assertTrue(_is_secret_name(".env"))
        self.assertTrue(_is_secret_name(".env.production"))
        self.assertTrue(_is_secret_name(".env.local"))

    def test_env_example_is_allowed(self):
        self.assertFalse(_is_secret_name(".env.example"))
        self.assertFalse(_is_secret_name(".env.template"))

    def test_key_and_pem_are_secret(self):
        self.assertTrue(_is_secret_name("server.key"))
        self.assertTrue(_is_secret_name("cert.pem"))
        self.assertTrue(_is_secret_name("my-key.key"))

    def test_id_files_are_secret(self):
        self.assertTrue(_is_secret_name("id_rsa"))
        self.assertTrue(_is_secret_name("id_ed25519"))
        self.assertTrue(_is_secret_name("id_dsa"))

    def test_netrc_is_secret(self):
        self.assertTrue(_is_secret_name(".netrc"))

    def test_regular_files_are_not_secret(self):
        self.assertFalse(_is_secret_name("README.md"))
        self.assertFalse(_is_secret_name("note.txt"))
        self.assertFalse(_is_secret_name("data.csv"))

    def test_secret_directories_are_denied(self):
        self.assertTrue(_is_secret_dir(".ssh"))
        self.assertTrue(_is_secret_dir(".gnupg"))
        self.assertTrue(_is_secret_dir(".aws"))
        self.assertFalse(_is_secret_dir("src"))
        self.assertFalse(_is_secret_dir(".git"))

    def test_is_secret_path_checks_subtree(self):
        self.assertTrue(_is_secret_path("/home/user/.ssh/id_rsa"))
        self.assertTrue(_is_secret_path("/home/user/.ssh/config"))
        self.assertTrue(_is_secret_path("/home/user/.aws/credentials"))
        self.assertFalse(_is_secret_path("/home/user/project/src/main.py"))

    def test_search_skips_secret_files(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        _write(os.path.join(folder, "normal.txt"), "contains TOKEN")
        _write(os.path.join(folder, ".env"), "SECRET_TOKEN=abc")
        result = search_files(folder, "TOKEN")
        self.assertIn("normal.txt", result)
        self.assertNotIn(".env", result)

    def test_search_skips_secret_directories(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        ssh_dir = os.path.join(folder, ".ssh")
        os.makedirs(ssh_dir)
        _write(os.path.join(ssh_dir, "id_rsa"), "secret-key")
        _write(os.path.join(folder, "main.py"), "import config")
        result = search_files(folder, "secret-key")
        self.assertEqual(result, "(no matches)")

    def test_list_dir_skips_secrets(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        _write(os.path.join(folder, "a.txt"))
        _write(os.path.join(folder, ".env"))
        os.makedirs(os.path.join(folder, ".ssh"))
        listing = _ws_list(folder, folder)
        self.assertIn("a.txt", listing)
        self.assertNotIn(".env", listing)
        self.assertNotIn(".ssh", listing)

    def test_read_file_refuses_secrets(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        _write(os.path.join(folder, ".env"), "SECRET=abc")
        with self.assertRaises(Exception):
            _ws_read(folder, ".env")


# ── Search ────────────────────────────────────────────────────────────

class SearchFiles(unittest.TestCase):
    def test_search_finds_text_in_file(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        _write(os.path.join(folder, "a.txt"), "hello world\nfoo bar")
        result = search_files(folder, "world")
        self.assertIn("a.txt", result)
        self.assertIn("hello world", result)

    def test_search_returns_no_matches_when_absent(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        _write(os.path.join(folder, "a.txt"), "hello")
        result = search_files(folder, "xyz")
        self.assertEqual(result, "(no matches)")

    def test_search_limit_is_respected(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        for i in range(20):
            _write(os.path.join(folder, f"f{i}.txt"), "MATCH")
        result = search_files(folder, "MATCH", limit=5)
        self.assertIn("MATCH", result)
        self.assertNotIn("f5.txt", result)


# ── Safe walk ─────────────────────────────────────────────────────────

class SafeWalk(unittest.TestCase):
    def test_walk_skips_secret_dirs(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        ssh_dir = os.path.join(folder, ".ssh")
        os.makedirs(ssh_dir)
        _write(os.path.join(ssh_dir, "key"))
        results = list(_safe_walk(folder))
        for dirpath, files in results:
            self.assertNotIn(".ssh", dirpath)
            for f in files:
                self.assertNotIn("key", f)


# ── Write / Edit ──────────────────────────────────────────────────────

class Containment_Separators(unittest.TestCase):
    def test_a_windows_path_is_inside_with_backslashes_and_any_case_and_not_beside_it(self):
        import ntpath
        from unittest import mock
        from harness.agent import workspace
        with mock.patch.object(workspace.os, "path", ntpath):
            self.assertTrue(workspace._contains("C:\\Users\\Me\\work", "C:\\Users\\Me\\work\\sub\\a.txt"))
            self.assertTrue(workspace._contains("C:\\Users\\Me\\work", "c:\\users\\me\\WORK"))
            self.assertFalse(workspace._contains("C:\\Users\\Me\\work", "C:\\Users\\Me\\work-other\\a.txt"))
            self.assertFalse(workspace._contains("C:\\Users\\Me\\work", "D:\\work\\a.txt"))


class Delete(unittest.TestCase):
    def test_a_file_moves_to_the_trash_and_nothing_else_can_be_deleted(self):
        from unittest import mock
        from harness.agent import tools, workspace
        folder, trash = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.addCleanup(shutil.rmtree, trash, True)
        with open(os.path.join(folder, "a.txt"), "w") as fh:
            fh.write("keep me")
        os.mkdir(os.path.join(folder, "sub"))
        with mock.patch.object(tools, "TRASH", trash):
            self.assertIn("Moved", workspace._ws_delete(folder, "a.txt"))
            self.assertFalse(os.path.exists(os.path.join(folder, "a.txt")))
            with open(os.path.join(trash, os.listdir(trash)[0])) as fh:
                self.assertEqual(fh.read(), "keep me")
            for bad in ("sub", "../outside.txt", "missing.txt"):
                with self.assertRaises(Exception):
                    workspace._ws_delete(folder, bad)


class EditWrite(unittest.TestCase):
    def test_write_inside_workspace_works(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        result = _ws_write(folder, "note.txt", "hello")
        self.assertIn("Wrote", result)
        with open(os.path.join(folder, "note.txt")) as fh:
            self.assertEqual(fh.read(), "hello")

    def test_write_outside_is_refused(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        with self.assertRaises(Exception):
            _ws_write(folder, "../outside.txt", "x")

    def test_write_secret_is_refused(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        with self.assertRaises(Exception):
            _ws_write(folder, ".env", "SECRET=abc")

    def test_edit_store_before_and_undo(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "a.txt")
        _write(path, "original")
        edit = EditStore()
        _ws_write(folder, "a.txt", "new content")
        with open(path) as fh:
            self.assertEqual(fh.read(), "new content")
        real = os.path.realpath(path)
        edit.before(real, "original")
        edit.undo(real)
        with open(path) as fh:
            self.assertEqual(fh.read(), "original")

    def test_undo_missing_path_raises(self):
        edit = EditStore()
        with self.assertRaises(Exception):
            edit.undo("/tmp/nope")

    def test_diff_shows_changes(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        _write(os.path.join(folder, "a.txt"), "line1\nline2\n")
        diff = _ws_diff(folder, "a.txt", "line1\nchanged\n")
        self.assertIn("-", diff)
        self.assertIn("+", diff)
        self.assertIn("line2", diff)
        self.assertIn("changed", diff)


# ── Git tools ─────────────────────────────────────────────────────────

class GitTools(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        # Init a repo. Not through os.system and a shell redirect: cmd on Windows has no /dev/null.
        _write(os.path.join(self.folder, "README.md"), "hello")
        for args in (["init", "-q"], ["config", "user.email", "test@test.com"], ["config", "user.name", "Test"],
                     ["add", "-A"], ["commit", "-m", "init"]):
            subprocess.run(["git", *args], cwd=self.folder, capture_output=True, check=True)

    def test_git_status_works(self):
        result = _git_run(self.folder, ["status"])
        self.assertIn("nothing to commit", result.lower())

    def test_git_log_works(self):
        result = _git_run(self.folder, ["log", "--max-count=1"])
        self.assertIn("init", result)

    def test_git_diff_on_clean_repo(self):
        result = _git_run(self.folder, ["diff"])
        self.assertIn("(clean)", result)

    def test_git_push_is_refused(self):
        with self.assertRaises(Exception):
            _git_run(self.folder, ["push"])

    def test_git_reset_hard_is_refused(self):
        with self.assertRaises(Exception):
            _git_run(self.folder, ["reset", "--hard"])

    def test_git_clean_is_refused(self):
        with self.assertRaises(Exception):
            _git_run(self.folder, ["clean"])

    def test_git_checkout_dash_dash_is_refused(self):
        with self.assertRaises(Exception):
            _git_run(self.folder, ["checkout", "--", "README.md"])


# ── Shell ─────────────────────────────────────────────────────────────

class ShellTools(unittest.TestCase):
    def test_shell_echo_works(self):
        result = shell_run(tempfile.gettempdir(), "echo hello")
        self.assertIn("hello", result)

    def test_shell_git_push_is_refused(self):
        with self.assertRaises(Exception):
            shell_run("/tmp", "git push origin main")

    def test_shell_git_reset_is_refused(self):
        with self.assertRaises(Exception):
            shell_run("/tmp", "git reset --hard HEAD")

    def test_shell_rm_rf_is_refused(self):
        with self.assertRaises(Exception):
            shell_run("/tmp", "rm -rf /tmp")


# ── Context rules ─────────────────────────────────────────────────────

class WorkspaceRules(unittest.TestCase):
    def test_loads_agents_md(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        _write(os.path.join(folder, "AGENTS.md"), "project rules here")
        rules = load_workspace_rules(folder)
        self.assertIn("AGENTS.md", rules)
        self.assertIn("project rules here", rules)

    def test_loads_claude_md_when_no_agents(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        _write(os.path.join(folder, "CLAUDE.md"), "claude rules")
        rules = load_workspace_rules(folder)
        self.assertIn("claude rules", rules)

    def test_missing_file_is_fine(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        rules = load_workspace_rules(folder)
        self.assertEqual(rules, "")

    def test_does_not_load_secret_rules_file(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        # A file named .env.example is allowed, but .env is secret.
        _write(os.path.join(folder, ".env"), "SECRET=abc")
        rules = load_workspace_rules(folder)
        self.assertEqual(rules, "")

    def test_size_capped(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        big = "x" * 20000
        _write(os.path.join(folder, "AGENTS.md"), big)
        rules = load_workspace_rules(folder)
        # Should be capped at MAX_RULE_CHARS (8000) plus header.
        self.assertLess(len(rules), 20000)


# ── Builtins ──────────────────────────────────────────────────────────

class WorkspaceBuiltins(unittest.TestCase):
    def test_tools_without_workspace_offer_no_file_tools(self):
        from harness.agent.tools import Tools
        tools = Tools()
        # Without a workspace, only the read-only builtins are offered; write_file requires permission.
        names = {t.name for t in tools.tools.values()}
        self.assertIn("read_file", names)
        self.assertIn("list_dir", names)
        self.assertIn("write_file", names)
        # No workspace-scoped tools (search, git, shell, edit, undo) without a workspace.
        self.assertNotIn("search", names)
        self.assertNotIn("git_status", names)
        self.assertNotIn("shell", names)
        self.assertNotIn("edit", names)

    def test_no_workspace_returns_empty(self):
        self.assertEqual(workspace_builtins(None, EditStore()), [])

    def test_workspace_returns_tools(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        tools = workspace_builtins(folder, EditStore())
        names = {t.name for t in tools}
        expected = {
            "list_dir", "read_file", "search",
            "write_file", "edit", "delete_file", "undo_edit", "undo_last", "diff",
            "git_status", "git_log", "git_diff",
            "shell",
        }
        self.assertEqual(names, expected)

    def test_writes_flag_on_edit_tools(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        tools = workspace_builtins(folder, EditStore())
        write_names = {t.name for t in tools if t.writes}
        self.assertIn("write_file", write_names)
        self.assertIn("delete_file", write_names)
        self.assertIn("shell", write_names)
        self.assertNotIn("read_file", write_names)
        self.assertNotIn("list_dir", write_names)
        self.assertNotIn("search", write_names)


# ── No Stefan-specific paths ─────────────────────────────────────────

class NoUserPaths(unittest.TestCase):
    def test_source_has_no_home_stefan(self):
        src = open(os.path.join(os.path.dirname(__file__),
                                "..", "harness", "agent", "workspace.py")).read()
        self.assertNotIn("/home/stefan", src, "no home/stefan path in source")
        self.assertNotIn("~/Projects", src, "no ~/Projects path in source")
        self.assertNotIn("~/dotfiles", src, "no ~/dotfiles path in source")
        self.assertNotIn("~/.config/botwidget/widget.json", src, "no widget.json path in source")

    def test_source_has_no_hardcoded_default_workspace(self):
        src = open(os.path.join(os.path.dirname(__file__),
                                "..", "harness", "agent", "workspace.py")).read()
        # No DEFAULT_WORKSPACE constant.
        self.assertFalse(
            any("DEFAULT_WORKSPACE" in line for line in src.splitlines()))
        # No hardcoded path assignment to a workspace variable.
        for line in src.splitlines():
            stripped = line.strip()
            if re.match(r"^workspace\s*=", stripped):
                val = stripped.split("=", 1)[1].strip().strip("'\"")
                self.assertNotIn("/", val,
                                 "workspace should not default to a filesystem path")


# ── Integration with permission modes ─────────────────────────────────

class PermissionModes(unittest.TestCase):
    def test_modes_tuple_contains_expected_values(self):
        self.assertEqual(PERMISSION_MODES, ("ask", "allow", "allow_session"))


# ── Existing tests compatibility ──────────────────────────────────────

class ExistingTestsStillPass(unittest.TestCase):
    """Ensure the new module does not break existing patterns.

    The real integration tests live in test_harness_agent.py and
    test_harness_tools.py. This just checks imports and basic
    compatibility.
    """

    def test_module_imports_cleanly(self):
        import harness.agent.workspace
        self.assertTrue(hasattr(harness.agent.workspace, "workspace_builtins"))
        self.assertTrue(hasattr(harness.agent.workspace, "resolve_workspace"))

    def test_tool_error_is_still_available(self):
        from harness.agent.tools import ToolError
        with self.assertRaises(ToolError):
            raise ToolError("test")


if __name__ == "__main__":
    unittest.main()
