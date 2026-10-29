#!/usr/bin/python3
"""夹具检查：把 capabilities-fixture.json 声明为“双拼/模糊音/纠错/学习可用”，
只用于证明设置界面在能力开启时会显示对应控件。不是真实引擎能力，不能当作功能已实现。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT.parent / "platform"), str(ROOT.parent / "engine" / "src"),
                str(ROOT / "tests")]

from ime_interface import config, settings_ui  # noqa: E402
from x11 import X, pump, screenshot  # noqa: E402

EVIDENCE = Path(os.environ["SERVER_IME_EVIDENCE"])
FIXTURE = ROOT / "config" / "capabilities-fixture.json"


def main():
    caps = config.Capabilities.from_file(FIXTURE)
    path = EVIDENCE / "settings-fixture.json"
    settings, _, _ = config.load(path, caps=caps)
    window = settings_ui.SettingsWindow(settings, caps, path)
    pump(0.6)
    # 本机：不先建立 Xlib 连接时 Gdk.pixbuf_get_from_window 会触发 cairo 断言，必须先连一次。
    x11 = X()
    x11.focus_window(window.window)
    pump(0.3)
    model = window.schema_combo.get_model()
    ids = [model[row][1] for row in range(len(model))]
    texts = [model[row][0] for row in range(len(model))]
    learning = hasattr(window, "learning_switch")
    unsupported = getattr(window, "unsupported_label", None)
    text = unsupported.get_text() if unsupported is not None else ""
    window.schema_combo.set_active_id("double_pinyin")
    if learning:
        window.learning_switch.set_active(True)
    saved = window.save()
    written, errors, _ = config.load(path, caps=caps)
    shot = screenshot(EVIDENCE / "settings-fixture-capabilities.png", window.window)
    ok = (ids == ["full_pinyin", "double_pinyin"] and texts == ["全拼", "双拼"] and learning
          and "双拼" not in text and saved and not errors
          and written["input"]["learning"] is True and written["input"]["schema"] == "double_pinyin")
    payload = {"check": "fixture-capabilities-show-future-controls",
               "result": "PASS" if ok else "FAIL", "schemas": ids, "schema_texts": texts,
               "learning_control": learning, "unsupported_text": text, "saved": saved,
               "written_input": written["input"], "errors": errors, "screenshot": shot,
               "note": "夹具：双拼/模糊音/纠错/学习不是真实引擎能力，仅验证控件门控"}
    (EVIDENCE / "settings-fixture-step.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    x11.close()
    print(("PASS " if ok else "FAIL ") + payload["check"], flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
