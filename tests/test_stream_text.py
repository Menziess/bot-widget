"""The stage every answer passes through, and the cost of passing: it runs on every piece of a streamed answer."""

import random
import re
import unittest

from harness import stream_text
from harness.stream_text import _LEAK, _strip_leak, _tail_cut, collapse_repeats, fold_chunk


def reference(text: str, endings) -> str:
    """What the stage did before it looked only at the end of a text: the same patterns over the whole text."""
    text = _LEAK.sub("", text)
    if endings:
        names = "|".join(re.escape(name) for name in sorted(endings, key=len, reverse=True))
        text = re.sub(rf"(?<=\S)(?:{names}|{_LEAK.pattern[:-1]})+$", "", text)
    return text


class SameAnswers(unittest.TestCase):
    def test_looking_only_at_the_end_gives_the_answers_the_whole_text_gave(self):
        pieces = ["Booked.", " ", "\n", "not_for_me", "not_for", "_me", "wait_for_user", "done", "Done", "noteddone",
                  "x", "2026", ".", "WAIT_FOR", "notforme", "undone"]
        rng = random.Random(7)
        for _ in range(3000):
            text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 12)))
            for endings in ((), ("done",), ("done", "not_for_me", "wait_for_user")):
                self.assertEqual(_strip_leak(text, endings), reference(text, endings), (text, endings))


class Cost(unittest.TestCase):
    def test_only_the_end_of_a_long_text_is_looked_at(self):
        seen = []

        class Spy:
            def search(self, text):
                seen.append(len(text))
                return _LEAK.search(text)

        text = "word " * 200_000 + "not_for_menot_for_me"
        self.assertEqual(_tail_cut(Spy(), text), "word " * 200_000)
        self.assertLessEqual(max(seen), stream_text._WINDOW + 1)

    def test_a_run_longer_than_the_window_goes_whole(self):
        text = "Answer. " + "not_for_me" * 100
        self.assertEqual(_strip_leak(text, ()), "Answer. ")

    def test_a_streamed_answer_folds_to_itself_piece_by_piece(self):
        answer = "".join(f"Paragraph {i} with some words.\n\n" for i in range(300))
        shown = ""
        for end in range(0, len(answer) + 7, 7):
            shown = fold_chunk(shown, answer[:end])
        self.assertEqual(shown, answer)


class Repeats(unittest.TestCase):
    def test_a_paragraph_the_one_before_says_again_goes_and_the_later_copy_stays(self):
        said = "Het script loopt nog, ik wacht op het resultaat.\n\nHet script loopt nog, ik wacht op het resultaat!"
        self.assertEqual(collapse_repeats(said), "Het script loopt nog, ik wacht op het resultaat!")
        thrice = "Waiting for the job to end now.\n\n" * 2 + "Waiting for the job to end now."
        self.assertEqual(collapse_repeats(thrice), "Waiting for the job to end now.")

    def test_a_paraphrase_a_short_line_and_a_code_block_stay(self):
        paraphrase = ("De achtergrondtaak voor woensdag 25 november 2026 draait nog. Ik wacht op het resultaat.\n\n"
                      "De boekingsopdracht voor woensdag 25 november 2026 is nog bezig. Ik wacht af.")
        self.assertEqual(collapse_repeats(paraphrase), paraphrase)
        self.assertEqual(collapse_repeats("Ok.\n\nOk."), "Ok.\n\nOk.")
        code = "Run this:\n\n```sh\nmake test\n```\n\n```sh\nmake test\n```"
        self.assertEqual(collapse_repeats(code), code)
        self.assertEqual(collapse_repeats("One.\n\nTwo is different here.\n\nThree is not like it."),
                         "One.\n\nTwo is different here.\n\nThree is not like it.")
        self.assertEqual(collapse_repeats(""), "")
