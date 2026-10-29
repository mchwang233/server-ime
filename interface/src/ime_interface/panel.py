"""候选面板与输入状态指示（GTK3）。

消费平台接口 `org.superpartner.ServerIME1` 的快照：
* 候选按**从左到右横向**排列（与微软拼音、IBus 面板一致）：同一页候选同一行、横坐标依次增加；
  `panel.layout="vertical"` 只为兼容旧式单列偏好保留，缺省值即横向；
* 候选显示 `candidates[page_start:page_start+page_size]`（**整页，一个不少**），数字键/鼠标点击都按候选 ID 操作；
  `panel.max_visible` 只是视口宽度预算（一次大约能看几个候选），不截断候选、不改逻辑页大小或数字映射；
* 鼠标滚轮与「‹ ›」按钮调用 `Page(context, ±1, revision)`；
* 点击「中/英」徽标调用 `SetMode`；
* 平台返回 false 时重读快照并提示“已刷新”，不对旧 revision 盲目重试。

宽度约束（横排候选放不下时**不丢弃候选**）：
* 文字/注释标签先用 `max-width-chars` + 末尾省略号压缩，并按实测宽度继续收缩到最少 2 字；
* 到最少字数仍然超宽时，把整行候选放进**固定宽度上限的单行横向视口**并显示横向滚动条
  （`Gtk.ScrolledWindow`，策略 `AUTOMATIC/NEVER`，非 overlay），面板本身仍在 `屏幕宽 - 2*edge_margin` 内；
* 逻辑页大小、候选序号与候选 ID 都不变：`rows` 始终装着本页的全部候选，滚动条是查看入口；
  `panel.max_visible` 仅用来算视口宽度预算（`viewport_cap`），页大小仍由平台快照的 `page_size` 决定；
* 高亮候选自动滚进可见区域：平台改变 `selected_index` 后，等 GTK 真正完成新行的
  `size-allocate`（拿到实际宽度）再滚动；布局前的 1px 占位不算数，也不靠固定延时。
  视口宽度或滚动范围变化时会重新核对，用户自己拖动滚动条不会被拽回；
* 省略只影响显示：`rows[i]["text"]`、`rows[i]["id"]` 始终是引擎给的完整候选，点击/数字选词
  仍然提交完整文本与正确 ID（检查里对省略/滚动后的候选做了点击回放）。
* 滚轮仍然翻页（视口上的 `scroll-event` 转给 `page()`），不改变原有翻页语义。

优先使用输入框架原生面板：平台在 `update_lookup_table` 中已经填好 IBus LookupTable，
启用 ibus-ui-gtk3 时由框架自己绘制候选窗；本面板是框架面板不可用/被禁用时的等价实现，
并额外提供状态徽标、页码、快捷键提示与字号缩放。
"""
from __future__ import annotations

import json
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import keymap  # noqa: E402

BASE_FONT_PX = 15.0
#: 卡片阴影占用的透明外边距（像素）；只在桌面有合成器时使用。
SHADOW_PX = 8
#: 每个候选格内的左右/上下留白（像素）。
ROW_PAD_X, ROW_PAD_Y = 6, 3
PAGE_ARROWS = {"prev": "‹", "next": "›"}
#: 候选容器方向；`horizontal` 是默认值（从左到右），`vertical` 仅为旧配置兼容保留。
LAYOUTS = ("horizontal", "vertical")
#: 每个候选至少显示的字数；再窄就靠横向滚动条查看，而不是让候选消失。
MIN_TEXT_CHARS = 2
#: 横向滚动条/边框占位（像素）：内容可用宽度 = 面板宽度上限 - 这个值。
SCROLLBAR_RESERVE_PX = 18
#: 视口最小宽度（像素）：`max_visible` 再小也留出这么宽，避免面板窄到无法操作。
MIN_VIEWPORT_PX = 160


def layout_of(options):
    """读取候选布局；缺省或非法值一律按横向，保证已有配置升级后立即横排。"""
    value = str((options or {}).get("layout", "horizontal")).strip().lower()
    return value if value in LAYOUTS else "horizontal"


def _emit(event):
    if os.environ.get("SERVER_IME_UI_EVENTS") == "1":
        sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
        sys.stdout.flush()



CARET = '<span foreground="#005fb8" weight="bold">|</span>'


def pinyin_markup(text, cursor):
    """The pinyin with a caret where the next letter goes (Left/Right move it)."""
    cursor = cursor if isinstance(cursor, int) and 0 <= cursor <= len(text) else len(text)
    return GLib.markup_escape_text(text[:cursor]) + CARET + GLib.markup_escape_text(text[cursor:])

class CandidatePanel:
    def __init__(self, options=None, client=None, snapshot=None):
        options = options or {}
        self.client = client
        self.font_scale = float(options.get("font_scale", 1.0))
        self.max_visible = int(options.get("max_visible", 9))
        self.show_page_info = bool(options.get("show_page_info", True))
        self.show_hints = bool(options.get("show_hints", True))
        self.margin = int(options.get("edge_margin", 8))
        self.layout = layout_of(options)
        self.snapshot = snapshot
        self.last_feedback = ""
        self.rows = []
        self.dropped = []
        self.content_width = 0
        self.content_natural_width = 0
        # 一次 render 只排一个“布局完成后核对滚动”的空闲回调；实际分配还会再排。
        self._reveal_scheduled = False
        self._reveal_serial = 0      # 每次 render 递增
        self._settled_serial = 0     # 已经按真实 allocation 核对过高亮的 render
        self._layout_signature = None
        self._build()

    # ---------------------------------------------------------------- 构建
    def _build(self):
        self.window = Gtk.Window(type=Gtk.WindowType.POPUP)
        self.window.set_decorated(False)
        self.window.set_accept_focus(False)
        self.window.set_focus_on_map(False)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.set_keep_above(True)
        self.window.set_resizable(False)
        self.window.get_style_context().add_class("ime-panel")
        self.window.connect("destroy", Gtk.main_quit)
        # Re-place once the window takes its new size (wider or narrower page).
        self.window.connect("size-allocate", lambda *_: self.rows and self.window.get_visible() and self._place())
        # 有合成器时用透明窗口画圆角卡片和阴影；否则退回普通方角面板。
        screen = Gdk.Screen.get_default()
        visual = screen.get_rgba_visual() if screen else None
        self.shadow = SHADOW_PX if (visual is not None and screen.is_composited()) else 0
        if self.shadow:
            self.window.set_visual(visual)
            self.window.set_app_paintable(True)
            self.window.get_style_context().add_class("ime-translucent")

        css = Gtk.CssProvider()
        css.load_from_data(_css(self.font_scale).encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.outer.get_style_context().add_class("ime-card")
        for side in ("top", "bottom", "start", "end"):
            getattr(self.outer, "set_margin_" + side)(self.shadow)
        self.window.add(self.outer)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.get_style_context().add_class("ime-header")
        self.badge_button = Gtk.EventBox()
        self.badge_button.set_tooltip_text("单击切换中/英文（等同 Ctrl+空格）")
        self.badge = Gtk.Label(label="中")
        self.badge.get_style_context().add_class("ime-badge")
        self.badge_button.add(self.badge)
        self.badge_button.connect("button-press-event", self._on_badge_click)
        header.pack_start(self.badge_button, False, False, 0)
        self.status = Gtk.Label(label="")
        self.status.get_style_context().add_class("ime-status")
        self.status.set_xalign(0.0)
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.status.set_single_line_mode(True)
        header.pack_start(self.status, True, True, 0)
        self.page_label = Gtk.Label(label="")
        self.page_label.get_style_context().add_class("ime-page")
        self.page_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.page_label.set_single_line_mode(True)
        self.prev_button = Gtk.Button(label=PAGE_ARROWS["prev"])
        self.next_button = Gtk.Button(label=PAGE_ARROWS["next"])
        for button in (self.prev_button, self.next_button):
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.get_style_context().add_class("ime-page-button")
        self.prev_button.connect("clicked", lambda *_: self.page(-1))
        self.next_button.connect("clicked", lambda *_: self.page(1))
        self.header = header
        self.outer.pack_start(header, False, False, 0)
        # The pinyin being typed, small and grey above the candidates (as in Windows 11).
        self.pinyin = Gtk.Label(label="")
        self.pinyin.get_style_context().add_class("ime-pinyin")
        self.pinyin.set_xalign(0.0)
        self.pinyin.set_ellipsize(Pango.EllipsizeMode.START)
        self.pinyin.set_single_line_mode(True)
        self.outer.pack_start(self.pinyin, False, False, 0)
        # 候选与翻页在同一行：候选 … 1/2 ‹ ›
        self.line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.line.get_style_context().add_class("ime-line")
        self.pager = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.pager.get_style_context().add_class("ime-pager")
        self.pager.pack_start(self.page_label, False, False, 0)
        self.pager.pack_start(self.prev_button, False, False, 0)
        self.pager.pack_start(self.next_button, False, False, 0)
        self.pager.set_valign(Gtk.Align.CENTER)

        self.rows_box = Gtk.Box(orientation=self._orientation(), spacing=2)
        self.rows_box.get_style_context().add_class("ime-rowbox")
        # 控件真正拿到分配后（包括视口变窄、短页收缩）再核对滚动位置，
        # 不能只依赖 render 里那一次空闲回调：新候选在 size-allocate 之前只有 1px 占位。
        self.rows_box.connect("size-allocate", self._on_layout_changed)
        # 单行横向视口：放不下时出现横向滚动条，本页候选一个都不少地留在行里。
        # 视口宽度自己定（`_fit_to_screen` 里的宽度上限/`max_visible` 预算），不向窗口传播内容自然宽度，
        # 否则一行候选会把整个面板撑到屏幕宽，滚动条就永远不出现。
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.scroller.set_propagate_natural_height(True)
        self.scroller.set_propagate_natural_width(False)
        self.scroller.set_halign(Gtk.Align.START)
        self.scroller.set_overlay_scrolling(False)
        self.scroller.set_kinetic_scrolling(False)
        self.scroller.get_style_context().add_class("ime-viewport")
        self.scroller.add(self.rows_box)
        # 视口宽度（page_size）变化同样要重新核对：先滚动后缩窄会让高亮落到视野外。
        self.scroller.connect("size-allocate", self._on_layout_changed)
        # 滚轮在候选上仍然翻页（不能被子视口吞掉变成横向滚动）。
        self.scroller.connect("scroll-event", self._on_scroll)
        self.line.pack_start(self.scroller, False, False, 0)
        self.line.pack_end(self.pager, False, False, 0)
        self.outer.pack_start(self.line, False, False, 0)

        self.hints = Gtk.Label(label="")
        self.hints.get_style_context().add_class("ime-hints")
        self.hints.set_xalign(0.0)
        self.hints.set_ellipsize(Pango.EllipsizeMode.END)
        self.hints.set_single_line_mode(True)
        self.outer.pack_start(self.hints, False, False, 0)

        self.window.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.window.connect("scroll-event", self._on_scroll)
        self.window.show_all()
        self.scroller.hide()
        self.window.hide()
        self.window.realize()
        self.window.move(self.margin, self.margin)

    # ---------------------------------------------------------------- 渲染
    def set_options(self, options):
        self.font_scale = float(options.get("font_scale", self.font_scale))
        self.max_visible = int(options.get("max_visible", self.max_visible))
        self.show_page_info = bool(options.get("show_page_info", self.show_page_info))
        self.show_hints = bool(options.get("show_hints", self.show_hints))
        self.layout = layout_of({**options, "layout": options.get("layout", self.layout)})
        self.rows_box.set_orientation(self._orientation())
        css = Gtk.CssProvider()
        css.load_from_data(_css(self.font_scale).encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        if self.snapshot:
            self.render(self.snapshot)

    def render(self, snapshot, feedback=""):
        if snapshot is None:
            self.snapshot = None
            self.rows = []
            self.window.hide()
            return
        context = snapshot.get("context_id")
        if not snapshot.get("focused") or not snapshot.get("enabled"):
            # 只有当前面板对应的上下文失焦时才收起；其它上下文的快照不抢显示。
            if context == getattr(self, "context_id", None):
                self.snapshot = snapshot
                self.rows = []
                self.window.hide()
            return
        self.context_id = context
        self.snapshot = snapshot
        self.last_feedback = feedback
        # 这一次 render 的“高亮已按真实布局核对”还没完成；等 allocation 到了再核对。
        self._reveal_serial += 1
        mode = snapshot.get("mode", "zh")
        self.badge.set_text("中" if mode == "zh" else "英")
        status = snapshot.get("status") or ""
        if snapshot.get("direct_input"):
            status = "直接输入（不转换）"
        parts = [status] if status else []
        if snapshot.get("error"):
            parts.append("错误：" + str(snapshot["error"]))
        if feedback:
            parts.append(feedback)
        # 正常输入时不显示状态行（和 Windows 11 一样只有候选）；
        # 直接输入、出错或有操作反馈时才显示。
        notice = [p for p in parts if p != (snapshot.get("status") or "")]
        self.status.set_text(" · ".join(notice))

        candidates = list(snapshot.get("candidates") or [])
        page_size = max(1, int(snapshot.get("page_size", 5)))
        start = int(snapshot.get("page_start", 0))
        selected = int(snapshot.get("selected_index", 0))
        visible = bool(snapshot.get("candidate_visible")) and bool(candidates)
        page_count = int(snapshot.get("page_count", 0)) or (
            (len(candidates) + page_size - 1) // page_size if candidates else 0)
        page_no = start // page_size + 1 if page_count else 0
        self.page_label.set_text(f"{page_no}/{page_count}" if (self.show_page_info and page_count) else "")
        self.prev_button.set_sensitive(start > 0)
        self.next_button.set_sensitive(start + page_size < len(candidates))

        for child in self.rows_box.get_children():
            self.rows_box.remove(child)
        self.rows = []
        self.dropped = []
        page = candidates[start:start + page_size]
        for offset, candidate in enumerate(page):
            row = self._row(offset, candidate, selected - start)
            row["index"] = candidate.get("index", start + offset)
            row["selected"] = offset == selected - start
            self.rows_box.pack_start(row["widget"], False, False, 0)
            self.rows.append(row)
        self.scroller.set_visible(visible)
        self.hints.set_visible(bool(self.show_hints))
        bindings = keymap.validate_shortcuts(_shortcuts_from_env())[2]
        self.hints.set_text(" · ".join([
            f"{bindings['move_prev'].describe()}/{bindings['move_next'].describe()} 选择",
            f"{bindings['page_prev'].describe()}/{bindings['page_next'].describe()} 翻页",
            f"数字或单击选词", f"{bindings['cancel'].describe()} 取消",
            f"{bindings['toggle_mode'].describe()} 中英"]))
        # Nothing to choose and nothing to tell: no window at all (no lone 中 box
        # between a commit and the next suggestions, which looked like a flash).
        if not visible and not self.status.get_text():
            self.window.hide()
        else:
            # Lay out and place before mapping, so the window never shows at the
            # previous page's size or position.
            self.outer.show_all()
            self.scroller.set_visible(visible)
            self.hints.set_visible(bool(self.show_hints) and visible)
            self.header.set_visible(bool(self.status.get_text()) or not visible)
            self.badge_button.set_visible(not visible)
            self.pager.set_visible(visible and page_count > 1)
            self.page_label.set_visible(bool(self.page_label.get_text()))
            preedit = (snapshot.get("preedit") or {}).get("text", "")
            self.pinyin.set_markup(pinyin_markup(preedit, (snapshot.get("preedit") or {}).get("cursor")))
            self.pinyin.set_visible(visible and bool(preedit))
            if visible:
                self._fit_to_screen()
            self._place()
            self.window.show()
        # 滚动不在这里做：新行还没有 allocation，按 1px 占位会把视口误滚到页首。
        # 空闲回调先兜一次，真正的尺寸分配（size-allocate）还会再排一次。
        self._schedule_reveal()
        _emit({"event": "render", "context": snapshot.get("context_id"),
               "revision": snapshot.get("revision"), "mode": mode,
               "page_start": start, "page_size": page_size, "page_count": page_count,
               "selected": selected, "visible": visible, "candidates": len(candidates),
               "layout": self.layout, "metrics": self.metrics(),
               "status": self.status.get_text(), "feedback": feedback})

    def _row(self, offset, candidate, selected_offset):
        box = Gtk.EventBox()
        box.get_style_context().add_class("ime-row")
        if self.layout == "horizontal":
            box.get_style_context().add_class("ime-cell")
        if offset == selected_offset:
            box.get_style_context().add_class("ime-row-selected")
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                        spacing=6 if self.layout == "horizontal" else 8)
        # GtkEventBox ignores CSS padding; the cell's inner space is set here.
        inner.set_margin_start(ROW_PAD_X)
        inner.set_margin_end(ROW_PAD_X)
        inner.set_margin_top(ROW_PAD_Y)
        inner.set_margin_bottom(ROW_PAD_Y)
        # Selected candidate: a short accent bar at its left edge (Windows 11 style).
        accent = Gtk.Box()
        accent.get_style_context().add_class("ime-accent")
        accent.set_size_request(3, -1)
        accent.set_valign(Gtk.Align.CENTER)
        accent.set_opacity(1.0 if offset == selected_offset else 0.0)
        index = Gtk.Label(label=f"{offset + 1}")
        index.get_style_context().add_class("ime-index")
        index.set_xalign(1.0)
        text = Gtk.Label(label=candidate.get("text", ""))
        text.get_style_context().add_class("ime-text")
        text.set_xalign(0.0)
        # 省略只在显示层：标签文字保持完整候选，rows[i]["text"]/["id"] 也保持引擎原值。
        text.set_ellipsize(Pango.EllipsizeMode.END)
        text.set_single_line_mode(True)
        inner.pack_start(accent, False, False, 0)
        inner.pack_start(index, False, False, 0)
        inner.pack_start(text, True, True, 0)
        annotation = candidate.get("annotation") or ""
        note = None
        if annotation and annotation != candidate.get("text"):
            note = Gtk.Label(label=annotation)
            note.get_style_context().add_class("ime-annotation")
            note.set_ellipsize(Pango.EllipsizeMode.END)
            note.set_single_line_mode(True)
            inner.pack_start(note, False, False, 0)
        box.add(inner)
        box.connect("button-press-event", self._on_row_click, candidate.get("id"))
        # 行自己的分配完成后再核对一次：视口宽度不变、只有候选内容变短时也收得到信号。
        box.connect("size-allocate", self._on_layout_changed)
        return {"id": candidate.get("id"), "text": candidate.get("text"),
                "widget": box, "text_widget": text, "note_widget": note,
                "label_text": text.get_text(), "annotation": annotation}

    # ---------------------------------------------------------------- 尺寸
    def _orientation(self):
        return Gtk.Orientation.HORIZONTAL if self.layout == "horizontal" else Gtk.Orientation.VERTICAL

    def _screen(self):
        screen = Gdk.Screen.get_default()
        return (screen.get_width(), screen.get_height()) if screen else (1024, 768)

    def _width_limit(self):
        """面板允许的最大宽度：屏幕宽减去两侧 edge_margin。"""
        return max(240, self._screen()[0] - 2 * max(0, self.margin))

    def _preferred_width(self):
        _minimum, natural = self.window.get_preferred_size()
        return int(natural.width)

    def _approx_char_px(self):
        """Pango 计算 `max-width-chars` 时用的近似字符宽（按数字实测，不是 CJK 宽）。"""
        label = self.rows[0]["text_widget"] if self.rows else self.status
        width = label.create_pango_layout("0000000000").get_pixel_size()[0] / 10.0
        return max(4.0, float(width))

    def _apply_char_budget(self, chars):
        chars = max(MIN_TEXT_CHARS, int(chars))
        for row in self.rows:
            row["text_widget"].set_max_width_chars(chars)
            if row["note_widget"] is not None:
                row["note_widget"].set_max_width_chars(max(MIN_TEXT_CHARS, chars // 2))

    def _content_natural_width(self):
        """整行候选的自然宽度（所有本页候选的总宽，含间距/分隔线）。"""
        return int(self.rows_box.get_preferred_size()[1].width)

    def _visible_budget(self):
        """`max_visible` 换算成视口宽度预算。

        只是“一次大约能看到几个候选”的宽度：本页候选数不超过它时返回 None（用屏幕上限即可），
        超过时返回前 `max_visible` 个候选的自然宽度之和。候选本身不会被这个预算裁掉。
        """
        count = max(1, int(self.max_visible))
        if not self.rows or len(self.rows) <= count:
            return None
        width = 0
        for row in self.rows[:count]:
            width += int(row["widget"].get_preferred_size()[1].width)
        return width + 2 * count

    def _fit_to_screen(self):
        """把面板宽度约束在屏幕内：只压缩文字，不减少候选。

        1. 先给文本标签一个字符上限（`max-width-chars` + 末尾省略号），单个超长候选撑不爆面板；
        2. 整页仍在宽度上限内就直接结束（默认横排、无滚动条）；
        3. 超宽时按实测宽度继续收缩字符预算，最低 `MIN_TEXT_CHARS`；
        4. 到最低字数仍超宽，就把内容放进固定宽度的单行横向视口并显示横向滚动条：
           本页候选（序号、完整 ID、原文）全部保留，高亮项自动滚进可见区域。
        视口宽度 = min(本页自然宽度, 屏幕可用宽度, `max_visible` 宽度预算)：`max_visible` 只影响
        这个宽度，不参与上面的文字压缩、也不裁剪候选或改写页大小。
        """
        # 上一页为了保住自然宽度给 rows_box/scroller 设过最小宽度；GTK 会把它计入
        # 下一轮 `get_preferred_size`，短页因此保留旧滚动范围（0.2.8 的短页线索）。
        # 测量前先撤掉请求，按本页真实内容重新算。
        self.rows_box.set_size_request(-1, -1)
        self.scroller.set_size_request(-1, -1)
        limit = self._width_limit()
        approx = self._approx_char_px()
        ascii_cap = max(8, int((limit * 0.6) / approx))
        self.hints.set_max_width_chars(ascii_cap)
        self.status.set_max_width_chars(max(6, int(ascii_cap * 0.6)))
        self.page_label.set_max_width_chars(8)
        # 内容可用宽度；滚动条与边框的占位先扣掉，面板窗口才不会顶到屏幕边。
        content_cap = max(240, limit - SCROLLBAR_RESERVE_PX)
        self.dropped = []  # 兼容旧字段：按宽度丢弃候选已取消，恒为空。
        chars = ascii_cap
        self._apply_char_budget(chars)
        for _ in range(8):
            width = self._content_natural_width()
            if width <= content_cap or chars <= MIN_TEXT_CHARS:
                break
            chars = max(MIN_TEXT_CHARS, int(chars * content_cap / max(1, width)) - 1)
            self._apply_char_budget(chars)
        self.content_natural_width = self._content_natural_width()
        # 视口宽度上限：屏幕约束是硬限制；`max_visible` 只作为宽度预算（一次大约看几个候选），
        # 本页多出来的候选留在同一行里靠横向滚动查看，绝不裁剪。
        viewport_cap = content_cap
        budget = self._visible_budget()
        if budget is not None:
            viewport_cap = max(MIN_VIEWPORT_PX, min(content_cap, budget))
        self.viewport_cap = viewport_cap
        # 视口宽度：内容放得下就按内容宽度，否则固定在上限，本页其余候选靠横向滚动查看。
        target = min(self.content_natural_width, viewport_cap)
        self.scroller.set_size_request(target, -1)
        # 行必须保住自己的自然宽度（作为最小宽度），否则 GtkViewport 会把行压到视口宽度、
        # 让候选被挤扁而不是出现滚动条。
        self.rows_box.set_size_request(self.content_natural_width if self.content_natural_width > target else -1, -1)
        # 头部/提示行也按视口宽度收窄，面板不会因为一行提示文字被撑宽、把视口留在左边一小块。
        meta_cap = max(8, int((max(target, MIN_VIEWPORT_PX) * 0.92) / approx))
        self.hints.set_max_width_chars(meta_cap)
        self.status.set_max_width_chars(max(6, int(meta_cap * 0.55)))
        self.page_label.set_max_width_chars(8)
        self.content_width = self._preferred_width()

    def _viewport_signature(self):
        """视口实际几何 + 滚动范围的指纹；用户自己滚动不会改变它。"""
        adj = self._hadjustment()
        return (self.scroller.get_allocated_width(), self.scroller.get_allocated_height(),
                int(adj.get_lower()) if adj else 0,
                int(adj.get_page_size()) if adj else 0,
                int(adj.get_upper()) if adj else 0,
                len(self.rows))

    def _on_layout_changed(self, *_args):
        """控件拿到新的分配后，排一次“布局稳定”后的核对。

        只对真正改变了几何/滚动范围的事件重排：用户拖动滚动条也会触发
        `size-allocate`，但页大小与滚动范围不变，不能把视口拽回高亮项。
        render 还没完成第一次真实分配核对时（serial 不等）也必须重排。
        """
        if not self.window.get_visible():
            return
        signature = self._viewport_signature()
        changed = signature != self._layout_signature
        self._layout_signature = signature
        if changed or self._settled_serial != self._reveal_serial:
            self._schedule_reveal()

    def _schedule_reveal(self):
        """合并同一轮布局里的多次请求，只留一个空闲回调。"""
        if self._reveal_scheduled:
            return
        self._reveal_scheduled = True
        GLib.idle_add(self._after_layout)

    def _after_layout(self):
        """GTK 完成本轮尺寸协商后再收敛滚动范围、把高亮送进视野。

        首次 render 的空闲回调可能早于 `size-allocate`：那时新候选只有 1px 占位，
        `reveal()` 返回 None（“还没布局”），不移动视口；等真正的分配信号到了再排一次。
        这里不做固定等待——只认 GTK 的实际分配结果。
        """
        self._reveal_scheduled = False
        if self.window.get_visible():
            self._clamp_scroll()
            revealed = self._reveal_selected()
            if revealed is not None:
                # 只有拿到真实分配并核对过，才算这次 render 的布局稳定了。
                self._settled_serial = self._reveal_serial
        self._report()
        return False

    # ---------------------------------------------------------------- 滚动视口
    def _hadjustment(self):
        try:
            return self.scroller.get_hadjustment()
        except Exception:  # noqa: BLE001 未实现/未附加时没有调整对象
            return None

    def _scrollbar_visible(self):
        adj = self._hadjustment()
        if adj is None:
            return False
        page = adj.get_page_size()
        return page > 0 and (adj.get_upper() - adj.get_lower()) > page + 0.5

    def scroll_by(self, delta):
        """按像素横向滚动视口，返回滚动后的位置（供检查与平台复用）。"""
        adj = self._hadjustment()
        if adj is None:
            return 0
        span = max(adj.get_lower(), adj.get_upper() - adj.get_page_size())
        value = max(adj.get_lower(), min(adj.get_value() + float(delta), span))
        adj.set_value(value)
        return int(adj.get_value())

    def _clamp_scroll(self):
        """把滚动位置收敛到当前有效范围：短页/窄视口不能让旧值停在空白处。"""
        adj = self._hadjustment()
        if adj is None or adj.get_page_size() <= 0:
            return 0
        lower = adj.get_lower()
        span = max(lower, adj.get_upper() - adj.get_page_size())
        value = adj.get_value()
        if value > span:
            adj.set_value(span)
        elif value < lower:
            adj.set_value(lower)
        return int(adj.get_value())

    def reveal(self, index):
        """把本页第 index 个候选滚进可见区域。

        返回 True=滚动了，False=已经完整可见（或不需要滚动），
        None=GTK 还没给这一行真正的分配（新行在 `size-allocate` 前只有 1px 占位）。
        `None` 绝不能被当成“已在视野内”：按 1px 占位计算会把视口误滚到页首，
        正是 0.2.8 里选中第 4 项却停在 scroll=0 的原因；调用方应等分配信号后重试。
        """
        if not 0 <= index < len(self.rows):
            return False
        adj = self._hadjustment()
        widget = self.rows[index]["widget"]
        if adj is None or not widget.get_mapped():
            return None
        page = adj.get_page_size()
        allocation = widget.get_allocation()
        if page <= 0 or allocation.width <= 1 or allocation.height <= 1:
            return None
        left, right = allocation.x, allocation.x + allocation.width
        value = adj.get_value()
        target = value
        if left < value:
            target = left
        elif right > value + page:
            target = right - page
        span = max(adj.get_lower(), adj.get_upper() - page)
        target = max(adj.get_lower(), min(target, span))
        if abs(target - value) < 1:
            return False
        adj.set_value(target)
        return True

    def _reveal_selected(self):
        for index, row in enumerate(self.rows):
            if row.get("selected"):
                return self.reveal(index)
        # 高亮不在本页（平台换了页/暂未给出）时从页首开始看，不能让视口停在上一页的滚动位置。
        return self.reveal(0) if self.rows else False

    def _place(self):
        """放在光标正下方（下方放不下就放上方）；不知道光标位置时放在左上角。

        窗口四周有 self.shadow 像素的透明阴影边距，定位时把卡片本身对齐光标。
        """
        # The size this content needs: get_size() still holds the previous page's.
        natural = self.window.get_preferred_size()[1]
        width, height = natural.width, natural.height
        screen_w, screen_h = self._screen()
        rect = (self.snapshot or {}).get("cursor_rect") or {}
        pad = self.shadow
        if rect.get("coordinate_space", "screen") == "screen" and "x" in rect and "y" in rect:
            x = int(rect["x"]) - pad
            below = int(rect["y"]) + int(rect.get("height", 0)) + 4 - pad
            above = int(rect["y"]) - 4 - height + pad
            y = below if below + height <= screen_h or above < 0 else above
        else:
            x = y = self.margin - pad
        x = max(-pad, min(x, screen_w - width + pad))
        y = max(-pad, min(y, screen_h - height + pad))
        self.window.move(x, y)

    def metrics(self):
        screen_w, screen_h = self._screen()
        adj = self._hadjustment()
        scrollable = self._scrollbar_visible()
        return {"layout": self.layout, "font_scale": round(self.font_scale, 3),
                "screen": [screen_w, screen_h], "width_limit": self._width_limit(),
                "content_width": self.content_width,
                "content_natural_width": getattr(self, "content_natural_width", 0),
                # max_visible 只体现为视口宽度预算；page_size/page_start 仍来自平台快照。
                "max_visible": int(self.max_visible),
                "viewport_cap": getattr(self, "viewport_cap", None),
                "page_start": int((self.snapshot or {}).get("page_start", 0)),
                "page_size": int((self.snapshot or {}).get("page_size", 0)),
                "visible": len(self.rows), "dropped_for_width": [],
                "ids": [row["id"] for row in self.rows],
                "in_view": [row["id"] for row in self.rows if self._row_in_view(row)],
                "scroll": {"value": int(adj.get_value()) if adj else 0,
                           "page_size": int(adj.get_page_size()) if adj else 0,
                           "upper": int(adj.get_upper()) if adj else 0,
                           "scrollable": scrollable,
                           "scrollbar_visible": scrollable}}

    # ---------------------------------------------------------------- 交互
    def _on_row_click(self, widget, event, candidate_id):
        if event.button == 1:
            self.select(candidate_id)
            return True
        return False

    def _on_badge_click(self, widget, event):
        if event.button == 1:
            self.toggle_mode()
            return True
        return False

    def _on_scroll(self, widget, event):
        direction = getattr(event, "direction", None)
        if direction == Gdk.ScrollDirection.UP or getattr(event, "delta_y", 0) < 0:
            self.page(-1)
        elif direction == Gdk.ScrollDirection.DOWN or getattr(event, "delta_y", 0) > 0:
            self.page(1)
        return True

    def select(self, candidate_id):
        if not self.client or not self.snapshot:
            return False
        accepted, fresh = self.client.act(self.snapshot, "select", candidate_id)
        if not accepted:
            self.render(fresh, "该候选已失效，已按最新状态刷新")
        _emit({"event": "select", "id": candidate_id, "accepted": bool(accepted),
               "revision": self.snapshot.get("revision"), "feedback": self.last_feedback})
        return bool(accepted)

    def page(self, delta):
        if not self.client or not self.snapshot:
            return False
        accepted, fresh = self.client.act(self.snapshot, "page", -1 if delta < 0 else 1)
        if accepted and fresh is not None:
            self.render(fresh)
        else:
            self.render(fresh if fresh is not None else self.snapshot, "已到边界，未翻页")
        _emit({"event": "page", "delta": delta, "accepted": bool(accepted)})
        return bool(accepted)

    def toggle_mode(self):
        if not self.client or not self.snapshot:
            return False
        target = "en" if self.snapshot.get("mode", "zh") == "zh" else "zh"
        accepted, fresh = self.client.act(self.snapshot, "mode", target)
        if fresh is not None:
            self.render(fresh)
        _emit({"event": "mode", "target": target, "accepted": bool(accepted)})
        return bool(accepted)

    # ---------------------------------------------------------------- 几何
    def geometry(self):
        if not self.window.get_visible():
            return None
        x, y = self.window.get_position()
        width, height = self.window.get_size()
        return {"x": x, "y": y, "w": width, "h": height}

    def _row_in_view(self, row):
        """候选是否完整落在横向视口的可见区域内（供检查与几何接口使用）。"""
        adj = self._hadjustment()
        widget = row["widget"]
        allocation = widget.get_allocation()
        # 尚未分配（1px 占位）不能算“可见”，否则会把布局前的瞬时状态当成结论。
        if allocation.width <= 1 or allocation.height <= 1:
            return False
        if adj is None or adj.get_page_size() <= 0:
            return True
        left, right = adj.get_value(), adj.get_value() + adj.get_page_size()
        return allocation.x >= left - 1 and allocation.x + allocation.width <= right + 1

    def row_geometry(self):
        out = []
        for row in self.rows:
            widget = row["widget"]
            if widget.get_window() is None:
                continue
            x, y = widget.translate_coordinates(self.window, 0, 0)
            ok, origin_x, origin_y = self.window.get_window().get_origin()
            allocation = widget.get_allocation()
            label = row["text_widget"]
            label_text = label.get_text()
            # 未受限的完整文本宽度：省略号是否生效要拿它和实际分配宽度比较。
            needed = label.create_pango_layout(label_text).get_pixel_size()[0] if label_text else 0
            # 只带候选原文（与旧版一致），不额外暴露显示文本，避免经 D-Bus 泄漏输入内容。
            out.append({"id": row["id"], "text": row["text"], "index": row["index"],
                        "x": origin_x + x, "y": origin_y + y,
                        "w": allocation.width, "h": allocation.height,
                        "text_w": label.get_allocation().width, "text_needed": needed,
                        "ellipsized": needed > label.get_allocation().width + 1,
                        "selected": bool(row.get("selected")),
                        "in_view": bool(self._row_in_view(row))})
        return out

    def _report(self):
        _emit({"event": "geometry", "panel": self.geometry(), "rows": self.row_geometry()})
        return False


def _shortcuts_from_env():
    from .config import defaults
    return defaults()["shortcuts"]


def _css(scale):
    base = BASE_FONT_PX * max(0.8, min(3.0, scale))
    # 辅助信息（状态/页码/序号/注释/提示）不跟着字号无限放大，否则提示行自己就能把面板撑出屏幕。
    meta = min(base * 0.75, 20)
    hint = min(base * 0.75, 18)
    return f"""
    .ime-panel {{ background-color: #f9f9f9; border: 1px solid #d5d5d5; }}
    .ime-panel.ime-translucent {{ background-color: transparent; border: none; }}
    .ime-card {{ background-color: #f9f9f9; padding: 4px 4px 4px 4px; }}
    .ime-translucent .ime-card {{ border: 1px solid rgba(0, 0, 0, 0.09); border-radius: 8px;
                                  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.13); }}
    .ime-card, .ime-card label {{ font-family: "Microsoft YaHei UI", "Noto Sans CJK SC",
                                  "Source Han Sans SC", sans-serif; }}
    .ime-pinyin {{ font-size: {meta:.0f}px; color: #5c5c5c; padding: 1px 8px 2px 8px; }}
    .ime-header {{ padding: 2px 6px 4px 6px; }}
    .ime-badge {{ font-size: {meta:.0f}px; font-weight: bold; color: #005fb8;
                  background-color: #e8f0fe; border-radius: 4px; padding: 0 6px; }}
    .ime-status {{ font-size: {meta:.0f}px; color: #5c5c5c; }}
    .ime-pager {{ padding: 0 0 0 4px; }}
    .ime-page {{ font-size: {meta:.0f}px; color: #8a8a8a; padding: 0 4px; }}
    .ime-page-button {{ font-size: {base:.0f}px; color: #5c5c5c; padding: 0 6px;
                        min-height: 0; min-width: 0; border-radius: 4px; border: none;
                        background: none; box-shadow: none; }}
    .ime-page-button:hover {{ background-color: rgba(0, 0, 0, 0.06); }}
    .ime-page-button:disabled {{ color: #c4c4c4; }}
    .ime-rowbox {{ padding: 0; }}
    .ime-row {{ border-radius: 4px; }}
    .ime-row:hover {{ background-color: rgba(0, 0, 0, 0.04); }}
    .ime-row-selected, .ime-row-selected:hover {{ background-color: rgba(0, 0, 0, 0.06); }}
    .ime-accent {{ background-color: #005fb8; border-radius: 2px; min-height: {base * 0.9:.0f}px; }}
    .ime-index {{ font-size: {meta:.0f}px; color: #7a7a7a; }}
    .ime-text {{ font-size: {base:.0f}px; color: #1b1b1b; }}
    .ime-annotation {{ font-size: {meta:.0f}px; color: #8a8a8a; }}
    .ime-hints {{ font-size: {hint:.0f}px; color: #8a8a8a; padding: 4px 8px 2px 8px; }}
    scrollbar {{ min-height: 4px; }}
    """


def main(argv=None):
    """独立运行候选面板：读取设置文件，订阅平台状态。"""
    import argparse

    from .bridge import Client
    from .config import Capabilities, load, panel_options

    parser = argparse.ArgumentParser(description="服务器输入法候选面板")
    parser.add_argument("--caps", help="引擎 capabilities JSON（缺省读取真实引擎）")
    parser.add_argument("--config", help="设置文件路径")
    args = parser.parse_args(argv)

    caps = _load_caps(args.caps)
    settings, errors, path = load(args.config, caps=caps)
    for error in errors:
        print(f"配置问题：{error['message']}", file=sys.stderr)
    panel = CandidatePanel(panel_options(settings), Client())
    _emit({"event": "ready", "config": str(path), "capabilities": caps.summary(),
           "panel": panel.geometry()})

    def on_state(snapshot):
        panel.render(snapshot)

    def on_removed(context_id):
        panel.render(None)
        _emit({"event": "context-removed", "context": context_id})

    client = panel.client
    client.subscribe(on_state, on_removed)
    for context_id in client.list_contexts():
        panel.render(client.get_state(context_id))
    _emit({"event": "subscribed", "contexts": client.list_contexts()})
    Gtk.main()
    return 0


def _load_caps(path):
    from .config import Capabilities
    if path:
        return Capabilities.from_file(path)
    try:
        from server_ime_engine import Engine

        with Engine() as engine:
            return Capabilities.from_engine(engine)
    except Exception:
        return Capabilities()


if __name__ == "__main__":
    raise SystemExit(main())
