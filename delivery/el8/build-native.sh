#!/bin/bash
# Builds the EL8 runtime inside a rockylinux:8 container (see delivery/el8/README.md):
#   /src  this repository (read only)
#   /deps third-party source archives, /dl the Python download (read only)
#   /out  results: lib/ (libpinyin + libime), python/ (Python 3.11 with PyGObject)
set -euo pipefail
MIRROR=${MIRROR:-https://mirrors.aliyun.com/rockylinux}
sed -i -e "s|^mirrorlist=|#mirrorlist=|" \
    -e "s|^#baseurl=http://dl.rockylinux.org/\$contentdir|baseurl=$MIRROR|" /etc/yum.repos.d/Rocky-*.repo
dnf -y -q --enablerepo=powertools --setopt=timeout=120 install \
    gcc-toolset-12 cmake make autoconf automake libtool gettext-devel pkgconfig gtk3 ibus-libs \
    glib2-devel libdb-devel libzstd-devel zlib-devel bzip2-devel \
    gobject-introspection-devel cairo-devel cairo-gobject-devel libffi-devel zstd xz bzip2 >/dev/null
source /opt/rh/gcc-toolset-12/enable
P=/opt/sime; W=/tmp/w; mkdir -p $P $W /out/lib /out/licenses
cd $W
# A newer CMake for the build only (ECM 6.29 needs 3.29; Rocky 8 has 3.26).
mkdir -p /tmp/bpy && tar xzf /dl/python-3.11.10.tar.gz -C /tmp/bpy
/tmp/bpy/python/bin/python3.11 -m pip install -q cmake==3.31.6
export PATH=/tmp/bpy/python/bin:$PATH
cmake --version | head -1

# fmt, ECM, fcitx5 utils (no event loop, X11, Wayland or D-Bus), libime: as for EL9.
tar xzf /deps/fmt-10.2.1.tar.gz
cmake -S fmt-10.2.1 -B b-fmt -DCMAKE_INSTALL_PREFIX=$P -DCMAKE_BUILD_TYPE=Release -DFMT_TEST=OFF -DFMT_DOC=OFF \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DBUILD_SHARED_LIBS=ON >/dev/null
cmake --build b-fmt -j"$(nproc)" >/dev/null
cmake --install b-fmt >/dev/null
tar xJf /deps/extra-cmake-modules-6.29.0.tar.xz
cmake -S extra-cmake-modules-6.29.0 -B b-ecm -DCMAKE_INSTALL_PREFIX=$P -DBUILD_TESTING=OFF -DBUILD_HTML_DOCS=OFF \
    -DBUILD_MAN_DOCS=OFF -DBUILD_QTHELP_DOCS=OFF >/dev/null
cmake --build b-ecm --target install >/dev/null
zstd -dc /deps/fcitx5-5.1.12.tar.zst | tar x
# Only the utility library is used: skip desktop data and translations (Rocky 8's gettext is too old).
sed -i -e '/add_subdirectory(data)/d' -e '/add_subdirectory(po)/d' fcitx5-5.1.12/CMakeLists.txt
cmake -S fcitx5-5.1.12 -B b-fcitx5 -DCMAKE_INSTALL_PREFIX=$P -DCMAKE_PREFIX_PATH=$P -DCMAKE_BUILD_TYPE=Release \
    -DEVENT_LOOP_BACKEND=none -DENABLE_X11=Off -DENABLE_WAYLAND=Off -DENABLE_DBUS=Off -DENABLE_KEYBOARD=Off \
    -DENABLE_SERVER=Off -DENABLE_EMOJI=Off -DENABLE_ENCHANT=Off -DENABLE_LIBUUID=Off -DENABLE_TEST=Off \
    -DENABLE_TESTING_ADDONS=Off -DBUILD_SPELL_DICT=Off -DENABLE_XDGAUTOSTART=Off -DENABLE_DOC=Off -DCMAKE_INSTALL_RPATH='$ORIGIN' >/dev/null
cmake --build b-fcitx5 -j"$(nproc)" >/dev/null
cmake --install b-fcitx5 >/dev/null
sed -i 's/set(CMAKE_CXX_STANDARD 17)/set(CMAKE_CXX_STANDARD 20)/' $P/lib64/cmake/Fcitx5Utils/Fcitx5CompilerSettings.cmake
# Boost 1.83 iostreams, static (Rocky 8's 1.66 lacks headers libime uses).
tar xjf /deps/boost_1_83_0.tar.bz2
(cd boost_1_83_0 && ./bootstrap.sh --with-libraries=iostreams --prefix=/opt/boost >/dev/null \
    && ./b2 -j"$(nproc)" -d0 link=static variant=release cxxflags=-fPIC cflags=-fPIC install >/dev/null)
zstd -dc /deps/libime-1.1.11.tar.zst | tar x
sed -i '27,35s/^/#/' libime-1.1.11/tools/CMakeLists.txt  # the fcitx4 migration tools are not needed
# The dictionary and model come prebuilt from engine/vendor/libime/data; skip building them.
echo > libime-1.1.11/data/CMakeLists.txt
cmake -S libime-1.1.11 -B b-libime -DCMAKE_INSTALL_PREFIX=$P -DCMAKE_PREFIX_PATH=$P -DCMAKE_BUILD_TYPE=Release \
    -DENABLE_TEST=Off -DENABLE_DOC=Off -DCMAKE_INSTALL_RPATH='$ORIGIN' -DBoost_ROOT=/opt/boost -DBoost_USE_STATIC_LIBS=ON >/dev/null
cmake --build b-libime -j"$(nproc)" >/dev/null
cmake --install b-libime >/dev/null
g++ -std=c++20 -O2 -fPIC -shared -o /out/lib/libsime_libime.so /src/engine/native/sime_libime.cpp \
    -I$P/include/LibIME -I$P/include/Fcitx5/Utils -I/opt/boost/include -L$P/lib64 -lIMEPinyin -lIMECore -lFcitx5Utils -Wl,-rpath,'$ORIGIN'
for name in libFcitx5Utils.so.2 libIMECore.so.0 libIMEPinyin.so.0; do
    cp -L $P/lib64/$name /out/lib/$name
done

# libpinyin 2.6.0 (Berkeley DB, as the EL9 package), with EL8's glib, libdb and pcre beside it.
tar xzf /src/engine/vendor/libpinyin-2.6.0.tar.gz
cd libpinyin-*/ && ./autogen.sh --prefix=$P --with-dbm=BerkeleyDB --disable-libzhuyin >/dev/null 2>&1 || \
    ./configure --prefix=$P --with-dbm=BerkeleyDB --disable-libzhuyin >/dev/null
make -C src -j"$(nproc)" >/dev/null
make -C src install >/dev/null
cd $W
cp -L $P/lib/libpinyin.so.13 /out/lib/libpinyin.so.13.0.0
cp -L /usr/lib64/libglib-2.0.so.0 /usr/lib64/libdb-5.3.so /usr/lib64/libpcre.so.1 /out/lib/

# Python 3.11 (python-build-standalone) with PyGObject 3.42.2, the last release for
# gobject-introspection 1.56, and pycairo; trimmed of what the input method never uses.
rm -rf /out/python && tar xzf /dl/python-3.11.10.tar.gz -C /out
PY=/out/python/bin/python3.11
# python-build-standalone records clang as its compiler; build the extensions with gcc.
CC=gcc CXX=g++ LDSHARED="gcc -shared" $PY -m pip install -q --no-cache-dir --no-warn-script-location pycairo==1.26.1 PyGObject==3.42.2
$PY -m pip uninstall -q -y pip setuptools >/dev/null 2>&1 || true
L=/out/python/lib/python3.11
rm -rf $L/test $L/idlelib $L/tkinter $L/turtledemo $L/lib2to3 $L/ensurepip $L/site-packages/*.dist-info/RECORD \
    /out/python/lib/libtcl* /out/python/lib/libtk* /out/python/lib/tcl* /out/python/lib/tk* /out/python/include \
    /out/python/share $L/config-3.11-x86_64-linux-gnu
find /out/python -name __pycache__ -type d -prune -exec rm -rf {} +
find /out/python/bin -mindepth 1 ! -name python3.11 -delete
$PY -c "import gi; gi.require_version('Gtk','3.0'); gi.require_version('IBus','1.0'); from gi.repository import Gtk, IBus; print('gi', gi.__version__)"
echo BUILD-OK
