"""Background shell jobs: start, list, cancel, a later turn, and optional exit hooks.

No network beyond localhost. Hook secrets stay in a key file and out of the log.
"""

import asyncio
import json
import os
import shlex
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from harness.agent.agent import LeanAgent
from harness.agent.jobs import JobRunner, config_from_env
from harness.agent.store import SessionStore
from harness.agent.tools import ToolError
from tests.test_harness_direct import ScriptModel

JOB_ENV = (
    "HARNESS_WORKSPACE", "HARNESS_WORKSPACE_PERMISSIONS", "HARNESS_AGENT_DIR",
    "HARNESS_JOB_HOOK", "HARNESS_JOB_HOOK_URL", "HARNESS_JOB_HOOK_KEY_FILE",
    "HARNESS_JOB_MAX", "HARNESS_JOB_TAIL", "HARNESS_JOB_TIMEOUT",
)
SECRET = "hook-bearer-token-9f3a"


def py(code: str) -> str:
    return f"{sys.executable} -c {shlex.quote(code)}"


def wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class Block:
    def __init__(self, text):
        self.text = text


def call(name, arguments, call_id="1"):
    return {"id": call_id, "function": {"name": name, "arguments": json.dumps(arguments)}}


class AskConn:
    def __init__(self, allow=True):
        self.allow = allow
        self.asks = []

    async def session_update(self, session_id, update):
        return None

    async def request_permission(self, **kwargs):
        self.asks.append(getattr(kwargs.get("tool_call"), "title", ""))

        class Outcome:
            outcome = "selected" if self.allow else "cancelled"
            option_id = "allow" if self.allow else ""

        class Response:
            outcome = Outcome()

        return Response()


class RecordingModel(ScriptModel):
    def __init__(self, scripts):
        super().__init__(scripts)
        self.seen = []
        self.tool_names = []
        self.specs = ""

    def stream(self, messages, tools=None, stop=None, opened=None):
        self.seen.append(json.dumps(messages))
        self.tool_names = [tool["function"]["name"] for tool in tools or []]
        self.specs = json.dumps(tools or [])
        return super().stream(messages, tools, stop, opened)


class HookServer:
    def __init__(self):
        self.hits = []
        self.event = threading.Event()
        box = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                box.hits.append((raw, self.headers.get("Authorization")))
                box.event.set()
                self.send_response(204)
                self.end_headers()

            def log_message(self, *_args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/hook"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()


class Jobs(unittest.TestCase):
    """Should start, list and cancel a background command without leaving it running."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.done = []
        self.runner = JobRunner(self.folder, lambda sid, text: self.done.append((sid, text)))
        self.addCleanup(self.runner.shutdown)

    def test_start_list_and_cancel(self):
        """Should show a running job and then stop it."""
        started = self.runner.start("s1", py("import time; time.sleep(30)"))
        self.assertIn("j1", started)
        listed = self.runner.list("s1")
        self.assertIn("j1", listed)
        self.assertIn("running", listed)
        self.assertEqual(self.runner.list("other"), "(no background jobs)")
        self.assertIn("Cancelled", self.runner.cancel("s1", "j1"))
        self.assertTrue(wait_until(lambda: self.runner.jobs["j1"].status != "running"))
        self.assertEqual(self.runner.jobs["j1"].status, "cancelled")
        self.assertIsNotNone(self.runner.jobs["j1"].proc.poll())
        self.assertTrue(wait_until(lambda: self.done), "a cancelled job is still delivered")

    def test_shutdown_kills_a_running_job(self):
        """Should kill jobs when the agent process stops."""
        self.runner.start("s1", py("import time; time.sleep(30)"))
        proc = self.runner.jobs["j1"].proc
        self.runner.shutdown()
        self.assertTrue(wait_until(lambda: proc.poll() is not None))

    def test_a_refused_command_does_not_start(self):
        """Should use the same refusal list as shell."""
        with self.assertRaises(ToolError):
            self.runner.start("s1", "rm -rf /tmp/bw-job")
        self.assertEqual(self.runner.jobs, {})

    def test_too_many_jobs_are_refused(self):
        """Should keep the default cap small."""
        self.runner.max_jobs = 1
        self.runner.start("s1", py("import time; time.sleep(30)"))
        with self.assertRaises(ToolError):
            self.runner.start("s1", py("import time; time.sleep(30)"))
        self.assertEqual(self.runner.running_count(), 1)

    def test_output_is_a_tail_and_secrets_are_redacted(self):
        """Should keep the end of a long output and hide a token."""
        self.runner.tail = 80
        code = "print('S'*3000 + 'ENDMARK token=super-secret-token-xyz')"
        self.runner.start("s1", py(code))
        self.assertTrue(wait_until(lambda: self.done))
        text = self.done[0][1]
        self.assertIn("ENDMARK", text)
        self.assertIn("[redacted]", text)
        self.assertNotIn("super-secret-token-xyz", text)
        self.assertNotIn("S" * 60, text)
        self.assertIn("…[cut]", text)
        self.assertIn("exit_code: 0", text)

    def test_hooks_are_off_by_default(self):
        """Should not call a webhook or a shell hook unless config says so."""
        self.assertEqual(config_from_env({}), {
            "hook_command": "", "hook_url": "", "hook_key_file": "",
            "tail": 4000, "max_jobs": 4, "timeout": None,
        })
        server = HookServer()
        self.addCleanup(server.close)
        self.runner.start("s1", py("print('quiet')"))
        self.assertTrue(wait_until(lambda: self.done))
        self.assertEqual(server.hits, [])
        self.assertEqual(self.runner.hook_command, "")
        self.assertEqual(self.runner.hook_url, "")


class Hooks(unittest.TestCase):
    """Should post the exit payload and keep the bearer token out of the log."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.key = os.path.join(self.folder, "hook-token")
        with open(self.key, "w") as fh:
            fh.write(SECRET + "\n")
        self.out = os.path.join(self.folder, "hook.json")
        script = os.path.join(self.folder, "hook.py")
        with open(script, "w") as fh:
            fh.write("import pathlib, sys\npathlib.Path(sys.argv[1]).write_text(sys.stdin.read())\n")
        self.hook_command = f"{sys.executable} {shlex.quote(script)} {shlex.quote(self.out)}"
        self.server = HookServer()
        self.addCleanup(self.server.close)
        self.done = []
        self.runner = JobRunner(
            self.folder, lambda sid, text: self.done.append((sid, text)),
            hook_command=self.hook_command, hook_url=self.server.url, hook_key_file=self.key)
        self.addCleanup(self.runner.shutdown)

    def test_webhook_and_shell_hook_get_the_payload_and_the_key_is_not_logged(self):
        """Should send job id, command, exit code, duration and a tail, and not log the token."""
        with self.assertLogs("harness.agent.jobs", level="INFO") as caught:
            self.runner.start("s1", py("print('hello-hook')"))
            self.assertTrue(wait_until(lambda: self.done), "the job result was not delivered")
        logged = "\n".join(caught.output)
        self.assertNotIn(SECRET, logged)
        body, auth = self.server.hits[0]
        payload = json.loads(body)
        self.assertEqual(auth, "Bearer " + SECRET)
        self.assertEqual(set(payload), {"job_id", "command", "exit_code", "duration", "summary"})
        self.assertEqual(payload["job_id"], "j1")
        self.assertEqual(payload["exit_code"], 0)
        self.assertIn("hello-hook", payload["summary"])
        self.assertNotIn(SECRET, body.decode())
        with open(self.out) as fh:
            shell_raw = fh.read()
        shell_payload = json.loads(shell_raw)
        self.assertEqual(shell_payload["job_id"], "j1")
        self.assertIn("hello-hook", shell_payload["summary"])
        self.assertNotIn(SECRET, shell_raw)
        self.assertNotIn(SECRET, logged)
        self.assertIn(self.key, self.runner.hook_key_file)
        self.assertNotIn(SECRET, self.runner.hook_key_file)

    def test_a_failing_hook_does_not_drop_the_result(self):
        """Should log a hook failure and still deliver the job."""
        self.runner.hook_command = py("import sys; sys.exit(3)")
        self.runner.hook_url = ""
        with self.assertLogs("harness.agent.jobs", level="WARNING") as caught:
            self.runner.start("s1", py("print('still-here')"))
            self.assertTrue(wait_until(lambda: self.done))
        self.assertIn("still-here", self.done[0][1])
        self.assertIn("job hook failed", "\n".join(caught.output))
        self.assertNotIn(SECRET, "\n".join(caught.output))


class AgentJobs(unittest.IsolatedAsyncioTestCase):
    """Should deliver a finished job to the same session, and only after the turn."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.addCleanup(shutil.rmtree, self.state, True)
        self._old = {key: os.environ.get(key) for key in JOB_ENV}
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        for key, value in self._old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _env(self, permission="ask", **extra):
        for key in JOB_ENV:
            os.environ.pop(key, None)
        os.environ["HARNESS_WORKSPACE"] = self.folder
        os.environ["HARNESS_WORKSPACE_PERMISSIONS"] = permission
        os.environ["HARNESS_AGENT_DIR"] = self.state
        os.environ.update(extra)

    def agent(self, model, allow=True, permission="ask", **extra):
        self._env(permission, **extra)
        agent = LeanAgent("JobBot", model, folder=self.state)
        agent.conn = AskConn(allow=allow)
        self.addCleanup(agent.shutdown)
        return agent

    async def _until(self, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            await asyncio.sleep(0.02)
        return False

    async def test_a_denied_ask_does_not_start_the_job(self):
        """Should refuse a background command when shell permission is denied."""
        model = RecordingModel([
            [("tool_calls", [call("shell_background", {"command": py("import time; time.sleep(30)")})])],
            [("text", "no")],
        ])
        agent = self.agent(model, allow=False, permission="ask")
        await agent.prompt("s1", [Block("go")])
        self.assertTrue(agent.conn.asks)
        self.assertIn("shell_background", agent.conn.asks[0])
        self.assertEqual(agent.jobs.running_count(), 0)
        self.assertEqual(agent.jobs.jobs, {})

    async def test_allowlist_still_asks_and_a_denial_does_not_start(self):
        """Should not treat allowlist as a bypass for background shell."""
        model = RecordingModel([
            [("tool_calls", [call("shell_background", {"command": py("import time; time.sleep(30)")})])],
            [("text", "no")],
        ])
        agent = self.agent(model, allow=False, permission="allowlist")
        await agent.prompt("s1", [Block("go")])
        self.assertEqual(agent.tools.permission, "allow")
        self.assertTrue(agent.conn.asks)
        self.assertEqual(agent.jobs.jobs, {})

    async def test_a_refused_pattern_does_not_start_even_when_allowed(self):
        """Should refuse rm -rf inside the same shell check."""
        model = RecordingModel([
            [("tool_calls", [call("shell_background", {"command": "rm -rf /tmp/bw-job"})])],
            [("text", "no")],
        ])
        agent = self.agent(model, allow=True, permission="ask")
        await agent.prompt("s1", [Block("go")])
        self.assertEqual(agent.jobs.jobs, {})
        self.assertIn("refused", model.seen[-1])

    async def test_a_finished_job_is_a_new_turn_in_the_same_session(self):
        """Should tell the model the exit output after the command exits."""
        command = py("import os; print(os.getcwd()); print('FINISHED-JOB')")
        model = RecordingModel([
            [("tool_calls", [call("shell_background", {"command": command})])],
            [("text", "started")],
            [("text", "saw the job")],
        ])
        agent = self.agent(model, allow=True, permission="ask")
        await agent.prompt("s1", [Block("go")])
        store = agent.stores["s1"]
        self.assertTrue(await self._until(lambda: any(
            message["role"] == "bot" and "saw the job" in message["text"] for message in store.messages())))
        text = "\n".join(message["text"] for message in store.messages() if message["role"] == "user")
        self.assertIn("FINISHED-JOB", text)
        self.assertIn(os.path.realpath(self.folder), text)
        self.assertIn("exit_code: 0", text)
        self.assertEqual(list(agent.stores), ["s1"])
        self.assertIn("shell_background", model.tool_names)
        self.assertIn("jobs", model.tool_names)
        self.assertIn("job_cancel", model.tool_names)
        self.assertIn("Same permission", model.specs)
        self.assertIn("Background shell", model.seen[0])

    async def test_a_job_that_finishes_during_a_turn_waits_until_the_turn_ends(self):
        """Should queue every completion and deliver it afterwards, in order."""
        state = {}

        def hold(stop):
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and sum(len(items) for items in agent._inbox.values()) < 2:
                time.sleep(0.02)
            state["queued"] = sum(len(items) for items in agent._inbox.values())
            state["mid"] = " ".join(message["text"] for message in agent.stores["s1"].messages())
            yield ("text", "turn done")

        model = RecordingModel([
            [("tool_calls", [
                call("shell_background", {"command": py("import time; time.sleep(0.2); print('FINISHED-ONE')")}, "1"),
                call("shell_background", {"command": py("import time; time.sleep(0.25); print('FINISHED-TWO')")}, "2"),
            ])],
            hold,
            [("text", "saw one")],
            [("text", "saw two")],
        ])
        agent = self.agent(model, allow=True)
        await agent.prompt("s1", [Block("go")])
        self.assertGreaterEqual(state.get("queued"), 2)
        self.assertNotIn("Background job j1 finished", state["mid"])
        self.assertNotIn("Background job j2 finished", state["mid"])
        # The command text is already in the tool call. The exit line is the result, and it waits.
        self.assertNotIn("Background job j1 finished", model.seen[1])
        self.assertNotIn("exit_code:", model.seen[1])
        store = agent.stores["s1"]
        self.assertTrue(await self._until(lambda: sum(
            1 for message in store.messages() if message["role"] == "bot" and message["text"].startswith("saw ")
        ) >= 2))
        users = [message["text"] for message in store.messages() if message["role"] == "user"]
        self.assertLess(users.index(next(text for text in users if "FINISHED-ONE" in text)),
                        users.index(next(text for text in users if "FINISHED-TWO" in text)))
        self.assertIn("FINISHED-ONE", model.seen[2])
        self.assertIn("FINISHED-TWO", model.seen[3])

    async def test_config_hooks_run_for_a_job_the_model_started(self):
        """Should read the hook URL and key file from config, not from a hard-coded address."""
        key = os.path.join(self.folder, "hook-token")
        with open(key, "w") as fh:
            fh.write(SECRET + "\n")
        out = os.path.join(self.folder, "hook.json")
        script = os.path.join(self.folder, "hook.py")
        with open(script, "w") as fh:
            fh.write("import pathlib, sys\npathlib.Path(sys.argv[1]).write_text(sys.stdin.read())\n")
        server = HookServer()
        self.addCleanup(server.close)
        command = py("print('from-agent')")
        model = RecordingModel([
            [("tool_calls", [call("shell_background", {"command": command})])],
            [("text", "started")],
            [("text", "noted")],
        ])
        agent = self.agent(
            model, allow=True,
            HARNESS_JOB_HOOK=f"{sys.executable} {shlex.quote(script)} {shlex.quote(out)}",
            HARNESS_JOB_HOOK_URL=server.url,
            HARNESS_JOB_HOOK_KEY_FILE=key)
        with self.assertLogs("harness.agent.jobs", level="INFO") as caught:
            await agent.prompt("s1", [Block("go")])
            self.assertTrue(await self._until(
                lambda: agent._inbox.get("s1") or any(
                    "from-agent" in message["text"] for message in agent.stores["s1"].messages())))
        logged = "\n".join(caught.output)
        self.assertNotIn(SECRET, logged)
        body, auth = server.hits[0]
        self.assertEqual(auth, "Bearer " + SECRET)
        payload = json.loads(body)
        self.assertEqual(payload["exit_code"], 0)
        self.assertIn("from-agent", payload["summary"])
        self.assertNotIn(SECRET, body.decode())
        with open(out) as fh:
            self.assertNotIn(SECRET, fh.read())
        self.assertEqual(agent.jobs.hook_url, server.url)
        self.assertEqual(agent.jobs.hook_key_file, key)
        self.assertNotIn(SECRET, agent.jobs.hook_key_file)
        self.assertTrue(os.path.exists(out))
