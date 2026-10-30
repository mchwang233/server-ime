"""中文设置界面（GTK3）。

原则：只给**真正会生效**的选项显示控件。

* 引擎 capabilities.features 为 true 的选项 → 可编辑控件；
* 双拼方案、模糊音规则、纠错规则只在**真实 capabilities 声明了清单**时出现，且只列出清单内的值；
* 为 false 的选项（如引擎未支持）→ 只在“引擎未支持”区列出说明文字，不显示开关；
* 保存与恢复默认走同一条路径 `apply_settings()`：
  - 提供了 `save_handler(settings)` 时，由回调完成验证、运行配置传播与持久化，
    窗口**不写盘、不创建临时引擎**；
  - 未提供回调时，先应用真实引擎（学习开启时必须带明确 `user_data_dir`），成功后才写盘，
    失败则原配置保持不变且不提示成功。
"""
from __future__ import annotations

import json
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk, Pango  # noqa: E402

from . import config as config_mod  # noqa: E402
from . import keymap, punctuation  # noqa: E402

UI_TEXT = {
    "title": "服务器输入法设置",
    "sections": {
        "input": "输入",
        "double_pinyin": "双拼",
        "fuzzy": "模糊音",
        "correction": "拼音纠错",
        "punctuation": "标点",
        "shortcuts": "快捷键",
        "panel": "候选面板",
        "capabilities": "引擎能力与生效位置",
    },
    "save": "保存",
    "reset": "恢复默认",
    "close": "关闭",
    "saved": "已保存：{path}",
    "saved_handler": "已保存，并已通知运行中的输入法服务",
    "defaults": "已恢复默认设置",
    "unsupported": "引擎未支持，本界面不提供开关：",
    "status_live": "即时生效",
    "status_config": "已写入配置，框架接入后生效",
    "status_unsupported": "未支持",
    "status_undeclared": "引擎未声明可选值",
    "page_size": "每页候选数",
    "incomplete": "不完整拼音（可用声母直接取候选）",
    "schema": "输入方案",
    "scheme": "双拼方案",
    "scheme_default": "默认（{name}）",
    "learning": "个人输入学习（保存在本机个人词库）",
    "prediction": "上屏后联想下一个词（数字键选择，其它键继续输入）",
    "shift_toggle": "单按 Shift 切换中英文（输入中按下时，已打的字母原样上屏）",
    "fuzzy_enabled": "启用模糊音",
    "fuzzy_rules": "生效的模糊音规则",
    "correction_enabled": "启用拼音纠错",
    "correction_rules": "生效的纠错规则",
    "no_catalog": "引擎声明支持{what}，但未提供规则清单（capabilities 为空），本界面不显示这些选项。",
    "chinese_punctuation": "使用中文标点（，。？！）",
    "full_width_pairs": "成对中文标点（“”、（）、《》）",
    "font_scale": "面板字号缩放",
    "max_visible": "面板最多显示候选",
    "show_page_info": "显示页码",
    "show_hints": "显示快捷键提示",
    "shortcuts_note": "以下绑定与平台按键层实际实现一致；改为其它按键会在保存时被拒绝并说明原因。",
    "punct_preview": "标点预览：",
    "conflicts": "发现 {count} 个问题，未保存：",
}

UNSUPPORTED_TEXT = {
    "double_pinyin": "双拼（capabilities.features.double_pinyin=false）",
    "fuzzy_pinyin": "模糊音（capabilities.features.fuzzy_pinyin=false）",
    "correction": "拼音纠错（capabilities.features.correction=false）",
    "learning": "个人输入学习（capabilities.features.learning=false）",
}


def apply_settings(settings, path, caps, save_handler=None, user_data_dir=None, env=None):
    """保存/恢复默认的统一路径；返回 ``(settings, info)``，失败抛 ``ConfigError``。

    有 ``save_handler`` 时：本函数只做一次本地校验，随后把规范化 settings 交给回调；
    回调负责持久化与运行配置传播，返回值作为新的规范化 settings。
    没有回调时：先 ``config.apply_engine``（学习开启时显式传 user_data_dir），
    成功后才 ``config.save`` 写盘；任何一步失败都不写盘、不吞掉异常。
    """
    normalized, errors = config_mod.validate(settings, caps)
    if errors:
        raise config_mod.ConfigError(errors)
    if save_handler is not None:
        try:
            result = save_handler(normalized)
        except config_mod.ConfigError:
            raise
        except Exception as exc:  # 回调内部异常同样是失败：不得提示成功、不得改动原配置
            raise config_mod.ConfigError([{
                "code": "handler-error", "path": "",
                "message": config_mod.MESSAGES["handler-error"].format(
                    message=f"{type(exc).__name__}: {exc}")}]) from exc
        if not isinstance(result, dict):
            raise config_mod.ConfigError([{
                "code": "handler-result", "path": "",
                "message": config_mod.MESSAGES["handler-result"].format(value=type(result).__name__)}])
        return result, {"persisted_by": "save_handler",
                        "engine_patch": config_mod.engine_patch(result, caps)}
    directory = user_data_dir
    if directory is None and normalized["input"].get("learning") and caps.supports("learning"):
        directory = config_mod.learning_data_dir(env)
    patch, state = config_mod.apply_engine(normalized, caps=caps, user_data_dir=directory, env=env)
    saved = config_mod.save(normalized, path=path, caps=caps, env=env)
    return saved, {"persisted_by": "config.save", "engine_patch": patch,
                   "engine_state_config": state.get("config") if isinstance(state, dict) else None,
                   "user_data_dir": str(directory) if directory is not None else None}


class SettingsWindow:
    """中文设置窗口。

    参数
    ----
    settings, caps, path
        当前设置、引擎能力视图、设置文件路径。
    on_saved(settings)
        可选；保存/恢复默认**成功后**调用（失败不调用）。
    save_handler(settings) -> dict
        可选；产品装配层提供的保存回调。提供时窗口不写盘、不调用引擎，
        由回调完成验证、运行中配置传播与持久化；回调失败应抛 ``ConfigError``。
    user_data_dir
        可选；无回调时传给 ``Engine(user_data_dir=…)`` 的个人数据目录。
    """

    def __init__(self, settings, caps, path, on_saved=None, save_handler=None, user_data_dir=None):
        self.settings = settings
        self.caps = caps
        self.path = path
        self.on_saved = on_saved
        self.save_handler = save_handler
        self.user_data_dir = user_data_dir
        self.shortcut_entries = {}
        self.fuzzy_checks = {}
        self.correction_checks = {}
        self.banner_lines = []
        self._build()

    # ------------------------------------------------------------- 构建
    def _build(self):
        self.window = Gtk.Window(title=UI_TEXT["title"])
        self.window.set_default_size(780, 760)
        # 限制最大宽度，避免长说明文字把窗口撑出屏幕（缩放到小屏/远程会话时仍可读）。
        geometry = Gdk.Geometry()
        geometry.max_width, geometry.max_height = 900, 1000
        geometry.min_width, geometry.min_height = 560, 380
        self.window.set_geometry_hints(None, geometry,
                                       Gdk.WindowHints.MAX_SIZE | Gdk.WindowHints.MIN_SIZE)
        self.window.set_border_width(0)
        self.window.connect("destroy", Gtk.main_quit)
        css = Gtk.CssProvider()
        css.load_from_data(_css().encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window.add(outer)
        header = Gtk.Label(label=UI_TEXT["title"])
        header.get_style_context().add_class("ime-settings-title")
        header.set_xalign(0)
        outer.pack_start(header, False, False, 0)

        self.banner = Gtk.Label(label="")
        self.banner.get_style_context().add_class("ime-error")
        self.banner.set_xalign(0)
        self.banner.set_line_wrap(True)
        self.banner.set_no_show_all(True)
        outer.pack_start(self.banner, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer.pack_start(scroller, True, True, 0)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        body.set_border_width(16)
        scroller.add(body)

        body.pack_start(self._section(UI_TEXT["sections"]["input"]), False, False, 0)
        body.pack_start(self._input_section(), False, False, 0)
        if hasattr(self, "scheme_combo"):
            body.pack_start(self._section(UI_TEXT["sections"]["double_pinyin"]), False, False, 0)
            body.pack_start(self._scheme_section(), False, False, 0)
        if self.caps.supports("fuzzy_pinyin"):
            body.pack_start(self._section(UI_TEXT["sections"]["fuzzy"]), False, False, 0)
            body.pack_start(self._rules_section("fuzzy"), False, False, 0)
        if self.caps.supports("correction"):
            body.pack_start(self._section(UI_TEXT["sections"]["correction"]), False, False, 0)
            body.pack_start(self._rules_section("correction"), False, False, 0)
        body.pack_start(self._section(UI_TEXT["sections"]["punctuation"]), False, False, 0)
        body.pack_start(self._punctuation_section(), False, False, 0)
        body.pack_start(self._section(UI_TEXT["sections"]["shortcuts"]), False, False, 0)
        body.pack_start(self._shortcut_section(), False, False, 0)
        body.pack_start(self._section(UI_TEXT["sections"]["panel"]), False, False, 0)
        body.pack_start(self._panel_section(), False, False, 0)
        body.pack_start(self._section(UI_TEXT["sections"]["capabilities"]), False, False, 0)
        body.pack_start(self._capability_section(), False, False, 0)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_border_width(12)
        self.status = Gtk.Label(label="")
        self.status.set_xalign(0)
        self.status.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.status.set_max_width_chars(40)
        self.status.get_style_context().add_class("ime-status")
        buttons.pack_start(self.status, True, True, 0)
        self.save_button = Gtk.Button(label=UI_TEXT["save"])
        self.reset_button = Gtk.Button(label=UI_TEXT["reset"])
        self.close_button = Gtk.Button(label=UI_TEXT["close"])
        self.save_button.get_style_context().add_class("suggested-action")
        self.save_button.connect("clicked", lambda *_: self.save())
        self.reset_button.connect("clicked", lambda *_: self.reset())
        self.close_button.connect("clicked", lambda *_: self.window.destroy())
        for button in (self.reset_button, self.save_button, self.close_button):
            buttons.pack_end(button, False, False, 0)
        outer.pack_start(buttons, False, False, 0)
        self.window.show_all()
        self.banner.hide()

    def _section(self, text):
        label = Gtk.Label(label=text)
        label.get_style_context().add_class("ime-settings-section")
        label.set_xalign(0)
        return label

    def _row(self, widget, label_text=None, note=None):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        if label_text:
            label = Gtk.Label(label=label_text)
            label.set_xalign(0)
            label.set_size_request(240, -1)
            row.pack_start(label, False, False, 0)
        row.pack_start(widget, False, False, 0)
        if note:
            note_label = Gtk.Label(label=note)
            note_label.get_style_context().add_class("ime-note")
            note_label.set_xalign(0)
            row.pack_start(note_label, False, False, 0)
        return row

    def _input_section(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.schema_combo = Gtk.ComboBoxText()
        for schema, label in (("full_pinyin", "全拼"), ("double_pinyin", "双拼")):
            if schema == "full_pinyin" or schema in self.caps.schemas:
                self.schema_combo.append(schema, label)
        self.schema_combo.set_active_id(self.settings["input"].get("schema", "full_pinyin"))
        box.pack_start(self._row(self.schema_combo, UI_TEXT["schema"], UI_TEXT["status_live"]), False, False, 0)
        if self.caps.supports("double_pinyin") and self.caps.double_pinyin_schemes:
            self.scheme_combo = Gtk.ComboBoxText()
            for name in self.caps.double_pinyin_schemes:
                self.scheme_combo.append(name, f"{self.caps.scheme_label(name)}（{name}）")
            self.scheme_combo.set_active_id(self.settings["input"].get("double_pinyin_scheme") or "")
            box.pack_start(self._row(self.scheme_combo, UI_TEXT["scheme"], UI_TEXT["status_live"]),
                           False, False, 0)
        self.page_spin = Gtk.SpinButton.new_with_range(1, 9, 1)
        self.page_spin.set_value(self.settings["input"].get("page_size", 5))
        box.pack_start(self._row(self.page_spin, UI_TEXT["page_size"], UI_TEXT["status_live"]), False, False, 0)
        self.incomplete_switch = Gtk.Switch()
        self.incomplete_switch.set_active(bool(self.settings["input"].get("incomplete", True)))
        box.pack_start(self._row(self.incomplete_switch, UI_TEXT["incomplete"], UI_TEXT["status_live"]),
                       False, False, 0)
        self.prediction_switch = Gtk.Switch()
        self.prediction_switch.set_active(bool(self.settings["input"].get("prediction", False)))
        box.pack_start(self._row(self.prediction_switch, UI_TEXT["prediction"], UI_TEXT["status_live"]),
                       False, False, 0)
        self.shift_switch = Gtk.Switch()
        self.shift_switch.set_active(bool(self.settings["input"].get("shift_toggle", True)))
        box.pack_start(self._row(self.shift_switch, UI_TEXT["shift_toggle"], UI_TEXT["status_live"]),
                       False, False, 0)
        if self.caps.supports("learning"):
            self.learning_switch = Gtk.Switch()
            self.learning_switch.set_active(bool(self.settings["input"].get("learning", False)))
            box.pack_start(self._row(self.learning_switch, UI_TEXT["learning"], UI_TEXT["status_live"]),
                           False, False, 0)
        return box

    def _scheme_section(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        names = "、".join(f"{self.caps.scheme_label(name)}（{name}）" for name in self.caps.double_pinyin_schemes)
        note = Gtk.Label(label="引擎声明的双拼方案：" + names + "。其它方案不会被保存。")
        note.set_xalign(0)
        note.set_line_wrap(True)
        note.get_style_context().add_class("ime-note")
        box.pack_start(note, False, False, 0)
        return box

    def _rules_section(self, kind):
        """模糊音 / 纠错：只显示引擎 capabilities 声明的规则。"""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        catalog = self.caps.fuzzy_rules if kind == "fuzzy" else self.caps.correction_rules
        current = self.settings["input"].get(kind) or {}
        what = "模糊音" if kind == "fuzzy" else "拼音纠错"
        if not catalog:
            note = Gtk.Label(label=UI_TEXT["no_catalog"].format(what=what))
            note.set_xalign(0)
            note.set_line_wrap(True)
            note.get_style_context().add_class("ime-note")
            box.pack_start(note, False, False, 0)
            return box
        switch = Gtk.Switch()
        switch.set_active(bool(current.get("enabled", False)))
        if kind == "fuzzy":
            self.fuzzy_switch = switch
        else:
            self.correction_switch = switch
        box.pack_start(self._row(switch, UI_TEXT[f"{kind}_enabled"], UI_TEXT["status_live"]), False, False, 0)
        grid = Gtk.Grid(column_spacing=16, row_spacing=2)
        checks = self.fuzzy_checks if kind == "fuzzy" else self.correction_checks
        enabled_rules = set(current.get("rules") or [])
        for index, name in enumerate(catalog):
            check = Gtk.CheckButton(label=self.caps.rule_label(name))
            check.set_active(name in enabled_rules)
            checks[name] = check
            grid.attach(check, index % 4, index // 4, 1, 1)
        box.pack_start(grid, False, False, 0)
        field = "fuzzy_rules" if kind == "fuzzy" else "correction_rules"
        note = Gtk.Label(label="勾选为空表示该类规则全部生效；可选规则来自引擎 "
                         f"capabilities.{field}（共 {len(catalog)} 项）。")
        note.set_xalign(0)
        note.set_line_wrap(True)
        note.get_style_context().add_class("ime-note")
        box.pack_start(note, False, False, 0)
        return box

    def _punctuation_section(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.chinese_punct = Gtk.Switch()
        self.chinese_punct.set_active(bool(self.settings["punctuation"].get("chinese", True)))
        self.chinese_punct.connect("notify::active", lambda *_: self._update_preview())
        box.pack_start(self._row(self.chinese_punct, UI_TEXT["chinese_punctuation"],
                                 UI_TEXT["status_config"]), False, False, 0)
        self.pairs_switch = Gtk.Switch()
        self.pairs_switch.set_active(bool(self.settings["punctuation"].get("use_full_width_pairs", True)))
        self.pairs_switch.connect("notify::active", lambda *_: self._update_preview())
        box.pack_start(self._row(self.pairs_switch, UI_TEXT["full_width_pairs"],
                                 UI_TEXT["status_config"]), False, False, 0)
        self.preview = Gtk.Label(label="")
        self.preview.set_xalign(0)
        self.preview.get_style_context().add_class("ime-note")
        box.pack_start(self.preview, False, False, 0)
        self._update_preview()
        return box

    def _shortcut_section(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        note = Gtk.Label(label=UI_TEXT["shortcuts_note"])
        note.set_xalign(0)
        note.set_line_wrap(True)
        note.get_style_context().add_class("ime-note")
        box.pack_start(note, False, False, 0)
        grid = Gtk.Grid(column_spacing=12, row_spacing=4)
        for row, item in enumerate(keymap.describe(keymap.validate_shortcuts(self.settings["shortcuts"])[2])):
            label = Gtk.Label(label=f"{item['label']}（{item['section']}）")
            label.set_xalign(0)
            entry = Gtk.Entry()
            entry.set_width_chars(16)
            entry.set_text(item["binding"])
            entry.set_tooltip_text(item["note"])
            status = Gtk.Label(label=UI_TEXT["status_config"])
            status.get_style_context().add_class("ime-note")
            status.set_xalign(0)
            grid.attach(label, 0, row, 1, 1)
            grid.attach(entry, 1, row, 1, 1)
            grid.attach(status, 2, row, 1, 1)
            self.shortcut_entries[item["action"]] = entry
        box.pack_start(grid, False, False, 0)
        return box

    def _panel_section(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.scale_spin = Gtk.SpinButton.new_with_range(0.8, 3.0, 0.1)
        self.scale_spin.set_digits(1)
        self.scale_spin.set_value(float(self.settings["panel"].get("font_scale", 1.0)))
        box.pack_start(self._row(self.scale_spin, UI_TEXT["font_scale"], UI_TEXT["status_live"]), False, False, 0)
        self.visible_spin = Gtk.SpinButton.new_with_range(1, 9, 1)
        self.visible_spin.set_value(int(self.settings["panel"].get("max_visible", 9)))
        box.pack_start(self._row(self.visible_spin, UI_TEXT["max_visible"], UI_TEXT["status_live"]), False, False, 0)
        self.page_info_switch = Gtk.Switch()
        self.page_info_switch.set_active(bool(self.settings["panel"].get("show_page_info", True)))
        box.pack_start(self._row(self.page_info_switch, UI_TEXT["show_page_info"], UI_TEXT["status_live"]),
                       False, False, 0)
        self.hints_switch = Gtk.Switch()
        self.hints_switch.set_active(bool(self.settings["panel"].get("show_hints", True)))
        box.pack_start(self._row(self.hints_switch, UI_TEXT["show_hints"], UI_TEXT["status_live"]),
                       False, False, 0)
        return box

    def _capability_section(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        source = ("夹具 capabilities（非真实引擎）" if self.caps.fixture
                  else f"真实引擎 {self.caps.backend} {self.caps.backend_version}")
        head = Gtk.Label(label=source + f"，接口 {self.caps.api_version}")
        head.set_xalign(0)
        box.pack_start(head, False, False, 0)
        missing = [text for feature, text in UNSUPPORTED_TEXT.items() if not self.caps.supports(feature)]
        if missing:
            label = Gtk.Label(label=UI_TEXT["unsupported"] + "；".join(missing))
            label.set_xalign(0)
            label.set_line_wrap(True)
            label.get_style_context().add_class("ime-unsupported")
            box.pack_start(label, False, False, 0)
            self.unsupported_label = label
        grid = Gtk.Grid(column_spacing=12, row_spacing=2)
        for row, item in enumerate(config_mod.mapping_report(self.settings, self.caps)):
            state = {"live": UI_TEXT["status_live"], "config-only": UI_TEXT["status_config"],
                     "unsupported": UI_TEXT["status_unsupported"],
                     "undeclared": UI_TEXT["status_undeclared"]}.get(item["state"], item["state"])
            if item.get("options"):
                state = state + "：" + "、".join(item["options"])
            for column, text in enumerate([item["label"], item["target"], state]):
                label = Gtk.Label(label=text)
                label.set_xalign(0)
                label.set_line_wrap(True)
                label.set_max_width_chars(38 if column == 1 else 30)
                if column == 2:
                    label.get_style_context().add_class("ime-note")
                grid.attach(label, column, row, 1, 1)
        box.pack_start(grid, False, False, 0)
        return box

    def _update_preview(self):
        punct = punctuation.Punctuation(self.chinese_punct.get_active(), self.pairs_switch.get_active())
        sample = ",.;:?!\"'()<>"
        self.preview.set_text(UI_TEXT["punct_preview"] + punct.map_text(sample))

    # ------------------------------------------------------------- 行为
    def collect(self):
        """把界面控件读回成设置对象（未校验）。"""
        settings = json.loads(json.dumps(self.settings))
        settings["input"]["schema"] = self.schema_combo.get_active_id() or "full_pinyin"
        if hasattr(self, "scheme_combo"):
            settings["input"]["double_pinyin_scheme"] = self.scheme_combo.get_active_id() or None
        settings["input"]["page_size"] = int(self.page_spin.get_value())
        settings["input"]["incomplete"] = bool(self.incomplete_switch.get_active())
        settings["input"]["prediction"] = bool(self.prediction_switch.get_active())
        settings["input"]["shift_toggle"] = bool(self.shift_switch.get_active())
        if hasattr(self, "learning_switch"):
            settings["input"]["learning"] = bool(self.learning_switch.get_active())
        for kind, switch_name, checks in (
                ("fuzzy", "fuzzy_switch", self.fuzzy_checks),
                ("correction", "correction_switch", self.correction_checks)):
            if not hasattr(self, switch_name):
                continue
            entry = dict(settings["input"].get(kind) or {})
            entry["enabled"] = bool(getattr(self, switch_name).get_active())
            entry["rules"] = [name for name, check in checks.items() if check.get_active()]
            settings["input"][kind] = entry
        settings["punctuation"]["chinese"] = bool(self.chinese_punct.get_active())
        settings["punctuation"]["use_full_width_pairs"] = bool(self.pairs_switch.get_active())
        for action, entry in self.shortcut_entries.items():
            settings["shortcuts"][action] = entry.get_text().strip()
        settings["panel"]["font_scale"] = round(float(self.scale_spin.get_value()), 1)
        settings["panel"]["max_visible"] = int(self.visible_spin.get_value())
        settings["panel"]["show_page_info"] = bool(self.page_info_switch.get_active())
        settings["panel"]["show_hints"] = bool(self.hints_switch.get_active())
        return settings

    def refresh_controls(self, settings):
        """用规范化后的 settings 回填所有控件（保存/恢复默认成功后调用）。"""
        in_value = settings.get("input", {})
        self.schema_combo.set_active_id(in_value.get("schema", "full_pinyin"))
        if hasattr(self, "scheme_combo"):
            self.scheme_combo.set_active_id(in_value.get("double_pinyin_scheme") or "")
        self.page_spin.set_value(int(in_value.get("page_size", 5)))
        self.incomplete_switch.set_active(bool(in_value.get("incomplete", True)))
        self.prediction_switch.set_active(bool(in_value.get("prediction", False)))
        self.shift_switch.set_active(bool(in_value.get("shift_toggle", True)))
        if hasattr(self, "learning_switch"):
            self.learning_switch.set_active(bool(in_value.get("learning", False)))
        for kind, switch_name, checks in (
                ("fuzzy", "fuzzy_switch", self.fuzzy_checks),
                ("correction", "correction_switch", self.correction_checks)):
            if not hasattr(self, switch_name):
                continue
            entry = in_value.get(kind) or {}
            getattr(self, switch_name).set_active(bool(entry.get("enabled", False)))
            rules = set(entry.get("rules") or [])
            for name, check in checks.items():
                check.set_active(name in rules)
        punct = settings.get("punctuation", {})
        self.chinese_punct.set_active(bool(punct.get("chinese", True)))
        self.pairs_switch.set_active(bool(punct.get("use_full_width_pairs", True)))
        for action, entry in self.shortcut_entries.items():
            entry.set_text(str(settings.get("shortcuts", {}).get(action, entry.get_text())))
        panel = settings.get("panel", {})
        self.scale_spin.set_value(float(panel.get("font_scale", 1.0)))
        self.visible_spin.set_value(int(panel.get("max_visible", 9)))
        self.page_info_switch.set_active(bool(panel.get("show_page_info", True)))
        self.hints_switch.set_active(bool(panel.get("show_hints", True)))
        self._update_preview()

    _refresh_controls = refresh_controls  # 旧名保留

    def show_errors(self, errors):
        self.banner_lines = [e["message"] for e in errors]
        self.banner.set_text(UI_TEXT["conflicts"].format(count=len(errors)) + "\n· " +
                             "\n· ".join(self.banner_lines))
        self.banner.show()
        self.status.set_text("")
        _emit({"event": "validation", "ok": False, "errors": errors})

    def clear_errors(self):
        self.banner_lines = []
        self.banner.hide()

    def save(self):
        """保存；成功返回 True。有 save_handler 时由回调写盘并传播配置。"""
        try:
            saved, info = apply_settings(self.collect(), self.path, self.caps,
                                         save_handler=self.save_handler,
                                         user_data_dir=self.user_data_dir)
        except config_mod.ConfigError as error:
            self.show_errors(error.errors)
            return False
        self.settings = saved
        self.refresh_controls(saved)
        self.clear_errors()
        if info.get("persisted_by") == "save_handler":
            self.status.set_text(UI_TEXT["saved_handler"])
        else:
            self.status.set_text(UI_TEXT["saved"].format(path=self.path))
        if self.on_saved:
            self.on_saved(saved)
        _emit({"event": "saved", "path": str(self.path), "settings": saved, **info})
        return True

    def reset(self, close=False):
        """恢复默认：与保存同一条路径（含回调），成功才刷新控件并触发 on_saved。"""
        try:
            saved, info = apply_settings(config_mod.defaults(), self.path, self.caps,
                                         save_handler=self.save_handler,
                                         user_data_dir=self.user_data_dir)
        except config_mod.ConfigError as error:
            self.show_errors(error.errors)
            return False
        self.settings = saved
        self.refresh_controls(saved)
        self.clear_errors()
        self.status.set_text(UI_TEXT["defaults"])
        if self.on_saved:
            self.on_saved(saved)
        _emit({"event": "reset", "path": str(self.path), "settings": saved, **info})
        if close:
            self.window.destroy()
        return saved

    def screenshot(self, path):
        window = self.window.get_window()
        pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, window.get_width(), window.get_height())
        pixbuf.savev(str(path), "png", [], [])
        return str(path)

    def geometry(self):
        window = self.window.get_window()
        width, height = self.window.get_size()
        return {"w": width, "h": height, "realized": window is not None}


def _emit(event):
    if os.environ.get("SERVER_IME_UI_EVENTS") == "1":
        sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def _css():
    return """
    window { background-color: #f8f9fa; }
    .ime-settings-title { font-size: 20px; font-weight: bold; padding: 14px 16px 6px 16px; color: #1f1f1f; }
    .ime-settings-section { font-size: 15px; font-weight: bold; color: #0b57d0; padding-top: 6px; }
    .ime-note { font-size: 12px; color: #5f6368; }
    .ime-error { background-color: #fce8e6; color: #a50e0e; padding: 8px 16px; font-size: 13px; }
    .ime-unsupported { font-size: 12px; color: #9a3412; background-color: #fff7ed;
                       padding: 6px 10px; border-radius: 4px; }
    .ime-status { font-size: 12px; color: #5f6368; }
    """


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="服务器输入法中文设置界面")
    parser.add_argument("--config", help="设置文件路径")
    parser.add_argument("--caps", help="引擎 capabilities JSON（夹具或真实导出）")
    parser.add_argument("--user-data-dir", help="个人数据目录（无保存回调时用于学习）")
    args = parser.parse_args(argv)
    caps = config_mod.Capabilities.from_file(args.caps) if args.caps else _engine_caps()
    settings, errors, path = config_mod.load(args.config, caps=caps)
    window = SettingsWindow(settings, caps, path, user_data_dir=args.user_data_dir)
    if errors:
        window.show_errors(errors)
    _emit({"event": "ready", "path": str(path), "capabilities": caps.summary(),
           "geometry": window.geometry(), "load_errors": errors})
    Gtk.main()
    return 0


def _engine_caps():
    try:
        from server_ime_engine import Engine

        return config_mod.Capabilities.from_engine(Engine)
    except Exception:
        return config_mod.Capabilities()


if __name__ == "__main__":
    raise SystemExit(main())
