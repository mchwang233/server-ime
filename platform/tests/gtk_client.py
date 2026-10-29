"""Actual Gtk.Entry + installed GTK IBus module + XTest key events, isolated X only."""
import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
gi.require_version("IBus", "1.0")
from gi.repository import Gtk, Gdk, GdkX11, GLib, IBus


def pump(seconds=.10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        time.sleep(.002)


def main():
    assert os.environ.get("SERVER_IME_ISOLATED") == "1", "test requires the isolated runner"
    assert os.environ.get("DISPLAY", "").startswith("127.0.0.1:"), "refusing host display"
    IBus.init()
    bus = IBus.Bus.new()
    assert bus.is_connected()
    assert bus.set_global_engine("server-ime-test"), "cannot select test engine on private bus"
    Gtk.init([])
    window = Gtk.Window(title="服务器输入法：隔离 GTK 链路测试")
    window.set_default_size(660, 230)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_border_width(20)
    window.add(box)
    box.pack_start(Gtk.Label(label="确定性后端 · 实际 GTK3 / IBus / X11 客户端"), False, False, 0)
    first, second = Gtk.Entry(), Gtk.Entry()
    first.set_placeholder_text("输入框 A")
    second.set_placeholder_text("输入框 B")
    box.pack_start(first, False, False, 0)
    box.pack_start(second, False, False, 0)
    records, checks = [], []
    for name, entry in [("A", first), ("B", second)]:
        entry.connect("preedit-changed", lambda entry, text, name=name:
                      records.append({"entry": name, "signal": "preedit", "text": text}))
        entry.connect("changed", lambda entry, name=name:
                      records.append({"entry": name, "signal": "changed", "text": entry.get_text()}))
        entry.connect("focus-in-event", lambda entry, event, name=name:
                      records.append({"entry": name, "signal": "focus-in"}) or False)
        entry.connect("focus-out-event", lambda entry, event, name=name:
                      records.append({"entry": name, "signal": "focus-out"}) or False)
    window.show_all()
    first.grab_focus()
    pump(.3)
    x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
    xtst = ctypes.CDLL(ctypes.util.find_library("Xtst"))
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XKeysymToKeycode.restype = ctypes.c_uint
    x11.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    display = x11.XOpenDisplay(os.environ["DISPLAY"].encode())
    assert display, "Xlib could not connect to isolated X server"

    def event(keysym, pressed):
        code = x11.XKeysymToKeycode(display, keysym)
        assert code, f"no keycode for {keysym}"
        assert xtst.XTestFakeKeyEvent(display, code, pressed, 0)
        x11.XSync(display, False)
        pump(.045)

    def key(keysym):
        event(keysym, True)
        event(keysym, False)

    def type_text(text):
        for ch in text:
            key(ord(ch))

    try:
        x11.XSetInputFocus(display, window.get_window().get_xid(), 2, 0)
        x11.XSync(display, False)
        pump(.4)
        assert first.has_focus()
        type_text("nihao")
        pump()
        assert any(r.get("signal") == "preedit" and r.get("text") == "nihao" for r in records), records
        assert first.get_text() == "", first.get_text()
        key(32)
        pump()
        assert first.get_text() == "你好", first.get_text()
        checks.append("xtest-key-events-through-gtk-ibus-preedit-and-chinese-commit")
        first.set_text("")
        type_text("ni")
        key(0xFF09)  # Tab must pass through and move focus to the other real widget.
        pump()
        assert second.has_focus(), "Tab did not transfer GTK focus"
        assert first.get_text() == "" and second.get_text() == "", "preedit leaked on focus transfer"
        type_text("hao")
        key(32)
        pump()
        assert second.get_text() == "好"
        checks.append("tab-passthrough-focus-transfer-and-no-preedit-leak")
        event(0xFFE3, True)  # Control_L
        key(ord('a'))
        event(0xFFE3, False)
        pump()
        assert second.get_selection_bounds() == (0, 1), second.get_selection_bounds()
        checks.append("ctrl-a-passthrough-selects-application-text")
        first.set_visibility(False)
        first.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        first.grab_focus()
        pump()
        start = len(records)
        type_text("abc123")
        assert first.get_text() == "abc123", first.get_text()
        assert not any(r.get("signal") == "preedit" and r.get("text") for r in records[start:])
        checks.append("gtk-password-entry-receives-literal-keys")
        first.set_text("")
        first.set_visibility(True)
        first.set_input_purpose(Gtk.InputPurpose.FREE_FORM)
        second.grab_focus(); pump(); first.grab_focus(); pump()
        type_text("ni")
        key(0xFF1B)  # Escape cancels in the application.
        assert first.get_text() == ""
        type_text("zhongwen")
        key(32)
        assert first.get_text() == "中文"
        checks.append("password-exit-and-escape-recover-normal-composition")
        first.set_text("")
        type_text("nhao")
        for _ in range(3):
            key(0xFF51)  # Left moves the caret inside the pinyin, not in the application.
        type_text("i")
        pump()
        assert any(r.get("signal") == "preedit" and r.get("text") == "nihao" for r in records[-6:]), records[-6:]
        key(32)
        pump()
        assert first.get_text() == "你好", first.get_text()
        checks.append("left-arrow-moves-caret-and-letters-insert-inside-pinyin")
        pixbuf = Gdk.pixbuf_get_from_window(window.get_window(), 0, 0,
                                           window.get_allocated_width(), window.get_allocated_height())
        pixbuf.savev(str(Path(os.environ["SERVER_IME_EVIDENCE"], "gtk-client.png")), "png", [], [])
        data = {"employee_id": "platform", "result": "PASS", "display": os.environ["DISPLAY"],
                "backend": "deterministic-fixture-v1", "checks": checks,
                "final_text": {"A": first.get_text(), "B": second.get_text()}, "observations": records}
        Path(os.environ["SERVER_IME_EVIDENCE"], "gtk-client.json").write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n")
        print(json.dumps({k: data[k] for k in ["result", "checks", "final_text"]}, ensure_ascii=False))
    finally:
        x11.XCloseDisplay(display)
        window.destroy()
        pump()


if __name__ == "__main__":
    main()
