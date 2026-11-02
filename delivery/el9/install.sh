#!/bin/sh
# Install (or upgrade to) server-ime @VERSION@ for glibc 2.34+ systems (RHEL/Rocky/Alma 9,
# Fedora, Ubuntu 22.04+), in your home directory and without root, then start it in this
# desktop session.
#   PREFIX    install directory   (default ~/.local/opt/server-ime)
#   DATA_DIR  personal data       (default ~/.local/share/server-ime)
set -e
here=$(cd "$(dirname "$0")" && pwd)
bundle="$here/server-ime-@VERSION@.tar.gz"
prefix=${PREFIX:-$HOME/.local/opt/server-ime}
data=${DATA_DIR:-$HOME/.local/share/server-ime}
run="$HOME/.cache/server-ime/run"

# This release runs on the system's Python, PyGObject, IBus and GTK 3: a GNOME desktop
# already has them. Say what is missing before installing anything.
missing=
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    missing="$missing python3(3.9+)"
elif ! python3 -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' 2>/dev/null; then
    missing="$missing python3-gobject/gtk3"
fi
command -v ibus-daemon >/dev/null 2>&1 || missing="$missing ibus"
command -v dbus-daemon >/dev/null 2>&1 || missing="$missing dbus-daemon"
if [ -n "$missing" ]; then
    echo "缺少系统组件：$missing" >&2
    echo "请管理员安装一次（RHEL/Rocky/Alma/Fedora）：" >&2
    echo "  sudo dnf install python3-gobject gtk3 ibus ibus-gtk3 dbus-daemon" >&2
    echo "（Ubuntu/Debian：sudo apt install python3-gi gir1.2-gtk-3.0 ibus dbus）" >&2
    echo "CentOS/RHEL 7、Rocky/Alma/RHEL 8 请改用 el7 / el8 版，它们自带 Python。" >&2
    exit 1
fi

action=install
[ -e "$prefix/ime/current" ] && action=upgrade
if [ "$action" = upgrade ] && [ -x "$prefix/bin/server-ime" ]; then
    "$prefix/bin/server-ime" --state-dir "$run" stop >/dev/null 2>&1 || true
fi
python3 -s "$here/bin/ime-install" "$action" "$bundle" --prefix "$prefix" --data-dir "$data"

if [ -n "$DISPLAY" ] && address=$(ibus address 2>/dev/null) && [ -n "$address" ] && [ "$address" != "(null)" ]; then
    IBUS_ADDRESS=$address "$prefix/bin/server-ime" --data-dir "$data" --state-dir "$run" start
    echo "已启动。在需要输入中文的程序里按 Ctrl+Space 切换中英文。"
else
    echo "已安装。在图形桌面的终端里运行下面的命令启动："
    echo "  IBUS_ADDRESS=\$(ibus address) \"$prefix/bin/server-ime\" --data-dir \"$data\" --state-dir \"$run\" start"
fi
