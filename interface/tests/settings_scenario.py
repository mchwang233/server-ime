#!/usr/bin/python3
"""中文设置界面检查：真实能力校验、回调保存、失败不写盘、恢复默认刷新、学习目录传递。

真实组件：GTK3 设置窗口、设置格式与校验、真实引擎 capabilities（含双拼/模糊音/纠错清单）、
真实引擎 configure 映射。夹具（capabilities-fixture.json）只用于证明“能力开启时控件出现”，
它没有声明 double_pinyin_schemes/fuzzy_rules/correction_rules，因此不能声称这些功能已实现。
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT.parent / "platform"), str(ROOT.parent / "engine" / "src"),
                str(ROOT / "tests")]

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from ime_interface import config, settings_ui  # noqa: E402
from x11 import X, pump, screenshot, wait_for, widget_center  # noqa: E402

EVIDENCE = Path(os.environ["SERVER_IME_EVIDENCE"])
FIXTURE = ROOT / "config" / "capabilities-fixture.json"


def contrast(foreground, background):
    def channel(value):
        value = value / 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    def luminance(color):
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

    a, b = sorted((luminance(foreground), luminance(background)), reverse=True)
    return round((a + 0.05) / (b + 0.05), 2)


class Scenario:
    def __init__(self, path, caps, partial=None):
        self.path = path
        self.caps = caps
        self.partial = partial
        self.checks = []
        self.saved_events = []

    def record(self, name, ok, **detail):
        self.checks.append({"check": name, "result": "PASS" if ok else "FAIL", **detail})
        print(("PASS " if ok else "FAIL ") + name, flush=True)
        if self.partial:
            self.partial.write_text(json.dumps({"checks": self.checks}, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
        return ok

    def open(self):
        settings, errors, path = config.load(self.path, caps=self.caps)
        self.window = settings_ui.SettingsWindow(settings, self.caps, path,
                                                 on_saved=self.saved_events.append)
        pump(0.5)
        self.x = X()
        self.x.focus_window(self.window.window)
        pump(0.3)
        return self.window

    def run(self):
        results = {}
        results["gating_real"] = self.step_real_catalog_controls()
        results["unsupported_refused"] = self.step_unsupported_refused()
        results["conflict"] = self.step_conflict()
        results["illegal"] = self.step_illegal()
        results["handler_save"] = self.step_handler_save()
        results["mouse_save"] = self.step_save_with_mouse()
        results["handler_failure"] = self.step_handler_failure()
        results["handler_crash"] = self.step_handler_crash()
        results["handler_reset"] = self.step_handler_reset()
        results["learning_dir"] = self.step_learning_directory()
        results["gating_fixture"] = self.step_fixture_gating()
        results["readability"] = self.step_readability()
        return results

    # ------------------------------------------------------------------ 步骤
    def step_real_catalog_controls(self):
        """控件只显示真实 capabilities 声明的方案与规则。"""
        window = self.open()
        model = window.schema_combo.get_model()
        ids = [model[row][1] for row in range(len(model))]
        texts = [model[row][0] for row in range(len(model))]
        scheme_model = window.scheme_combo.get_model() if hasattr(window, "scheme_combo") else None
        schemes = [scheme_model[row][1] for row in range(len(scheme_model))] if scheme_model else []
        fuzzy = sorted(window.fuzzy_checks)
        correction = sorted(window.correction_checks)
        unsupported = getattr(window, "unsupported_label", None)
        unsupported_text = unsupported.get_text() if unsupported is not None else ""
        shot = screenshot(EVIDENCE / "settings-real-capabilities.png", window.window)
        ok = (ids == [s for s in ("full_pinyin", "double_pinyin") if s in self.caps.schemas]
              and schemes == self.caps.double_pinyin_schemes
              and "mspy" not in schemes and "abc" not in schemes
              and fuzzy == sorted(self.caps.fuzzy_rules) and len(fuzzy) >= 10
              and correction == sorted(self.caps.correction_rules) and "mg_mg" not in correction
              and hasattr(window, "learning_switch")
              and "未支持" not in unsupported_text)
        return self.record("controls-show-real-declared-options",
                           ok, schemas=ids, schema_texts=texts, double_pinyin_schemes=schemes,
                           default_scheme=self.caps.default_scheme,
                           fuzzy_rules=fuzzy, correction_rules=correction,
                           learning_control=hasattr(window, "learning_switch"),
                           unsupported_text=unsupported_text,
                           capabilities=self.caps.summary(), screenshot=shot)

    def step_unsupported_refused(self):
        """引擎拒绝的方案/规则在保存前被拒绝，且不写盘。"""
        cases = {
            "mspy": lambda raw: raw["input"].update({"schema": "double_pinyin",
                                                     "double_pinyin_scheme": "mspy"}),
            "fuzzy": lambda raw: raw["input"].update({"fuzzy": {"enabled": True, "rules": ["not-a-rule"]}}),
            "correction": lambda raw: raw["input"].update({"correction": {"enabled": True, "rules": ["mg_mg"]}}),
        }
        detail, ok = {}, True
        for name, mutate in cases.items():
            raw = config.defaults()
            mutate(raw)
            _, errors = config.validate(raw, self.caps)
            codes = [e["code"] for e in errors]
            detail[name] = {"codes": codes,
                            "message": errors[0]["message"] if errors else "",
                            "file_written": self.path.exists()}
            ok = ok and bool(codes) and not self.path.exists()
        return self.record("unsupported-scheme-and-rules-refused-before-save", ok, **detail)

    def step_conflict(self):
        window = self.window
        window.page_spin.set_value(7)
        window.shortcut_entries["page_next"].set_text("Page_Up")
        pump(0.2)
        saved = window.save()
        messages = "\n".join(window.banner_lines)
        exists = self.path.exists()
        shot = screenshot(EVIDENCE / "settings-shortcut-conflict.png", window.window)
        ok = (not saved) and ("快捷键冲突" in messages) and not exists and window.banner.get_visible()
        return self.record("shortcut-conflict-blocks-save-with-message", ok, saved=saved,
                           banner=messages, file_written=exists, screenshot=shot)

    def step_illegal(self):
        window = self.window
        window.shortcut_entries["page_next"].set_text("Page_Down")
        window.shortcut_entries["cancel"].set_text("Hyper+x")
        window.page_spin.set_value(10)  # 越界，GTK 会夹紧到 9，再用非法动作验证
        saved = window.save()
        messages = "\n".join(window.banner_lines)
        ok = (not saved) and ("未知修饰键" in messages or "Hyper" in messages)
        shot = screenshot(EVIDENCE / "settings-illegal-binding.png", window.window)
        window.page_spin.set_value(7)
        return self.record("illegal-binding-rejected-with-reason", ok, saved=saved, banner=messages,
                           screenshot=shot)

    def step_handler_save(self):
        """提供 save_handler 时：回调承担验证/传播/持久化，窗口不写盘、不建临时引擎。"""
        window = self.window
        window.shortcut_entries["cancel"].set_text("Escape")
        window.page_spin.set_value(7)
        pump(0.2)
        calls, seen = [], []

        def handler(normalized):
            seen.append({"page_size": normalized["input"]["page_size"]})
            calls.append(normalized)
            return _normalized(normalized, page_size=4)  # 产品侧规范化后返回

        window.save_handler = handler
        real_apply, real_save = config.apply_engine, config.save

        def boom(*args, **kwargs):
            raise AssertionError("有 save_handler 时窗口不得写盘或创建引擎")

        config.apply_engine = boom
        config.save = boom
        try:
            saved = window.save()
        finally:
            config.apply_engine = real_apply
            config.save = real_save
        window.save_handler = None
        shot = screenshot(EVIDENCE / "settings-handler-save.png", window.window)
        ok = (saved is True and len(calls) == 1 and calls[0]["input"]["page_size"] == 7
              and not self.path.exists()
              and window.status.get_text() == settings_ui.UI_TEXT["saved_handler"]
              and window.page_spin.get_value() == 4          # 控件已按回调返回值刷新
              and window.settings["input"]["page_size"] == 4
              and self.saved_events and self.saved_events[-1]["input"]["page_size"] == 4
              and window.banner_lines == [])
        return self.record("save-handler-persists-without-window-write", ok,
                           saved=saved, handler_calls=len(calls), handler_saw=seen,
                           file_written=self.path.exists(), status=window.status.get_text(),
                           refreshed_page_size=window.page_spin.get_value(),
                           on_saved_events=[e["input"]["page_size"] for e in self.saved_events],
                           screenshot=shot)

    def step_save_with_mouse(self):
        """无回调时：真实引擎接受后才写盘。"""
        window = self.window
        window.page_spin.set_value(7)
        window.chinese_punct.set_active(False)
        pump(0.2)
        x, y = widget_center(window.save_button)
        self.x.click(x, y)
        written = wait_for(lambda: self.path.exists(), 5.0)
        saved_settings, errors, _ = config.load(self.path, caps=self.caps)
        shot = screenshot(EVIDENCE / "settings-saved.png", window.window)
        mode = stat.S_IMODE(self.path.stat().st_mode) if self.path.exists() else None
        ok = (bool(written) and not errors and saved_settings["input"]["page_size"] == 7
              and saved_settings["punctuation"]["chinese"] is False and mode == 0o600
              and window.banner_lines == [] and not window.banner.get_visible())
        return self.record("mouse-click-save-writes-config", ok,
                           page_size=saved_settings["input"]["page_size"],
                           chinese_punctuation=saved_settings["punctuation"]["chinese"],
                           file_mode=oct(mode) if mode else None, errors=errors,
                           status=window.status.get_text(), screenshot=shot)

    def step_handler_failure(self):
        """回调失败：不提示成功、不覆盖原配置、不触发 on_saved。"""
        window = self.window
        before = self.path.read_bytes()
        events_before = len(self.saved_events)

        def failing(normalized):
            raise config.ConfigError([{"code": "engine-learning_unavailable", "path": "input",
                                       "message": "引擎拒绝了配置：learning requires explicit user_data_dir"}])

        window.save_handler = failing
        window.page_spin.set_value(3)
        pump(0.2)
        saved = window.save()
        window.save_handler = None
        messages = "\n".join(window.banner_lines)
        shot = screenshot(EVIDENCE / "settings-handler-failure.png", window.window)
        after = self.path.read_bytes()
        ok = (saved is False and after == before
              and "learning requires explicit user_data_dir" in messages
              and window.banner.get_visible() and window.status.get_text() == ""
              and len(self.saved_events) == events_before
              and window.page_spin.get_value() == 3)  # 失败不刷新控件，用户可继续修正
        return self.record("handler-failure-keeps-config-and-reports-error", ok, saved=saved,
                           banner=messages, file_unchanged=after == before,
                           status=window.status.get_text(),
                           on_saved_events=len(self.saved_events), screenshot=shot)

    def step_handler_crash(self):
        """回调内部异常（非 ConfigError）：同样不得提示成功、不得改动原配置。"""
        window = self.window
        before = self.path.read_bytes()
        events_before = len(self.saved_events)

        def exploding(normalized):
            raise RuntimeError("product service exploded")

        window.save_handler = exploding
        window.page_spin.set_value(6)
        pump(0.2)
        saved = window.save()
        window.save_handler = None
        messages = "\n".join(window.banner_lines)
        shot = screenshot(EVIDENCE / "settings-handler-crash.png", window.window)
        after = self.path.read_bytes()
        ok = (saved is False and after == before
              and "保存回调失败" in messages and "product service exploded" in messages
              and window.banner.get_visible() and window.status.get_text() == ""
              and len(self.saved_events) == events_before)
        window.page_spin.set_value(7)
        return self.record("handler-crash-keeps-config-and-reports-error", ok, saved=saved,
                           banner=messages, file_unchanged=after == before,
                           status=window.status.get_text(),
                           on_saved_events=len(self.saved_events), screenshot=shot)

    def step_handler_reset(self):
        """恢复默认走同一回调：成功才刷新控件、显示成功、触发 on_saved。"""
        window = self.window
        before = self.path.read_bytes()
        window.page_spin.set_value(9)
        window.chinese_punct.set_active(False)
        window.shortcut_entries["cancel"].set_text("Escape")
        pump(0.2)
        calls = []
        window.save_handler = lambda normalized: (calls.append(normalized), normalized)[1]
        pump(0.2)
        x, y = widget_center(window.reset_button)
        self.x.click(x, y)
        pump(0.6)
        window.save_handler = None
        shot = screenshot(EVIDENCE / "settings-reset-refreshed.png", window.window)
        after = self.path.read_bytes()
        ok = (len(calls) == 1 and calls[0]["input"]["page_size"] == 5
              and window.page_spin.get_value() == 5
              and window.chinese_punct.get_active() is True
              and window.shortcut_entries["cancel"].get_text() == "Escape"
              and window.status.get_text() == settings_ui.UI_TEXT["defaults"]
              and self.saved_events and self.saved_events[-1]["input"]["page_size"] == 5
              and after == before and window.banner_lines == [])
        return self.record("reset-uses-handler-and-refreshes-controls", ok,
                           handler_calls=len(calls),
                           handler_page_size=calls[0]["input"]["page_size"] if calls else None,
                           refreshed_page_size=window.page_spin.get_value(),
                           refreshed_chinese_punct=window.chinese_punct.get_active(),
                           status=window.status.get_text(),
                           file_unchanged=after == before,
                           on_saved_events=[e["input"]["page_size"] for e in self.saved_events],
                           screenshot=shot)

    def step_learning_directory(self):
        """无回调时的学习路径：真实引擎必须拿到明确的 user_data_dir。"""
        window = self.window
        window.learning_switch.set_active(True)
        window.page_spin.set_value(5)
        pump(0.2)
        real = config.apply_engine
        calls = []
        directory = config.learning_data_dir()

        def spy(settings, engine=None, caps=None, user_data_dir=None, env=None):
            patch, state = real(settings, engine=engine, caps=caps, user_data_dir=user_data_dir, env=env)
            calls.append({"user_data_dir": str(user_data_dir) if user_data_dir else None,
                          "state_config": state.get("config") if isinstance(state, dict) else None})
            return patch, state

        config.apply_engine = spy
        try:
            saved = window.save()
        finally:
            config.apply_engine = real
        written, errors, _ = config.load(self.path, caps=self.caps)
        meta = (directory / "meta.json").is_file()
        window.learning_switch.set_active(False)
        window.save()  # 复位，避免后续检查带上学习开关
        state_config = calls[0]["state_config"] if calls else None
        ok = (saved is True and len(calls) == 1
              and calls[0]["user_data_dir"] == str(directory)
              and state_config and state_config.get("learning") is True
              and written["input"]["learning"] is True and not errors and meta)
        return self.record("learning-applied-with-explicit-user-data-dir", ok, saved=saved,
                           engine_calls=len(calls),
                           user_data_dir=calls[0]["user_data_dir"] if calls else None,
                           engine_state_config=state_config, written_learning=written["input"]["learning"],
                           learning_meta_created=meta, errors=errors)

    def step_fixture_gating(self):
        """夹具能力检查在独立进程里跑：两个 GTK 顶层窗口同进程时本机 cairo 会断言崩溃。"""
        result = subprocess.run([sys.executable, str(ROOT / "tests" / "settings_fixture_step.py")],
                                env=os.environ.copy(), capture_output=True, text=True, timeout=180)
        path = EVIDENCE / "settings-fixture-step.json"
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
            "result": "FAIL", "stderr": result.stderr[-400:], "stdout": result.stdout[-400:]}
        ok = payload.get("result") == "PASS"
        return self.record("fixture-capabilities-show-controls-only", ok,
                           schemas=payload.get("schemas"), schema_texts=payload.get("schema_texts"),
                           learning_control=payload.get("learning_control"),
                           unsupported_text=payload.get("unsupported_text"),
                           written_input=payload.get("written_input"),
                           screenshot=payload.get("screenshot"),
                           note=payload.get("note", "夹具覆盖，非真实功能"))

    def step_readability(self):
        ratios = {"body_text": contrast("#1f1f1f", "#f8f9fa"),
                  "section_title": contrast("#0b57d0", "#f8f9fa"),
                  "note": contrast("#5f6368", "#f8f9fa"),
                  "error_banner": contrast("#a50e0e", "#fce8e6"),
                  "unsupported": contrast("#9a3412", "#fff7ed")}
        worst = min(ratios.values())
        ok = worst >= 4.5
        return self.record("settings-readability-contrast-min-4.5", ok, ratios=ratios, worst=worst)


def _normalized(settings, **changes):
    result = json.loads(json.dumps(settings))
    result["input"].update(changes)
    return result


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="settings-", dir=str(EVIDENCE)))
    path = tmp / "settings.json"
    caps = _caps()
    payload = {"employee_id": "interface", "kind": "settings-ui",
               "components": {"real": ["GTK3 settings window", "settings v1 validation",
                                       f"engine capabilities ({caps.backend} {caps.backend_version})",
                                       "real double_pinyin_schemes/fuzzy_rules/correction_rules catalogs",
                                       "engine configure mapping", "save_handler contract"],
                              "fixture": [str(FIXTURE.relative_to(ROOT.parent))]},
               "capabilities": caps.summary(),
               "result": "FAIL"}
    scenario = Scenario(path, caps, partial=EVIDENCE / "settings-checks-partial.json")
    try:
        payload["snapshots"] = scenario.run()
        payload["result"] = "PASS" if all(c["result"] == "PASS" for c in scenario.checks) else "FAIL"
    except Exception as exc:  # noqa: BLE001
        payload["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        payload["checks"] = scenario.checks
        (EVIDENCE / "settings-checks.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"result": payload["result"]}, ensure_ascii=False), flush=True)
        return 0 if payload["result"] == "PASS" else 1


def _caps():
    try:
        from server_ime_engine import Engine

        return config.Capabilities.from_engine(Engine)
    except Exception:
        return config.Capabilities()


if __name__ == "__main__":
    raise SystemExit(main())
