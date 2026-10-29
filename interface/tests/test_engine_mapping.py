"""映射检查：设置 → 真实引擎 configure，设置 → 平台 Controller(page_size)，快捷键 → 平台按键行为。

引擎缺失时相关用例明确 skip，不伪造结果。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
sys.path[:0] = [str(ROOT / "src"), str(WORKSPACE / "platform"), str(WORKSPACE / "engine" / "src")]

from ime_interface import config  # noqa: E402

try:  # 真实引擎
    from server_ime_engine import Engine  # noqa: E402

    ENGINE_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover
    Engine = None
    ENGINE_IMPORT_ERROR = str(exc)

from server_ime.controller import Controller  # noqa: E402
from server_ime.deterministic import create_session  # noqa: E402


class EngineMappingTest(unittest.TestCase):
    def setUp(self):
        if Engine is None:
            self.skipTest(f"真实引擎不可导入：{ENGINE_IMPORT_ERROR}")

    def real_caps(self):
        with Engine() as engine:
            return config.Capabilities.from_engine(engine)

    def test_settings_reach_engine_configure(self):
        caps = self.real_caps()
        settings = config.defaults()
        settings["input"]["page_size"] = 7
        settings["input"]["incomplete"] = False
        patch, state = config.apply_engine(settings, caps=caps)
        self.assertEqual(patch["page_size"], 7)
        self.assertEqual(state["config"]["page_size"], 7)
        self.assertIs(state["config"]["incomplete"], False)
        self.assertEqual(state["config"]["schema"], "full_pinyin")

    def test_engine_rejects_option_that_fixture_claims(self):
        """夹具声称支持双拼 → 真实引擎必须拒绝，证明夹具不是功能实现。"""
        caps = config.Capabilities.from_file(ROOT / "config" / "capabilities-fixture.json")
        settings = config.defaults()
        settings["input"]["double_pinyin_scheme"] = "ziranma"
        settings["input"]["learning"] = True
        with self.assertRaises(config.ConfigError) as caught:
            config.apply_engine(settings, caps=caps)
        error = caught.exception.errors[0]
        self.assertTrue(error["code"].startswith("engine-"), error)
        self.assertIn("引擎拒绝了配置", error["message"])


class PlatformMappingTest(unittest.TestCase):
    def controller(self, page_size):
        published, commits = [], []
        controller = Controller(create_session(), "ctx-1", published.append, commits.append,
                               page_size=page_size)
        controller.enable()
        controller.focus_in()
        return controller, published, commits

    def test_page_size_from_config_used_by_controller(self):
        settings = config.defaults()
        settings["input"]["page_size"] = 3
        patch = config.platform_patch(settings)
        controller, published, _ = self.controller(patch["page_size"])
        for char in "ni":
            controller.key(ord(char), 0, 0)
        snapshot = published[-1]
        self.assertEqual(snapshot["page_size"], 3)
        self.assertEqual(len(snapshot["candidates"]), 7)
        self.assertEqual(snapshot["page_count"], 3)

    def test_digit_and_page_keys_match_keymap(self):
        controller, published, commits = self.controller(5)
        for char in "ni":
            controller.key(ord(char), 0, 0)
        first = published[-1]
        self.assertEqual(len(first["candidates"]), 7)
        controller.key(0xFF56, 0, 0)  # Page_Down
        paged = published[-1]
        self.assertEqual(paged["page_start"], 5)
        self.assertTrue(controller.key(ord("2"), 0, 0))  # 数字选词
        self.assertEqual(published[-1]["page_start"], 0)
        self.assertTrue(commits, "数字选词应产生提交")

    def test_mode_toggle_key(self):
        controller, published, _ = self.controller(5)
        self.assertTrue(controller.key(0x20, 0, 4))  # Ctrl+space
        self.assertEqual(published[-1]["mode"], "en")
        self.assertTrue(controller.key(0x20, 0, 4))
        self.assertEqual(published[-1]["mode"], "zh")


if __name__ == "__main__":
    unittest.main()
