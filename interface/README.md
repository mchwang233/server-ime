# 服务器输入法 · 交互界面（employee_id=interface）

候选展示与选择、翻页、输入状态提示、中英切换、标点选项、快捷键配置与中文设置界面。消费
`platform/` 的候选/状态 D-Bus 接口（`org.superpartner.ServerIME1`）与 `engine/` 的
`capabilities()`/`configure()`，不自己实现转换，不改平台按键与焦点生命周期。

## 组件

| 模块 | 内容 |
|---|---|
| `src/ime_interface/config.py` | 设置格式 v1、校验（类型/范围/能力门控/快捷键）、原子保存（0600）、恢复默认、`engine_patch()`/`platform_patch()`/`apply_engine()`、映射报告 |
| `src/ime_interface/keymap.py` | 快捷键格式 `MOD+Key`、解析、冲突与非法绑定校验、按键解析（与平台 `Controller.key` 判定顺序一致） |
| `src/ime_interface/punctuation.py` | 中文标点映射表（含成对引号/括号）与预览 |
| `src/ime_interface/panel.py` | GTK3 候选面板 + 中/英/后端状态提示；候选**从左到右横排**（默认，`panel.layout` 可改回旧式单列）、鼠标点击选词、滚轮/‹› 翻页、点击徽标切中英、字号缩放；超宽时先省略文字，仍超宽则用单行横向滚动视口（可见滚动条、高亮自动滚入视野），**本页候选一个不丢**，面板绝不超出屏幕 |
| `src/ime_interface/settings_ui.py` | GTK3 中文设置界面；只对引擎支持的选项显示控件 |
| `src/ime_interface/bridge.py` | 平台 `StateClient` 的薄封装（按显示中的快照 revision 发动作） |
| `config/` | `defaults.json`、`settings-v1.schema.json`、`capabilities-fixture.json`（夹具，见下） |
| `tools/run_checks.py` | 自检入口：无显示单测 + 隔离 X11/D-Bus/IBus 下的真实界面检查 |
| `tests/` | 单测与界面场景脚本 |
| `evidence/run-*/` | 每次检查的截图、日志与 JSON 结果；`evidence/latest.json` 指向最近一次 |

## 用法

```bash
export PYTHONPATH=$PWD/interface/src:$PWD/platform:$PWD/engine/src
python3 -m ime_interface.app validate            # 校验并打印设置映射
python3 -m ime_interface.app save --set-page-size 7
python3 -m ime_interface.app reset               # 恢复默认
python3 -m ime_interface.app apply-engine        # 映射到真实引擎 configure 并回读
python3 -m ime_interface.app settings            # 中文设置界面（需要显示）
python3 -m ime_interface.app panel               # 候选面板（需要显示 + IBUS_ADDRESS）
```

设置文件默认 `$XDG_CONFIG_HOME/server-ime/settings.json`（未设置时 `~/.config/...`），
`SERVER_IME_CONFIG` 可覆盖。格式见 `docs/config-format.md`，快捷键见 `docs/shortcuts.md`，
设置项到配置接口的对应关系见 `docs/mapping.md`。

## 真实组件与夹具

* **真实**：GTK3 候选面板与设置窗口、设置格式与校验、快捷键校验、标点映射表、平台 D-Bus
  候选/状态接口、GTK3 应用输入框、IBus 1.5 适配器、libpinyin 2.6.0 转换后端（`backend=libpinyin`，
  `deterministic=false`）。检查中面板点击选词、数字键选词、键盘与滚轮翻页、徽标切中英都走这些真实组件。
* **夹具**：`config/capabilities-fixture.json` 把双拼/模糊音/纠错/学习声明为可用，仅用于检查
  “能力开启时设置界面会出现对应控件”。真实引擎 `capabilities.features` 中这四项仍为 `false`，
  因此默认界面**不显示**这些开关，只在“引擎未支持”区域列出。夹具不是功能已实现的证据。

## 检查

```bash
python3 interface/tools/run_checks.py
```

在 `interface/.runtime/` 下自建 Xvnc（`127.0.0.1:<n>`）、私有 D-Bus 与私有 IBus 地址，不使用宿主显示与会话；
结束后清理运行目录。最近一次结果：**PASS**（`unit` 51 项、`display`、`manifest`、`panel-ui` 18 项、
`settings-ui` 12 项），证据见 `evidence/run-20261029-123114/` 与 `docs/checks.md`。
其中 `panel-ui` 的 6 项候选宽度/滚动检查用夹具候选数据（超长候选、360px 窄屏、`selected_index` 跳转、
`page_size`×`max_visible` 组合），面板控件、Pango 排版、`Gtk.ScrolledWindow` 横向视口、XTest 点击与坐标
都是真实组件，结果里逐项标了 `fixture: true`。

## 许可与来源（适用范围）

**适用本目录的原创部分**，采用 **GPL-3.0-or-later**（GNU GPL v3 或更高版本）：

| 适用 | 说明 |
|---|---|
| `src/ime_interface/*.py` | 候选面板、状态提示、快捷键、标点映射、设置格式与设置界面、D-Bus 客户端封装、命令行入口 |
| `bin/ime-interface`、`tools/*.py`、`tests/*.py` | 启动包装、自检入口、单测与界面场景脚本 |
| `config/*.json`、`docs/*.md`、本 `README.md`、`SOURCES.md`、`LICENSE` | 默认设置、格式 v1 的 JSON Schema、检查夹具、文档 |
| `evidence/*` | 本组件自检产生的截图与结果 JSON；其中系统进程（Xvnc、ibus-daemon 等）自己的日志按原归属保留 |

完整许可文本见 [`LICENSE`](LICENSE)：文件头为 SPDX 标识 `GPL-3.0-or-later` 与版权行，其后是
**逐字未改的 GNU GPL v3 全文**（正文 35,147 字节，与系统 `libpinyin` 附带的 `COPYING` 用 `diff`
比对无差异；含头部的完整文件 36,160 字节 / 696 行）。没有 Warranty 声明之外附加任何限制，也没有
替代上游声明授权或署名。

**不适用本许可**，各自保留原许可、原文与署名：

* 第三方运行期依赖（GTK 3、PyGObject、GLib、Pango、IBus、libpinyin、Python）与检查用程序
  （Xvnc、XTest/libX11、dbus-daemon、ibus-daemon）均为**系统包**，本目录**不复制、不重新分发**
  其源码或二进制，也未修改它们；版本、RPM 许可字段与用途逐项列在 [`SOURCES.md`](SOURCES.md)。
* 同包其它目录：`platform/` 为 MIT、`engine/` 与 `integration/` 代码为 GPL-3.0-or-later、
  `lexicon/` 代码 GPL-3.0-or-later / 数据 CC-BY-4.0。各组件的许可互不覆盖，发布包同时保留各自原文；
  汇总表见 `delivery/docs/licenses.md`。
* `config/capabilities-fixture.json` 是检查夹具，不是第三方数据，也不代表引擎真实能力。
* 本目录不含第三方字体或词库；中文界面使用系统字体（字体许可由系统包提供，如 Noto CJK 为 OFL-1.1）。

许可元数据字段 `license`（`GPL-3.0-or-later`）、`license_file`（`interface/LICENSE`）、
`sources_file`（`interface/SOURCES.md`）记录在 [`handoff.json`](handoff.json)，供发布包汇总引用。

## 已知限制（如实说明）

* 候选面板位置固定在屏幕左上角 + `panel.edge_margin`；产品装配层（`integration/src/server_ime_product`）
  用平台给的 `cursor_rect` 覆盖定位，本包只提供等价默认值。
* 屏幕很窄或字号很大时，候选文字会被省略（最少 2 字）；仍放不下则把整页放进单行横向滚动视口
  （可见滚动条，高亮候选自动滚入视野）。**本页候选一个都不丢**，编号与 ID 不变。
  `panel.max_visible` 只是视口宽度预算（一次大约能看几个候选），不截断候选、不改页大小或数字映射。
* 框架原生面板（ibus-ui-gtk3）在本环境**无法运行**：主检查用 `--panel=disable`；另用
  `python3 interface/tools/native_panel_probe.py` 专门探测过——daemon 不自动启动面板，手工启动时
  面板以 `panel_switch_engine: assertion failed` 退出（引擎未进入面板 engine 列表），且本机缺少
  `ca.desrt.dconf` 服务，写不进 `input-sources`。因此原生面板未通过运行检查，本包 GTK 面板是
  已验证的等价实现；平台已填 `IBus.LookupTable`/`InputMode`，接线给集成任务。
* `input.page_size` 已能映射到引擎 `configure(page_size)`，但平台 `Controller` 的 `page_size`
  仍由平台构造参数决定（默认 5）；框架侧读取设置需要平台在集成任务中接入，见 `docs/mapping.md`。
* 标点映射与快捷键目前是“配置 + 校验 + 映射表 + 待集成”状态，尚未在框架按键/提交路径里生效。
* 双拼、模糊音、纠错、学习：引擎能力为 `false`，界面按要求不提供开关（夹具只验证门控逻辑）。
