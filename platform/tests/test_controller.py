import unittest
from types import SimpleNamespace

from server_ime.controller import (Controller, CONTROL, RELEASE, PAGE_DOWN, BACKSPACE,
                                   LEFT, DELETE, RETURN, ESCAPE, TAB, MAX_COMPOSITION, MOD4, MOD5)
from server_ime.deterministic import create_session
from server_ime.port import Candidate, Conversion, Selection


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.states, self.commits = [], []
        self.backend = create_session()
        self.c = Controller(self.backend, "unit-context", self.states.append, self.commits.append)
        self.c.enable()
        self.c.focus_in()

    def type(self, text):
        for ch in text:
            self.assertTrue(self.c.key(ord(ch), 0, 0))

    def test_preedit_candidates_commit_clear(self):
        self.type("nihao")
        state = self.c.snapshot()
        self.assertEqual(state["preedit"]["text"], "nihao")
        self.assertEqual(state["candidates"][0]["text"], "你好")
        self.assertTrue(self.c.key(32, 0, 0))
        self.assertEqual(self.commits, ["你好"])
        self.assertFalse(self.c.snapshot()["candidate_visible"])

    def test_focus_out_discards_without_committing(self):
        self.type("ni")
        old = self.c.snapshot()
        self.c.focus_out()
        self.assertFalse(self.c.select("ni:0", old["revision"]))
        self.assertFalse(self.c.key(ord('a'), 0, 0))
        self.c.focus_in()
        self.assertEqual(self.c.snapshot()["preedit"]["text"], "")
        self.assertEqual(self.commits, [])

    def test_password_and_pin_never_convert(self):
        calls = []
        self.backend.convert = lambda *args: calls.append(args)
        for purpose, hints in [(8, 0), (9, 0)]:
            self.c.set_content_type(purpose, hints)
            self.assertFalse(self.c.key(ord('n'), 0, 0))
            self.assertFalse(self.c.key(32, 0, CONTROL))
            self.assertEqual(self.c.snapshot()["candidates"], [])
        self.assertEqual(calls, [])
        self.assertTrue(self.backend.context.private)

    def test_input_hints_preserved_and_numeric_direct(self):
        self.c.set_content_type(5, 0x4000 | 2048 | 8)
        self.assertEqual(self.backend.context.hints, 0x4808)
        self.assertEqual(self.backend.context.purpose, 5)
        self.assertFalse(self.c.blocked)  # Unknown hint bits have no invented semantics.
        for p in [2, 3, 4]:
            self.c.set_content_type(p, 0)
            self.assertFalse(self.c.key(ord('1'), 0, 0))

    def test_shortcuts_release_and_english_passthrough(self):
        self.type("ni")
        self.assertFalse(self.c.key(ord('n'), 0, RELEASE))
        self.assertEqual(self.c.composition, "ni")
        self.assertFalse(self.c.key(ord('c'), 0, CONTROL))
        self.assertEqual(self.c.composition, "")
        self.assertTrue(self.c.key(32, 0, CONTROL))
        self.assertEqual(self.c.mode, "en")
        self.assertFalse(self.c.key(ord('a'), 0, 0))

    def test_x11_super_and_altgr_modifiers_pass_through(self):
        for modifier in [MOD4, MOD5]:
            self.type("ni")
            self.assertFalse(self.c.key(ord('e'), 0, modifier))
            self.assertEqual(self.c.composition, "")
            self.assertFalse(self.c.key(32, 0, modifier | CONTROL))
            self.assertEqual(self.c.mode, "zh")

    def test_paging_and_number_selection(self):
        self.type("ni")
        self.c.key(PAGE_DOWN, 0, 0)
        self.assertEqual(self.c.snapshot()["page_start"], 5)
        self.c.key(ord('2'), 0, 0)
        self.assertEqual(self.commits, ["妮"])

    def test_stale_candidate_and_duplicate_action_rejected(self):
        self.type("ni")
        revision = self.c.revision
        self.c.move(1)
        self.assertFalse(self.c.select("ni:0", revision))
        revision = self.c.revision
        self.assertTrue(self.c.select("ni:1", revision))
        self.assertFalse(self.c.select("ni:1", revision))
        self.assertEqual(self.commits, ["呢"])

    def test_cursor_delete_and_raw_commit(self):
        self.type("nia")
        self.c.key(LEFT, 0, 0)
        self.c.key(DELETE, 0, 0)
        self.assertEqual(self.c.composition, "ni")
        self.c.key(BACKSPACE, 0, 0)
        self.assertEqual(self.c.composition, "n")
        self.c.key(RETURN, 0, 0)
        self.assertEqual(self.commits, ["n"])

    def test_tab_escape_reset_disable_cleanup(self):
        for action in [lambda: self.c.key(TAB, 0, 0), lambda: self.c.key(ESCAPE, 0, 0),
                       self.c.reset, self.c.disable]:
            self.type("ni")
            action()
            self.assertEqual(self.c.snapshot()["preedit"]["text"], "")
            self.assertEqual(self.commits, [])

    def test_backend_failure_keeps_raw_text_recoverable(self):
        def fail(*_):
            raise RuntimeError("must not leak arbitrary backend exception text")
        self.backend.convert = fail
        self.type("ni")
        self.assertEqual(self.c.snapshot()["error"], "backend-convert-failed")
        self.c.key(RETURN, 0, 0)
        self.assertEqual(self.commits, ["ni"])

    def test_partial_selection_supported(self):
        self.type("nihao")
        self.backend.select = lambda cid: Selection("你", "hao", 3)
        self.assertTrue(self.c.select("nihao:0"))
        self.assertEqual(self.commits, ["你"])
        self.assertEqual(self.c.composition, "hao")
        self.assertEqual(self.c.snapshot()["candidates"][0]["text"], "好")

    def test_duplicate_candidate_ids_rejected(self):
        self.backend.convert = lambda raw, pos: Conversion(raw, pos, (Candidate("dup", "你"), Candidate("dup", "呢")))
        self.type("ni")
        self.assertEqual(self.c.snapshot()["candidates"], [])
        self.assertEqual(self.c.snapshot()["error"], "backend-convert-failed")

    def test_input_length_bound(self):
        self.type("a" * (MAX_COMPOSITION + 1))
        self.assertEqual(len(self.c.composition), MAX_COMPOSITION)

    def test_structural_backend_needs_no_platform_import(self):
        self.backend.convert = lambda raw, pos: SimpleNamespace(preedit="你", cursor=1,
            candidates=[SimpleNamespace(id="foreign", text="你", annotation="foreign class")])
        self.backend.select = lambda cid: SimpleNamespace(commit="你", remaining="", cursor=0)
        self.type("ni")
        self.assertTrue(self.c.select("foreign"))
        self.assertEqual(self.commits, ["你"])

    def test_invalid_display_cursor_falls_back_to_raw(self):
        self.backend.convert = lambda raw, pos: Conversion(raw, .5)
        self.type("ni")
        self.assertEqual(self.c.snapshot()["error"], "backend-convert-failed")
        self.c.key(RETURN, 0, 0)
        self.assertEqual(self.commits, ["ni"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
