"""XTest 键盘/鼠标注入，供界面检查使用（只在隔离 X 服务器上运行）。"""
import ctypes
import ctypes.util
import os
import time

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

KEYSYMS = {"space": 0x20, "Return": 0xFF0D, "Escape": 0xFF1B, "Tab": 0xFF09,
           "Page_Up": 0xFF55, "Page_Down": 0xFF56, "Up": 0xFF52, "Down": 0xFF54,
           "BackSpace": 0xFF08, "Control_L": 0xFFE3, "Shift_L": 0xFFE1}


def pump(seconds=0.1):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        time.sleep(0.002)


def wait_for(predicate, timeout=5.0, interval=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        pump(interval)
        value = predicate()
        if value:
            return value
    return predicate()


class X:
    def __init__(self):
        assert os.environ.get("SERVER_IME_ISOLATED") == "1", "只在隔离会话中注入事件"
        assert os.environ.get("DISPLAY", "").startswith("127.0.0.1:"), "拒绝向宿主显示注入事件"
        self.x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
        self.xtst = ctypes.CDLL(ctypes.util.find_library("Xtst"))
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.x11.XKeysymToKeycode.restype = ctypes.c_uint
        self.x11.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        self.x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        self.xtst.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        self.xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        self.display = self.x11.XOpenDisplay(os.environ["DISPLAY"].encode())
        assert self.display, "Xlib 无法连接隔离显示"

    def focus_window(self, gtk_window):
        self.x11.XSetInputFocus(self.display, gtk_window.get_window().get_xid(), 2, 0)
        self.x11.XSync(self.display, False)
        pump(0.2)

    def _code(self, keysym):
        code = self.x11.XKeysymToKeycode(self.display, keysym)
        assert code, f"没有 {keysym:#x} 的 keycode"
        return code

    def press(self, keysym, pressed):
        self.xtst.XTestFakeKeyEvent(self.display, self._code(keysym), 1 if pressed else 0, 0)
        self.x11.XSync(self.display, False)
        pump(0.04)

    def key(self, name):
        keysym = KEYSYMS.get(name, ord(name[0]) if len(name) == 1 else None)
        assert keysym, name
        self.press(keysym, True)
        self.press(keysym, False)
        pump(0.05)

    def type_text(self, text):
        for char in text:
            self.key(char)

    def click(self, x, y, button=1):
        self.xtst.XTestFakeMotionEvent(self.display, -1, int(x), int(y), 0)
        self.x11.XSync(self.display, False)
        pump(0.05)
        self.xtst.XTestFakeButtonEvent(self.display, button, 1, 0)
        self.x11.XSync(self.display, False)
        pump(0.03)
        self.xtst.XTestFakeButtonEvent(self.display, button, 0, 0)
        self.x11.XSync(self.display, False)
        pump(0.15)

    def scroll(self, x, y, up=True):
        self.click(x, y, button=4 if up else 5)

    def close(self):
        self.x11.XCloseDisplay(self.display)


def widget_center(widget):
    """控件中心的根坐标。GtkButton 等控件没有独立 GdkWindow，需要逐级换算。"""
    toplevel = widget.get_toplevel()
    x, y = widget.translate_coordinates(toplevel, 0, 0)
    window = toplevel.get_window()
    assert window is not None, "顶层窗口尚未实现"
    ok, origin_x, origin_y = window.get_origin()
    allocation = widget.get_allocation()
    return origin_x + x + allocation.width // 2, origin_y + y + allocation.height // 2


def screenshot(path, widget=None):
    import gi
    from gi.repository import Gdk

    target = widget.get_window() if widget is not None else Gdk.get_default_root_window()
    if widget is None:
        width, height = target.get_width(), target.get_height()
    else:
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
    pixbuf = Gdk.pixbuf_get_from_window(target, 0, 0, width, height)
    assert pixbuf is not None, "截图失败"
    pixbuf.savev(str(path), "png", [], [])
    return {"path": str(path), "width": pixbuf.get_width(), "height": pixbuf.get_height()}
