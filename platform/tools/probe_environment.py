#!/usr/bin/python3
"""Read only public system facts; never inspect home configuration or other sessions."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    records = []

    def run(argv):
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=10)
            rec = {"command": argv, "exit_code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
        except (OSError, subprocess.TimeoutExpired) as exc:
            rec = {"command": argv, "error": str(exc)}
        records.append(rec)
        return rec

    run(["cat", "/etc/os-release"])
    run(["uname", "-srmo"])
    run(["id"])
    sessions = run(["loginctl", "list-sessions", "--no-legend"])
    for line in sessions.get("stdout", "").splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[1] == str(os.getuid()):
            run(["loginctl", "show-session", fields[0], "-p", "Id", "-p", "Type", "-p", "Display",
                 "-p", "Remote", "-p", "Service", "-p", "State", "-p", "Seat"])
    run(["ibus", "version"])
    run(["rpm", "-q", "ibus", "ibus-gtk3", "python3-gobject", "gtk3", "libXtst", "libX11", "tigervnc-server", "fcitx5"])
    for module in ["ibus-1.0", "glib-2.0", "gio-2.0", "gtk+-3.0", "fcitx5", "libpinyin"]:
        run(["pkg-config", "--print-errors", "--exists", module])
    run(["pkg-config", "--version"])
    run(["journalctl", "--version"])
    run(["/usr/bin/python3", "-c", "import gi; gi.require_version('IBus','1.0'); gi.require_version('Gtk','3.0'); from gi.repository import IBus,Gtk; print('IBus GI', IBus.MAJOR_VERSION, IBus.MINOR_VERSION, IBus.MICRO_VERSION); print('Gtk GI', Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version())"])
    data = {"employee_id": "platform", "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "environment": {k: os.environ.get(k, "") for k in ["DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE",
                "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "GTK_IM_MODULE", "QT_IM_MODULE", "XMODIFIERS"]},
            "executables": {k: shutil.which(k) for k in ["Xvnc", "Xvfb", "ibus-daemon", "dbus-daemon", "fcitx5", "wayland-info", "xdpyinfo"]},
            "commands": records,
            "restrictions": ["No reads of user home/config/auth files or /tmp/.X11-unix",
                "No host display/bus connection, session activation, gsettings mutation, or service changes"]}
    Path(args.output).write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n")
    print(args.output)


if __name__ == "__main__":
    main()
