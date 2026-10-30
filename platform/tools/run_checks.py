#!/usr/bin/python3
"""Own the entire disposable X11 + D-Bus + IBus test session. No host discovery."""
import datetime
import json
import os
from pathlib import Path
import secrets
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.umask(0o077)
    runtime_parent = ROOT / ".runtime"
    runtime_parent.mkdir(exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix="r-", dir=runtime_parent))
    evidence = ROOT / "evidence" / ("run-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    evidence.mkdir(parents=True)
    env = os.environ.copy()
    for key in ["DBUS_SESSION_BUS_ADDRESS", "DBUS_STARTER_ADDRESS", "DBUS_STARTER_BUS_TYPE", "IBUS_ADDRESS",
                "DISPLAY", "WAYLAND_DISPLAY", "SESSION_MANAGER", "XDG_SESSION_ID"]:
        env.pop(key, None)
    for key, name in {"XDG_CONFIG_HOME": "config", "XDG_CACHE_HOME": "cache", "XDG_DATA_HOME": "data",
                      "XDG_STATE_HOME": "state", "XDG_RUNTIME_DIR": "run", "TMPDIR": "tmp"}.items():
        folder = runtime / name
        folder.mkdir(mode=0o700)
        env[key] = str(folder)
    env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1", GSETTINGS_BACKEND="memory",
               GTK_IM_MODULE="ibus", QT_IM_MODULE="ibus", XMODIFIERS="@im=ibus", GDK_BACKEND="x11",
               NO_AT_BRIDGE="1", GTK_USE_PORTAL="0", IBUS_USE_PORTAL="0", XDG_SESSION_TYPE="x11",
               SERVER_IME_EVIDENCE=str(evidence), SERVER_IME_ISOLATED="1")
    env["IBUS_ADDRESS_FILE"] = str(runtime / "ibus-address")
    # Do not let ibus-daemon discover components from user home.
    components = runtime / "components"
    components.mkdir()
    env["IBUS_COMPONENT_PATH"] = str(components)
    authority = runtime / "auth"
    authority.write_bytes(struct.pack("!H", 65535) + b"".join(
        struct.pack("!H", len(v)) + v for v in [b"", b"", b"MIT-MAGIC-COOKIE-1", secrets.token_bytes(16)]))
    env["XAUTHORITY"] = str(authority)
    processes, logs, commands = [], [], []
    summary = {"employee_id": "platform", "backend": "deterministic-fixture-v1", "result": "FAIL", "checks": []}

    def start(argv, name, pass_fds=()):
        commands.append({"name": name, "argv": argv})
        log = (evidence / (name + ".log")).open("w")
        logs.append(log)
        p = subprocess.Popen(argv, env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, pass_fds=pass_fds)
        processes.append(p)
        return p

    def check(argv, name, timeout=45):
        commands.append({"name": name, "argv": argv})
        result = subprocess.run(argv, env=env, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        (evidence / (name + ".log")).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f"{name} failed ({result.returncode}); see {evidence / (name + '.log')}")
        summary["checks"].append(name)
        print(name + ": PASS", flush=True)

    try:
        check([sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-p", "test_*.py", "-v"], "unit")
        read_fd, write_fd = os.pipe()
        try:
            # TigerVNC 1.8 (EL7) has no VNC unix socket; with -rfbport -1 it then serves no VNC at all.
            usage = subprocess.run(["/usr/bin/Xvnc", "-help"], capture_output=True, text=True)
            unix_vnc = ["-rfbunixpath", str(runtime / "vnc")] if "rfbunixpath" in usage.stdout + usage.stderr else []
            start(["/usr/bin/Xvnc", "-displayfd", str(write_fd), "-geometry", "1024x768", "-depth", "24",
                   "-rfbport", "-1", *unix_vnc, "-localhost", "-nolisten", "unix",
                   "-nolisten", "local", "-listen", "tcp", "-auth", str(authority), "-noreset"], "xserver", (write_fd,))
        finally:
            os.close(write_fd)
        try:
            # Xorg writes the number and trailing newline separately. Closing
            # after a partial read can make its second write fail with EPIPE.
            payload = b""
            deadline = time.monotonic() + 10
            while b"\n" not in payload and time.monotonic() < deadline:
                ready, _, _ = select.select([read_fd], [], [], max(0, deadline-time.monotonic()))
                if not ready:
                    break
                chunk = os.read(read_fd, 32)
                if not chunk:
                    break
                payload += chunk
            display = payload.decode().strip() if b"\n" in payload else ""
            if not display.isdecimal():
                raise RuntimeError("isolated Xvnc display unavailable; see xserver.log")
        finally:
            os.close(read_fd)
        env["DISPLAY"] = "127.0.0.1:" + display
        summary["isolated_display"] = env["DISPLAY"]
        check(["xdpyinfo", "-display", env["DISPLAY"]], "display")
        dbus_config = runtime / "session.conf"
        dbus_address = "unix:path=" + str(runtime / "session")
        dbus_config.write_text('<busconfig><type>session</type><listen>' + escape(dbus_address) +
            '</listen><auth>EXTERNAL</auth><policy context="default"><allow send_destination="*"/>'
            '<allow receive_sender="*"/><allow own="*"/></policy></busconfig>')
        start(["dbus-daemon", "--nofork", "--config-file=" + str(dbus_config)], "dbus")
        for _ in range(100):
            if (runtime / "session").exists():
                break
            time.sleep(.03)
        env["DBUS_SESSION_BUS_ADDRESS"] = dbus_address
        # IBus 1.5.25 mkdirs the entire unix:path value and 1.5.19 (EL8) knows no
        # unix:dir, so use unix:tmpdir and read its generated client address from
        # our explicit private address file.
        # 1.5.17 (EL7) has no emoji extension to turn off.
        usage = subprocess.run(["ibus-daemon", "--help"], capture_output=True, text=True).stdout
        emoji = ["--emoji-extension=disable"] if "--emoji-extension" in usage else []
        start(["ibus-daemon", "--single", "--panel=disable", "--config=disable", *emoji,
               "--cache=none", "--address=unix:tmpdir=" + str(runtime)], "ibus-daemon")
        for _ in range(100):
            address_file = Path(env["IBUS_ADDRESS_FILE"])
            if address_file.exists():
                for line in address_file.read_text().splitlines():
                    if line.startswith("IBUS_ADDRESS="):
                        env["IBUS_ADDRESS"] = line.partition("=")[2]
            if env.get("IBUS_ADDRESS"):
                break
            time.sleep(.03)
        else:
            raise RuntimeError("private IBus address unavailable; see ibus-daemon.log")
        check([sys.executable, str(ROOT / "launch.py"), "--test-backend", "--manifest", str(evidence / "server-ime-test.xml")], "manifest")
        start([sys.executable, str(ROOT / "launch.py"), "--register", "--test-backend"], "adapter")
        for _ in range(100):
            if '"event": "ready"' in (evidence / "adapter.log").read_text():
                break
            if processes[-1].poll() is not None:
                raise RuntimeError("adapter exited before registering; see adapter.log")
            time.sleep(.03)
        else:
            raise RuntimeError("adapter registration timed out")
        check([sys.executable, str(ROOT / "tests" / "ibus_client.py")], "ibus-client")
        check([sys.executable, str(ROOT / "tests" / "gtk_client.py")], "gtk-client")
        summary["result"] = "PASS"
    except Exception as exc:
        summary["error"] = str(exc)
        print(str(exc), file=sys.stderr, flush=True)
    finally:
        exits = []
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
            exits.append({"pid": process.pid, "exit_code": process.returncode})
        for log in logs:
            log.close()
        summary["processes_reaped"] = exits
        summary["commands"] = commands
        # All generated credentials, config, D-Bus sockets and caches are disposable.
        shutil.rmtree(runtime)
        summary["runtime_removed"] = not runtime.exists()
        (evidence / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n")
        print(str(evidence), flush=True)
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
