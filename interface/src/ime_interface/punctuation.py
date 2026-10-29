"""中文标点映射（punctuation-v1）。

平台在中文模式下把未处理的 ASCII 标点透传给应用，标点转换归界面/集成负责。
本模块提供唯一的映射表，供候选面板、设置界面预览和集成层调用：

    from ime_interface.punctuation import Punctuation
    punct = Punctuation(chinese=True, full_width_pairs=True)
    punct.map_char(",")      -> "，"
    punct.map_char('"')      -> "“"（下一次调用返回 "”"）

成对符号（引号/括号）按调用顺序交替，调用方在光标移动或组合结束时调用 reset_pairs()。
"""
from __future__ import annotations

#: ASCII → 中文（非成对）
SIMPLE = {
    ",": "，", ".": "。", "?": "？", "!": "！", ":": "：", ";": "；",
    "\\": "、", "/": "、", "-": "－", "_": "——", "~": "～", "@": "＠",
    "#": "＃", "$": "￥", "%": "％", "^": "……", "&": "＆", "*": "＊",
    "+": "＋", "=": "＝", "|": "｜", "`": "｀", " ": "　",
}
#: 成对映射：ASCII → (开, 闭)
PAIRS = {
    '"': ("“", "”"),
    "'": ("‘", "’"),
    "(": ("（", "）"),
    ")": ("）", None),
    "[": ("【", "】"),
    "]": ("】", None),
    "{": ("｛", "｝"),
    "}": ("｝", None),
    "<": ("《", "》"),
    ">": ("》", None),
}
#: 英文标点模式下保持原样
ASCII_SAFE = set("".join(SIMPLE) + "".join(PAIRS))


class Punctuation:
    def __init__(self, chinese=True, full_width_pairs=True):
        self.chinese = bool(chinese)
        self.full_width_pairs = bool(full_width_pairs)
        self.open_state = {}

    def reset_pairs(self):
        self.open_state.clear()

    def map_char(self, char):
        if not self.chinese or char not in ASCII_SAFE:
            return char
        if char in PAIRS and self.full_width_pairs:
            if char in (")", "]", "}", ">"):
                return PAIRS[char][0]
            opening, closing = PAIRS[char]
            is_open = not self.open_state.get(char, False)
            self.open_state[char] = is_open
            return opening if is_open else closing
        if char in PAIRS:
            return PAIRS[char][0]
        return SIMPLE[char]

    def map_text(self, text):
        return "".join(self.map_char(char) for char in text)

    def table(self):
        """设置界面预览：ASCII → 中文标点。"""
        rows = []
        for ascii_char, chinese in list(SIMPLE.items()) + [(k, "/".join(p for p in v if p)) for k, v in PAIRS.items()]:
            rows.append({"ascii": ascii_char, "chinese": chinese})
        return rows
