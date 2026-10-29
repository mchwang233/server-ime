# 应用兼容性记录

employee_id: platform；装配 0.2.9 / interface 0.1.5 / 引擎 0.4.0；`verifies: []`。

## 0.2.9 固定装配结果

构建完全结束后，从归档解包到 `integration/.runtime/layout-0.2.9/product`，全部图形检查始终使用该目录。
`assembly-0.2.9-preparation/pinned-before.json` 与 `pinned-after.json` 核对全部 115 个文件；
两组运行各保留 `tested-runtime-hashes.json`、`runtime-hashes-after.json`，前后相同。
`fixed-runtime-audit.json` 记录构建、解包和检查顺序；最终归档只更新本说明、README 和兼容矩阵，运行文件与成功证据逐项核对。

| 检查 | 证据 | 结果 |
|---|---|---|
| 真实 360×960 / 300% 字号，两条 IBus 路径 | `integration/evidence/layout-assembled-0.2.9/viewport-summary.json` | 各 38 项，通过 |
| 常规 gedit / Chrome，两条 IBus 路径 | 同目录 managed / existing | 各 32 项，通过；各含 8 项横排检查 |
| 真实引擎控制器 | 同目录 controller-summary.json | 8/8 |
| 装配既有功能 | `integration/checks/assembly-0.2.9.log` | 20/20 |
| 统一入口终端、gedit、Chrome | `integration/evidence/apps-assembled-0.2.9/applications.json` | 43 条观察，1,898 条浏览器事件 |
| 设置、学习、完整重启与故障恢复 | 同目录 product-contract.json | 10/10 |
| 归档、运行身份与程序化搬迁 | `integration/checks/layout-inventory-0.2.9.json` | 最终发布身份校验入口 |

窄屏每条路径均完整访问真实 ni 的 126 个 ID / 14 页；经产品设置事务实际保存 9/3、5/1，
逐项高亮自动可见，前两页的末项鼠标与数字选择均从 gedit 保存文件读回正确完整文本。
手动将视口滚到末端后，再用真实上下键移动高亮；检查不调用面板 reveal/scroll RPC。
真实 hao 的末页有 4 项：9/9、9/3 下完整页→短页→完整页的 upper 为 859→384→859px，
5/1 为 479→384→479px；末端有候选且最后一项完整可见，页首返回可见，ID/编号/逻辑页不变。

先完成 managed-narrow、existing-narrow，全部通过后才运行 managed、existing 和三应用检查。
原有 148 条反馈断言全部保留，新增 21 条；`assertion-preservation.json` 提供源码比较。
四个会话的原生 lookup/auxiliary 可见信号均为零，正常应用预编辑可见信号分别为 480/480/354/354。
既有 IBus/原生面板在停止产品后仍存活，私有输入设置保持不变；独立 native 适配器信号仍通过。

0.2.8 稳定失败证据和构建重叠诊断目录均保留；后者不计作成功版本证据。
原始缺陷报告保持原字节，闭环记录为 `integration/defects/interface-layout-after-allocation-resolution-0.2.9.json`。
44 个历史包/摘要文件、493 个失败证据文件的前后摘要一致，包含 0.2.7、失败的 0.2.8 和安装包/源码 0.1.5。
后续现有 delivery 任务消费 0.2.9，负责新安装包与源码、升级回滚及配置/词库保留。

本轮没有部署到用户实际桌面；此前双框的实机根因和实际修复效果仍未确认。
Firefox 配置初始化权限问题、Wayland、原生 Qt、RDP、多屏和分数缩放继续标为未验证，不重复尝试。
裸 Xvnc 无窗口管理器的鼠标稳定性、完整 IBus 崩溃后的旧应用自动重连仍未确立。
Chrome 密码框直接处理输入且不报告 IBus PASSWORD；实测无组合事件、候选/学习泄漏；compositionend.isTrusted=false 原样记录。
联想和 Windows 11 对照仍不在本轮完成条件中。引擎质量与长尾延迟差距见 `engine/handoff.json`。

复跑必须先等待构建退出码为 0，解包到新的专用目录，再固定下列两个环境变量；不得向正在检查的目录重新构建：

```sh
SERVER_IME_FEEDBACK_PRODUCT_ROOT="$PWD/integration/.runtime/layout-0.2.9/product" python3 -B integration/checks/test_feedback.py --skip-baseline --output integration/evidence/layout-NEW
SERVER_IME_PRODUCT_ROOT="$PWD/integration/.runtime/layout-0.2.9/product" python3 -B integration/checks/run_checks.py --window-manager xfwm4 --output integration/evidence/apps-NEW
python3 -B integration/checks/check_delivery.py --output integration/checks/layout-inventory-0.2.9.json
```

## 历史版本记录（以下证据不代表当前版本）

以下为保留的 0.2.1 历史证据（0.2.3 与 0.2.4 结果见文末）：`integration/evidence/run-20261029-000050/`。
43 条应用观察全部通过，浏览器保留 1,898 条原始 DOM 事件。
产品从装配目录的统一入口启动，使用真实 libpinyin；会话为独立 Xvnc/X11 + xfwm4 + D-Bus + IBus。

| 会话 / 应用 | 实际读回与候选位置 | 交互检查 | 状态 |
|---|---|---|---|
| 隔离 X11 / xfce4-terminal | PTY stdin；鼠标首选、翻页数字选择；光标/面板矩形和截图 | 直接句读、原文点号、混输、编辑、分段、Esc/Enter、Ctrl+U | PASS，12 条观察 |
| 同一隔离会话 / gedit | Ctrl+S 保存文件及 Ctrl+C 读实际缓冲；光标/面板矩形 | 直接句读、混输、编辑、分段、Ctrl+A/C/S、跨应用焦点与过期候选拒绝 | PASS，10 条观察 |
| 同一隔离会话 / Chrome for Testing 156.0.8078.73 | 只读 DOM input/composition 事件；两输入框的 DOM/光标/面板矩形 | 直接句读、混输、编辑、分段、鼠标/数字选择、Tab、Ctrl+A/C、密码框 | PASS，20 条观察（含 browser-page） |
| 隔离 X11 / Firefox 140.12.0esr | 未验证 | 未验证 | 历史配置初始化 mkdir EACCES，本轮未重复尝试 |
| 用户 session 3 / TigerVNC / X11 :2 | 未验证 | 未验证 | NOT_DEPLOYED；既有 Xauthority、X11 socket、用户配置不可访问 |
| Wayland / 原生 Qt / RDP / 多屏、分数缩放 | 未验证 | 未验证 | 本步骤无可访问的对应环境 |

另 1 条观察确认全部应用检查完成。全部混输和标点序列保持中文模式。

## 标点返工：直接按键与实际文本

`applications.py::sentence_punctuation` 在每种应用中直接输入 `nihao,`、`nihao.`、`nihao?`、`nihao!`，
这些符号前没有空格或数字选词。通过同一个产品 RPC 切换中文标点开关，再直接输入相同四组按键。
三个应用均实际读回以下一行（对应证据名 `direct-pinyin-punctuation-actual-text`）：

```text
你好，你好。你好？你好！ 你好,你好.你好?你好! 你号码。尼号，你号v？西安！ ni.hao@example.org
```

这同时覆盖当前高亮的整句“你号码”、分段候选“尼”及后缀、分段后仍有原文 `v`、
`xi'an` 音节分隔符，以及 `ni` + `KP_Decimal` + `hao@example.org` + Enter 的明确原文路径。
分段后的 `hao` 在这版引擎中首选“号”，检查使用引擎实际排序，没有改词库制造预期结果。
先提交选中的前缀，再逐段处理返回的未消费原文，不能重复提交已消费前缀；最后只提交一次标点。

gedit 的首次输入也从 `nihao` 直接按逗号，删除了旧脚本先按数字 `1` 再按逗号的绕过步骤。
`editor-actual.txt` 保存实际文件读回，`browser-actual.txt` 保存 DOM 读回；
终端实际 PTY 行和三个应用的完整文本均在 `applications.json`。

原有混输、编辑和分段用例全部重跑，并新增小写地址：

```text
你好 v2.0 AbC123 User+Tag@Example.org https://Example.org/A?v=2 你好API2世界 nihao@example.org https://example.org/a?v=2
你好API2世界 abc123 你好Linux6.1世界 你好hello
```

gedit 的首行在“你好”后另有中文逗号，保存文件时自动补末尾换行。
`abc123` 使用小键盘明确插入数字，`你好Linux6.1世界` 由三个候选分段提交。
小写地址前缀与拼音在第一个点号处可能有歧义，详细默认行为和原文输入方式见 [混输说明](mixed-input.md)。

所有输入均为合成数据，通过 XTest 的真实按键/鼠标进入应用和 IBus；大小写、问号和感叹号实际使用 Shift。
没有 DOM 赋值、合成 DOM 事件或直接向应用写入预期中文。
`application-state-events.json` 保存候选状态，`browser-events.json` 保存逐事件值/时序/坐标/可信标志。
`editor-final.png`、`browser-final.png` 及候选截图已检查，候选矩形和浏览器字段坐标断言通过。

## 配置、学习与故障恢复

同轮 `product-contract.json` 的 10 项检查通过：真实提交、设置窗口保存到运行服务、
引擎/平台/面板传播、非首选“泥”的学习和排名、敏感用途不学习、自然码/模糊音/纠错配置生效、
非法配置拒绝，以及完整程序重启。配置文件权限为 0600。
`after-restart.json` 记录配置及“泥”首选恢复，受管 panel/service/IBus 各一次 SIGKILL 后恢复，
新客户端重新收到“中文”。整个 IBus 崩溃后旧应用自动重连仍未验证。
`final-status.json` 是 stopped、children 为空；`summary.json` 中 stop=0，Xvnc/D-Bus/xfwm4 均已回收。

`learning-fragments.json` 检查本轮个人词库仅有中文片段，没有保存标点、邮箱、网址或原文数字 token。
三类应用各执行一次指定分段场景，对应“尼”“你”“你号码”“西安”各计数 3，“号”计数 6，无重复学习。
浏览器密码框实际收到合成 `AbC123@Example.org`，没有组合事件、预编辑/候选泄漏，学习文件前后 SHA256 相同：
`6ba2ab3c613bb58ef2bf45310877e773bd831fe6a267831289fa80dc9c595f30`。

Chrome 在应用侧直接处理密码，没有给最后的 IBus context 上报 PASSWORD 用途；中文徽标可能保留在前一个输入框。
所有 key/input/beforeinput、焦点、compositionstart/update 事件的 isTrusted 均为 true；
36 个 compositionend 的 isTrusted 为 false，按浏览器原值保存。这些限制没有被省略或改写。

## 会话条件、失败记录与复跑

`run-20261028-235645/` 与 `run-20261028-235853/` 保留本轮前两次失败：没有窗口管理器的裸 Xvnc 下，
终端鼠标进入候选窗后反复失焦/聚焦，混输检查中止，尚未执行到新标点场景。
检查改为在同一独立 Xvnc 中启动本机现有 xfwm4 后，完整三应用检查通过；产品运行文件没有为此修改。
因此本轮通过范围明确包含 xfwm4，不声称裸 X11 的鼠标焦点已稳定，也不将隔离会话当成用户桌面部署。

```sh
python3 -B integration/checks/test_assembly.py
PYTHONPATH=platform python3 -B -m unittest discover -s platform/tests -p 'test_*.py'
python3 integration/tools/build_product.py
SERVER_IME_PRODUCT_ROOT=/绝对路径/integration/build/product python3 integration/checks/run_checks.py --window-manager xfwm4
python3 integration/checks/check_delivery.py --output integration/checks/punctuation-inventory.json
```

真实引擎控制器 19/19、平台通用单测 16/16，通过后运行上面的装配目录检查。
`tested-runtime-hashes.json` 在启动前记录运行文件和检查脚本 SHA256，退出后确认运行文件未变；
最终装配清单再与该成功运行核对。`assembly-punctuation-before.log` 保留修复前的直接标点失败断言。
0.2.0 和更早的包、证据均保留，历史快照为 `handoff-before-punctuation-revision.json` 和
`compatibility-before-punctuation-revision.json`；最终安装包及配套源码更新由已有 delivery 任务接续。

系统 Firefox 的历史复现见 [浏览器启动记录](browser-startup.md)。仍无 Windows 11 同机对照，
不能声称达到 Windows 11 水平。引擎质量和长尾延迟差距继续参见 `engine/handoff.json`。

## 0.2.3 双框修复装配

本轮仅修复候选显示：产品自绘面板为唯一候选窗，隐藏本引擎原生 lookup/auxiliary，正常应用预编辑继续输出；独立平台默认 native 模式保留。
联想开发及 Windows 11 对照已取消，不作为本轮完成条件；上屏后清空候选，空闲空格/回车交还应用。按键、混输、标点、学习与敏感隔离恢复并保持 0.2.1 语义。
测试条件为新建认证 Xvnc + xfwm4 + 私有 D-Bus/IBus，受管与已有 IBus 两条路径中的“已有”也仅指任务自建会话。不得关闭用户系统面板或修改共享输入配置。
用户报告双框的实际桌面根因和可见修复效果仍未确认；NOT_DEPLOYED。没有新增范围外环境验证。
0.2.1、含联想的 0.2.2 历史包及证据保留。当前证据如下。

成功三应用证据：`integration/evidence/run-20261029-095207/`，43 条应用观察、10 项产品契约检查通过，浏览器事件 1,898 条；装配回归 19/19。
双框证据：`integration/evidence/feedback-0.2.3-serial/`，0.2.1 双窗基线复现、8 项控制器检查、受管和已有 IBus 各 20 项应用检查通过；lookup/auxiliary 可见信号为零，应用预编辑保留，独立 native 模式信号检查通过。已有 IBus/原生面板在停止产品后存活，私有输入设置保持不变。
首轮并行检查显示连接失败保留于 `feedback-0.2.3/`；Xvnc 日志显示监听冲突，串行重跑通过，没有改动产品或测试断言。
对照 0.2.1，全部引擎 Python 文件相同；仅版本号、产品 runtime 显示模式、panel 空闲隐藏与提示/几何信息、适配器 lookup/auxiliary 通道及原生点击门控、控制器显示元数据有差异。按键与提交策略相同，详见 `integration/checks/display-only-diff-0.2.3.json`。
`test_assembly.py` 仅撤回联想条件断言并恢复上屏后候选隐藏，19 项既有功能检查均保留。
反馈检查直接调用现有脚本的 baseline/controller/isolated 入口，显式传入装配路径；未修改脚本。两组 `tested-runtime-hashes.json` 与最终清单逐文件核对。
最终整包及搬迁结果见 `integration/checks/feedback-inventory.json`，反馈哈希核对见 `integration/checks/feedback-runtime-match-0.2.3.json`。搬迁范围为解包入口与真实混输/标点程序化运行，不声称 GUI 搬迁或用户桌面部署。

## 0.2.4 单一候选窗、候选横向排列

本轮消费 interface 0.1.1 的横排候选和 `panel.layout` 配置，保留 0.2.3 的单候选显示通道。
`ProductPanel` 直接继承横排布局和宽度约束；本轮无需更改平台按键、提交或面板定位实现。
旧配置缺少 `panel.layout` 时采用 `horizontal`，显式 `vertical` 偏好保留；配置保存与重启检查包含这一兼容行为。
界面组件的长候选、省略后 ID 保持、300% 字号和 360px 窄屏检查由 interface 的
`evidence/run-20261029-101704/` 提供；下面的产品应用检查为真实 1280×960 单屏 Xvnc。

`test_feedback.py` 在每条 IBus 连接路径的 gedit 和 Chrome 中新增四组几何检查：
默认页鼠标、默认页数字、翻页后鼠标、翻页后数字。
每组检查同页完整候选的 y 一致、x 严格递增且互不重叠、ID 与引擎当前页一致、候选和面板位于屏幕内，
并从编辑器保存文件及浏览器 DOM 读回对应提交文本。
继续检查候选出现时只有一个自绘窗、上屏与失焦后隐藏、应用预编辑正常、原生 lookup/auxiliary 不可见，
以及全部既有标点、混输、焦点、编辑、快捷键和密码输入断言。
受管和已有 IBus 路径串行运行；“已有”仍为本任务自建会话，原生面板、总线和私有输入设置应保留。

重跑入口（输出目录必须不存在）：

```sh
SERVER_IME_FEEDBACK_PRODUCT_ROOT="$PWD/integration/build/product" python3 -B integration/checks/test_feedback.py --skip-baseline --output integration/evidence/horizontal-local
SERVER_IME_PRODUCT_ROOT="$PWD/integration/build/product" python3 -B integration/checks/test_assembly.py
SERVER_IME_PRODUCT_ROOT="$PWD/integration/build/product" python3 -B integration/checks/run_checks.py --window-manager xfwm4
python3 -B integration/checks/check_delivery.py --output integration/checks/horizontal-local-inventory.json
```

保留 0.2.3 及更早归档和 sidecar；0.2.1 双框基线复现沿用
`integration/evidence/feedback-0.2.3-serial/baseline/`，本次不重复该未变的历史包检查。
本轮首个源码检查保留在 `integration/evidence/horizontal-source-0.2.4/`：编辑器检查通过，
Chrome 因检查脚本使用过长的项目临时路径而触发 `Socket path too long`，两条路径均失败。
改回新建的短 `/tmp/ime-layout-*` 临时路径后，源码重跑
`integration/evidence/horizontal-source-0.2.4-retry/` 通过：控制器 8/8、两条路径各 32 项应用检查，
临时会话已清理，所有持久证据在项目目录中。没有关闭浏览器沙箱、修改权限或绕过桌面限制。

用户真实桌面仍为 NOT_DEPLOYED；不能从隔离通过推断用户报告的双框已经消失。
连续联想及 Windows 11 对照保持取消状态，不再以额外环境反馈作为本次代码修复完成条件。
最终安装包及源码、从 0.1.3 升级/回滚和数据保留由已有 delivery 任务消费新装配后完成。

装配版成功证据：

- `integration/evidence/run-20261029-102946/`：终端 12、gedit 10、Chrome 20 和完成标记 1，共 43 条应用观察；DOM 事件 1,901 条；配置与重启恢复契约 10/10。
- `integration/evidence/horizontal-assembled-0.2.4/`：真实控制器 8/8，受管与已有 IBus 各 32 项应用检查（各含 8 组横排几何），本引擎原生 lookup/auxiliary 可见次数均为零，应用预编辑保留；已有面板、总线和输入设置保留。
- `integration/checks/assembly-horizontal-0.2.4-built.log`：装配目录 20/20，含旧配置加载/保存/重启后的横排默认值。
- `integration/checks/horizontal-runtime-diff-0.2.4.json`：对照 0.2.3，引擎、词库与平台运行文件不变；只更新界面布局/配置及装配版本。
- `integration/checks/horizontal-inventory-0.2.4.json`：最终清单、归档、许可、无测试后端、两组成功运行摘要、历史包及搬迁入口的发布校验。搬迁范围为入口和真实引擎程序化检查，不代指 GUI 搬迁或用户桌面部署。

这两组装配版图形运行结束后均已回收自建进程和临时目录；完整产品停止后无受管子进程残留。
最终运行文件以两组 `tested-runtime-hashes.json` 对照最终清单，文档与清单更新不改变实测运行代码。

## 0.2.5 最终横排修复装配

消费最终 ProductPanel 文字宽度约束、光标定位与 Geometry.metrics 修复，以及强化后的横排反馈检查。保留 0.2.4 及更早包，不改变既有功能断言。唯一候选通道仍为自绘面板，应用预编辑保留；上屏、Esc、切换英文或失焦后隐藏。连续联想已取消，没有联想触发或取消操作。测试限定自建 Xvnc + xfwm4 + 私有 D-Bus/IBus；用户桌面未部署，用户双框现象仍待确认。最终证据与摘要见 integration/handoff.json。

0.2.5 成功证据：`integration/evidence/horizontal-assembled-0.2.5/`（控制器 8/8，两路径各 32 项应用检查、各 8 项横排检查）；`integration/evidence/run-20261029-105306/`（43 条应用观察、10 项配置/学习/恢复检查）。装配回归 `integration/checks/assembly-0.2.5.log` 为 20/20。最终包逐文件、两组运行摘要、全部历史包与程序化搬迁结果见 `integration/checks/feedback-inventory.json`。相较 0.2.4，运行文件仅版本号和 ProductPanel 变化。

## 0.2.6 窄屏完整候选页

本次只消费 interface 0.1.2 的横向视口修复，保留单一自绘候选通道、应用预编辑与既有按键语义。
ProductPanel 对最终产品提示重新约束宽度，删去旧的“其余用翻页查看”说明，Geometry 增加实际视口/滚动条坐标及快照页码、revision。
归档 0.2.5 及更早版本和 sidecar 均保留；未改引擎或词库，不重做引擎评测，联想和 Windows 11 对照继续取消。

检查使用真正的 360×960 Xvnc 显示、300% 字号和真实引擎（fixture=false）。
`ni` 的 126 个候选共 14 页，每页完整 9 项：点击可见滚动条到页尾，逐项用 Down/Up 核对完整 ID、顺序和高亮可见性。
核对第 9 项经鼠标和数字提交；另以 `hao` 检查少于 9 项的最后一页，点击/数字仍提交完整文本，失焦后隐藏并拒绝过期候选。
正常 1280×960 显示仍要求同页全部候选完整可见、无需滚动、横坐标有序且无重叠。
受管和已有 IBus 路径均在自建隔离会话执行，原生 lookup/auxiliary 保持不可见，应用预编辑正常。

```sh
SERVER_IME_FEEDBACK_PRODUCT_ROOT="$PWD/integration/build/product" python3 -B integration/checks/test_feedback.py --skip-baseline --output integration/evidence/narrow-local
# 仅窄屏交互（输出目录必须不存在）
SERVER_IME_FEEDBACK_PRODUCT_ROOT="$PWD/integration/build/product" python3 -B integration/checks/test_feedback.py --narrow-only --output integration/evidence/narrow-local-only
```

源码阶段：`integration/evidence/narrow-source-0.2.6/`（真实 360px，受管 IBus，通过；最后一页为 ni 的完整页）。
最终装配检查使用新增的 hao 不满页场景；结果、运行文件摘要、统一启动与重启检查以 `integration/handoff.json` 为准。
用户实际桌面继续 NOT_DEPLOYED；Firefox、Wayland、Qt、RDP、多屏与分数缩放缺口保留，不重复请求这些环境。

本轮诊断记录保留：`narrow-assembled-0.2.6/` 的常规宽度两路径各 32 项通过，但窄屏检查在 GTK 延迟布局结束前立即读取高亮可见性而失败。
检查改为在 4 秒内等待同 revision、正确候选次序、最终几何及高亮可见；未放宽最终可见性断言，也未改变产品运行代码。
`narrow-layout-wait-0.2.6/` 保留一次 Xvnc 启动失败：displayfd 数字与换行分开到达，检查脚本过早关闭管道，Xvnc 报 Cannot write display number。
修正检查脚本读取整行后，`narrow-layout-wait-0.2.6-retry/` 通过 21 项真实窄屏检查，包括 `hao` 的末页 4 项。
最终串行汇总路径为 `integration/evidence/narrow-assembled-0.2.6-final/`；失败目录不改写为通过。

0.2.6 最终通过记录（employee_id=platform，verifies=[]）：

- `integration/evidence/narrow-assembled-0.2.6-final/`：控制器 8/8；受管与已有 IBus 常规检查各 32 项、窄屏检查各 21 项，合计 106 项应用检查。每条窄屏路径遍历 ni 的 126 个 ID / 14 页，并核对 hao 最后 4 项；全部通过。
- `integration/evidence/run-20261029-113836/`：终端 12、gedit 10、Chrome 20、完成标记 1，共 43 条应用观察；配置/学习/重启/故障恢复 10/10；DOM 事件 1901 条。最终状态 stopped，children 为空。
- `integration/checks/assembly-0.2.6.log`：20/20；既有功能断言均保留。
- `integration/checks/narrow-runtime-diff-0.2.6.json`：相对 0.2.5，仅装配版本、ProductPanel 和 interface CandidatePanel 变化；引擎/词库/平台运行文件不变。
- `integration/checks/narrow-inventory-0.2.6.json`：最终归档、逐文件摘要、两组成功运行文件、历史归档及搬迁检查入口。搬迁检查为解包后入口与真实引擎程序化运行，非 GUI 部署。

装配包内兼容矩阵保留全部应用结果和未验证项；正式安装包与对应源码由既有 delivery 任务消费 0.2.6，保留 0.1.4 并检查从 0.1.4 升级、回滚及配置/学习保留。

## 0.2.7 最终交接同步

消费完整滚动候选页及强化后的逐页 ID 覆盖检查，界面许可元数据同步为 0.1.3。
保留 0.2.6、0.2.5、0.2.1 及所有历史包和 sidecar；20 项装配功能检查不删改。
唯一候选显示策略仍为自绘面板，原生 lookup/auxiliary 隐藏、应用预编辑保留。
联想继续取消，没有新增联想触发或取消操作；上屏清空候选，Esc、切换英文及失焦取消组合。
本轮限定自建认证 Xvnc + xfwm4 + 私有 D-Bus/IBus，两条连接路径均非用户桌面。
正常 1280×960 与窄屏 360×960 / 300% 字号检查沿用真实引擎和真实应用读回。
用户双框现象的实际根因与升级后效果仍待用户确认；NOT_DEPLOYED，不要求额外环境验收。
最终证据索引及摘要见 integration/handoff.json；搬迁仅检查解包入口和真实引擎程序化运行。

0.2.7 成功证据：`integration/evidence/narrow-assembled-0.2.7/`（控制器 8/8，常规两路径各 32 项、窄屏各 21 项）；`integration/evidence/run-20261029-121246/`（43 条应用观察、10 项产品契约检查）。装配目录回归 `integration/checks/assembly-0.2.7.log` 为 20/20。最终归档和两组成功运行逐文件匹配、全部历史包保留及程序化搬迁结果见 `integration/checks/feedback-inventory.json`。下游 delivery 消费 0.2.7 与清单摘要，保留安装包 0.1.4，接续升级/回滚和数据保留检查。
