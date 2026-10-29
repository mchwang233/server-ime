# 服务器输入法产品装配

employee_id: platform；`verifies: []`。装配版本 0.2.9；真实转换引擎为 libpinyin 2.6.0 / server_ime_engine 0.4.0。
产品通过平台 IBus 适配器、词库 UserStore、GTK 候选面板和设置界面运行；没有测试后端入口。
当前 0.2.9 已通过固定装配的窄屏和应用检查，发布身份校验见 `checks/layout-inventory-0.2.9.json`；0.2.8 失败证据保留，修复结果见 `defects/interface-layout-after-allocation-resolution-0.2.9.json`。原始失败记录见 [界面缺陷证据](defects/interface-layout-after-allocation.md)。
本次接入 interface 0.1.5 的布局后自动可见和短页范围收缩修复，沿用唯一自绘候选通道。
同页候选从左到右排列，应用中的预编辑保留；上屏、取消或失焦后收起候选。
已有配置缺少 `panel.layout` 时自动采用 `horizontal`，显式 `vertical` 偏好继续兼容。
长候选只在显示时省略，不改变候选 ID 或提交文本；宽度受屏幕边界限制。
窄屏放不下整页时显示单行横向滚动条，本页全部候选和数字编号保留；高亮项自动滚入视野。
滚动条只移动本页视口，Page Up/Down 和滚轮仍按原有逻辑翻页。
`panel.max_visible` 只控制视口宽度预算；例如页大小为 9、预算为 3 时，9 个候选和数字映射全部保留。
旧配置页大小为 5、预算为 1 也保留整页，滚动或上下键可到达后续候选。

## 启动与退出

源码入口 `integration/bin/server-ime`，装配后入口 `integration/build/product/bin/server-ime`。
所有全局参数放在子命令前。运行时需要明确的 `DISPLAY`、会话 `DBUS_SESSION_BUS_ADDRESS`，
以及可访问的显示授权。不自动查找用户会话或修改现有桌面输入源。

```sh
integration/bin/server-ime --config /可写路径/settings.json --data-dir /可写路径/data --state-dir /较短可写路径/run start --managed-ibus
integration/bin/server-ime --state-dir /较短可写路径/run exec -- xfce4-terminal --disable-server
integration/bin/server-ime --state-dir /较短可写路径/run settings
integration/bin/server-ime --state-dir /较短可写路径/run status
integration/bin/server-ime --state-dir /较短可写路径/run stop
```

`start --managed-ibus` 创建自己的 IBus，只影响经 `exec -- 应用` 启动且采用该输入框架的应用。
`exec` 设置应用需要的输入法环境并移除 `IBUS_USE_PORTAL`，因为 IBus 1.5.25 把该变量存在视为启用，
包括值 `0`（[上游源码](https://github.com/ibus/ibus/blob/1.5.25/src/ibusbus.c#L459-L464)）。
已有会话可显式给 `IBUS_ADDRESS` 后 `start`；此模式注册并选择 `server-ime`，停止时不终止已有 daemon。
`run` 是前台版本。停止只终止本产品创建的子进程。学习数据和设置保留。
同一个 state-dir 拒绝重复启动；socket 路径过长时明确报错，使用较短的可写目录。

首次默认配置不自动写盘；学习默认关闭。`--config` 优先于 `SERVER_IME_CONFIG`，
`--data-dir` 优先于 `SERVER_IME_DATA` / `$XDG_DATA_HOME/server-ime`；学习位于 data-dir/learning。
`--state-dir` 默认 data-dir/run。环境目录不可写时显式提供上述三个路径。
默认启用中文标点，普通空格保留为空格。Ctrl+空格切中英；Enter 提交原拼音；
空格/数字/鼠标选词，Page Up/Down 翻页，Esc 取消，Tab 取消组合并交给应用换焦点。
中文模式支持拼音与原文片段组合，例如 `nihaoAPI2shijie` → `你好API2世界`；
大小写、版本号、实际输入的邮箱/网址符号保留。顶排数字在纯拼音位置选词、原文位置插入；
数字小键盘总是插入数字。连续小写边界仍有歧义，可选原文或混合候选；详见 [混输按键说明](docs/mixed-input.md)。
纯拼音末尾按 `, . ? !` 会提交当前候选及未消费后缀，再应用标点设置，例如 `nihao,` → `你好，`。
关闭中文标点后同样操作得到 `你好,`。地址/版本中的符号保持原样；小写地址前缀与拼音有歧义时，
用小键盘小数点明确插入 `.`，或先切到英文模式输入完整原文。

## 设置传播、学习和恢复

设置窗口 `SettingsWindow.save_handler` 调用运行服务的配置事务，依次校验真实能力、
配置所有引擎、原子保存 0600 JSON、刷新所有 Controller 和面板。更新取消当前预编辑。
失败返回结构化错误并回滚引擎配置，不报告保存成功。损坏的配置在启动时拒绝加载，不静默重置。

```sh
integration/bin/server-ime --state-dir /较短可写路径/run config get
integration/bin/server-ime --state-dir /较短可写路径/run config apply /可写路径/settings-new.json
integration/bin/server-ime --state-dir /较短可写路径/run config reset
integration/bin/server-ime --state-dir /较短可写路径/run learning-status
integration/bin/server-ime --state-dir /较短可写路径/run reload-lexicon
```

配置格式和能力清单由 interface 所有；双拼目前只允许自然码。快捷键仅允许组件声明的绑定；
回车可改为 KP_Enter，其余任意自定义绑定仍会被拒绝。
学习只由引擎选词事件调用 lexicon.UserStore，普通候选提交才有资格，开关和敏感用途再做门控。
程序重启重新加载同一目录；不复制输入文本到产品日志。个人词库管理/备份/导入导出由 lexicon 工具提供，
应对同一 learning 目录操作；随后调用 reload-lexicon。运行日志只记录进程与异常，候选状态仅在会话总线传输。

受管 IBus、引擎或候选面板退出后自动重启，60 秒内最多恢复 3 次；超限停止整个产品并记录 failed。
原生崩溃时的未提交预编辑丢弃。已提交文本不重放。完整 IBus 重启后建议重新通过 exec 打开应用，
因为旧应用可能缓存旧的总线地址；恢复证据包含新客户端恢复输入，未承诺所有旧应用自动重连。
候选窗使用 IBus 的屏幕光标矩形并避开屏幕边界；未提供坐标的应用使用屏幕角落，标记 anchored=false。

## 构建和本步骤检查

```sh
python3 integration/tools/build_product.py
python3 integration/checks/run_checks.py --window-manager xfwm4
# 仅补测浏览器（需已取得下述官方浏览器检查工具）
python3 integration/checks/run_checks.py --browser-only --window-manager xfwm4
# 最小复现系统 Firefox 包装器/实际程序的启动差异
python3 integration/checks/run_checks.py --browser-startup-only
```

构建校验 engine/vendor.lock.json，保留依赖源包和许可，输出 product/、归属/逐文件 SHA256 清单与 tar.gz。
没有 deterministic.py、夹具能力文件或平台测试服务。delivery 负责人消费该目录做最终安装包，
`component-delivery.json` 是装配清单，不是 delivery 的安装清单。
候选面板使用 interface 的 GTK 实现；仅隐藏本引擎的原生 lookup/auxiliary，
已有 ibus-ui-gtk3 面板和共享输入配置继续保留。独立平台适配器默认 native 模式不变。

本步骤检查自身交付：在新建的 Xvnc/X11 + xfwm4 + D-Bus 会话通过统一入口启动，使用 XTest 向真实应用打字，
终端从 PTY 读回、gedit 保存文件、Chrome for Testing 从 DOM input/composition 事件读回。
所有测试输入均为合成文本，均由 XTest 按键/鼠标经产品入口提交，没有 DOM 赋值。
`integration/evidence/latest.json` 指向最近一轮及其检查范围；`integration/compatibility.json` 记录当前结果及历史证据。
本轮裸 Xvnc 无窗口管理器的两次鼠标焦点失败也保留；成功范围为带 xfwm4 的隔离会话。
实际用户 TigerVNC 会话与隔离会话严格区分，
当前权限禁止用户 Xauthority、既有 X11 socket 和用户配置，因此未向用户会话部署。
浏览器检查使用官方 Chrome for Testing 156.0.8078.73；本轮各应用补测结果见兼容矩阵，版本、来源及校验值在
`integration/browser-runtime/source.json`，该浏览器只用于检查，不进入产品包。
系统 Firefox 140.12.0esr 在应用级配置初始化时受权限限制，仍单独记为未验证；
其包装器与实际程序的最小复现见 `integration/docs/browser-startup.md`。
完整应用矩阵及浏览器保留差异见 `integration/docs/application-compatibility.md`。
Wayland、原生 Qt、远程 RDP、多屏/分数缩放未验证。引擎质量与长尾延迟差距见 engine/docs/QUALITY-PERFORMANCE.md。

装配包包含 interface/LICENSE、interface/SOURCES.md，采用界面负责人已交付的 GPL-3.0-or-later 声明。
`integration/build/server-ime-product-0.2.9.tar.gz` 供既有 delivery 任务制作安装包；0.2.8 失败产物、0.2.7 及全部历史包与运行记录保留。
本轮横排与单候选窗检查命令及证据索引见 [应用兼容性记录](docs/application-compatibility.md)。
连续联想和 Windows 11 对照已取消，不属于本次修复的完成条件；用户实际桌面尚未部署。
