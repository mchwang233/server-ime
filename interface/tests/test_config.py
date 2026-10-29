"""设置格式 v1 的无显示检查：真实能力校验、学习目录、回调保存路径、映射。

覆盖 `integration/checks/interface-defects.json` 的三类缺陷：
1. 引擎拒绝的双拼方案（mspy）必须在保存前被拒绝，原文件不变；
2. 不存在的模糊音/纠错规则必须在保存前被拒绝；
3. learning=true 必须走带明确 user_data_dir 的真实引擎（或产品保存回调），
   不能靠“没有个人目录的临时引擎”蒙混成功。
另外验证 `settings_ui.apply_settings`：回调失败/引擎失败都不写盘、不返回成功。
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT.parent / "platform")]

from ime_interface import config, keymap, settings_ui  # noqa: E402

FIXTURE = ROOT / "config" / "capabilities-fixture.json"

ENGINE_SRC = ROOT.parent / "engine" / "src"
if ENGINE_SRC.exists():
    sys.path.insert(0, str(ENGINE_SRC))


def real_caps():
    """真实引擎能力；不可用时返回空能力视图（相关用例会 skip）。"""
    try:
        from server_ime_engine import Engine

        return config.Capabilities.from_engine(Engine)
    except Exception:
        return config.Capabilities()


def require_engine(caps):
    if not caps.backend or caps.backend == "unknown":
        raise unittest.SkipTest("真实引擎不可导入，跳过依赖真实 capabilities 的用例")


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "settings.json"
        self.caps = real_caps()

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_are_valid(self):
        settings, errors = config.validate(config.defaults(), self.caps)
        self.assertEqual(errors, [])
        self.assertEqual(settings["input"]["page_size"], 5)

    def test_save_permissions_and_roundtrip(self):
        settings = config.defaults()
        settings["input"]["page_size"] = 7
        settings["panel"]["font_scale"] = 1.5
        saved = config.save(settings, path=self.path, caps=self.caps)
        self.assertEqual(saved["input"]["page_size"], 7)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        loaded, errors, _ = config.load(self.path, caps=self.caps)
        self.assertEqual(errors, [])
        self.assertEqual(loaded["panel"]["font_scale"], 1.5)

    def test_reset_restores_defaults(self):
        settings = config.defaults()
        settings["input"]["page_size"] = 2
        config.save(settings, path=self.path, caps=self.caps)
        config.reset(path=self.path, caps=self.caps)
        loaded, errors, _ = config.load(self.path, caps=self.caps)
        self.assertEqual(errors, [])
        self.assertEqual(loaded["input"]["page_size"], 5)

    def test_bad_version_rejected(self):
        raw = config.defaults()
        raw["version"] = 2
        _, errors = config.validate(raw, self.caps)
        self.assertEqual([e["code"] for e in errors], ["bad-version"])
        self.assertIn("配置版本", errors[0]["message"])

    def test_page_size_range_and_type(self):
        for value, code in ((0, "out-of-range"), (10, "out-of-range"), ("7", "not-integer")):
            raw = config.defaults()
            raw["input"]["page_size"] = value
            _, errors = config.validate(raw, self.caps)
            self.assertEqual([e["code"] for e in errors], [code], value)

    def test_unsupported_features_are_refused(self):
        empty = config.Capabilities({})
        raw = config.defaults()
        raw["input"].update({"learning": True, "double_pinyin_scheme": "ziranma",
                             "fuzzy": {"enabled": True, "rules": []},
                             "correction": {"enabled": True, "rules": []}})
        _, errors = config.validate(raw, empty)
        self.assertEqual([e["code"] for e in errors],
                         ["unsupported-option"] * 4)
        self.assertIn("引擎不支持", errors[0]["message"])

    def test_unknown_keys_preserved_for_future_extensions(self):
        raw = config.defaults()
        raw["engine_future"] = {"hmm": True}
        raw["input"]["tomorrow"] = [1, 2, 3]
        settings, errors = config.validate(raw, self.caps)
        self.assertEqual(errors, [])
        self.assertEqual(settings["engine_future"], {"hmm": True})
        self.assertEqual(settings["input"]["tomorrow"], [1, 2, 3])
        saved = config.save(settings, path=self.path, caps=self.caps)
        self.assertEqual(saved["input"]["tomorrow"], [1, 2, 3])

    def test_engine_patch_only_contains_supported_keys(self):
        empty = config.Capabilities({})
        self.assertEqual(sorted(config.engine_patch(config.defaults(), empty)),
                         ["incomplete", "page_size", "schema"])

    def test_engine_patch_uses_real_capabilities_and_declared_values(self):
        require_engine(self.caps)
        settings = config.defaults()
        settings["input"].update({"schema": "double_pinyin", "double_pinyin_scheme": "ziranma",
                                  "fuzzy": {"enabled": True, "rules": ["z_zh"]},
                                  "learning": False})
        patch = config.engine_patch(settings, self.caps)
        self.assertEqual(patch["double_pinyin_scheme"], "ziranma")
        self.assertEqual(patch["fuzzy"], {"enabled": True, "rules": ["z_zh"]})
        self.assertIn("correction", patch)
        self.assertIn("learning", patch)

    def test_engine_patch_never_sends_undeclared_rules(self):
        require_engine(self.caps)
        settings = config.defaults()
        settings["input"]["fuzzy"] = {"enabled": True, "rules": ["not-a-rule"]}
        patch = config.engine_patch(settings, self.caps)
        self.assertEqual(patch["fuzzy"], {"enabled": True, "rules": []})

    def test_platform_patch(self):
        settings = config.defaults()
        settings["input"]["page_size"] = 8
        self.assertEqual(config.platform_patch(settings), {"page_size": 8})

    def test_panel_layout_defaults_to_horizontal(self):
        settings, errors = config.validate(config.defaults(), self.caps)
        self.assertEqual(errors, [])
        self.assertEqual(settings["panel"]["layout"], "horizontal")
        self.assertEqual(config.panel_options(settings)["layout"], "horizontal")

    def test_old_config_without_panel_layout_is_horizontal(self):
        """旧版本写下的设置（没有 panel.layout）升级后立即横排，不需要用户改配置。"""
        raw = config.defaults()
        raw["panel"].pop("layout")
        settings, errors = config.validate(raw, self.caps)
        self.assertEqual(errors, [])
        self.assertEqual(settings["panel"]["layout"], "horizontal")
        self.assertEqual(config.panel_options(settings)["layout"], "horizontal")
        saved = config.save(raw, path=self.path, caps=self.caps)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["panel"]["layout"], "horizontal")
        self.assertEqual(saved["panel"]["layout"], "horizontal")

    def test_panel_layout_enum_rejects_unknown_and_keeps_legacy_vertical(self):
        for value in ("grid", "Horizontal ", 1, None):
            raw = config.defaults()
            raw["panel"]["layout"] = value
            _, errors = config.validate(raw, self.caps)
            self.assertEqual([e["code"] for e in errors], ["bad-enum"], value)
            self.assertIn("horizontal, vertical", errors[0]["message"])
        raw = config.defaults()
        raw["panel"]["layout"] = "vertical"
        settings, errors = config.validate(raw, self.caps)
        self.assertEqual(errors, [])
        self.assertEqual(config.panel_options(settings)["layout"], "vertical")

    def test_mapping_report_marks_unsupported(self):
        empty = config.Capabilities({})
        report = {item["key"]: item["state"] for item in config.mapping_report(config.defaults(), empty)}
        self.assertEqual(report["input.page_size"], "live")
        for key in ("input.double_pinyin_scheme", "input.fuzzy", "input.correction", "input.learning"):
            self.assertEqual(report[key], "unsupported")
        self.assertEqual(report["shortcuts.*"], "config-only")

    def test_mapping_report_lists_real_options(self):
        require_engine(self.caps)
        report = {item["key"]: item for item in config.mapping_report(config.defaults(), self.caps)}
        self.assertEqual(report["input.double_pinyin_scheme"]["state"], "live")
        self.assertEqual(report["input.double_pinyin_scheme"]["options"],
                         [f"ziranma（{self.caps.scheme_label('ziranma')}）"])
        self.assertIn("自然码", self.caps.scheme_label("ziranma"))
        self.assertEqual(len(report["input.fuzzy"]["options"]), len(self.caps.fuzzy_rules))
        self.assertEqual(len(report["input.correction"]["options"]), len(self.caps.correction_rules))


class CapabilityCatalogTest(unittest.TestCase):
    """缺陷 1/2：不支持的方案与规则必须在保存前被拒绝，原文件不变。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "settings.json"
        self.caps = real_caps()
        require_engine(self.caps)

    def tearDown(self):
        self.tmp.cleanup()

    def test_catalogs_come_from_engine_capabilities(self):
        self.assertEqual(self.caps.double_pinyin_schemes, ["ziranma"])
        self.assertEqual(self.caps.default_scheme, "ziranma")
        self.assertNotIn("mspy", self.caps.double_pinyin_schemes)
        self.assertIn("z_zh", self.caps.fuzzy_rules)
        self.assertIn("transpose", self.caps.correction_rules)
        self.assertGreaterEqual(len(self.caps.fuzzy_rules), 10)
        self.assertGreaterEqual(len(self.caps.correction_rules), 8)

    def test_unsupported_double_scheme_rejected_before_save(self):
        original = config.defaults()
        original["input"]["page_size"] = 7
        config.save(original, path=self.path, caps=self.caps)
        before = self.path.read_bytes()

        candidate = config.load(self.path, caps=self.caps)[0]
        candidate["input"].update({"schema": "double_pinyin", "double_pinyin_scheme": "mspy"})
        _, errors = config.validate(candidate, self.caps)
        self.assertEqual([e["code"] for e in errors], ["bad-enum"])
        self.assertIn("ziranma", errors[0]["message"])
        self.assertNotIn("mspy", errors[0]["message"], "可选值只列出引擎声明的方案")

        with self.assertRaises(config.ConfigError) as caught:
            config.save(candidate, path=self.path, caps=self.caps)
        self.assertEqual(caught.exception.codes(), ["bad-enum"])
        self.assertEqual(self.path.read_bytes(), before, "被拒绝的配置不得改写原文件")

    def test_unknown_fuzzy_rule_rejected_before_save(self):
        candidate = config.defaults()
        candidate["input"]["fuzzy"] = {"enabled": True, "rules": ["z_zh", "not-a-rule"]}
        _, errors = config.validate(candidate, self.caps)
        self.assertEqual([e["code"] for e in errors], ["unknown-rule"])
        self.assertIn("not-a-rule", errors[0]["message"])
        with self.assertRaises(config.ConfigError):
            config.save(candidate, path=self.path, caps=self.caps)
        self.assertFalse(self.path.exists(), "拒绝保存时不得创建配置文件")

    def test_duplicate_fuzzy_rule_rejected(self):
        candidate = config.defaults()
        candidate["input"]["fuzzy"] = {"enabled": True, "rules": ["l_n", "l_n"]}
        _, errors = config.validate(candidate, self.caps)
        self.assertEqual([e["code"] for e in errors], ["duplicate-rule"])

    def test_unknown_correction_rule_rejected(self):
        candidate = config.defaults()
        candidate["input"]["correction"] = {"enabled": True, "rules": ["mg_mg"]}
        _, errors = config.validate(candidate, self.caps)
        self.assertEqual([e["code"] for e in errors], ["unknown-rule"])
        self.assertIn("mg_ng", errors[0]["message"])

    def test_fixture_capabilities_declare_no_catalog(self):
        fixture = config.Capabilities.from_file(FIXTURE)
        self.assertEqual(fixture.double_pinyin_schemes, [])
        self.assertEqual(fixture.fuzzy_rules, [])
        self.assertEqual(fixture.correction_rules, [])
        candidate = config.defaults()
        candidate["input"]["double_pinyin_scheme"] = "ziranma"
        _, errors = config.validate(candidate, fixture)
        self.assertEqual([e["code"] for e in errors], ["undeclared-catalog"])

    def test_scheme_default_filled_when_double_pinyin_selected(self):
        candidate = config.defaults()
        candidate["input"].update({"schema": "double_pinyin", "double_pinyin_scheme": None})
        settings, errors = config.validate(candidate, self.caps)
        self.assertEqual(errors, [])
        patch = config.engine_patch(settings, self.caps)
        self.assertEqual(patch["double_pinyin_scheme"], "ziranma")


class LearningDirectoryTest(unittest.TestCase):
    """缺陷 3：learning=true 必须带明确的 user_data_dir。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.learn = Path(self.tmp.name) / "learn"
        self.caps = real_caps()
        require_engine(self.caps)

    def tearDown(self):
        self.tmp.cleanup()

    def learning_settings(self):
        settings = config.defaults()
        settings["input"].update({"learning": True, "page_size": 6})
        return settings

    def test_learning_data_dir_defaults(self):
        self.assertEqual(config.learning_data_dir({"XDG_DATA_HOME": "/tmp/x"}),
                         Path("/tmp/x/server-ime/learning"))
        self.assertEqual(config.learning_data_dir({"HOME": "/home/u"}),
                         Path("/home/u/.local/share/server-ime/learning"))
        self.assertEqual(config.learning_data_dir({"SERVER_IME_DATA": "/srv/data"}),
                         Path("/srv/data/learning"))

    def test_explicit_user_data_dir_is_passed_to_engine(self):
        patch, state = config.apply_engine(self.learning_settings(), caps=self.caps,
                                           user_data_dir=self.learn)
        self.assertIs(state["config"]["learning"], True)
        self.assertEqual(state["config"]["page_size"], 6)
        self.assertEqual(patch["learning"], True)
        self.assertTrue((self.learn / "meta.json").is_file(), "学习目录应被真实引擎创建")

        from server_ime_engine import Engine

        with Engine(user_data_dir=self.learn) as engine:
            status = engine.learning_status()
        self.assertTrue(status["available"])
        self.assertTrue(status["enabled"])

    def test_default_learning_dir_used_for_real_capabilities(self):
        patch, state = config.apply_engine(self.learning_settings(), caps=self.caps,
                                           env={"XDG_DATA_HOME": self.tmp.name})
        self.assertTrue((Path(self.tmp.name) / "server-ime" / "learning" / "meta.json").is_file())
        self.assertIs(state["config"]["learning"], True)

    def test_fixture_capabilities_do_not_fake_learning(self):
        """夹具能力不创建真实个人目录；兼容旧行为——引擎如实报 learning_unavailable。"""
        fixture = config.Capabilities.from_file(FIXTURE)
        with self.assertRaises(config.ConfigError) as caught:
            config.apply_engine(self.learning_settings(), caps=fixture,
                                env={"XDG_DATA_HOME": self.tmp.name})
        self.assertTrue(caught.exception.errors[0]["code"].startswith("engine-"),
                        caught.exception.errors[0])
        self.assertFalse((Path(self.tmp.name) / "server-ime").exists())


class ApplySettingsTest(unittest.TestCase):
    """`settings_ui.apply_settings`：回调路径不写盘、失败不覆盖原配置、不报告成功。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "settings.json"
        self.caps = real_caps()

    def tearDown(self):
        self.tmp.cleanup()

    def seeded(self):
        settings = config.defaults()
        settings["input"]["page_size"] = 7
        config.save(settings, path=self.path, caps=self.caps)
        return config.load(self.path, caps=self.caps)[0]

    def test_engine_failure_keeps_original_file(self):
        seeded = self.seeded()
        before = self.path.read_bytes()
        candidate = json.loads(json.dumps(seeded))
        candidate["input"]["page_size"] = 3
        failure = config.ConfigError([{"code": "engine-invalid_config", "path": "input",
                                       "message": "引擎拒绝了配置：boom"}])
        with mock.patch.object(config, "apply_engine", side_effect=failure) as apply_mock:
            with self.assertRaises(config.ConfigError) as caught:
                settings_ui.apply_settings(candidate, self.path, self.caps)
        self.assertEqual(caught.exception.codes(), ["engine-invalid_config"])
        self.assertEqual(apply_mock.call_count, 1)
        self.assertEqual(self.path.read_bytes(), before, "应用失败不得覆盖原配置")
        self.assertEqual(config.load(self.path, caps=self.caps)[0]["input"]["page_size"], 7)

    def test_success_writes_after_engine_accepts(self):
        candidate = config.defaults()
        candidate["input"]["page_size"] = 6
        saved, info = settings_ui.apply_settings(candidate, self.path, self.caps)
        self.assertEqual(saved["input"]["page_size"], 6)
        self.assertEqual(info["persisted_by"], "config.save")
        self.assertEqual(info["engine_state_config"]["page_size"], 6)
        self.assertEqual(config.load(self.path, caps=self.caps)[0]["input"]["page_size"], 6)

    def test_validation_failure_happens_before_engine_and_disk(self):
        candidate = config.defaults()
        candidate["input"]["fuzzy"] = {"enabled": True, "rules": ["not-a-rule"]}
        with mock.patch.object(config, "apply_engine") as apply_mock, \
                mock.patch.object(config, "save") as save_mock:
            with self.assertRaises(config.ConfigError) as caught:
                settings_ui.apply_settings(candidate, self.path, self.caps)
        self.assertEqual(caught.exception.codes(), ["unknown-rule"])
        apply_mock.assert_not_called()
        save_mock.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_handler_replaces_write_and_engine(self):
        candidate = config.defaults()
        candidate["input"]["page_size"] = 4
        seen = []

        def handler(normalized):
            seen.append(normalized)
            result = json.loads(json.dumps(normalized))
            result["input"]["page_size"] = 5  # 产品侧规范化
            return result

        with mock.patch.object(config, "apply_engine") as apply_mock, \
                mock.patch.object(config, "save") as save_mock:
            saved, info = settings_ui.apply_settings(candidate, self.path, self.caps,
                                                     save_handler=handler)
        apply_mock.assert_not_called()
        save_mock.assert_not_called()
        self.assertFalse(self.path.exists(), "有回调时窗口不得写盘")
        self.assertEqual(info["persisted_by"], "save_handler")
        self.assertEqual(seen[0]["input"]["page_size"], 4)
        self.assertEqual(saved["input"]["page_size"], 5)

    def test_handler_failure_is_not_success(self):
        seeded = self.seeded()
        before = self.path.read_bytes()

        def handler(normalized):
            raise config.ConfigError([{"code": "engine-learning_unavailable", "path": "input",
                                       "message": "引擎拒绝了配置：learning requires explicit user_data_dir"}])

        with self.assertRaises(config.ConfigError) as caught:
            settings_ui.apply_settings(seeded, self.path, self.caps, save_handler=handler)
        self.assertEqual(caught.exception.codes(), ["engine-learning_unavailable"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_handler_must_return_settings(self):
        with self.assertRaises(config.ConfigError) as caught:
            settings_ui.apply_settings(config.defaults(), self.path, self.caps,
                                       save_handler=lambda normalized: True)
        self.assertEqual(caught.exception.codes(), ["handler-result"])

    def test_handler_unexpected_exception_is_failure_not_success(self):
        """回调内部抛出非 ConfigError 异常时同样按失败处理：不写盘、不返回成功。"""
        seeded = self.seeded()
        before = self.path.read_bytes()

        def handler(normalized):
            raise RuntimeError("service exploded")

        with self.assertRaises(config.ConfigError) as caught:
            settings_ui.apply_settings(seeded, self.path, self.caps, save_handler=handler)
        self.assertEqual(caught.exception.codes(), ["handler-error"])
        self.assertIn("service exploded", caught.exception.errors[0]["message"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_reset_goes_through_same_handler(self):
        changed = config.defaults()
        changed["input"]["page_size"] = 2
        config.save(changed, path=self.path, caps=self.caps)
        before = self.path.read_bytes()
        seen = []

        def handler(normalized):
            seen.append(normalized)
            return normalized

        saved, info = settings_ui.apply_settings(config.defaults(), self.path, self.caps,
                                                 save_handler=handler)
        self.assertEqual(seen[0]["input"]["page_size"], 5)
        self.assertEqual(saved, config.defaults())
        self.assertEqual(info["persisted_by"], "save_handler")
        self.assertEqual(self.path.read_bytes(), before, "恢复默认也由回调写盘，窗口自己不动文件")

    def test_learning_through_handler_with_real_engine(self):
        require_engine(self.caps)
        learn = Path(self.tmp.name) / "learn"

        def handler(normalized):
            patch, state = config.apply_engine(normalized, caps=self.caps, user_data_dir=learn)
            self.assertTrue(state["config"]["learning"])
            return normalized

        candidate = config.defaults()
        candidate["input"]["learning"] = True
        saved, _ = settings_ui.apply_settings(candidate, self.path, self.caps, save_handler=handler)
        self.assertIs(saved["input"]["learning"], True)
        self.assertFalse(self.path.exists())


class ShortcutTest(unittest.TestCase):
    def setUp(self):
        self.caps = real_caps()

    def test_defaults_have_no_conflicts_and_match_platform(self):
        normalized, errors, bindings = keymap.validate_shortcuts(config.defaults()["shortcuts"])
        self.assertEqual(errors, [])
        self.assertEqual(normalized, config.defaults()["shortcuts"])

    def test_conflict_is_reported(self):
        shortcuts = dict(config.defaults()["shortcuts"])
        shortcuts["page_next"] = "Page_Up"
        _, errors, _ = keymap.validate_shortcuts(shortcuts)
        codes = [e["code"] for e in errors]
        self.assertIn("conflict", codes)
        message = [e["message"] for e in errors if e["code"] == "conflict"][0]
        self.assertIn("快捷键冲突", message)
        self.assertIn("上一页", message)

    def test_illegal_bindings(self):
        cases = {"": "empty-binding", "Control+": "invalid-key", "Hyper+x": "invalid-modifier",
                 "Ctrl+space": "invalid-modifier", "F13": "invalid-key", "9-1": "bad-range"}
        for value, code in cases.items():
            shortcuts = dict(config.defaults()["shortcuts"])
            shortcuts["cancel"] = value
            _, errors, _ = keymap.validate_shortcuts(shortcuts)
            self.assertIn(code, [e["code"] for e in errors], (value, [e["code"] for e in errors]))
            self.assertTrue(all(e["message"] for e in errors))

    def test_unknown_action(self):
        shortcuts = dict(config.defaults()["shortcuts"])
        shortcuts["teleport"] = "Control+space"
        _, errors, _ = keymap.validate_shortcuts(shortcuts)
        self.assertIn("unknown-action", [e["code"] for e in errors])

    def test_unsupported_but_syntactically_valid_binding(self):
        shortcuts = dict(config.defaults()["shortcuts"])
        shortcuts["page_next"] = "Control+Page_Down"
        _, errors, _ = keymap.validate_shortcuts(shortcuts)
        self.assertEqual([e["code"] for e in errors], ["unsupported-binding"])
        self.assertIn("平台按键层", errors[0]["message"])

    def test_conflict_blocks_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = config.defaults()
            settings["shortcuts"]["page_next"] = "Page_Up"
            with self.assertRaises(config.ConfigError) as caught:
                config.save(settings, path=Path(tmp) / "s.json", caps=self.caps)
            self.assertIn("conflict", caught.exception.codes())

    def test_resolve_matches_platform_shapes(self):
        bindings = keymap.validate_shortcuts(config.defaults()["shortcuts"])[2]
        self.assertEqual(keymap.resolve(0x20, 4, bindings), "toggle_mode")
        self.assertIsNone(keymap.resolve(0x20, 4 | 1, bindings))       # Ctrl+Shift+space
        self.assertIsNone(keymap.resolve(ord("a"), 4, bindings))       # Ctrl+a 给应用
        self.assertIsNone(keymap.resolve(ord("a"), 1 << 30, bindings))  # release
        self.assertEqual(keymap.resolve(ord("3"), 0, bindings), "select_digit")
        self.assertEqual(keymap.resolve(0xFF56, 0, bindings), "page_next")
        self.assertEqual(keymap.resolve(0xFF0D, 0, bindings), "commit_raw")
        self.assertIsNone(keymap.resolve(ord("q"), 0, bindings))


class PunctuationTest(unittest.TestCase):
    def test_chinese_mapping(self):
        from ime_interface.punctuation import Punctuation

        punct = Punctuation(chinese=True, full_width_pairs=True)
        self.assertEqual(punct.map_text(",."), "，。")
        self.assertEqual(punct.map_char("?"), "？")
        self.assertEqual(punct.map_char('"'), "“")
        self.assertEqual(punct.map_char('"'), "”")
        self.assertEqual(punct.map_char("<"), "《")
        self.assertEqual(punct.map_char(">"), "》")
        self.assertEqual(punct.map_char(")"), "）")

    def test_english_mode_passthrough(self):
        from ime_interface.punctuation import Punctuation

        punct = Punctuation(chinese=False)
        self.assertEqual(punct.map_text(",.;:'\"()"), ",.;:'\"()")

    def test_preview_table(self):
        from ime_interface.punctuation import Punctuation

        rows = Punctuation().table()
        self.assertTrue(any(r["ascii"] == "," and r["chinese"] == "，" for r in rows))


if __name__ == "__main__":
    unittest.main()
