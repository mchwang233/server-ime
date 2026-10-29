"""Next-word suggestions after a commit (product_controller.py), on the test backend.

Run: PYTHONPATH=platform:interface/src python3 -B platform/tests/test_prediction_flow.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "platform"), str(ROOT / "interface/src")]

from ime_interface import config
from server_ime.deterministic import create_session
from server_ime.product_controller import ProductController

ESCAPE, BACKSPACE, DOWN = 0xFF1B, 0xFF08, 0xFF54


class Suggesting:
    """The deterministic backend plus a predict() that records what it was asked."""

    def __init__(self):
        self.backend = create_session()
        self.asked = []

    def predict(self, history, limit=10):
        self.asked.append(list(history))
        return ["的", "我们", "可以"][:limit] if history[-1] != "无" else []

    def __getattr__(self, name):
        return getattr(self.backend, name)


class PredictionFlowTests(unittest.TestCase):
    def setUp(self, prediction=True):
        self.commits, self.states = [], []
        settings = config.defaults()
        settings["input"]["prediction"] = prediction
        self.session = Suggesting()
        self.c = ProductController(self.session, "ctx", self.states.append, self.commits.append,
                                   settings=settings)
        self.c.enable()
        self.c.focus_in()

    def type(self, text):
        for ch in text:
            self.assertTrue(self.c.key(ord(ch), 0, 0))

    def suggestions(self):
        state = self.c.snapshot()
        return [c["text"] for c in state["candidates"]] if state["candidate_visible"] else []

    def test_commit_shows_suggestions_and_digit_picks_one(self):
        self.type("nihao")
        self.assertTrue(self.c.key(32, 0, 0))
        self.assertEqual(["你好"], self.commits)
        self.assertEqual(["的", "我们", "可以"], self.suggestions())
        self.assertFalse(self.c.snapshot()["preedit"]["visible"])
        self.assertTrue(self.c.key(ord("2"), 0, 0))
        self.assertEqual(["你好", "我们"], self.commits)
        # The picked word is context for the next suggestions.
        self.assertEqual(["你好", "我们"], self.session.asked[-1])
        self.assertEqual(["的", "我们", "可以"], self.suggestions())

    def test_commit_to_suggestions_is_one_update(self):
        self.type("nihao")
        before = len(self.states)
        self.c.key(32, 0, 0)
        published = self.states[before:]
        self.assertEqual(1, len(published))
        self.assertEqual(["的", "我们", "可以"], [c["text"] for c in published[0]["candidates"]])
        before = len(self.states)
        self.c.key(ord("1"), 0, 0)
        self.assertEqual(1, len(self.states) - before)

    def test_letter_dismisses_and_starts_typing(self):
        self.type("nihao")
        self.c.key(32, 0, 0)
        self.type("ni")
        self.assertEqual("ni", self.c.snapshot()["preedit"]["text"])
        self.assertNotIn("的", self.suggestions())
        self.assertEqual(["你好"], self.commits)

    def test_space_escape_backspace_and_punctuation_pass_on(self):
        for key, handled in ((32, False), (ESCAPE, True), (BACKSPACE, False)):
            with self.subTest(key=key):
                self.type("nihao")
                self.c.key(32, 0, 0)
                self.assertTrue(self.suggestions())
                self.assertEqual(handled, self.c.key(key, 0, 0))
                self.assertEqual([], self.suggestions())
        self.type("nihao")
        self.c.key(32, 0, 0)
        self.c.key(ord(","), 0, 0)
        self.assertEqual("，", self.commits[-1])
        self.assertEqual([], self.suggestions())
        # Punctuation ends the context: the next commit starts a new history.
        self.type("nihao")
        self.c.key(32, 0, 0)
        self.assertEqual(["你好"], self.session.asked[-1])

    def test_paging_keys_move_within_suggestions(self):
        self.type("nihao")
        self.c.key(32, 0, 0)
        self.assertTrue(self.c.key(DOWN, 0, 0))
        self.assertEqual(1, self.c.snapshot()["selected_index"])
        self.assertTrue(self.suggestions())

    def test_mouse_selection_of_a_suggestion(self):
        self.type("nihao")
        self.c.key(32, 0, 0)
        state = self.c.snapshot()
        self.assertTrue(self.c.select(state["candidates"][2]["id"], state["revision"]))
        self.assertEqual(["你好", "可以"], self.commits)

    def test_off_in_settings_or_private_or_nothing_to_suggest(self):
        self.setUp(prediction=False)
        self.type("nihao")
        self.c.key(32, 0, 0)
        self.assertEqual([], self.suggestions())
        self.assertEqual([], self.session.asked)
        self.setUp()
        self.c.set_content_type(8, 0)  # password: direct input, nothing shown
        self.assertFalse(self.c.key(ord("n"), 0, 0))
        self.assertEqual([], self.session.asked)

    def test_focus_out_forgets_history(self):
        self.type("nihao")
        self.c.key(32, 0, 0)
        self.c.focus_out()
        self.c.focus_in()
        self.assertEqual([], self.suggestions())
        self.type("nihao")
        self.c.key(32, 0, 0)
        self.assertEqual(["你好"], self.session.asked[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
