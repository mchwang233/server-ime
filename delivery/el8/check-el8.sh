#!/bin/bash
# Checks the EL8 release on a clean Rocky 8 container that has what a GNOME desktop
# brings (GTK 3, IBus, fonts) plus Xvnc for a private display. No python3 is installed.
#   /src  this repository (read only)   /rel  delivery/dist-el8 (read only)
# Run: podman run --rm --network=host --security-opt label=disable -v "$PWD":/src:ro \
#        -v "$PWD"/delivery/dist-el8:/rel:ro docker.io/rockylinux/rockylinux:8 bash /src/delivery/el8/check-el8.sh <version>
set -euo pipefail
VERSION=$1
MIRROR=${MIRROR:-https://mirrors.aliyun.com/rockylinux}
sed -i -e "s|^mirrorlist=|#mirrorlist=|" \
    -e "s|^#baseurl=http://dl.rockylinux.org/\$contentdir|baseurl=$MIRROR|" /etc/yum.repos.d/Rocky-*.repo
rpm -q tigervnc-server >/dev/null 2>&1 || dnf -y -q --setopt=timeout=120 --setopt=install_weak_deps=False install \
    gtk3 ibus ibus-gtk3 dbus-daemon dbus-x11 tigervnc-server xorg-x11-utils libXtst google-noto-sans-cjk-ttc-fonts \
    gobject-introspection libffi cairo-gobject >/dev/null
if command -v python3 >/dev/null; then echo "note: python3 present: $(command -v python3)"; else echo "no system python3"; fi
rpm -q glibc ibus gtk3 | tr '\n' ' '; echo
id tester >/dev/null 2>&1 || useradd -m tester
cat > /home/tester/run.sh <<'EOF'
set -euo pipefail
VERSION=$1
cd ~ && tar xzf /rel/server-ime-el8-$VERSION.tar.gz
DISPLAY= ./server-ime-el8-$VERSION/install.sh | tail -3
P=~/.local/opt/server-ime; C=$P/ime/current; PY=$C/python/bin/python3.11
"$P/bin/server-ime" --help >/dev/null && echo "entry: ok"

echo "== engine tests on the installed tree"
cp -rL "$C" ~/tree && cp -r /src/engine/tests /src/engine/bin ~/tree/engine/
# The JSONL tool is a source-tree helper (not installed); run it on the bundled Python.
sed -i "1s|.*|#!$PY|" ~/tree/engine/bin/server-ime-engine
for t in ~/tree/engine/tests/test_*.py; do
    printf '%-28s ' "$(basename "$t")"; "$PY" -s -B "$t" 2>&1 | grep -v "open  failed" | tail -1 || true
done

echo "== isolated GTK + IBus checks (platform/tools/run_checks.py)"
mkdir -p ~/platform ~/interface && cp -r /src/platform/server_ime /src/platform/tools /src/platform/tests /src/platform/launch.py ~/platform/ \
    && cp -r /src/interface/src /src/interface/config ~/interface/
PYTHONPATH=~/interface/src "$PY" -s -B ~/platform/tools/run_checks.py 2>&1 | tail -8 || true

echo "== typing with the real engine in a GTK entry"
"$PY" -s -B /src/delivery/el8/type_check.py "$P"
EOF
chown tester /home/tester/run.sh
su - tester -c "bash run.sh $VERSION"
