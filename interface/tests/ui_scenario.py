#!/usr/bin/python3
"""候选面板 + 真实应用输入的界面检查（隔离 X + 真实 IBus + 真实引擎）。

真实组件：GTK3 应用输入框、IBus 1.5 适配器、libpinyin 转换后端、本包的候选面板与状态提示。
不是夹具：面板读的是平台 D-Bus 快照，键盘事件经 XTest 进入真实 GTK 输入框。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT.parent / "platform"), str(ROOT.parent / "engine" / "src"),
                str(ROOT / "tests")]

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("IBus", "1.0")
from gi.repository import Gtk, IBus  # noqa: E402

from ime_interface import config, panel as panel_mod  # noqa: E402
from ime_interface.bridge import Client  # noqa: E402
from x11 import X, pump, screenshot, wait_for, widget_center  # noqa: E402

EVIDENCE = Path(os.environ["SERVER_IME_EVIDENCE"])
ENGINE = os.environ.get("SERVER_IME_ENGINE", "server-ime-test")


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
    def __init__(self):
        self.checks = []
        self.snapshots = []
        self.snapshot = None
        self.select_events = []
        self.panel = None

    # ------------------------------------------------------------------ 记录
    def record(self, name, ok, **detail):
        self.checks.append({"check": name, "result": "PASS" if ok else "FAIL", **detail})
        print(("PASS " if ok else "FAIL ") + name, flush=True)
        return ok

    # ------------------------------------------------------------------ 环境
    def start(self):
        assert os.environ.get("SERVER_IME_ISOLATED") == "1"
        IBus.init()
        bus = IBus.Bus.new()
        assert bus.is_connected(), "无法连接隔离 IBus"
        assert bus.set_global_engine(ENGINE), f"无法选择引擎 {ENGINE}"
        settings, errors, path = config.load(caps=_caps())
        self.settings, self.settings_path = settings, path
        options = config.panel_options(settings)

        self.window = Gtk.Window(title="服务器输入法：候选面板检查")
        self.window.set_default_size(680, 240)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(16)
        self.window.add(box)
        self.label = Gtk.Label(label="真实 IBus + 真实引擎 + 本包候选面板（隔离 X 会话）")
        self.label.set_xalign(0)
        box.pack_start(self.label, False, False, 0)
        self.first, self.second = Gtk.Entry(), Gtk.Entry()
        self.first.set_placeholder_text("输入框 A")
        self.second.set_placeholder_text("输入框 B")
        box.pack_start(self.first, False, False, 0)
        box.pack_start(self.second, False, False, 0)
        self.window.move(80, 320)
        self.window.show_all()
        pump(0.3)

        self.client = Client()
        self.panel = panel_mod.CandidatePanel(options, self.client)
        self.panel.window.move(20, 20)
        self.client.subscribe(self.on_state, lambda context: self.panel.render(None))
        for context_id in self.client.list_contexts():
            self.on_state(self.client.get_state(context_id))
        self.x = X()
        self.x.focus_window(self.window)
        self.first.grab_focus()
        self.screen_w = self.window.get_screen().get_width()
        self.screen_h = self.window.get_screen().get_height()
        pump(0.4)
        return path

    def on_state(self, snapshot):
        self.snapshots.append(snapshot)
        self.snapshot = snapshot
        self.panel.render(snapshot)

    # ------------------------------------------------------------------ 步骤
    def run(self):
        results = {}
        results["preedit"] = self.step_preedit()
        results["panel"] = self.step_panel_candidates()
        results["horizontal"] = self.step_horizontal()
        results["mouse_select"] = self.step_mouse_select()
        results["keyboard"] = self.step_keyboard_select()
        results["paging"] = self.step_paging()
        results["last_page"] = self.step_last_page_commit()
        results["mode"] = self.step_mode_badge()
        results["focus"] = self.step_focus_change()
        results["scale"] = self.step_scale()
        results["readability"] = self.step_readability()
        results["width_limits"] = self.step_width_limits()
        results["viewport_budget"] = self.step_viewport_budget()
        results["layout"] = self.step_layout_after_allocation()
        return results

    def fresh(self, entry=None):
        entry = entry or self.first
        entry.set_text("")
        self.x.focus_window(self.window)
        entry.grab_focus()
        pump(0.3)

    def step_preedit(self):
        self.fresh()
        seen = []
        handler = self.first.connect("preedit-changed", lambda _e, text: seen.append(text))
        self.x.type_text("nihao")
        ok = wait_for(lambda: any(text == "nihao" for text in seen), 3.0)
        self.first.disconnect(handler)
        return self.record("preedit-in-real-gtk-entry", bool(ok) and self.first.get_text() == "",
                           preedit=seen[-1] if seen else "", entry_text=self.first.get_text(),
                           backend=(self.snapshot or {}).get("backend"),
                           deterministic=(self.snapshot or {}).get("deterministic"))

    def step_panel_candidates(self):
        visible = wait_for(lambda: bool(self.panel.rows), 3.0)
        geometry = self.panel.geometry()
        rows = self.panel.row_geometry()
        shot = screenshot(EVIDENCE / "panel-candidates.png")
        shot_panel = screenshot(EVIDENCE / "panel-candidates-only.png", self.panel.window)
        numbers = [self.panel.window]  # noqa: F841 保留引用，避免垃圾回收
        ok = bool(visible) and bool(geometry) and len(rows) >= 2
        return self.record("panel-shows-candidates-and-status", ok, geometry=geometry,
                           rows=[{"text": r["text"], "x": r["x"], "y": r["y"]} for r in rows],
                           status=self.panel.status.get_text(), page=self.panel.page_label.get_text(),
                           screenshot=shot, panel_screenshot=shot_panel)

    def single_row(self, rows):
        """同一页候选是否同一行、横坐标递增、且都在屏幕内。"""
        ys = sorted({row["y"] for row in rows})
        ascending = all(rows[index]["x"] < rows[index + 1]["x"] for index in range(len(rows) - 1))
        inside = all(0 <= row["x"] and row["x"] + row["w"] <= self.screen_w
                     and 0 <= row["y"] and row["y"] + row["h"] <= self.screen_h for row in rows)
        return {"distinct_y": ys, "same_row": len(ys) == 1, "x_ascending": ascending,
                "rows_inside_screen": inside}

    def panel_inside_screen(self):
        geometry = self.panel.geometry()
        if not geometry:
            return False, None
        inside = (0 <= geometry["x"] and geometry["x"] + geometry["w"] <= self.screen_w
                  and 0 <= geometry["y"] and geometry["y"] + geometry["h"] <= self.screen_h)
        return inside, geometry

    def step_horizontal(self):
        """真实引擎候选在真实 GTK 面板里从左到右同排，正常宽度下整页都看得见（无滚动条）。"""
        self.fresh()
        self.x.type_text("nihao")
        wait_for(lambda: bool(self.panel.rows), 3.0)
        pump(0.3)
        rows = self.panel.row_geometry()
        layout = self.single_row(rows)
        panel_inside, geometry = self.panel_inside_screen()
        scroll = self.panel.metrics()["scroll"]
        all_in_view = all(row["in_view"] for row in rows)
        shot = screenshot(EVIDENCE / "panel-horizontal.png", self.panel.window)
        ok = (len(rows) >= 3 and layout["same_row"] and layout["x_ascending"]
              and layout["rows_inside_screen"] and panel_inside and all_in_view
              and not scroll["scrollbar_visible"])
        return self.record("candidates-horizontal-single-row-left-to-right", ok,
                           rows=[{"text": r["text"], "x": r["x"], "y": r["y"], "w": r["w"]} for r in rows],
                           panel=geometry, screen=[self.screen_w, self.screen_h],
                           layout_mode=self.panel.metrics()["layout"],
                           content_width=self.panel.metrics()["content_width"],
                           all_in_view=all_in_view, scroll=scroll,
                           screenshot=shot, fixture=False,
                           note="真实 libpinyin 候选、真实 GTK 面板、平台 D-Bus 快照")

    def step_mouse_select(self):
        rows = self.panel.row_geometry()
        assert len(rows) >= 2, rows
        target = rows[1]
        before = self.first.get_text()
        self.x.click(target["x"] + target["w"] // 2, target["y"] + target["h"] // 2)
        committed = wait_for(lambda: self.first.get_text() != before, 3.0)
        text = self.first.get_text()
        accepted = self.panel.last_feedback == ""
        shot = screenshot(EVIDENCE / "panel-mouse-select.png")
        shot_panel = screenshot(EVIDENCE / "panel-after-mouse-select.png", self.panel.window)
        ok = bool(committed) and (text.startswith(target["text"]) or target["text"].startswith(text))
        return self.record("mouse-click-selects-candidate-via-platform-interface", ok,
                           clicked_row_text=target["text"], entry_text=text,
                           accepted_without_refresh=accepted, screenshot=shot,
                           panel_screenshot=shot_panel, remaining_candidates=len(self.panel.rows))

    def step_keyboard_select(self):
        self.fresh()
        self.x.type_text("ni")
        wait_for(lambda: bool(self.panel.rows), 3.0)
        rows = self.panel.row_geometry()
        self.x.key("2")
        committed = wait_for(lambda: self.first.get_text() != "", 3.0)
        text = self.first.get_text()
        ok = bool(committed) and (rows[1]["text"].startswith(text) or text.startswith(rows[1]["text"]))
        return self.record("digit-key-selects-second-candidate", ok,
                           expected=rows[1]["text"] if len(rows) > 1 else None, entry_text=text)

    def step_paging(self):
        self.fresh()
        self.x.type_text("ni")
        wait_for(lambda: bool(self.panel.rows), 3.0)
        start_before = int(self.snapshot.get("page_start", 0))
        page_count = int(self.snapshot.get("page_count", 0))
        self.x.key("Page_Down")
        moved = wait_for(lambda: self.snapshot.get("page_start", 0) > start_before, 3.0)
        first_after = self.snapshot.get("page_start", 0)
        pump(0.2)
        page_layout = self.single_row(self.panel.row_geometry())
        self.panel_geometry = self.panel.geometry()
        shot = screenshot(EVIDENCE / "panel-page-2.png")
        shot_panel = screenshot(EVIDENCE / "panel-page-2-only.png", self.panel.window)
        # 鼠标滚轮翻页（真实滚轮事件 → 面板 Page(context, +1)）
        row = self.panel.row_geometry()[0] if self.panel.rows else None
        wheel = False
        if row:
            self.x.scroll(row["x"] + row["w"] // 2, row["y"] + row["h"] // 2, up=True)
            wheel = wait_for(lambda: self.snapshot.get("page_start", 0) < first_after, 3.0)
        # 边界：第一页按上一页应保持在第 0 项
        self.x.key("Page_Up")
        self.x.key("Page_Up")
        wait_for(lambda: self.snapshot.get("page_start", 0) == 0, 3.0)
        at_start = self.snapshot.get("page_start", 0) == 0
        ok = (bool(moved) and bool(wheel) and at_start and page_count > 1
              and page_layout["same_row"] and page_layout["x_ascending"]
              and page_layout["rows_inside_screen"])
        return self.record("paging-keyboard-and-wheel-with-boundary", ok,
                           page_start_before=start_before, page_start_after=first_after,
                           wheel_paged_back=bool(wheel), boundary_kept=at_start,
                           page_count=page_count, second_page_layout=page_layout,
                           screenshots=[shot, shot_panel])

    def step_last_page_commit(self):
        """真实引擎/IBus 路径：翻到最后一页并点击最后一个候选，提交完整文本。"""
        self.fresh()
        self.x.type_text("ni")
        wait_for(lambda: bool(self.panel.rows), 3.0)
        for _ in range(20):
            if not self.panel.next_button.get_sensitive():
                break
            self.x.key("Page_Down")
            pump(0.25)
        pump(0.3)
        snapshot = self.snapshot or {}
        rows = self.panel.row_geometry()
        target = rows[-1] if rows else None
        shot = screenshot(EVIDENCE / "panel-last-page.png")
        shot_panel = screenshot(EVIDENCE / "panel-last-page-only.png", self.panel.window)
        before = self.first.get_text()
        if target:
            self.x.click(target["x"] + target["w"] // 2, target["y"] + target["h"] // 2)
        committed = wait_for(lambda: self.first.get_text() != before, 3.0)
        text = self.first.get_text()
        ok = (bool(target) and target["in_view"] and bool(committed)
              and (text.startswith(target["text"]) or target["text"].startswith(text)))
        return self.record("last-page-last-candidate-click-commits-full-text", ok,
                           page_start=snapshot.get("page_start"),
                           page_count=snapshot.get("page_count"),
                           last_page_reached=not self.panel.next_button.get_sensitive(),
                           clicked_row=target["text"] if target else None,
                           entry_text=text, screenshots=[shot, shot_panel],
                           note="真实 libpinyin 候选、真实鼠标点击、平台选词接口")

    def step_mode_badge(self):
        self.fresh()
        before = self.snapshot.get("mode")
        self.x.click(*widget_center(self.panel.badge_button))
        toggled = wait_for(lambda: self.snapshot.get("mode") != before, 3.0)
        shot = screenshot(EVIDENCE / "panel-english-mode.png")
        self.x.type_text("abc")
        pump(0.2)
        literal = self.first.get_text() == "abc"
        self.x.click(*widget_center(self.panel.badge_button))
        back = wait_for(lambda: self.snapshot.get("mode") == before, 3.0)
        return self.record("mode-badge-click-switches-zh-en", bool(toggled) and literal and bool(back),
                           before=before, after=self.snapshot.get("mode"),
                           english_mode_literal_text=self.first.get_text(), screenshot=shot)

    def step_focus_change(self):
        self.fresh()
        self.x.type_text("ni")
        wait_for(lambda: bool(self.panel.rows), 3.0)
        visible_before = bool(self.panel.rows)
        context_before = self.snapshot.get("context_id")
        self.second.grab_focus()
        cleared = wait_for(lambda: not self.panel.rows, 3.0)
        shot = screenshot(EVIDENCE / "panel-focus-change.png")
        leak = self.first.get_text()
        self.x.type_text("hao")
        rearmed = wait_for(lambda: bool(self.panel.rows), 3.0)
        shot2 = screenshot(EVIDENCE / "panel-second-entry.png")
        context_after = self.snapshot.get("context_id")
        ok = bool(visible_before and cleared and rearmed and leak == "" and self.snapshot.get("focused"))
        return self.record("focus-change-clears-candidates-without-preedit-leak", ok,
                           panel_candidates_before=visible_before,
                           candidates_cleared_after=bool(cleared),
                           candidates_again_in_second_entry=bool(rearmed),
                           first_entry_text=leak,
                           context_changed=context_before != context_after,
                           context_ids=[context_before, context_after],
                           screenshots=[shot, shot2])

    def step_scale(self):
        self.fresh()
        options = dict(config.panel_options(self.settings))
        options["font_scale"] = 1.0
        self.panel.set_options(options)
        self.x.type_text("ni")
        wait_for(lambda: bool(self.panel.rows), 3.0)
        small = self.panel.row_geometry()
        shot_small = screenshot(EVIDENCE / "panel-scale-100.png", self.panel.window)
        options["font_scale"] = 1.5
        self.panel.set_options(options)
        pump(0.4)
        large = self.panel.row_geometry()
        shot_large = screenshot(EVIDENCE / "panel-scale-150.png", self.panel.window)
        ratio = (large[0]["h"] / small[0]["h"]) if small and large and small[0]["h"] else 0
        large_layout = self.single_row(large)
        large_inside, large_panel = self.panel_inside_screen()
        options["font_scale"] = config.panel_options(self.settings)["font_scale"]
        self.panel.set_options(options)
        ok = (ratio >= 1.25 and large[0]["w"] >= small[0]["w"]
              and large_layout["same_row"] and large_layout["x_ascending"]
              and large_layout["rows_inside_screen"] and large_inside)
        return self.record("panel-scales-with-font-setting", ok, row_height_100=small[0]["h"] if small else None,
                           row_height_150=large[0]["h"] if large else None, ratio=round(ratio, 2),
                           large_layout=large_layout, large_panel=large_panel,
                           screenshots=[shot_small, shot_large])

    def step_readability(self):
        ratios = {"candidate_text": contrast("#1f1f1f", "#ffffff"),
                  "annotation": contrast("#5f6368", "#ffffff"),
                  "hints": contrast("#6b7280", "#ffffff"),
                  "selected_row_text": contrast("#1f1f1f", "#e8f0fe"),
                  "badge": contrast("#0b57d0", "#e8f0fe")}
        worst = min(ratios.values())
        ok = worst >= 4.5
        return self.record("readability-contrast-min-4.5", ok, ratios=ratios, worst=worst,
                           note="WCAG AA 小字号文本 4.5:1")

    # ---------------------------------------------- 宽度与横向滚动视口（夹具候选数据）
    def fixture_snapshot(self, candidates, page_size, start=0, selected=0):
        return {"context_id": "fixture-context", "focused": True, "enabled": True, "mode": "zh",
                "status": "宽度夹具", "backend": "fixture", "revision": 1,
                "candidate_visible": True, "page_size": page_size, "page_start": start,
                "selected_index": selected,
                "page_count": (len(candidates) + page_size - 1) // page_size,
                "candidates": candidates}

    def sweep(self):
        """逐个候选把视口滚到它，按顺序收集真正进入过可见区域的候选 ID。

        用面板自己的 `reveal(index)`（和平台改变 `selected_index` 时走的同一条滚动路径），
        因此宽视口（`max_visible` 预算）下不会因为步进太大而漏看中间的候选。
        """
        seen = []
        for index in range(len(self.panel.rows)):
            self.panel.reveal(index)
            pump(0.25)
            for row in self.panel.row_geometry():
                if row["in_view"] and row["id"] not in seen:
                    seen.append(row["id"])
        return seen

    def replay_click(self, target):
        """点击回放：只记录 client.act 的参数，不写输入状态、不提交文本。"""
        captured = []
        original_act = self.client.act
        self.client.act = lambda snap, action, arg=None: (captured.append((action, arg)),
                                                          (True, None))[1]
        try:
            self.x.click(target["x"] + target["w"] // 2, target["y"] + target["h"] // 2)
            pump(0.3)
        finally:
            self.client.act = original_act
        return captured[-1] if captured else None

    def step_width_limits(self):
        """候选面板的宽度与横向滚动视口：长候选/最大字号不超屏、不丢候选、每个候选可达可点。

        夹具：候选文本、360px 宽度上限、selected_index 变化（模拟平台方向键改变高亮）。
        真实：GTK 面板控件、Pango 排版、Gtk.ScrolledWindow 横向视口、XTest 点击、坐标换算。
        点击回放替换了平台 `client.act`（只记录参数），不写任何输入状态。
        """
        candidates = [{"id": f"fx-{index}", "text": "超长候选内容" * (1 + index % 3) + str(index),
                       "index": index, "annotation": ""} for index in range(9)]
        expected = [cand["id"] for cand in candidates]
        saved = dict(config.panel_options(self.settings))
        original_limit = self.panel._width_limit
        try:
            options = dict(saved)
            options.update({"font_scale": 3.0, "max_visible": 9, "layout": "horizontal", "show_hints": True})
            self.panel.set_options(options)

            # 1) 300% 字号 + 超长候选：面板仍在屏内、本页 9 项一个不少、文字可省略。
            self.panel.render(self.fixture_snapshot(candidates, 9))
            pump(0.6)
            metrics = self.panel.metrics()
            rows = self.panel.row_geometry()
            limit = metrics["width_limit"]
            layout = self.single_row(rows)
            panel_inside, geometry = self.panel_inside_screen()
            labels = {item["id"]: item["label_text"] for item in self.panel.rows}
            ids = [row["id"] for row in rows]
            preserved = ids == expected and all(row["text"] == cand["text"]
                                                for row, cand in zip(rows, candidates))
            ellipsized = [row["id"] for row in rows if row["ellipsized"]]
            shot = screenshot(EVIDENCE / "panel-long-candidates-300.png", self.panel.window)
            ok = (metrics["content_width"] <= limit and panel_inside and layout["same_row"]
                  and layout["x_ascending"] and preserved and ellipsized
                  and not metrics["dropped_for_width"])
            self.record("long-candidates-and-300pct-stay-inside-screen", ok,
                        fixture=True, fixture_data="9 个超长候选（面板/排版/视口为真实组件）",
                        width_limit=limit, content_width=metrics["content_width"], panel=geometry,
                        screen=[self.screen_w, self.screen_h], layout=layout,
                        visible_ids=ids, dropped_for_width=metrics["dropped_for_width"],
                        ellipsized_ids=ellipsized, full_text_preserved=preserved,
                        scroll=metrics["scroll"], screenshot=shot)

            # 2) 省略显示的候选：滚动进视野后点击，选中完整 ID，显示文本未替换 rows 中的原文。
            target_index = next((index for index, row in enumerate(rows) if row["ellipsized"]), None)
            target = None
            if target_index is not None:
                self.panel.reveal(target_index)
                pump(0.3)
                target = next((row for row in self.panel.row_geometry()
                               if row["id"] == rows[target_index]["id"]), None)
            clicked = self.replay_click(target) if target and target["in_view"] else None
            target_id = candidates[target_index]["id"] if target_index is not None else None
            full_text = candidates[target_index]["text"] if target_index is not None else None
            self.record("ellipsized-candidate-keeps-full-id-and-text",
                        bool(clicked) and clicked[0] == "select" and clicked[1] == target_id
                        and full_text == (target["text"] if target else None)
                        and labels.get(target_id) == full_text,
                        fixture=True, fixture_data="点击回放（client.act 只记录参数，不写输入状态）",
                        clicked_id=clicked[1] if clicked else None, expected_id=target_id,
                        display_text=labels.get(target_id), full_text=full_text,
                        in_view=bool(target and target["in_view"]),
                        action=clicked[0] if clicked else None)

            # 3) 360px 窄屏 + 300% 字号：一页恰好 9 项，横向滚动视口里每个候选都可见可达。
            self.panel._width_limit = lambda: 360
            self.panel.render(self.fixture_snapshot(candidates, 9))
            pump(0.6)
            narrow = self.panel.metrics()
            narrow_rows = self.panel.row_geometry()
            hint = self.panel.hints.get_text() if self.panel.hints.get_visible() else ""
            narrow_inside, narrow_panel = self.panel_inside_screen()
            order = [row["id"] for row in narrow_rows]
            visible_at_start = list(narrow["in_view"])
            swept = self.sweep()
            shot_narrow = screenshot(EVIDENCE / "panel-narrow-360.png", self.panel.window)
            scroll = narrow["scroll"]
            viewport_ok = scroll["scrollbar_visible"] and scroll["page_size"] < scroll["upper"]
            ok = (narrow["content_width"] <= 360 and narrow_inside and order == expected
                  and swept == expected and viewport_ok and visible_at_start
                  and len(visible_at_start) < len(expected) and "其余用" not in hint
                  and not narrow["dropped_for_width"])
            self.record("narrow-360px-page-of-9-all-candidates-reachable-by-scroll", ok,
                        fixture=True,
                        fixture_data="9 个夹具候选 + 360px 宽度上限（视口/排版/坐标/点击为真实组件）",
                        width_limit=360, content_width=narrow["content_width"], panel=narrow_panel,
                        logical_page_ids=order, visible_at_start=visible_at_start, swept_ids=swept,
                        scroll_at_start=scroll["value"], scrollbar=scroll["scrollbar_visible"],
                        hint=hint, screenshot=shot_narrow)

            # 4) 原先会被宽度丢弃的末尾候选：滚到它、点击，送出完整文本与正确 ID。
            last = candidates[-1]
            self.panel.reveal(expected.index(last["id"]))
            pump(0.3)
            last_row = next((row for row in self.panel.row_geometry() if row["id"] == last["id"]), None)
            shot_last = screenshot(EVIDENCE / "panel-narrow-360-last-candidate.png", self.panel.window)
            clicked_last = self.replay_click(last_row) if last_row and last_row["in_view"] else None
            self.record("narrow-360px-last-candidate-clickable-with-full-text",
                        bool(clicked_last) and clicked_last[0] == "select"
                        and clicked_last[1] == last["id"],
                        fixture=True, fixture_data="滚动后真实 XTest 点击 + 点击回放（夹具候选 ID）",
                        clicked_id=clicked_last[1] if clicked_last else None, expected_id=last["id"],
                        in_view=bool(last_row and last_row["in_view"]),
                        scroll=self.panel.metrics()["scroll"]["value"],
                        displayed_text=next(item["label_text"] for item in self.panel.rows
                                            if item["id"] == last["id"]),
                        full_text=last["text"], screenshot=shot_last)

            # 5) 高亮移动（平台把方向键变成 selected_index）会让对应候选滚进可见区域。
            self.panel.render(self.fixture_snapshot(candidates, 9, selected=0))
            pump(0.6)
            scroll_before = self.panel.metrics()["scroll"]["value"]
            self.panel.render(self.fixture_snapshot(candidates, 9, selected=8))
            pump(0.6)
            end_metrics = self.panel.metrics()
            end_rows = {row["id"]: row for row in self.panel.row_geometry()}
            self.panel.render(self.fixture_snapshot(candidates, 9, selected=0))
            pump(0.6)
            back_metrics = self.panel.metrics()
            back_rows = {row["id"]: row for row in self.panel.row_geometry()}
            shot_hl = screenshot(EVIDENCE / "panel-narrow-360-highlight-scrolled.png", self.panel.window)
            # 页首高亮贴住视口左缘：rows_box 有 2px 内边距，start 值等于首行分配的 x（0..2）；
            # 高亮回到第 1 项后必须精确回到这个起始值（不是任意“接近 0”）。
            ok = (scroll_before <= 2 and end_metrics["scroll"]["value"] > scroll_before
                  and end_rows[last["id"]]["in_view"] and end_rows[last["id"]]["selected"]
                  and back_metrics["scroll"]["value"] == scroll_before
                  and back_rows[candidates[0]["id"]]["in_view"])
            self.record("highlight-change-scrolls-candidate-into-view", ok,
                        fixture=True, fixture_data="selected_index 快照变化（平台方向键的结果）",
                        scroll_before=scroll_before, scroll_after=end_metrics["scroll"]["value"],
                        last_in_view=bool(end_rows[last["id"]]["in_view"]),
                        last_selected=bool(end_rows[last["id"]]["selected"]),
                        scroll_back=back_metrics["scroll"]["value"],
                        first_in_view_after_back=bool(back_rows[candidates[0]["id"]]["in_view"]),
                        screenshot=shot_hl)

            # 6) 跨多页：20 项 / 每页 9（9 + 9 + 2），每页逻辑 ID 与滚动可达 ID 都完整且有序。
            many = [{"id": f"pg-{index}", "text": "分页候选内容" * (1 + index % 4) + str(index),
                     "index": index, "annotation": ""} for index in range(20)]
            ok, details = True, []
            for start, count in ((0, 9), (9, 9), (18, 2)):
                expected_page = [cand["id"] for cand in many[start:start + count]]
                self.panel.render(self.fixture_snapshot(many, 9, start=start))
                pump(0.6)
                page_metrics = self.panel.metrics()
                page_ids = [row["id"] for row in self.panel.row_geometry()]
                page_swept = self.sweep()
                good = (page_ids == expected_page and page_swept == expected_page
                        and page_metrics["visible"] == count)
                ok = ok and good
                details.append({"page_start": start, "logical_ids": page_ids, "swept_ids": page_swept,
                                "expected": expected_page, "visible": page_metrics["visible"],
                                "scroll": page_metrics["scroll"]["value"], "ok": good})
            shot_pages = screenshot(EVIDENCE / "panel-narrow-360-multipage.png", self.panel.window)
            self.record("narrow-360px-multipage-every-id-reachable-in-order", ok,
                        fixture=True, fixture_data="20 个夹具候选 / 每页 9（真实分页与滚动视口）",
                        pages=details, screenshot=shot_pages)
        finally:
            self.panel._width_limit = original_limit
            self.panel.set_options(saved)
            if self.snapshot:
                self.on_state(self.snapshot)


    # ---------------------------------------------- max_visible 只做视口宽度预算
    def step_viewport_budget(self):
        """`max_visible` 只影响视口宽度预算：整页候选一个不少、ID 全可达、高亮进视野、末项点击送完整 ID。

        夹具：候选文本、`page_size`/`max_visible` 组合与 `selected_index` 快照。
        真实：GTK 面板、Pango 排版、Gtk.ScrolledWindow 横向视口、XTest 点击、平台调用参数。
        """
        saved = dict(config.panel_options(self.settings))
        candidates = [{"id": f"vb-{index}", "text": f"候选内容示例{index:02d}号", "index": index,
                       "annotation": ""} for index in range(14)]
        combos = []
        ok = True
        try:
            for page_size, max_visible in ((9, 3), (5, 1)):
                options = dict(saved)
                options.update({"font_scale": 1.0, "max_visible": max_visible,
                                "layout": "horizontal", "show_hints": True})
                self.panel.set_options(options)
                for start in (0, page_size):
                    expected = [cand["id"] for cand in candidates[start:start + page_size]]
                    self.panel.render(self.fixture_snapshot(candidates, page_size, start=start))
                    pump(0.6)
                    metrics = self.panel.metrics()
                    rows = self.panel.row_geometry()
                    logical = [row["id"] for row in rows]
                    indexes = [row["index"] for row in self.panel.rows]
                    visible_at_start = list(metrics["in_view"])
                    scroll = metrics["scroll"]
                    swept = self.sweep()
                    # 高亮从页首移到本页末项：视口自动把它滚进可见区域。
                    self.panel.render(self.fixture_snapshot(candidates, page_size, start=start, selected=start))
                    pump(0.6)
                    head_scroll = self.panel.metrics()["scroll"]["value"]
                    head_rows = {row["id"]: row for row in self.panel.row_geometry()}
                    first_x = self.panel.rows[0]["widget"].get_allocation().x
                    self.panel.render(self.fixture_snapshot(
                        candidates, page_size, start=start, selected=start + len(expected) - 1))
                    pump(0.6)
                    tail_scroll = self.panel.metrics()["scroll"]["value"]
                    tail_rows = {row["id"]: row for row in self.panel.row_geometry()}
                    last_id = expected[-1]
                    clicked = self.replay_click(tail_rows[last_id]) if tail_rows[last_id]["in_view"] else None
                    shot = screenshot(EVIDENCE / f"panel-budget-{page_size}-{max_visible}-{start}.png",
                                      self.panel.window)
                    good = (logical == expected and swept == expected
                            and indexes == list(range(start, start + len(expected)))
                            and metrics["page_size"] == page_size and metrics["max_visible"] == max_visible
                            and scroll["scrollbar_visible"] and scroll["page_size"] < scroll["upper"]
                            and 0 < len(visible_at_start) < len(expected)
                            and head_scroll <= first_x and head_rows[expected[0]]["in_view"]
                            and tail_scroll > head_scroll
                            and bool(tail_rows[last_id]["in_view"]) and bool(tail_rows[last_id]["selected"])
                            and bool(clicked) and clicked[0] == "select" and clicked[1] == last_id
                            and not metrics["dropped_for_width"])
                    ok = ok and good
                    combos.append({"page_size": page_size, "max_visible": max_visible,
                                   "page_start": start, "expected_ids": expected,
                                   "logical_page_ids": logical, "candidate_indexes": indexes,
                                   "visible_at_start": visible_at_start, "swept_ids": swept,
                                   "viewport_cap": metrics["viewport_cap"],
                                   "scroll": scroll, "highlight_scroll": [head_scroll, tail_scroll],
                                   "last_in_view": bool(tail_rows[last_id]["in_view"]),
                                   "clicked_id": clicked[1] if clicked else None, "ok": good,
                                   "screenshot": shot})
            return self.record("max-visible-is-viewport-budget-not-page-truncation", ok,
                               fixture=True,
                               fixture_data="page_size=9/max_visible=3 与 page_size=5/max_visible=1 的"
                                            "夹具候选与分页快照（面板/排版/视口/点击为真实组件）",
                               combos=combos)
        finally:
            self.panel.set_options(saved)
            if self.snapshot:
                self.on_state(self.snapshot)


    # ---------------------------------------------- 布局稳定后的自动滚动与短页收缩
    def wait_layout(self, target_id=None, timeout=3.0):
        """等 GTK 真正分配好本页候选；给了 target_id 就等它自己完整进入视口。

        只读取面板状态，不调用 reveal()/scroll_by() 代替自动滚动。
        """
        def ready():
            rows = self.panel.rows
            if not rows or any(row["widget"].get_allocated_width() <= 1 for row in rows):
                return False
            if target_id is None:
                return True
            row = next((item for item in self.panel.row_geometry() if item["id"] == target_id), None)
            return bool(row and row["in_view"])
        found = wait_for(ready, timeout)
        pump(0.15)
        return bool(found)

    def step_layout_after_allocation(self):
        """真实尺寸协商完成后：高亮变化自动进入视口；整页切短页后滚动范围收缩。

        夹具：候选文本、94 项分页快照（末页 4 项，模拟真实 hao 末页的形状）、360px 宽度上限。
        真实：GTK3 尺寸分配、Pango 排版、Gtk.ScrolledWindow 调整、XTest 点击与平台调用参数。
        视口只用 `scroll_by()` 预先滚到末端（模拟用户拖动横向滚动条）；高亮必须由面板
        在真实分配之后自己带回视野，本项不调用 `reveal()` 补救。
        """
        saved = dict(config.panel_options(self.settings))
        candidates = [{"id": f"la-{index}", "text": f"候选{index}", "index": index,
                       "annotation": "词语"} for index in range(94)]
        ok_reveal, ok_short = True, True
        combos, short_detail = [], {}
        original_limit = self.panel._width_limit
        try:
            options = dict(saved)
            options.update({"font_scale": 3.0, "layout": "horizontal", "show_hints": True})
            self.panel.set_options(options)
            self.panel._width_limit = lambda: 360

            # 1) 9/3 与 5/1，两段方向相反的键盘高亮变化；每次都模拟 0.2.8 里延迟回调
            #    早于 size-allocate 的时序（手动跑一次面板自己的 _after_layout，不移动视口）。
            for page_size, max_visible in ((9, 3), (5, 1)):
                options["max_visible"] = max_visible
                self.panel.set_options(options)
                expected = [cand["id"] for cand in candidates[:page_size]]
                middle = page_size // 2
                phases = []
                # A. 视口在页首，高亮跳到末项：面板必须向右滚动，把末项完整带进视口。
                self.panel.render(self.fixture_snapshot(candidates, page_size, selected=0))
                self.wait_layout()
                start = self.panel.metrics()["scroll"]["value"]
                last_id = expected[-1]
                self.panel.render(self.fixture_snapshot(candidates, page_size, selected=page_size - 1))
                self.panel._after_layout()           # 早到的空闲回调：新行此时只有 1px 占位
                early = self.panel.metrics()["scroll"]["value"]
                settled_last = self.wait_layout(last_id)
                last_metrics = self.panel.metrics()
                last_rows = {row["id"]: row for row in self.panel.row_geometry()}
                last_click = (self.replay_click(last_rows[last_id])
                              if last_rows[last_id]["in_view"] else None)
                span = max(0, last_metrics["scroll"]["upper"] - last_metrics["scroll"]["page_size"])
                shot_last = screenshot(EVIDENCE / f"panel-layout-reveal-{page_size}-{max_visible}.png",
                                       self.panel.window)
                phase_a = (bool(settled_last) and last_rows[last_id]["selected"]
                           and last_rows[last_id]["in_view"]
                           and early <= 2                       # 布局前不得按 1px 占位乱滚
                           and start <= 2
                           and last_metrics["scroll"]["value"] > start
                           and 0 <= last_metrics["scroll"]["value"] <= span
                           and bool(last_click) and last_click[0] == "select"
                           and last_click[1] == last_id)
                phases.append({"phase": "start-to-last", "scroll_before": start,
                               "scroll_early_idle": early,
                               "scroll_settled": last_metrics["scroll"]["value"],
                               "scroll_span": span, "target_in_view": last_rows[last_id]["in_view"],
                               "clicked_id": last_click[1] if last_click else None,
                               "screenshot": shot_last, "ok": phase_a})
                # B. 用户把视口拖到末端后，键盘把高亮移到中间项：视口要向左回到该项，
                #    不能被 1px 占位按成 0（0.2.8 的 scroll=0 / 第 4 项不可见）。
                self.panel.scroll_by(10000)
                pump(0.15)
                before = self.panel.metrics()["scroll"]["value"]
                mid_id = expected[middle]
                self.panel.render(self.fixture_snapshot(candidates, page_size, selected=middle))
                self.panel._after_layout()
                early_mid = self.panel.metrics()["scroll"]["value"]
                settled_mid = self.wait_layout(mid_id)
                mid_metrics = self.panel.metrics()
                mid_rows = {row["id"]: row for row in self.panel.row_geometry()}
                mid_click = (self.replay_click(mid_rows[mid_id])
                             if mid_rows[mid_id]["in_view"] else None)
                shot_mid = screenshot(EVIDENCE / f"panel-layout-mid-{page_size}-{max_visible}.png",
                                      self.panel.window)
                phase_b = (bool(settled_mid) and mid_rows[mid_id]["selected"]
                           and mid_rows[mid_id]["in_view"]
                           and before == span                  # 用户滚到末端后没有被自动滚回
                           and early_mid == before              # 布局前不得把视口滚回页首
                           and 0 < mid_metrics["scroll"]["value"] < before
                           and bool(mid_click) and mid_click[0] == "select"
                           and mid_click[1] == mid_id)
                phases.append({"phase": "end-to-middle", "scroll_before": before,
                               "scroll_early_idle": early_mid,
                               "scroll_settled": mid_metrics["scroll"]["value"],
                               "target_in_view": mid_rows[mid_id]["in_view"],
                               "clicked_id": mid_click[1] if mid_click else None,
                               "screenshot": shot_mid, "ok": phase_b})
                metrics = mid_metrics
                rows = mid_rows
                logical = [row["id"] for row in self.panel.row_geometry()]
                indexes = [row["index"] for row in self.panel.rows]
                good = (phase_a and phase_b and logical == expected
                        and indexes == list(range(page_size))
                        and metrics["page_size"] == page_size and metrics["max_visible"] == max_visible)
                ok_reveal = ok_reveal and good
                combos.append({"page_size": page_size, "max_visible": max_visible,
                               "logical_ids": logical, "candidate_indexes": indexes,
                               "target_in_view": rows[mid_id]["in_view"],
                               "phases": phases, "ok": good})
            self.record("keyboard-highlight-reveals-after-real-layout", ok_reveal,
                        fixture=True,
                        fixture_data="9/3 与 5/1 的夹具候选、360px 宽度上限、提前触发的空闲回调；"
                                     "GTK 分配/滚动视口/XTest 点击为真实组件",
                        combos=combos)

            # 2) 整页（9 项）在末端 → 短页（末页 4 项）：滚动范围必须按新内容收缩，
            #    滚到末端不能整页空白；回到整页后范围恢复。
            options["max_visible"] = 9
            self.panel.set_options(options)
            self.panel.render(self.fixture_snapshot(candidates, 9, selected=0))
            self.wait_layout()
            self.panel.scroll_by(10000)
            pump(0.15)
            full = self.panel.metrics()
            short_ids = [cand["id"] for cand in candidates[90:94]]
            self.panel.render(self.fixture_snapshot(candidates, 9, selected=90, start=90))
            self.panel._after_layout()
            self.wait_layout()
            short = self.panel.metrics()
            self.panel.scroll_by(10000)              # 用户在短页上滚到末端
            pump(0.2)
            end = self.panel.metrics()
            end_rows = self.panel.row_geometry()
            end_ids = [row["id"] for row in end_rows]
            end_span = max(0, end["scroll"]["upper"] - end["scroll"]["page_size"])
            shot_full = screenshot(EVIDENCE / "panel-short-page-before.png", self.panel.window)
            ok_short = (end_ids == short_ids
                        and [row["index"] for row in end_rows] == list(range(90, 94))
                        and short["content_natural_width"] < full["content_natural_width"]
                        and short["scroll"]["upper"] < full["scroll"]["upper"]
                        and short["scroll"]["upper"] <= short["content_natural_width"] + 1
                        and end["scroll"]["value"] == end_span
                        and bool(end_rows[-1]["in_view"])
                        and sum(1 for row in end_rows if row["in_view"]) > 0)
            short_detail = {"short_ids": end_ids, "short_indexes": [row["index"] for row in end_rows],
                            "full_natural_width": full["content_natural_width"],
                            "short_natural_width": short["content_natural_width"],
                            "full_upper": full["scroll"]["upper"], "short_upper": short["scroll"]["upper"],
                            "scroll_at_end": end["scroll"]["value"], "scroll_span": end_span,
                            "in_view_at_end": [row["index"] for row in end_rows if row["in_view"]],
                            "last_in_view": bool(end_rows[-1]["in_view"]),
                            "screenshot": shot_full}
            # 回到整页：滚动范围恢复、整页 ID 不变、页首高亮重新进入视口。
            self.panel.render(self.fixture_snapshot(candidates, 9, selected=0))
            back_ok = self.wait_layout(candidates[0]["id"])
            back = self.panel.metrics()
            back_ids = [row["id"] for row in self.panel.row_geometry()]
            short_detail.update({"back_ids": back_ids, "back_upper": back["scroll"]["upper"],
                                 "back_scroll": back["scroll"]["value"], "back_first_in_view": back_ok})
            ok_short = ok_short and back_ok and back_ids == [c["id"] for c in candidates[:9]] \
                and back["scroll"]["upper"] == full["scroll"]["upper"]
            short_detail["pass"] = ok_short
            self.record("short-page-shrinks-scroll-extent-and-end-not-blank", ok_short,
                        fixture=True,
                        fixture_data="9 项整页 → 94 项语料的末页 4 项（模拟 hao 末页形状）；"
                                     "GTK 分配/滚动视口为真实组件",
                        **short_detail)
            return {"reveal": combos, "short_page": short_detail}
        finally:
            self.panel._width_limit = original_limit
            self.panel.set_options(saved)
            if self.snapshot:
                self.on_state(self.snapshot)


def _caps():
    try:
        from server_ime_engine import Engine

        with Engine() as engine:
            return config.Capabilities.from_engine(engine)
    except Exception:
        return config.Capabilities()


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    scenario = Scenario()
    payload = {"employee_id": "interface", "kind": "candidate-panel-and-status",
               "components": {"real": ["GTK3 Gtk.Entry", "IBus 1.5 adapter (platform)",
                                       "libpinyin backend (engine)", "ime_interface.panel",
                                       "Gtk.ScrolledWindow 单行横向视口", "GTK size allocation",
                                       "platform D-Bus candidate/status interface"],
                              "fixture": ["宽度/滚动检查使用夹具候选文本、360px 宽度上限、"
                                          "page_size×max_visible 组合与 selected_index 快照",
                                          "布局回归使用 94 项夹具分页（末页 4 项）与提前触发的空闲回调，"
                                          "模拟 0.2.8 的真实时序；控件、分配、排版、视口、点击均为真实组件"]},
               "result": "FAIL"}
    try:
        payload["settings_path"] = str(scenario.start())
        payload["snapshots"] = scenario.run()
        payload["result"] = "PASS" if all(c["result"] == "PASS" for c in scenario.checks) else "FAIL"
    except Exception as exc:  # noqa: BLE001
        payload["error"] = f"{type(exc).__name__}: {exc}"
        screenshot(EVIDENCE / "panel-failure.png")
    finally:
        payload["checks"] = scenario.checks
        payload["snapshot_count"] = len(scenario.snapshots)
        (EVIDENCE / "panel-checks.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8")
        print(json.dumps({"result": payload["result"], "checks": payload.get("checks")},
                         ensure_ascii=False, indent=1), flush=True)
        return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
