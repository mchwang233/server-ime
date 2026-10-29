#!/usr/bin/python3
"""interface 自检入口：无显示单测 + 隔离 X11/D-Bus/IBus 下的真实界面检查。

不使用宿主显示：X 服务器为本进程启动的 Xvnc，监听 127.0.0.1 的临时显示号；
X 授权文件、D-Bus、IBus 地址、HOME/XDG 目录都在 interface/.runtime 下，结束后清理。
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
PLATFORM = WORKSPACE / "platform"
ENGINE_SRC = WORKSPACE / "engine" / "src"


def main():
    os.umask(0o077)
    runtime_parent = ROOT / ".runtime"
    runtime_parent.mkdir(exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix="r-", dir=runtime_parent))
    evidence = ROOT / "evidence" / ("run-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    evidence.mkdir(parents=True)
    env = os.environ.copy()
    for key in ["DBUS_SESSION_BUS_ADDRESS", "DBUS_STARTER_ADDRESS", "DBUS_SESSION_BUS_PID",
                "IBUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY", "SESSION_MANAGER", "XDG_SESSION_ID"]:
        env.pop(key, None)
    for key, name in {"XDG_CONFIG_HOME": "config", "XDG_CACHE_HOME": "cache", "XDG_DATA_HOME": "data",
                      "XDG_STATE_HOME": "state", "XDG_RUNTIME_DIR": "run", "TMPDIR": "tmp",
                      "HOME": "home"}.items():
        folder = runtime / name
        folder.mkdir(mode=0o700, parents=True)
        env[key] = str(folder)
    env.update(PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(PLATFORM), str(ENGINE_SRC)]),
               PYTHONDONTWRITEBYTECODE="1", GSETTINGS_BACKEND="memory",
               GTK_IM_MODULE="ibus", QT_IM_MODULE="ibus", XMODIFIERS="@im=ibus", GDK_BACKEND="x11",
               NO_AT_BRIDGE="1", GTK_USE_PORTAL="0", IBUS_USE_PORTAL="0", XDG_SESSION_TYPE="x11",
               SERVER_IME_EVIDENCE=str(evidence), SERVER_IME_ISOLATED="1",
               SERVER_IME_ENGINE="server-ime-test",
               SERVER_IME_CONFIG=str(runtime / "config" / "server-ime" / "settings.json"))
    env["IBUS_ADDRESS_FILE"] = str(runtime / "ibus-address")
    components = runtime / "components"
    components.mkdir()
    env["IBUS_COMPONENT_PATH"] = str(components)
    authority = runtime / "auth"
    authority.write_bytes(struct.pack("!H", 65535) + b"".join(
        struct.pack("!H", len(value)) + value
        for value in [b"", b"", b"MIT-MAGIC-COOKIE-1", secrets.token_bytes(16)]))
    env["XAUTHORITY"] = str(authority)

    processes, logs, commands = [], [], []
    summary = {"employee_id": "interface", "result": "FAIL",
               "real": ["GTK3 candidate panel", "GTK3 settings window", "IBus 1.5 adapter",
                        "libpinyin backend", "platform D-Bus candidate/status interface",
                        "settings v1 format and validation"],
               "fixture": ["config/capabilities-fixture.json（仅用于展示能力开启时的控件）"],
               "checks": []}

    def start(argv, name, pass_fds=()):
        commands.append({"name": name, "argv": argv})
        log = (evidence / (name + ".log")).open("w")
        logs.append(log)
        process = subprocess.Popen(argv, env=env, cwd=str(ROOT), stdout=log,
                                   stderr=subprocess.STDOUT, pass_fds=pass_fds)
        processes.append(process)
        return process

    def check(argv, name, timeout=180):
        commands.append({"name": name, "argv": argv})
        result = subprocess.run(argv, env=env, cwd=str(ROOT), capture_output=True, text=True,
                                timeout=timeout)
        (evidence / (name + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"{name} 失败（{result.returncode}）；见 {evidence / (name + '.log')}")
        summary["checks"].append(name)
        print(name + ": PASS", flush=True)

    try:
        # 1) 无显示单测：设置格式、快捷键冲突/非法、引擎与平台映射
        check([sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"),
               "-p", "test_*.py", "-v"], "unit")
        # 2) 隔离 X 服务器
        read_fd, write_fd = os.pipe()
        try:
            start(["/usr/bin/Xvnc", "-displayfd", str(write_fd), "-geometry", "1024x768", "-depth", "24",
                   "-rfbport", "-1", "-rfbunixpath", str(runtime / "vnc"), "-localhost",
                   "-nolisten", "unix", "-nolisten", "local", "-listen", "tcp",
                   "-auth", str(authority), "-noreset"], "xserver", pass_fds=(write_fd,))
        finally:
            os.close(write_fd)
        try:
            payload = b""
            deadline = __import__("time").monotonic() + 10
            while b"\n" not in payload and __import__("time").monotonic() < deadline:
                ready, _, _ = select.select([read_fd], [], [], 0.2)
                if ready:
                    chunk = os.read(read_fd, 32)
                    if not chunk:
                        break
                    payload += chunk
            display = payload.decode().strip() if b"\n" in payload else ""
            if not display.isdecimal():
                raise RuntimeError("隔离 Xvnc 显示不可用；见 xserver.log")
        finally:
            os.close(read_fd)
        env["DISPLAY"] = "127.0.0.1:" + display
        summary["isolated_display"] = env["DISPLAY"]
        check(["xdpyinfo", "-display", env["DISPLAY"]], "display")
        # 3) 私有 D-Bus + IBus
        dbus_config = runtime / "session.conf"
        dbus_address = "unix:path=" + str(runtime / "session")
        dbus_config.write_text(
            '<busconfig><type>session</type><listen>' + dbus_address + '</listen><auth>EXTERNAL</auth>'
            '<policy context="default"><allow send_destination="*"/><allow receive_sender="*"/>'
            '<allow own="*"/></policy></busconfig>', encoding="utf-8")
        start(["dbus-daemon", "--nofork", "--config-file=" + str(dbus_config)], "dbus")
        for _ in range(200):
            if (runtime / "session").exists():
                break
            __import__("time").sleep(0.03)
        env["DBUS_SESSION_BUS_ADDRESS"] = dbus_address
        start(["ibus-daemon", "--single", "--panel=disable", "--config=disable",
               "--emoji-extension=disable", "--cache=none",
               "--address=unix:dir=" + str(runtime)], "ibus-daemon")
        for _ in range(200):
            address_file = Path(env["IBUS_ADDRESS_FILE"])
            if address_file.exists():
                for line in address_file.read_text().splitlines():
                    if line.startswith("IBUS_ADDRESS="):
                        env["IBUS_ADDRESS"] = line.partition("=")[2]
            if env.get("IBUS_ADDRESS"):
                break
            __import__("time").sleep(0.03)
        else:
            raise RuntimeError("私有 IBus 地址不可用；见 ibus-daemon.log")
        # 4) 平台适配器 + 真实 libpinyin 引擎
        check([sys.executable, str(PLATFORM / "launch.py"), "--backend",
               "server_ime_engine.platform_adapter:create_session", "--manifest",
               str(evidence / "server-ime-test.xml")], "manifest")
        adapter = start([sys.executable, str(PLATFORM / "launch.py"), "--register", "--backend",
                         "server_ime_engine.platform_adapter:create_session"], "adapter")
        for _ in range(200):
            if '"event": "ready"' in (evidence / "adapter.log").read_text(encoding="utf-8"):
                break
            if adapter.poll() is not None:
                raise RuntimeError("适配器在注册前退出；见 adapter.log")
            __import__("time").sleep(0.03)
        else:
            raise RuntimeError("适配器注册超时")
        # 5) 真实界面检查
        check([sys.executable, str(ROOT / "tests" / "ui_scenario.py")], "panel-ui")
        check([sys.executable, str(ROOT / "tests" / "settings_scenario.py")], "settings-ui")
        # 6) 汇总
        for name, key in (("panel-ui", "panel-checks.json"), ("settings-ui", "settings-checks.json")):
            payload = json.loads((evidence / key).read_text(encoding="utf-8"))
            summary.setdefault("scenarios", {})[name] = {
                "result": payload.get("result"),
                "checks": [{c["check"]: c["result"]} for c in payload.get("checks", [])],
                "components": payload.get("components"),
            }
            if payload.get("result") != "PASS":
                raise RuntimeError(f"{name} 有失败项；见 {evidence / key}")
        summary["result"] = "PASS"
    except Exception as exc:  # noqa: BLE001
        summary["error"] = str(exc)
        print("失败：" + str(exc), file=sys.stderr, flush=True)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                summary.setdefault("processes_reaped", []).append(
                    {"pid": process.pid, "exit_code": process.wait(timeout=10)})
            except subprocess.TimeoutExpired:
                process.kill()
                summary["processes_reaped"].append({"pid": process.pid, "exit_code": "killed"})
        for log in logs:
            log.close()
        summary["commands"] = commands
        summary["evidence"] = str(evidence)
        (evidence / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")
        (ROOT / "evidence" / "latest.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        shutil.rmtree(runtime, ignore_errors=True)
        print(json.dumps({"result": summary["result"], "evidence": str(evidence)}, ensure_ascii=False),
              flush=True)
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
