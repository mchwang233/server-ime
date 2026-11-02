#!/bin/sh
# Install (or upgrade to) server-ime @VERSION@ for CentOS/RHEL 7, in your home
# directory and without root, then start it in this desktop session.
#   PREFIX    install directory   (default ~/.local/opt/server-ime)
#   DATA_DIR  personal data       (default ~/.local/share/server-ime)
# Arguments go to ime-install, e.g. ./install.sh --repair to reinstall the same version.
set -e
here=$(cd "$(dirname "$0")" && pwd)
bundle="$here/server-ime-@VERSION@.tar.gz"
prefix=${PREFIX:-$HOME/.local/opt/server-ime}
data=${DATA_DIR:-$HOME/.local/share/server-ime}
run="$HOME/.cache/server-ime/run"

# The installer runs on the Python inside the bundle: EL7 has no python3.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
tar xzf "$bundle" -C "$tmp" payload/python
python="$tmp/payload/python/bin/python3.11"
action=install
[ -e "$prefix/ime/current" ] && action=upgrade
if [ "$action" = upgrade ] && [ -x "$prefix/bin/server-ime" ]; then
    "$prefix/bin/server-ime" --state-dir "$run" stop >/dev/null 2>&1 || true
fi
start() {
    [ -n "$DISPLAY" ] && address=$(ibus address 2>/dev/null) && [ -n "$address" ] && [ "$address" != "(null)" ] &&
        IBUS_ADDRESS=$address "$prefix/bin/server-ime" --data-dir "$data" --state-dir "$run" start
}
status=0
"$python" -s "$here/bin/ime-install" "$action" "$bundle" --prefix "$prefix" --data-dir "$data" "$@" || status=$?
if [ "$status" -ne 0 ]; then
    # Nothing changed: bring back the input method stopped above.
    [ "$action" = upgrade ] && start >/dev/null 2>&1 && echo "未升级，原来的版本已重新启动。" >&2
    [ "$status" -eq 3 ] && echo "如果确实要用这个包覆盖已装的同版本，运行：./install.sh --repair" >&2
    exit "$status"
fi

if start; then
    echo "已启动。在需要输入中文的程序里按 Ctrl+Space 切换中英文。"
else
    echo "已安装。在图形桌面的终端里运行下面的命令启动："
    echo "  IBUS_ADDRESS=\$(ibus address) \"$prefix/bin/server-ime\" --data-dir \"$data\" --state-dir \"$run\" start"
fi
