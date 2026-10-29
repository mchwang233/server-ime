# interface/ 来源、许可与第三方组件

本文件说明 `interface/`（候选面板、输入状态提示、快捷键/标点选项与中文设置界面）的代码来源、
许可范围，以及运行/检查时用到的第三方组件及其原许可。所有内容依据本机实际文件与 `rpm` 元数据核对，
没有从其它项目复制源码，也没有替代上游声明授权或署名。

## 1. 原创部分与许可

`interface/` 下除 `evidence/` 中记录的系统日志外，其余文件均为本项目为本任务原创：

| 路径 | 内容 |
|---|---|
| `src/ime_interface/{config,keymap,punctuation,panel,settings_ui,bridge,app}.py` | 设置格式与校验、快捷键、标点映射、GTK3 候选面板、GTK3 中文设置界面、平台 D-Bus 客户端封装、命令行入口 |
| `bin/ime-interface` | 启动包装脚本 |
| `config/{defaults.json,settings-v1.schema.json,capabilities-fixture.json}` | 默认设置、设置格式 v1 的 JSON Schema、**仅用于检查**的能力夹具 |
| `tests/`、`tools/`、`docs/`、`README.md` | 单测、隔离界面场景、自检入口、文档 |
| `evidence/` | 本组件自检产生的截图、JSON 与日志（含 IBus/Xvnc 等系统进程自身输出的日志） |

这些原创文件采用 **GPL-3.0-or-later**，完整许可文本在 [`LICENSE`](LICENSE)（文件头含 SPDX 行与
版权声明）。选择该许可与本产品其它原创代码一致（`engine/`、`integration/`、`lexicon/` 代码同为
GPL-3.0-or-later；`platform/` 为 MIT，`lexicon/` 的词库数据为 CC-BY-4.0）：本组件运行时会通过
`engine/` 绑定 GPL-3.0-or-later 的 libpinyin，并与 `engine/`、`platform/` 一起由发布包分发，
各组件许可互不覆盖，均保留各自原文。

`config/capabilities-fixture.json` 是**检查用夹具**，其中把双拼/模糊音/纠错/学习声明为可用，
不代表引擎真实能力，也不是从任何第三方项目取得的数据。

`interface/` 不包含任何第三方源码副本、二进制、词库或字体；`src/`、`tests/`、`tools/`
中没有第三方版权头或 SPDX 标记（已用 `grep -rIn "SPDX\|Copyright\|GPL\|MIT\|LGPL"` 核对，
仅有本组件自己的引用与测试用的 X11 cookie 名称，无外部代码）。

## 2. 运行期依赖（系统包，不随 `interface/` 分发）

| 组件 | 本机版本（RPM） | 上游许可 | 用途 |
|---|---|---|---|
| GTK 3（Gtk/Gdk） | `gtk3-3.24.31-8.el9` | LGPL-2.1-or-later（RPM 标注 `LGPLv2+`） | 候选面板与设置窗口控件 |
| PyGObject (gi) | `python3-gobject-3.40.1-6.el9` | LGPL-2.1-or-later 与 MIT（RPM `LGPLv2+ and MIT`） | GTK/IBus 的 Python 绑定 |
| GLib / GObject | `glib2-2.68.4-19.el9_8.1` | LGPL-2.1-or-later（RPM `LGPLv2+`） | 主循环、事件与 idle 回调 |
| Pango | `pango-1.48.7-3.el9` | LGPL-2.1-or-later（RPM `LGPLv2+`） | 文本布局与字号缩放 |
| IBus | `ibus-1.5.25-6.el9` | LGPL-2.1-or-later（RPM `LGPLv2+`） | 仅检查脚本用于启动私有 IBus 总线/引擎；运行代码只通过平台 D-Bus 接口取状态 |
| libpinyin | `libpinyin-2.6.0-4.el9` | GPL-3.0-or-later（RPM `GPLv3+`） | 经 `engine/` 的 ctypes 绑定提供真实转换；`interface/` 不直接链接 |
| Python | `python3-3.9.25-7.el9_8` | PSF-2.0（RPM `Python`） | 运行时语言 |

`interface/` 只 `import gi`/`Gtk`/`Gdk`/`GLib`/`Pango`，通过 `PYTHONPATH` 使用 `platform/`
的 `server_ime.ui_client` 与 `engine/` 的 `server_ime_engine`；**没有复制**这两个组件的源码，
它们各自的许可与来源见 `platform/README.md`、`engine/README.md` 与 `engine/LICENSE`。

## 3. 检查用外部程序（只在自检时启动，不属于交付运行依赖）

| 程序 | 本机版本 | 许可 | 用途 |
|---|---|---|---|
| Xvnc（TigerVNC） | 1.15.0 | GPL-2.0-or-later | `tools/run_checks.py`、`tools/native_panel_probe.py` 启动的隔离 X 显示（`127.0.0.1:<n>`） |
| XTest（libXtst） / libX11 | `libXtst-1.2.3-16.el9`、`libX11-1.8.12-1.el9` | MIT / MIT AND X11 | `tests/x11.py` 经 ctypes 注入键盘、鼠标事件 |
| dbus-daemon | `dbus-1.12.20-8.el9` | GPL-2.0-or-later 或 AFL-2.1（RPM `(GPLv2+ or AFL) and GPLv2+`） | 检查用私有会话总线 |
| ibus-daemon / ibus-engine-libpinyin | `ibus-1.5.25-6.el9`、`libpinyin-2.6.0-4.el9` | LGPL-2.1-or-later / GPL-3.0-or-later | 检查中运行真实引擎链路 |

这些程序由系统包提供，`interface/` 不分发它们的二进制或源码；其许可文本在各自系统包的
`/usr/share/licenses/<包名>/` 下。检查时产生的日志（`evidence/*/xserver.log`、`ibus-daemon.log` 等）
保留原样，仅作为证据，不改变其归属。

## 4. 字体与数据

* 界面使用系统字体渲染中文（本机 `google-noto-cjk` 等），`interface/` **不打包字体**；
  字体许可由系统包提供（Noto CJK 为 OFL-1.1）。
* `config/defaults.json` 与 `settings-v1.schema.json` 为本项目原创设置数据；不含个人词库或用户输入。
* 自检产生的截图与 JSON 为本项目原创证据，其中出现的候选文字来自检查用的固定测试输入。

## 5. 许可核验记录（2026-10-29，本机实跑）

| 检查 | 命令 | 结果 |
|---|---|---|
| 许可文件完整性 | `wc -c -l interface/LICENSE` | 36,160 字节 / 696 行；前 22 行为 SPDX 头，正文 35,147 字节 |
| 正文是否逐字等于 GPL-3.0 | `sed -n '23,696p' interface/LICENSE > /tmp/if_gpl.txt && diff -u /usr/share/doc/libpinyin/COPYING /tmp/if_gpl.txt` | 无差异（rc=0），即完整未改动的 GNU GPL v3 全文 |
| 是否存在第三方代码 | `grep -rIn "SPDX\|Copyright" interface/src interface/tests interface/tools interface/bin interface/config` | 无匹配：`interface/` 原创文件不含他人版权头或 SPDX 标记，也没有 `Copyright (C) 2026 server-ime contributors` 之外的署名 |
| 依赖版本 | `rpm -q gtk3 python3-gobject glib2 pango ibus libpinyin python3 libXtst libX11 dbus tigervnc-server-minimal` | 与本文件第 2、3 节列出的版本逐项一致（如 `gtk3-3.24.31-8.el9`、`libpinyin-2.6.0-4.el9`） |
| 许可字段一致性 | `python3 -c "import json;..."`（见下） | `handoff.json` 的 `license=GPL-3.0-or-later`、`license_file=interface/LICENSE`、`sources_file=interface/SOURCES.md`，两文件均存在 |

交付前的自检命令（发布包可复跑）：

```bash
python3 -c "import json; from pathlib import Path; h=json.loads(Path('interface/handoff.json').read_text()); \
assert h['license']=='GPL-3.0-or-later'; assert Path(h['license_file']).is_file(); \
assert Path(h['sources_file']).is_file(); print('interface license metadata: PASS')"
```

未做而未声明的事：本组件没有自行判断 libpinyin 之外的第三方（如 Xvnc、dbus）许可文本内容是否完整，
只记录其系统包与 RPM 许可字段；发布包若决定随包分发这些程序，需按第 4 节约定另补许可原文与源码获取方式。

## 6. 维护约定

* 新增第三方代码/数据时，必须在此文件登记来源、版本、许可与许可文本位置，并在 `interface/LICENSE`
  之外单独保留其原始许可文本；不得改写或删除上游版权与许可声明。
* 若未来把 GTK/IBus 等库或字体随安装包分发，需要同时补入对应许可文本与（GPL/LGPL 组件的）源码获取方式。
* 本组件的许可元数据同步记录在 `interface/handoff.json` 的 `license`、`license_file`、`sources_file`
  字段，供发布包汇总（`delivery/docs/licenses.md`）引用。
