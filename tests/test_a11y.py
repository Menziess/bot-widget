"""Desktop accessibility is reported without a real bus."""

import json
import os
import tempfile
import unittest
from unittest import mock

from botwidget.system import a11y
from harness.agent.agent import A11Y_NUDGE, LeanAgent
from harness.agent.context import SYSTEM
from harness.agent.tools import Tools, accessibility_requested, accessibility_text
from tests.test_harness_direct import Block, Conn, ScriptModel


class _Child:
    def __init__(self, name):
        self._name = name

    def get_name(self):
        return self._name


class _Desktop:
    def __init__(self, names):
        self._names = names

    def get_child_count(self):
        return len(self._names)

    def get_child_at_index(self, index):
        return _Child(self._names[index])


class _Bus:
    def __init__(self, names=("botwidget", "gnome-shell")):
        self.names = names

    def get_desktop(self, index):
        return _Desktop(self.names)


class AccessibilityProbe(unittest.TestCase):
    def setUp(self):
        a11y.clear()

    def test_a_working_bus_is_available(self):
        with mock.patch.object(a11y, "_platform_name", return_value="linux"):
            row = a11y.accessibility(load=lambda: _Bus())
        self.assertTrue(row["available"])
        self.assertEqual(row["reason"], "AT-SPI")
        self.assertEqual(row["platform"], "linux")

    def test_a_missing_typelib_is_unavailable_and_names_the_desktop_packages(self):
        def load():
            raise ImportError("Atspi typelib")

        with mock.patch.object(a11y, "_platform_name", return_value="linux"):
            row = a11y.accessibility(load=load)
        self.assertFalse(row["available"])
        self.assertIn("gir1.2-atspi-2.0", row["reason"])
        self.assertIn("python3-gi", row["reason"])
        self.assertNotIn("sudo", row["reason"])
        self.assertNotIn("pyatspi", row["reason"])

    def test_an_empty_desktop_is_unavailable(self):
        with mock.patch.object(a11y, "_platform_name", return_value="linux"):
            row = a11y.accessibility(load=lambda: type("B", (), {"get_desktop": lambda self, i: None})())
        self.assertFalse(row["available"])
        self.assertIn("no desktop", row["reason"])

    def test_the_status_is_logged_once(self):
        lines = []
        with mock.patch.object(a11y, "_probe", return_value={"available": True, "reason": "AT-SPI", "platform": "linux"}):
            a11y.log_once(lines.append)
            a11y.log_once(lines.append)
        self.assertEqual(lines, ["accessibility: yes (AT-SPI)"])

    def test_application_names_come_from_the_bus(self):
        names = a11y.application_names(load=lambda: _Bus(("botwidget", "Chrome")))
        self.assertEqual(names, ["botwidget", "Chrome"])

    def test_install_does_nothing_until_the_user_agrees(self):
        calls = []
        self.assertIn("agreement", a11y.install_after_agree(False, run=calls.append))
        self.assertEqual(calls, [])
        a11y.install_after_agree(True, run=lambda command, check=False: calls.append(command))
        self.assertEqual(calls, [["pkexec", "apt-get", "install", "-y", "gir1.2-atspi-2.0", "python3-gi"]])

    def test_a_missing_gi_says_to_run_doctor_and_does_not_link(self):
        def load():
            raise ModuleNotFoundError("No module named 'gi'")

        with mock.patch.object(a11y, "_platform_name", return_value="linux"):
            row = a11y.accessibility(load=load)
        self.assertFalse(row["available"])
        self.assertIn("botwidget doctor", row["reason"])
        self.assertNotIn("sudo", row["reason"])

    def test_doctor_links_then_reports(self):
        with mock.patch.object(a11y, "link_system_gi", return_value=["/venv/gi"]) as link, \
                mock.patch.object(a11y, "accessibility", return_value={"available": True, "reason": "AT-SPI", "platform": "linux"}):
            text = a11y.doctor()
        link.assert_called_once_with()
        self.assertIn("linked gi", text)
        self.assertIn("accessibility: yes", text)

    def test_importing_botwidget_does_not_link_gi(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "botwidget", "__init__.py")) as fh:
            source = fh.read()
        self.assertNotIn("link_system_gi", source)

    def test_a_fresh_venv_gets_the_system_gi_link(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "dist")
            site = os.path.join(folder, "site")
            os.makedirs(os.path.join(source, "gi"))
            with open(os.path.join(source, "gi", "__init__.py"), "w") as fh:
                fh.write("gi = 1\n")
            os.makedirs(os.path.join(source, "PyGObject-1.dist-info"))
            made = a11y.link_system_gi(site, source=source)
            self.assertTrue(os.path.islink(os.path.join(site, "gi")))
            self.assertTrue(os.path.islink(os.path.join(site, "PyGObject-1.dist-info")))
            self.assertEqual(a11y.link_system_gi(site, source=source), [])
            self.assertEqual(len(made), 2)

    def test_a_symlink_error_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "dist")
            site = os.path.join(folder, "site")
            os.makedirs(os.path.join(source, "gi"))
            with mock.patch("os.symlink", side_effect=OSError("busy")):
                self.assertEqual(a11y.link_system_gi(site, source=source), [])
            self.assertFalse(os.path.lexists(os.path.join(site, "gi")))

    def test_a_non_debian_machine_does_not_use_the_debian_path(self):
        seen = []

        def isdir(path):
            seen.append(path)
            return False

        with mock.patch("os.path.isfile", return_value=False), mock.patch("os.path.isdir", side_effect=isdir):
            self.assertEqual(a11y.system_gi_source(), "")
        self.assertFalse(any(str(path).startswith("/usr/lib/python3/dist-packages") for path in seen))

    def test_consent_is_a_design_and_does_not_run_pkexec(self):
        self.assertFalse(a11y.CONSENT["built"])
        self.assertEqual(a11y.CONSENT["choices"], ("Agree", "Not now"))
        self.assertEqual(a11y.CONSENT["install"], "install_after_agree")
        self.assertNotIn("pkexec", a11y.CONSENT["choices"])

    def test_windows_and_macos_are_named_and_not_available(self):
        with mock.patch.object(a11y, "_platform_name", return_value="windows"):
            row = a11y.accessibility(load=lambda: _Bus())
        self.assertFalse(row["available"])
        self.assertIn("UI Automation", row["reason"])
        with mock.patch.object(a11y, "_platform_name", return_value="macos"):
            row = a11y.accessibility(load=lambda: _Bus())
        self.assertFalse(row["available"])
        self.assertIn("AX", row["reason"])


class AccessibilityTool(unittest.IsolatedAsyncioTestCase):
    def test_the_prompt_names_the_tool_and_an_empty_query_lists_names(self):
        self.assertIn("heuristic", accessibility_requested.__doc__.lower())
        self.assertIn("matching tool", SYSTEM)
        self.assertTrue(accessibility_requested(
            "Which applications are open on my desktop? Use your accessibility tool."))
        self.assertFalse(accessibility_requested("hello"))
        with mock.patch("botwidget.system.a11y.accessibility", return_value={"available": True, "reason": "AT-SPI", "platform": "linux"}), \
                mock.patch("botwidget.system.a11y.application_names", return_value=["botwidget", "Chrome"]):
            text = accessibility_text("")
        self.assertIn("botwidget", text)
        offered = {tool.name for tool in Tools("").tools.values()}
        self.assertIn("accessibility", offered)

    async def test_a_reply_without_the_call_is_nudged_into_the_tool(self):
        promise = [("text", "No applications matched"), ("finish", "stop")]
        call = ("tool_calls", [{"id": "a1", "function": {"name": "accessibility", "arguments": json.dumps({})}}])
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, True))
        agent = LeanAgent("bot", ScriptModel([promise, [call, ("finish", "tool_calls")],
                                               [("text", "botwidget is open."), ("finish", "stop")]]),
                          folder=os.path.join(folder, "agent"))
        agent.on_connect(Conn())
        session = (await agent.new_session(cwd=folder)).session_id
        with mock.patch("botwidget.system.a11y.accessibility", return_value={"available": True, "reason": "AT-SPI", "platform": "linux"}), \
                mock.patch("botwidget.system.a11y.application_names", return_value=["botwidget"]):
            await agent.prompt(session, [Block("Which applications are open on my desktop? Use your accessibility tool.")])
        results = agent.stores[session].tool_results()
        self.assertTrue(results)
        self.assertEqual(results[-1]["name"], "accessibility")
        self.assertIn("botwidget", results[-1]["full"])

    async def test_any_reply_that_ends_on_a_promise_is_nudged_into_the_tool(self):
        promise = [("text", "Ik ga ze nu opvragen."), ("finish", "stop")]
        call = ("tool_calls", [{"id": "b1", "function": {"name": "accessibility", "arguments": json.dumps({})}}])
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, True))
        agent = LeanAgent("bot", ScriptModel([promise, [call, ("finish", "tool_calls")],
                                               [("text", "Klaar."), ("finish", "stop")]]),
                          folder=os.path.join(folder, "agent"))
        agent.on_connect(Conn())
        session = (await agent.new_session(cwd=folder)).session_id
        with mock.patch("botwidget.system.a11y.accessibility", return_value={"available": True, "reason": "AT-SPI", "platform": "linux"}), \
                mock.patch("botwidget.system.a11y.application_names", return_value=["botwidget"]):
            await agent.prompt(session, [Block("Doe iets nuttigs")])
        self.assertEqual(agent.stores[session].tool_results()[-1]["name"], "accessibility")

    async def test_a_done_claim_with_no_tool_call_in_the_turn_is_nudged_into_the_tool(self):
        claim = [("text", "Done. hello.py geschreven en uitgevoerd."), ("finish", "stop")]
        call = ("tool_calls", [{"id": "c1", "function": {"name": "accessibility", "arguments": json.dumps({})}}])
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, True))
        agent = LeanAgent("bot", ScriptModel([claim, [call, ("finish", "tool_calls")],
                                               [("text", "Ok."), ("finish", "stop")]]),
                          folder=os.path.join(folder, "agent"))
        agent.on_connect(Conn())
        session = (await agent.new_session(cwd=folder)).session_id
        with mock.patch("botwidget.system.a11y.accessibility", return_value={"available": True, "reason": "AT-SPI", "platform": "linux"}), \
                mock.patch("botwidget.system.a11y.application_names", return_value=["botwidget"]):
            await agent.prompt(session, [Block("Schrijf een script")])
        self.assertEqual(agent.stores[session].tool_results()[-1]["name"], "accessibility")

    async def test_a_line_written_before_the_accessibility_call_is_never_shown(self):
        """The model guesses the result before it has it ("No applications matched"); only the tool's list counts."""
        guess = [("text", "Geen applicaties gevonden."),
                 ("tool_calls", [{"id": "a1", "function": {"name": "accessibility", "arguments": json.dumps({})}}]),
                 ("finish", "tool_calls")]
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, True))
        conn = Conn()
        agent = LeanAgent("bot", ScriptModel([guess, [("text", "Open: botwidget."), ("finish", "stop")]]),
                          folder=os.path.join(folder, "agent"))
        agent.on_connect(conn)
        session = (await agent.new_session(cwd=folder)).session_id
        with mock.patch("botwidget.system.a11y.accessibility", return_value={"available": True, "reason": "AT-SPI", "platform": "linux"}), \
                mock.patch("botwidget.system.a11y.application_names", return_value=["botwidget"]):
            await agent.prompt(session, [Block("Which applications are open on my desktop?")])
        shown = "".join(u.content.text for _s, u in conn.updates
                        if getattr(u, "session_update", "") == "agent_message_chunk")
        self.assertEqual(shown, "Open: botwidget.")

    async def test_a_correct_accessibility_call_is_one_answer_with_no_nudge(self):
        seen = []

        class Watch(ScriptModel):
            def stream(self, messages, tools=None, stop=None, opened=None):
                seen.append(messages)
                return super().stream(messages, tools, stop, opened)

        call = ("tool_calls", [{"id": "a1", "function": {"name": "accessibility", "arguments": json.dumps({})}}])
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, True))
        agent = LeanAgent("bot", Watch([[call, ("finish", "tool_calls")],
                                         [("text", "botwidget is open."), ("finish", "stop")]]),
                          folder=os.path.join(folder, "agent"))
        agent.on_connect(Conn())
        session = (await agent.new_session(cwd=folder)).session_id
        ask = "Which applications are open on my desktop? Use your accessibility tool."
        with mock.patch("botwidget.system.a11y.accessibility", return_value={"available": True, "reason": "AT-SPI", "platform": "linux"}), \
                mock.patch("botwidget.system.a11y.application_names", return_value=["botwidget"]):
            await agent.prompt(session, [Block(ask)])
        self.assertEqual(len(seen), 2)
        blob = json.dumps(seen)
        self.assertNotIn(A11Y_NUDGE, blob)
        texts = [item[1].content.text for item in agent.conn.updates
                 if getattr(item[1], "session_update", "") == "agent_message_chunk"]
        self.assertEqual(texts, ["botwidget is open."])

    async def test_a_hidden_accessibility_tool_is_not_nudged(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, True))
        agent = LeanAgent("bot", ScriptModel([[("text", "I cannot list them."), ("finish", "stop")]]),
                          folder=os.path.join(folder, "agent"))
        agent.on_connect(Conn())
        session = (await agent.new_session(cwd=folder)).session_id
        agent.stores[session].set("skill_deny", "accessibility")
        await agent.prompt(session, [Block("Which applications are open on my desktop? Use your accessibility tool.")])
        self.assertEqual(agent.stores[session].tool_results(), [])
