# server-ime for CentOS / RHEL 7

A separate release of server-ime for EL7 (glibc 2.17) and newer systems. It needs no
root and installs nothing system-wide.

## Installing

On a machine with a graphical desktop (GNOME, which already brings IBus and GTK 3):

```sh
tar xzf server-ime-el7-<version>.tar.gz
cd server-ime-el7-<version>
./install.sh
```

`install.sh` installs into `~/.local/opt/server-ime` (personal data in
`~/.local/share/server-ime`), upgrades an earlier installation in place, and starts the
input method in the current desktop session. `PREFIX` and `DATA_DIR` choose other
directories. Switch between Chinese and English with Ctrl+Space.

If IBus is not the desktop's input method yet: `yum install ibus ibus-gtk3` (as root), choose
IBus in the region and language settings, then log in again.

## What differs from the main release

| | main release | EL7 release |
|---|---|---|
| systems | glibc 2.34+ (EL9, Fedora 35+, Ubuntu 22.04+) | glibc 2.17+ (CentOS/RHEL 7 and newer) |
| Python | the system's 3.9+ with PyGObject | bundled 3.11.10 (python-build-standalone) with PyGObject 3.42.2 and pycairo 1.26.1 |
| libpinyin, libime | built on EL9 | rebuilt on CentOS 7 with devtoolset-11; glib, libdb and pcre from CentOS 7, zstd from EPEL 7 |
| IBus | 1.5.25+ | 1.5.17+ (the desktop's) |

The dictionaries, language models and all Python code are the same.

## Building

CentOS 7 is end of life: the scripts take packages from the CentOS vault and EPEL archive
(`MIRROR`, default `https://mirrors.aliyun.com`).

1. Third-party sources in `/projects/workspace/ime-deps/src` (fmt 10.2.1, ECM 6.29.0,
   fcitx5 5.1.12, Boost 1.83.0, libime 1.1.11) and the Python download in
   `/projects/workspace/ime-deps/el8/downloads/python-3.11.10.tar.gz`
   (sha256 8b50a442b04724a24c1eebb65a36a0c0e833d35374dbdf9c9470d8a97b164cd9).
2. Native libraries and Python, in a CentOS 7 container:

   ```sh
   D=/projects/workspace/ime-deps
   podman run --rm --network=host --security-opt label=disable \
     -v "$PWD":/src:ro -v $D/src:/deps:ro -v $D/el8/downloads:/dl:ro -v $D/el7/out:/out \
     docker.io/library/centos:7 bash /src/delivery/el7/build-native.sh
   ```

3. The release: `python3 delivery/el7/ime-build-el7 --version <version>` writes
   `delivery/dist-el7/server-ime-el7-<version>.tar.gz`.
4. Checks on CentOS 7: `delivery/el7/check-el7.sh` (see that script).
