"""Tray icon: glyph size and restoring IBus's own systray icon.

Run: python3 integration/tests/test_tray.py
"""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / p) for p in ('integration/src', 'platform', 'interface/src')]

import gi
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk

from server_ime_product import tray


def ink_height(pixbuf):
    """Rows that contain any visible pixel."""
    data, stride, n = pixbuf.get_pixels(), pixbuf.get_rowstride(), pixbuf.get_n_channels()
    rows = [y for y in range(pixbuf.get_height())
            if any(data[y * stride + x * n + 3] for x in range(pixbuf.get_width()))]
    return rows[-1] - rows[0] + 1 if rows else 0


class FakeSettings:
    def __init__(self, value):
        self.value = value

    def get_boolean(self, key):
        return self.value

    def set_boolean(self, key, value):
        self.value = value


class FakeTray(tray.ModeTray):
    """ModeTray without GTK/IBus: only the systray-setting bookkeeping."""
    def __init__(self, settings, marker):
        self.panel_settings, self.marker = settings, marker
        self.hid_ibus_icon = marker.exists()


class TrayTest(unittest.TestCase):
    def test_glyph_is_larger_than_ibus(self):
        rgba = Gdk.RGBA()
        rgba.parse('#415099')
        for symbol in ('中', '英'):
            for size in (16, 22, 48):
                height = ink_height(tray.render_symbol(symbol, size, rgba))
                # ibus-ui-gtk3's symbol fills about 30/48 of the icon.
                self.assertGreaterEqual(height / size, 0.8, (symbol, size, height))
                self.assertLessEqual(height, size)

    def test_hides_and_restores_ibus_icon(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / 'ibus-icon-hidden'
            settings = FakeSettings(True)
            t = FakeTray(settings, marker)
            t._set_ibus_icon(False)
            self.assertFalse(settings.value)
            self.assertTrue(marker.exists())
            # A panel started after a crash still knows to restore the icon.
            t = FakeTray(settings, marker)
            t._set_ibus_icon(True)
            self.assertTrue(settings.value)
            self.assertFalse(marker.exists())

    def test_leaves_icon_alone_if_user_had_it_off(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / 'ibus-icon-hidden'
            settings = FakeSettings(False)
            t = FakeTray(settings, marker)
            t._set_ibus_icon(False)
            t._set_ibus_icon(True)
            self.assertFalse(settings.value)  # never turned on what the user turned off
            self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
