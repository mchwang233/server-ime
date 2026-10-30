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

1. Third-party sources in `/projects/workspace/ime-deps/src` (fmt 10.2.1, ECM 6.29.0,
   fcitx5 5.1.12, libime 1.1.11) and the Python download in
   `/projects/workspace/ime-deps/el8/downloads/python-3.11.10.tar.gz`
   (sha256 8b50a442b04724a24c1eebb65a36a0c0e833d35374dbdf9c9470d8a97b164cd9).
2. Native libraries and Python, in a Rocky 8 container:

   ```sh
   D=/projects/workspace/ime-deps
   podman run --rm --network=host --security-opt label=disable \
     -v "$PWD":/src:ro -v $D/src:/deps:ro -v $D/el8/downloads:/dl:ro -v $D/el8/out:/out \
     docker.io/rockylinux/rockylinux:8 bash /src/delivery/el8/build-native.sh
   ```

3. The release: `python3 delivery/el8/ime-build-el8 --version <version>` writes
   `delivery/dist-el8/server-ime-el8-<version>.tar.gz`.
4. Checks on Rocky 8: `delivery/el8/check-el8.sh` (see that script).
