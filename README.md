# server-ime

一个运行在 Linux 桌面（X11 + IBus）上的中文拼音输入法，全部在本机处理，不联网、不上传输入内容，
安装不需要 root。

A Chinese pinyin input method for Linux desktops (X11 + IBus). Everything runs locally: no
network, no cloud, no root needed to install.

## 功能

- 全拼整句输入：libime 解码（与 fcitx5 同一套引擎和语言模型），带下一个词的联想
- 中英混输：中文模式下直接打 `github`、`docker` 这类英文词
- 单按 Shift 或 `Ctrl+Space` 切换中英文
- 自然码双拼、模糊音、常见拼写纠错
- 个人词库：自定义短语；可选的输入学习（默认关闭，数据只存本机）
- 候选面板跟随光标，GTK 设置界面

## 支持的系统

| 版本 | 系统 | 说明 |
| --- | --- | --- |
| 主版本 | glibc 2.34+（RHEL/Rocky/Alma 9、Fedora 35+、Ubuntu 22.04+） | 使用系统的 Python 3.9+ 与 PyGObject，IBus 1.5.25+ |
| EL8 版 | Rocky/Alma/RHEL 8 及更新 | 自带 Python 3.11，IBus 1.5.19+ |
| EL7 版 | CentOS/RHEL 7 及更新 | 自带 Python 3.11，IBus 1.5.17+ |

只在 X11 会话中验证过；Wayland 未验证。

## 安装

从 [Releases](https://github.com/mchwang233/server-ime/releases) 下载对应系统的安装包。

解压后运行 `install.sh`，三个版本的方法一样：

```sh
tar xzf server-ime-el9-<版本>.tar.gz      # 或 server-ime-el8-…、server-ime-el7-…
cd server-ime-el9-<版本>
./install.sh
```

`install.sh` 安装到 `~/.local/opt/server-ime`（个人数据在 `~/.local/share/server-ime`），
已装过的会就地升级，在图形桌面的终端里运行时会直接启动。

主版本（el9 包）用系统的 Python、PyGObject、IBus 和 GTK 3，装了 GNOME 桌面的系统都已自带；
缺少时 `install.sh` 会列出缺什么，由管理员装一次：
`sudo dnf install python3-gobject gtk3 ibus ibus-gtk3 dbus-daemon`。EL7 / EL8 版自带 Python，不需要这一步。

升级：下载新版本的包，同样解压后运行 `./install.sh`，它会先停掉正在运行的旧版本，装好后再启动新版本。
升级没成功时（比如包有问题），`install.sh` 会把原来的版本重新启动，什么都不改。
如果提示“版本已存在且内容不同”（已装的同版本文件被改过，或同一版本号的包重新发布过），
确认要用这个包覆盖时运行 `./install.sh --repair`，旧文件会移到 `~/.local/opt/server-ime/ime/backup`。

回滚、卸载、校验等其他操作见 [delivery/docs/使用指南.md](delivery/docs/使用指南.md)。

以后每次登录后，在图形桌面的终端里启动：

```sh
IBUS_ADDRESS=$(ibus address) ~/.local/opt/server-ime/bin/server-ime \
    --data-dir ~/.local/share/server-ime --state-dir ~/.cache/server-ime/run start
```

### 打开输入学习

学习功能默认关闭。打开后，从候选里选过的词，下次输入相同拼音时会排在前面。

```sh
~/.local/opt/server-ime/bin/server-ime --state-dir ~/.cache/server-ime/run settings        # 打开“个人输入学习”
~/.local/opt/server-ime/bin/server-ime --state-dir ~/.cache/server-ime/run learning-status # 查看是否开启、已学词数
```

## 从源码构建

每个 Release 都附有对应源码包 `*-sources.tar.gz`，内含该版本的项目源码和全部第三方上游源码。

- 主版本：`python3 delivery/bin/ime-build --version <版本>`，再用 `delivery/el9/ime-package-el9 --version <版本>` 打成带 `install.sh` 的包；详见 [delivery/docs/SOURCE-BUILD.md](delivery/docs/SOURCE-BUILD.md)。
  第三方源码与运行库的下载地址和校验和在 `engine/dependencies.json`、`engine/vendor.lock.json`。
- EL8 / EL7 版：在 `el8` / `el7` 分支的 `delivery/el8/README.md`、`delivery/el7/README.md`，用容器构建。

## 目录

| 目录 | 内容 |
| --- | --- |
| `engine/` | 拼音转换引擎（libpinyin、libime 的 ctypes 绑定，候选与学习逻辑） |
| `lexicon/` | 词库格式、个人词库存储 |
| `platform/` | IBus 适配层 |
| `interface/` | 候选面板与设置界面（GTK 3） |
| `integration/` | 产品装配、`server-ime` 入口与进程管理 |
| `delivery/` | 构建、安装包、安装工具、发布文档 |

## 测试

```sh
for t in engine/tests/test_*.py; do python3 "$t"; done
python3 -m unittest discover -s platform/tests
python3 platform/tools/run_checks.py      # 需要 Xvnc、dbus-daemon、ibus-daemon：在隔离的显示和总线上测试
```

## 许可

GPL-3.0-or-later，见 [LICENSE](LICENSE)。`platform/` 为 MIT。
随包的第三方组件、数据及其许可见 [delivery/docs/licenses.md](delivery/docs/licenses.md)；
其中英文词表 `engine/data/english-v1.txt` 派生自 FrequencyWords（CC-BY-SA-4.0）。
