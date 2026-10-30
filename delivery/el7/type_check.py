"""Type into a real GTK entry through the installed product (EL7 check, check-el7.sh).

Starts a private Xvnc display and session bus, runs `server-ime start --managed-ibus`,
then `server-ime exec` this script with --typer, which types pinyin with XTest and
reports what the entry received.
Run: <python> type_check.py <prefix>
"""
import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

CASES = [("nihao ", "你好"), ("woyongdockerbushu ", "我用Docker部署"), ("github ", "GitHub"),
         ("nhao", None),  # then three Lefts, "i" and space: "你好"
         ("\x01abc\x01nihao ", "abc你好")]  # \x01: Shift pressed and released alone
LEFT = 0xFF51


def typer():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib

    def pump(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            time.sleep(.005)

    x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
    xtst = ctypes.CDLL(ctypes.util.find_library("Xtst"))
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    display = x11.XOpenDisplay(os.environ["DISPLAY"].encode())
    Gtk.init([])
    window, entry = Gtk.Window(), Gtk.Entry()
    window.add(entry)
    window.show_all()
    entry.grab_focus()
    pump(1.0)
    x11.XSetInputFocus(display, window.get_window().get_xid(), 2, 0)
    pump(1.0)

    def key(keysym):
        for pressed in (1, 0):
            xtst.XTestFakeKeyEvent(display, x11.XKeysymToKeycode(display, keysym), pressed, 0)
            x11.XSync(display, 0)
            pump(.08)

    results = []
    for typed, expected in CASES:
        entry.set_text("")
        pump(.2)
        for ch in typed:
            key(0xFFE1 if ch == "\x01" else ord(ch))
            pump(.3 if not results else .05)
        if expected is None:
            for _ in range(3):
                key(LEFT)
            key(ord("i"))
            key(32)
            typed, expected = "nhao ←←← i ", "你好"
        pump(.5)
        results.append({"typed": typed.replace("\x01", "<Shift>"), "expected": expected, "got": entry.get_text(),
                        "ok": entry.get_text() == expected})
    print(json.dumps(results, ensure_ascii=False))


def main(prefix):
    entry = Path(prefix) / "bin/server-ime"
    tmp = Path(tempfile.mkdtemp())
    display = os.environ.get("TYPE_DISPLAY", ":7")
    env = dict(os.environ, DISPLAY=display, XDG_RUNTIME_DIR=str(tmp))
    xvnc = subprocess.Popen(["Xvnc", display, "-geometry", "1024x768", "-depth", "24", "-SecurityTypes", "None"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    bus = subprocess.check_output(["dbus-daemon", "--session", "--fork", "--print-address=1"], text=True).strip()
    env["DBUS_SESSION_BUS_ADDRESS"] = bus
    state = ["--state-dir", str(tmp / "run")]
    try:
        started = subprocess.run([str(entry), "--data-dir", str(tmp / "data"), *state, "start", "--managed-ibus"],
                                 env=env, capture_output=True, text=True, timeout=120)
        print("start:", started.returncode, started.stdout.strip()[-300:], started.stderr.strip()[-500:])
        out = subprocess.run([str(entry), *state, "exec", "--", sys.executable, "-s", __file__, "--typer"],
                             env=env, capture_output=True, text=True, timeout=180)
        print(out.stdout.strip() or out.stderr.strip()[-1500:])
        results = json.loads(out.stdout.strip().splitlines()[-1])
        print("TYPING:", "PASS" if all(r["ok"] for r in results) else "FAIL")
    finally:
        subprocess.run([str(entry), *state, "stop"], env=env, capture_output=True, timeout=60)
        xvnc.terminate()


if __name__ == "__main__":
    typer() if sys.argv[1:] == ["--typer"] else main(sys.argv[1])
