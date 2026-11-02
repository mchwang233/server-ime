# server-ime for RHEL/Rocky/Alma 9 and other glibc 2.34+ systems

The main release of server-ime, packaged the same way as the EL7 and EL8 releases. It
needs no root and installs nothing system-wide.

## Installing

On a machine with a graphical desktop (GNOME, which already brings Python 3, PyGObject,
IBus and GTK 3):

```sh
tar xzf server-ime-el9-<version>.tar.gz
cd server-ime-el9-<version>
./install.sh
```

`install.sh` installs into `~/.local/opt/server-ime` (personal data in
`~/.local/share/server-ime`), upgrades an earlier installation in place, and starts the
input method in the current desktop session. `PREFIX` and `DATA_DIR` choose other
directories. Switch between Chinese and English with Ctrl+Space or a tap of Shift.

To upgrade, run the new release's `install.sh` the same way. If the upgrade fails, nothing
changes and the version that was running is started again. If it reports that the same
version is already installed with different content, `./install.sh --repair` reinstalls it
from this archive (the old files move to `~/.local/opt/server-ime/ime/backup`).

Rollback, uninstall and the other operations: `python3 bin/ime-install --help` in this
directory, and section 0 of `delivery/docs/使用指南.md` in the source.

If the system has no desktop yet, `install.sh` names what is missing; an administrator
installs it once with `sudo dnf install python3-gobject gtk3 ibus ibus-gtk3 dbus-daemon`.

## Requirements

- glibc 2.34+ (RHEL/Rocky/Alma 9, Fedora 35+, Ubuntu 22.04+); EL7 and EL8 have their own releases
- the system's Python 3.9+ with PyGObject and GTK 3
- IBus 1.5.25+ and dbus-daemon

`server-ime-<version>.tar.gz` inside this archive is the same bundle published on its own
in the release; `delivery/el9/ime-package-el9` wraps it.
