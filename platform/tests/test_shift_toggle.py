"""Shift pressed and released alone switches Chinese/English (product_controller.py).

Run: python3 -B platform/tests/test_shift_toggle.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "platform"), str(ROOT / "interface/src")]

from ime_interface import config
from server_ime.deterministic import create_session
from server_ime.product_controller import ProductController

SHIFT_L, SHIFT_R, CONTROL_L = 0xFFE1, 0xFFE2, 0xFFE3
SHIFT, CONTROL, RELEASE = 1, 4, 1 << 30


class ShiftToggleTests(unittest.TestCase):
    def setUp(self, enabled=True):
        self.commits = []
        settings = config.defaults()
        settings["input"]["shift_toggle"] = enabled
        self.c = ProductController(create_session(), "ctx", lambda s: None, self.commits.append,
                                   settings=settings)
        self.c.enable()
        self.c.focus_in()

    def tap(self, keyval=SHIFT_L):
        self.assertFalse(self.c.key(keyval, 0, 0))
        self.assertFalse(self.c.key(keyval, 0, SHIFT | RELEASE))  # the application sees both

    def test_tap_switches_both_ways(self):
        self.tap()
        self.assertEqual("en", self.c.mode)
        self.assertFalse(self.c.key(ord("a"), 0, 0))  # English goes straight through
        self.tap(SHIFT_R)
        self.assertEqual("zh", self.c.mode)

    def test_shift_with_a_letter_does_not_switch(self):
        self.c.key(SHIFT_L, 0, 0)
        self.c.key(ord("A"), 0, SHIFT)
        self.c.key(ord("A"), 0, SHIFT | RELEASE)
        self.c.key(SHIFT_L, 0, SHIFT | RELEASE)
        self.assertEqual("zh", self.c.mode)

    def test_control_shift_does_not_switch(self):
        self.c.key(CONTROL_L, 0, 0)
        self.c.key(SHIFT_L, 0, CONTROL)
        self.c.key(SHIFT_L, 0, CONTROL | SHIFT | RELEASE)
        self.assertEqual("zh", self.c.mode)

    def test_typed_letters_are_committed_as_they_are(self):
        for ch in "nihao":
            self.c.key(ord(ch), 0, 0)
        self.tap()
        self.assertEqual(["nihao"], self.commits)
        self.assertEqual("en", self.c.mode)
        self.assertEqual("", self.c.composition)

    def test_off_in_settings(self):
        self.setUp(enabled=False)
        self.tap()
        self.assertEqual("zh", self.c.mode)


if __name__ == "__main__":
    unittest.main(verbosity=2)
