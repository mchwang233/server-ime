"""The InputMode property drives the IBus tray icon (icon_prop_key)."""
from pathlib import Path
import unittest

import gi
gi.require_version("IBus", "1.0")
from gi.repository import IBus

from server_ime.ibus_adapter import ServerIME, icon_path


def state(mode="zh", direct_input=False):
    return {"mode": mode, "direct_input": direct_input, "status": "", "backend": "test"}


class TrayIconTest(unittest.TestCase):
    def mode_prop(self, **kwargs):
        # properties() uses only class attributes, so no engine object is needed.
        props = ServerIME.properties(ServerIME, state(**kwargs))
        prop = props.get(0)
        self.assertEqual(prop.get_key(), "InputMode")
        return prop

    def test_symbol_follows_mode(self):
        self.assertEqual(self.mode_prop(mode="zh").get_symbol().get_text(), "中")
        self.assertEqual(self.mode_prop(mode="en").get_symbol().get_text(), "英")
        self.assertEqual(self.mode_prop(mode="zh", direct_input=True).get_symbol().get_text(), "英")

    def test_icons_exist_and_have_no_text(self):
        for name in ("server-ime", "server-ime-zh", "server-ime-en"):
            svg = Path(icon_path(name))
            self.assertTrue(svg.is_file(), svg)
            # Glyphs are outlines so the icons do not depend on installed fonts.
            self.assertNotIn("<text", svg.read_text())
        self.assertEqual(self.mode_prop(mode="zh").get_icon(), icon_path("server-ime-zh"))


if __name__ == "__main__":
    unittest.main()
