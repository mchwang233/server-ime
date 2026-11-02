# server-ime for Rocky / Alma / RHEL 8

A separate release of server-ime for EL8 (glibc 2.28) and newer systems. It needs no
root and installs nothing system-wide.

## Installing

On a machine with a graphical desktop (GNOME, which already brings IBus and GTK 3):

```sh
tar xzf server-ime-el8-<version>.tar.gz
cd server-ime-el8-<version>
./install.sh
```

`install.sh` installs into `~/.local/opt/server-ime` (personal data in
`~/.local/share/server-ime`), upgrades an earlier installation in place, and starts the
input method in the current desktop session. `PREFIX` and `DATA_DIR` choose other
directories. Switch between Chinese and English with Ctrl+Space.

## What differs from the main release

| | main release | EL8 release |
|---|---|---|
| systems | glibc 2.34+ (EL9, Fedora 35+, Ubuntu 22.04+) | glibc 2.28+ (EL8 and newer) |
| Python | the system's 3.9+ with PyGObject | bundled 3.11.10 (python-build-standalone) with PyGObject 3.42.2 and pycairo 1.26.1 |
| libpinyin, libime | built on EL9 | rebuilt on Rocky 8 with gcc-toolset-12; glib, libdb and pcre from Rocky 8 |
| IBus | 1.5.25+ | 1.5.19+ (the desktop's) |

The dictionaries, language models and all Python code are the same.

## Building

1. Put these upstream archives in one directory, `$DEPS/src` (the release's `-sources.tar.gz`
   holds the first three under `third-party/`):
   - `libime-1.1.11.tar.zst`, `fcitx5-5.1.12.tar.zst` (download.fcitx-im.org)
   - `fmt-10.2.1.tar.gz` (github.com/fmtlib/fmt, tag 10.2.1)
   - `extra-cmake-modules-6.29.0.tar.xz` (download.kde.org)
   - `boost_1_83_0.tar.bz2` (archives.boost.io)

   and python-build-standalone's 3.11.10 x86_64-unknown-linux-gnu install_only archive as
   `$DEPS/downloads/python-3.11.10.tar.gz`
   (sha256 8b50a442b04724a24c1eebb65a36a0c0e833d35374dbdf9c9470d8a97b164cd9).
   The build also reads `engine/vendor/libpinyin-2.6.0.tar.gz` from this repository (not in git:
   it is in the `-sources.tar.gz`, and its download address is in `engine/dependencies.json`).
2. Native libraries and Python, in a Rocky 8 container, into `delivery/build/el8-native`:

   ```sh
   mkdir -p delivery/build/el8-native
   podman run --rm --network=host --security-opt label=disable \
     -v "$PWD":/src:ro -v "$DEPS"/src:/deps:ro -v "$DEPS"/downloads:/dl:ro \
     -v "$PWD"/delivery/build/el8-native:/out docker.io/rockylinux/rockylinux:8 bash /src/delivery/el8/build-native.sh
   ```

3. The release: `python3 delivery/el8/ime-build-el8 --version <version>` writes
   `delivery/dist-el8/server-ime-el8-<version>.tar.gz` (`SERVER_IME_EL8_NATIVE` names another
   native directory).
4. Checks on Rocky 8: `delivery/el8/check-el8.sh` (see that script).
