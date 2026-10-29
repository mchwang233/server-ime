"""快捷键格式与校验（keymap-v1）。

格式：`MOD+Key`，修饰键为 Control/Shift/Alt/Super（可组合，顺序固定），Key 取
keysym 名称（space、Return、Page_Up、a…z、1…9 等）。`select_digit` 使用区间形式 `1-9`。

平台按键层当前实现的绑定是固定集合（见 platform/docs/interfaces.md）。因此本模块只允许
**平台真正会执行**的绑定：其它绑定校验时报 `unsupported-binding`，设置界面明确拒绝而不
假装生效。等平台接上 keymap-v1 后，把 ACTION_SPECS 的 `implemented` 扩展即可。
"""
from __future__ import annotations

import re

MODIFIERS = ("Control", "Shift", "Alt", "Super")
MODIFIER_BITS = {"Control": 4, "Shift": 1, "Alt": 8, "Super": 1 << 26}

#: keysym 名称 → (keyval, 中文名)
KEYS = {
    "space": (0x20, "空格"),
    "Return": (0xFF0D, "回车"),
    "KP_Enter": (0xFF8D, "小键盘回车"),
    "Escape": (0xFF1B, "Esc"),
    "Tab": (0xFF09, "Tab"),
    "BackSpace": (0xFF08, "退格"),
    "Delete": (0xFFFF, "删除"),
    "Left": (0xFF51, "左方向键"),
    "Up": (0xFF52, "上方向键"),
    "Right": (0xFF53, "右方向键"),
    "Down": (0xFF54, "下方向键"),
    "Home": (0xFF50, "Home"),
    "End": (0xFF57, "End"),
    "Page_Up": (0xFF55, "Page Up"),
    "Page_Down": (0xFF56, "Page Down"),
}
KEYS.update({letter: (ord(letter), letter.upper()) for letter in "abcdefghijklmnopqrstuvwxyz"})
KEYS.update({digit: (ord(digit), digit) for digit in "123456789"})

#: 动作 → 平台实际实现、可由配置表达的绑定。`accepted` 是平台会执行的精确绑定集合。
ACTION_SPECS = {
    "toggle_mode": {"label": "中英切换", "section": "全局", "accepted": ("Control+space",),
                    "default": "Control+space", "note": "取消未提交组合后切换中/英"},
    "select_digit": {"label": "数字选词", "section": "候选", "accepted": ("1-9",),
                     "default": "1-9", "note": "选择当前页第 N 项，受候选数限制"},
    "page_prev": {"label": "上一页", "section": "候选", "accepted": ("Page_Up",),
                  "default": "Page_Up", "note": "边界不循环"},
    "page_next": {"label": "下一页", "section": "候选", "accepted": ("Page_Down",),
                  "default": "Page_Down", "note": "边界不循环"},
    "move_prev": {"label": "上一项", "section": "候选", "accepted": ("Up",),
                  "default": "Up", "note": "逐项移动当前选中候选"},
    "move_next": {"label": "下一项", "section": "候选", "accepted": ("Down",),
                  "default": "Down", "note": "逐项移动当前选中候选"},
    "commit_raw": {"label": "提交原始拼音", "section": "编辑", "accepted": ("Return", "KP_Enter"),
                   "default": "Return", "note": "不选词，直接上屏拼音原文"},
    "cancel": {"label": "取消输入", "section": "编辑", "accepted": ("Escape",),
               "default": "Escape", "note": "清空预编辑，不提交"},
    "pass_focus": {"label": "切换焦点", "section": "编辑", "accepted": ("Tab",),
                   "default": "Tab", "note": "取消组合后交给应用切换焦点"},
}

RANGE_RE = re.compile(r"^([1-9])-([1-9])$")


class Binding:
    """解析后的绑定：modifiers 为规范化修饰键元组，key 为 keysym 名称，range 为数字区间。"""

    def __init__(self, text, modifiers=(), key=None, digit_range=None):
        self.text, self.modifiers, self.key, self.digit_range = text, tuple(modifiers), key, digit_range

    def normalized(self):
        if self.digit_range:
            return self.text
        return "+".join(list(self.modifiers) + [self.key])

    def keyval(self):
        return None if self.digit_range else KEYS[self.key][0]

    def modifier_bits(self):
        bits = 0
        for name in self.modifiers:
            bits |= MODIFIER_BITS[name]
        return bits

    def describe(self):
        if self.digit_range:
            return f"数字 {self.digit_range[0]}–{self.digit_range[1]}"
        names = [name for name in self.modifiers]
        return "+".join(names + [KEYS[self.key][1]])


def parse_binding(text):
    """解析绑定文本，返回 (Binding|None, error|None)。"""
    if not isinstance(text, str) or not text.strip():
        return None, {"code": "empty-binding", "message": "快捷键不能为空"}
    text = text.strip()
    match = RANGE_RE.match(text)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        if low > high:
            return None, {"code": "bad-range", "message": f"数字区间 {text} 起点大于终点"}
        return Binding(text, digit_range=(low, high)), None
    parts = text.split("+")
    if any(not part for part in parts):
        return None, {"code": "invalid-key", "message": f"快捷键“{text}”格式错误"}
    key = parts[-1]
    modifiers = parts[:-1]
    unknown = [m for m in modifiers if m not in MODIFIERS]
    if unknown:
        return None, {"code": "invalid-modifier",
                      "message": f"未知修饰键 {'/'.join(unknown)}；可用 Control/Shift/Alt/Super"}
    if len(set(modifiers)) != len(modifiers):
        return None, {"code": "invalid-modifier", "message": f"快捷键“{text}”重复了修饰键"}
    if key not in KEYS:
        return None, {"code": "invalid-key",
                      "message": f"未知按键“{key}”；可用按键：空格/回车/Esc/Tab/方向键/Page Up/Page Down/a–z/1–9"}
    return Binding(text, modifiers=modifiers, key=key), None


def validate_shortcuts(shortcuts):
    """校验整个快捷键表，返回 (normalized, errors, bindings)。

    errors 覆盖：未知动作、语法错误、平台不实现的绑定、两个动作绑定同一按键。
    """
    errors, normalized, bindings = [], {}, {}
    for action, spec in ACTION_SPECS.items():
        raw = shortcuts.get(action, spec["default"]) if isinstance(shortcuts, dict) else spec["default"]
        binding, error = parse_binding(raw)
        if error:
            errors.append({"code": error["code"], "path": f"shortcuts.{action}",
                           "message": f"{spec['label']}：{error['message']}"})
            continue
        normalized[action] = binding.normalized()
        if binding.normalized() not in spec["accepted"]:
            errors.append({"code": "unsupported-binding", "path": f"shortcuts.{action}",
                           "message": f"{spec['label']} 不能绑定为 {binding.describe()}；"
                                      f"平台按键层当前只执行 {_accepted_text(spec)}"})
        bindings[action] = binding
    for action, raw in (shortcuts or {}).items():
        if action not in ACTION_SPECS:
            errors.append({"code": "unknown-action", "path": f"shortcuts.{action}",
                           "message": f"未知快捷键动作“{action}”"})
    seen = {}
    for action, binding in bindings.items():
        key = binding.normalized()
        if key in seen:
            other = seen[key]
            label_a, label_b = ACTION_SPECS[other]["label"], ACTION_SPECS[action]["label"]
            message = f"快捷键冲突：{label_a} 与 {label_b} 都绑定为 {binding.describe()}，请只保留一个"
            errors.append({"code": "conflict", "path": f"shortcuts.{action}",
                           "message": message, "actions": [other, action]})
        else:
            seen[key] = action
    return normalized, errors, bindings


def _accepted_text(spec):
    names = []
    for text in spec["accepted"]:
        binding, _ = parse_binding(text)
        names.append(binding.describe() if binding else text)
    return " 或 ".join(names)


def resolve(keyval, state, bindings=None):
    """把 (keyval, 修饰位) 解析成动作名；与平台 Controller.key 的判定顺序一致。

    release 事件、含 Control/Alt/Super 的其它组合返回 None（平台会让给应用）。
    """
    from .config import defaults  # 局部导入避免循环

    if state & (1 << 30):
        return None
    bindings = bindings or validate_shortcuts(defaults()["shortcuts"])[2]
    if state & (4 | 8 | 1 << 26):
        binding = bindings.get("toggle_mode")
        if binding and keyval == binding.keyval() and state & 4 and not state & (1 | 8 | 1 << 26):
            return "toggle_mode"
        return None
    for action, binding in bindings.items():
        if binding.digit_range:
            low, high = binding.digit_range
            if ord(str(low)) <= keyval <= ord(str(high)):
                return action
            continue
        if keyval == binding.keyval():
            return action
    return None


def describe(bindings):
    """生成给设置界面/文档用的只读说明行。"""
    rows = []
    for action, spec in ACTION_SPECS.items():
        binding = bindings.get(action)
        rows.append({"action": action, "label": spec["label"], "section": spec["section"],
                     "binding": binding.normalized() if binding else "",
                     "keys": binding.describe() if binding else "", "note": spec["note"]})
    return rows
