#!/usr/bin/python3
"""框架原生候选面板探针（ibus-ui-gtk3）。

与其他检查不同，这里**不**传 `--panel=disable`，让 ibus-daemon 启动自带的 GTK 面板，
然后向真实 GTK 输入框注入按键，观察框架面板是否出现并被截图。

结果只作为“原生面板可用性”的观察记录，不进入 `run_checks.py` 的通过条件：
本机没有窗口管理器，原生面板的位置/可见性可能依赖会话环境。
"""
from __future__ import annotations

import datetime
import json
import os
import select
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
PLATFORM = WORKSPACE / "platform"
ENGINE_SRC = WORKSPACE / "engine" / "src"
CLIENT = r"""
import os, sys
from pathlib import Path
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("IBus", "1.0")
from gi.repository import Gtk, IBus
sys.path.insert(0, os.environ["INTERFACE_TESTS"])
from x11 import X, pump, screenshot, wait_for
IBus.init(); bus = IBus.Bus.new(); assert bus.is_connected()
assert bus.set_global_engine("server-ime-test"), "无法选择引擎"
win = Gtk.Window(title="native panel probe client"); win.set_default_size(640, 200)
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); box.set_border_width(16)
win.add(box)
label = Gtk.Label(label="原生面板探针：输入框 A"); label.set_xalign(0); box.pack_start(label, False, False, 0)
entry = Gtk.Entry(); entry.set_placeholder_text("输入框 A"); box.pack_start(entry, False, False, 0)
win.move(60, 380); win.show_all(); pump(0.4)
x = X(); x.focus_window(win); entry.grab_focus(); pump(0.5)
x.type_text("nihao")
wait_for(lambda: False, 1.6)
import subprocess as sp
tree = sp.run(["xwininfo", "-root", "-tree"], capture_output=True, text=True)
(Path(os.environ["SERVER_IME_EVIDENCE"]) / "xwininfo-tree-live.txt").write_text(tree.stdout, encoding="utf-8")
shot = screenshot(Path(os.environ["SERVER_IME_EVIDENCE"]) / "native-panel-probe.png")
payload = {"entry_text": entry.get_text(), "screenshot": shot}
(Path(os.environ["SERVER_IME_EVIDENCE"]) / "native-panel-client.json").write_text(
    __import__("json").dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(__import__("json").dumps(payload, ensure_ascii=False), flush=True)
"""


def main():
    os.umask(0o077)
    runtime = Path(tempfile.mkdtemp(prefix="native-", dir=str(ROOT / ".runtime")))
    evidence = ROOT / "evidence" / ("native-panel-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    evidence.mkdir(parents=True)
    env = os.environ.copy()
    for key in ["DBUS_SESSION_BUS_ADDRESS", "IBUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY", "SESSION_MANAGER"]:
        env.pop(key, None)
    for key, name in {"XDG_CONFIG_HOME": "config", "XDG_CACHE_HOME": "cache", "XDG_RUNTIME_DIR": "run",
                      "TMPDIR": "tmp", "HOME": "home"}.items():
        folder = runtime / name
        folder.mkdir(mode=0o700, parents=True)
        env[key] = str(folder)
    env.update(PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(PLATFORM), str(ENGINE_SRC)]),
               PYTHONDONTWRITEBYTECODE="1", GTK_IM_MODULE="ibus", XMODIFIERS="@im=ibus",
               GDK_BACKEND="x11", NO_AT_BRIDGE="1", GTK_USE_PORTAL="0", IBUS_USE_PORTAL="0",
               SERVER_IME_ISOLATED="1", SERVER_IME_EVIDENCE=str(evidence),
               INTERFACE_TESTS=str(ROOT / "tests"))
    env["IBUS_ADDRESS_FILE"] = str(runtime / "ibus-address")
    components = runtime / "components"
    components.mkdir()
    env["IBUS_COMPONENT_PATH"] = str(components)
    authority = runtime / "auth"
    authority.write_bytes(struct.pack("!H", 65535) + b"".join(
        struct.pack("!H", len(value)) + value
        for value in [b"", b"", b"MIT-MAGIC-COOKIE-1", secrets.token_bytes(16)]))
    env["XAUTHORITY"] = str(authority)
    processes = []
    report = {"employee_id": "interface", "kind": "native-ibus-panel-probe", "result": "FAIL",
              "note": "观察记录：框架原生面板是否在本机隔离会话中启动并绘制"}

    def start(argv):
        log = (evidence / (Path(argv[0]).name.replace(".", "_") + "-" + str(len(processes)) + ".log")).open("w")
        process = subprocess.Popen(argv, env=env, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
        processes.append(process)
        return process

    try:
        read_fd, write_fd = os.pipe()
        try:
            process = subprocess.Popen(
                ["/usr/bin/Xvnc", "-displayfd", str(write_fd), "-geometry", "1024x768", "-depth", "24",
                 "-rfbport", "-1", "-rfbunixpath", str(runtime / "vnc"), "-localhost", "-nolisten", "unix",
                 "-nolisten", "local", "-listen", "tcp", "-auth", str(authority), "-noreset"],
                env=env, pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(process)
        finally:
            os.close(write_fd)
        payload = b""
        deadline = time.monotonic() + 10
        while b"\n" not in payload and time.monotonic() < deadline:
            ready, _, _ = select.select([read_fd], [], [], 0.2)
            if ready:
                chunk = os.read(read_fd, 32)
                if not chunk:
                    break
                payload += chunk
        os.close(read_fd)
        display = payload.decode().strip()
        env["DISPLAY"] = "127.0.0.1:" + display
        report["display"] = env["DISPLAY"]
        dbus_config = runtime / "session.conf"
        dbus_address = "unix:path=" + str(runtime / "session")
        dbus_config.write_text('<busconfig><type>session</type><listen>' + dbus_address + '</listen>'
                               '<auth>EXTERNAL</auth><policy context="default"><allow send_destination="*"/>'
                               '<allow receive_sender="*"/><allow own="*"/></policy></busconfig>', encoding="utf-8")
        start(["dbus-daemon", "--nofork", "--config-file=" + str(dbus_config)])
        for _ in range(200):
            if (runtime / "session").exists():
                break
            time.sleep(0.03)
        env["DBUS_SESSION_BUS_ADDRESS"] = dbus_address
        # 让 daemon/面板看到引擎列表：写入输入源与预加载引擎（私有 dconf，HOME 已重定向）
        for command in (["gsettings", "set", "org.freedesktop.ibus.general", "preload-engines",
                         "['server-ime-test']"],
                        ["gsettings", "set", "org.gnome.desktop.input-sources", "sources",
                         "[('xkb','us'),('ibus','server-ime-test')]"]):
            done = subprocess.run(command, env=env, capture_output=True, text=True)
            report.setdefault("gsettings", []).append({"argv": command, "rc": done.returncode,
                                                        "stderr": done.stderr.strip()[:200]})
        # 关键区别：不传 --panel=disable，由框架自己拉起 ibus-ui-gtk3。
        start(["ibus-daemon", "--single", "--emoji-extension=disable", "--cache=none",
               "--address=unix:dir=" + str(runtime)])
        for _ in range(300):
            address_file = Path(env["IBUS_ADDRESS_FILE"])
            if address_file.exists():
                for line in address_file.read_text().splitlines():
                    if line.startswith("IBUS_ADDRESS="):
                        env["IBUS_ADDRESS"] = line.partition("=")[2]
            if env.get("IBUS_ADDRESS"):
                break
            time.sleep(0.03)
        if not env.get("IBUS_ADDRESS"):
            raise RuntimeError("私有 IBus 地址不可用")
        adapter = start([sys.executable, str(PLATFORM / "launch.py"), "--register", "--backend",
                         "server_ime_engine.platform_adapter:create_session"])
        for _ in range(300):
            if any((evidence / name).exists() and '"event": "ready"' in (evidence / name).read_text(encoding="utf-8")
                   for name in [p.name for p in evidence.glob("*.log")]):
                break
            if adapter.poll() is not None:
                raise RuntimeError("适配器退出")
            time.sleep(0.03)
        time.sleep(2.0)
        ps = subprocess.run(["ps", "-o", "pid,cmd", "-C", "ibus-ui-gtk3"], capture_output=True, text=True)
        report["panel_process"] = ps.stdout.strip() or "未运行"
        client = subprocess.run([sys.executable, "-c", CLIENT], env=env, cwd=str(ROOT),
                                capture_output=True, text=True, timeout=120)
        report["client_stdout"] = client.stdout[-600:]
        report["client_stderr"] = client.stderr[-600:]
        live_tree = evidence / "xwininfo-tree-live.txt"
        tree_text = live_tree.read_text(encoding="utf-8") if live_tree.exists() else ""
        report["window_count"] = tree_text.count("\n")
        report["named_windows"] = [line.strip() for line in tree_text.splitlines() if "0x" in line]
        client_json = evidence / "native-panel-client.json"
        report["client"] = json.loads(client_json.read_text(encoding="utf-8")) if client_json.exists() else None
        panel_ok = "ibus-ui-gtk3" in ps.stdout and "<defunct>" not in ps.stdout
        report["panel_alive"] = panel_ok
        report["result"] = "PASS" if (panel_ok and report["client"] and report["client"].get("screenshot")) else "UNAVAILABLE"
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        (evidence / "native-panel-probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                          encoding="utf-8")
        shutil.rmtree(runtime, ignore_errors=True)
        print(json.dumps(report, ensure_ascii=False, indent=1), flush=True)
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
