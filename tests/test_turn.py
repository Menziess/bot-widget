"""A turn as data: the guards that may send a step back to work, the loop detector, and where messages begin and end."""

import json
import unittest

from harness.agent.turn import Governor, LoopDetector, Step, Turn

OFFERED = {"accessibility", "browser_tabs", "write_file", "shell", "edit"}


def turn(user="hoi", **kwargs):
    return Turn(user_text=user, offered=OFFERED, **kwargs)


def step(text="", *names):
    calls = [{"id": name, "function": {"name": name, "arguments": json.dumps({"n": 1})}} for name in names]
    return Step(chunks=[text], calls=calls)


class Guards(unittest.TestCase):
    def test_an_answer_with_nothing_wrong_ends_the_turn(self):
        self.assertIsNone(Governor().review(turn(), step("Het is 14 graden.")))

    def test_a_tool_the_user_named_must_be_called(self):
        nudge = Governor().review(turn("Gebruik je browser_tabs tool"), step("Je hebt 3 tabs."))
        self.assertIn("browser_tabs", nudge.text)
        self.assertFalse(nudge.keeps_text, "a guess is not an answer")
        self.assertIsNone(Governor().review(turn("Gebruik je browser_tabs tool", called={"browser_tabs"}),
                                            step("Je hebt 3 tabs.")))

    def test_a_plain_word_that_is_also_a_tool_name_is_not_a_request(self):
        self.assertIsNone(Governor().review(turn("Ik wil edit niet gebruiken"), step("Prima.")))

    def test_a_claim_of_work_needs_a_tool_that_could_have_done_it(self):
        self.assertIsNotNone(Governor().review(turn(), step("Klaar, het staat erin.")))
        self.assertIsNotNone(Governor().review(turn(called={"list_dir"}), step("Het bestand is geschreven.")))
        self.assertIsNone(Governor().review(turn(called={"write_file"}), step("Het bestand is geschreven.")))
        self.assertIsNone(Governor().review(turn(), step("Is het bestand al geschreven?")), "a question claims nothing")

    def test_a_failure_the_closing_words_do_not_mention_is_sent_back_unless_they_own_up(self):
        self.assertIn("failed", Governor().review(turn(tool_failed=True), step("Het staat erin.")).text)
        self.assertIsNone(Governor().review(turn(tool_failed=True), step("Het is niet gelukt: bestand niet gevonden.")))

    def test_a_skill_message_is_kept_even_when_it_is_sent_back(self):
        nudge = Governor().review(turn(skill_on=True), step("Ik heb gekeken."))
        self.assertTrue(nudge.keeps_text)

    def test_each_guard_speaks_within_its_limit_so_a_turn_always_ends(self):
        governor = Governor()
        asked = turn("Gebruik browser_tabs")
        self.assertIsNotNone(governor.review(asked, step("Drie.")))
        self.assertIsNone(governor.review(asked, step("Drie.")), "the same reason never blocks twice")
        skill = Governor()
        skilled = turn(skill_on=True)
        self.assertEqual([bool(skill.review(skilled, step("Ok."))) for _ in range(3)], [True, True, False])
        self.assertTrue(skill.nudged)


class Loops(unittest.TestCase):
    def test_the_same_step_three_times_in_a_row_is_a_loop(self):
        loop = LoopDetector(3)
        self.assertEqual([loop.stuck(step("", "shell")) for _ in range(3)], ["", "", "shell"])

    def test_three_equal_calls_inside_one_step_are_one_step(self):
        self.assertEqual(LoopDetector(3).stuck(step("", "shell", "shell", "shell")), "")

    def test_a_different_step_breaks_the_run_and_zero_turns_it_off(self):
        loop = LoopDetector(3)
        for names in (("shell",), ("edit",), ("shell",)):
            self.assertEqual(loop.stuck(step("", *names)), "")
        off = LoopDetector(0)
        self.assertEqual([off.stuck(step("", "shell")) for _ in range(5)], [""] * 5)


class Messages(unittest.TestCase):
    def test_pieces_with_one_id_are_one_message_and_another_id_starts_a_new_one(self):
        from botwidget.acplink import _append_message
        messages = []
        _append_message(messages, "bot", "Het ", True, "a")
        _append_message(messages, "bot", "Het is gelukt.", True, "a")
        _append_message(messages, "bot", "I stopped: a loop.", True, "b")
        self.assertEqual([m["text"] for m in messages], ["Het is gelukt.", "I stopped: a loop."])

    def test_an_agent_without_ids_keeps_one_message_per_run_of_pieces(self):
        from botwidget.acplink import _append_message
        messages = []
        _append_message(messages, "bot", "Een ", False)
        _append_message(messages, "bot", "bericht", False)
        self.assertEqual([m["text"] for m in messages], ["Een bericht"])


if __name__ == "__main__":
    unittest.main()
