import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from botwidget import remote


class FakeLink:
    def __init__(self):
        self.messages = []

    def send(self, text):
        self.messages.append({"role": "user", "text": text})
        return True, ""

    def chat(self):
        return {"messages": list(self.messages), "activity": "", "failed": "", "approvals": []}

    def active(self):
        return False

    def decide(self, request_id, accept, source, by):
        self.decided = (request_id, accept, source, by)
        return request_id == "r1"

    def note(self):
        return ""


class RemoteTest(unittest.TestCase):
    def test_send_then_read_through_the_file_info(self):
        link = FakeLink()
        faces = SimpleNamespace(faces={"acp:x": SimpleNamespace(link=link)})
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(remote, "INFO", os.path.join(folder, "i")):
            server = remote.serve(faces)
            try:
                self.assertEqual(remote._call("")["bots"], ["acp:x"])
                self.assertTrue(remote._call("send", {"bot": "acp:x", "text": "hoi"})["ok"])
                self.assertEqual(remote._call("acp:x")["messages"][0]["text"], "hoi")
                self.assertIn("error", remote._call("nope"))
                self.assertTrue(remote._call("decide", {"bot": "acp:x", "id": "r1", "accept": True, "by": "claude"})["ok"])
                self.assertEqual(link.decided, ("r1", True, "cli", "claude"))
                self.assertFalse(remote._call("decide", {"bot": "acp:x", "id": "r2", "accept": True, "by": "c"})["ok"])
            finally:
                server.shutdown()


if __name__ == "__main__":
    unittest.main()
