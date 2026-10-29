# 界面检查记录（employee_id=interface）

入口：`python3 interface/tools/run_checks.py`。自建隔离 Xvnc（`127.0.0.1:<n>`，`-auth` 临时 cookie）+
私有 D-Bus + 私有 IBus 地址（`--address=unix:dir=…`），不使用宿主显示/会话；运行目录 `interface/.runtime/`
结束即删。

最近一次：**PASS** — `evidence/run-20261029-131625/summary.json`
（本轮为布局后自动滚动 / 短页滚动范围返工后的复跑：`unit` 51、`display`、`manifest`、
`panel-ui` 20/20、`settings-ui` 12/12）。

## 环境事实

| 项 | 值 |
|---|---|
| 显示 | Xvnc `127.0.0.1:0`，1024×768×24，无窗口管理器 |
| 输入框架 | ibus-daemon 1.5.25，`--panel=disable --config=disable`，私有地址 |
| 适配器 | `platform/launch.py --register --backend server_ime_engine.platform_adapter:create_session` |
| 转换后端 | 真实 libpinyin 2.6.0（快照 `backend=libpinyin-2.6.0-api1`，`deterministic=false`） |
| 字体 | 系统 CJK 字体可用（`fc-list` 匹配 81 项），截图中中文正常渲染 |

## 检查项

`unit`（无显示，51 项 unittest）：设置格式、范围/类型/版本校验、未知键保留、保存权限 0600、恢复默认、
能力门控、错误码与中文提示、快捷键冲突/非法/不支持绑定、按键解析、标点映射，以及设置→真实引擎
`configure` 映射、设置→平台 `Controller(page_size)` 映射、`panel.layout` 缺省/旧配置升级/非法值拒绝。

`panel-ui`（真实 GTK3 窗口 + XTest 注入，`evidence/run-*/panel-checks.json`）：

| 检查 | 结果 | 说明 |
|---|---|---|
| preedit-in-real-gtk-entry | PASS | XTest 输入 `nihao`，GTK 输入框收到预编辑，未上屏 |
| panel-shows-candidates-and-status | PASS | 面板显示真实引擎候选、页码、后端名、快捷键提示 |
| candidates-horizontal-single-row-left-to-right | PASS | 真实候选 5 项：`y` 全为 31（同一行），`x` = 10/110/210/318/458（从左到右递增），候选与面板都在 1024×768 屏幕内（截图 `panel-horizontal.png`） |
| mouse-click-selects-candidate-via-platform-interface | PASS | XTest 鼠标点第 2 个候选（横排坐标）→ 经 `SelectCandidate` 提交并上屏 |
| digit-key-selects-second-candidate | PASS | 数字键选词与面板第 2 个候选一致 |
| paging-keyboard-and-wheel-with-boundary | PASS | Page Down 与滚轮翻页，翻页后仍为同一行且横坐标递增，第 0 页再上一页保持在边界 |
| last-page-last-candidate-click-commits-full-text | PASS | 真实引擎翻到最后一页，鼠标点击该页最后一个候选 → 应用上屏文本与候选一致（截图 `panel-last-page*.png`） |
| mode-badge-click-switches-zh-en | PASS | 点徽标切英文后字母原样进入应用，再点回中文 |
| focus-change-clears-candidates-without-preedit-leak | PASS | 焦点移到第二个输入框：候选清空、无预编辑泄漏、可继续输入 |
| panel-scales-with-font-setting | PASS | `font_scale` 1.0→1.5，行高 1.47 倍，放大后仍是同一行、仍在屏幕内（截图 panel-scale-100/150.png） |
| readability-contrast-min-4.5 | PASS | 候选/注释/提示/选中行/徽标对比度最低 4.83:1（WCAG AA） |
| long-candidates-and-300pct-stay-inside-screen | **夹具** | 9 个超长候选 + `font_scale=3.0`：面板宽度 ≤ 上限 1008px，仍排一行、`x` 递增；本页 9 项的 `id`/`text` 一个不少（`dropped_for_width` 恒为 `[]`），被省略的候选 `rows[i].text` / `id` 保持完整（截图 `panel-long-candidates-300.png`） |
| ellipsized-candidate-keeps-full-id-and-text | **夹具** | 把被省略的候选滚进视野后 XTest 点击：送出的是完整 ID（`fx-0`）与完整原文，不是省略后的显示文本；点击回放只替换 `client.act` 记录参数，不写输入状态 |
| narrow-360px-page-of-9-all-candidates-reachable-by-scroll | **夹具** | 宽度上限按 360px 注入 + 300% 字号、一页恰好 9 项：面板 342px（含横向滚动条）仍在屏内，9 个候选全部留在逻辑页里、顺序不变；视口初始可见前 5 项，从头滚到尾依次看得见 `fx-0…fx-8`（`swept_ids` 与逻辑页完全一致）；提示行不再出现“其余用 Page Down 翻页”这类错误说明（截图 `panel-narrow-360.png`） |
| narrow-360px-last-candidate-clickable-with-full-text | **夹具** | 原先会被宽度丢弃的末尾候选 `fx-8`：滚到它之后真实 XTest 点击，选中 ID 为 `fx-8`、完整文本与夹具候选一致（点击回放记录参数） |
| highlight-change-scrolls-candidate-into-view | **夹具** | 高亮（平台把方向键变成 `selected_index`）从第 1 项移到第 9 项：视口滚动 2→353px，`fx-8` 进入可见区域且标记 `selected`；高亮回到第 1 项后精确回到起始值 2px（rows_box 的 2px 内边距，首行完整可见），`fx-0` 重新可见 |
| narrow-360px-multipage-every-id-reachable-in-order | **夹具** | 20 个候选 / 每页 9（9+9+2）：逐页核对逻辑页 ID 与滚动可达 ID 完全一致、顺序正确、无遗漏（每页 `visible` = 9/9/2，翻页后视口从页首开始） |
| max-visible-is-viewport-budget-not-page-truncation | **夹具** | `page_size=9/max_visible=3` 与旧配置 `page_size=5/max_visible=1`（各测第 1 页与下一页）：逻辑页 ID 分别恒为 9 项 / 5 项、序号 `0..8` / `5..9`，视口宽度 297/402/160px 只由 `max_visible` 预算决定；初始可见 3/3/1 项，逐个滚到末端时本页全部 ID 依次可达；高亮从页首移到页末使滚动回到页首（≤首行 x）→578/260/502px 且末项 `in_view`+`selected`；末项 XTest 点击送出完整 ID（`vb-8`/`vb-13`/`vb-4`/`vb-9`） |
| keyboard-highlight-reveals-after-real-layout | **夹具** | 0.2.8 失败时序的回归：高亮变化后先手动触发一次面板自己的延迟回调（复现“空闲回调早于 `size-allocate`”，此时新行只有 1px 占位），再等真实分配。9/3 与 5/1 各测两段：① 页首→末项，滚动 2→638/377px，末项 `in_view`+`selected`，点击送 `la-8`/`la-4`；② 用户拖到末端（640/379px）后高亮跳到中间项，**布局前滚动值不变**（640/379，不被 1px 占位按成 0），分配完成后 640→430px / 379→216px，中间项完整进入视口，点击送 `la-4`/`la-2`。本项不调用 `reveal()` 补救，`scroll_by()` 只用于模拟用户先把视口拖到末端。 |
| short-page-shrinks-scroll-extent-and-end-not-blank | **夹具** | 整页 9 项在末端 → 语料末页 4 项（模拟真实 `hao` 末页形状）：`content_natural_width` 967→432px、滚动 `upper` 967→432px（不保留旧页的 rows_box 宽度请求），滚到末端 `value=90=span`，末项 `in_view`、无整页空白；回到整页后 `upper` 恢复 967px、9 个 ID/序号不变、页首高亮重新可见（截图 `panel-short-page-before.png`） |

上面 9 项用夹具候选数据/夹具宽度上限/夹具 `selected_index` 变化：候选文本、360px 上限与高亮跳转
不是真实引擎输出，但面板控件、Pango 排版、`Gtk.ScrolledWindow` 横向视口、GTK 尺寸分配、坐标换算、
XTest 注入都是真实组件；结果 JSON 里逐项带 `fixture: true` 与夹具说明。布局回归里只有“提前触发
一次面板自己的 `_after_layout()`”是人为时序（复现 0.2.8 的真实竞态），滚动本身仍由面板在真实
`size-allocate` 之后完成。

`settings-ui`（真实 GTK3 设置窗口 + XTest 点击保存，`evidence/run-*/settings-checks.json`）：

| 检查 | 结果 | 说明 |
|---|---|---|
| controls-show-real-declared-options | PASS | 真实引擎声明的双拼（自然码）/10 个模糊音/12 个纠错/学习开关都出现；未声明的方案与规则不在列表里 |
| unsupported-scheme-and-rules-refused-before-save | PASS | `mspy`/`not-a-rule` 保存前被拒（`bad-enum`/`unknown-rule`），原文件字节不变 |
| shortcut-conflict-blocks-save-with-message | PASS | 下一页=Page Up → 红条“快捷键冲突：上一页 与 下一页 …”，不写盘 |
| illegal-binding-rejected-with-reason | PASS | `Hyper+x` → “未知修饰键 Hyper；可用 Control/Shift/Alt/Super” |
| save-handler-persists-without-window-write | PASS | 有 `save_handler` 时由回调持久化，窗口自己不写盘 |
| mouse-click-save-writes-config | PASS | XTest 点击“保存” → 文件写入，`page_size=7`、`punctuation.chinese=false`、权限 0600 |
| handler-failure-keeps-config-and-reports-error | PASS | 回调抛 `ConfigError` → 红条、文件不变、未提示成功 |
| handler-crash-keeps-config-and-reports-error | PASS | 回调抛 `RuntimeError` → `handler-error`，同上（截图 `settings-handler-crash.png`） |
| reset-uses-handler-and-refreshes-controls | PASS | “恢复默认”走同一回调路径并回填控件 |
| learning-applied-with-explicit-user-data-dir | PASS | 学习只在显式 `user_data_dir` 下写入 |
| fixture-capabilities-show-controls-only | **夹具** | 用 `config/capabilities-fixture.json` 打开能力位 → 出现双拼下拉与学习开关；仅验证控件门控，不代表功能已实现 |
| settings-readability-contrast-min-4.5 | PASS | 正文/标题/说明/错误条/未支持区域最低 4.74:1 |

## 截图索引（`evidence/run-20261029-123114/`）

| 文件 | 内容 |
|---|---|
| `panel-candidates.png` | 1024×768 全屏：GTK 应用 + 候选面板 + 状态徽标 |
| `panel-candidates-only.png` / `panel-after-mouse-select.png` | 面板窗口单独截图（选词前/后） |
| `panel-mouse-select.png` | 鼠标选词后的应用文本与面板 |
| `panel-page-2.png` / `panel-page-2-only.png` | 第二页候选（全屏 / 面板窗口） |
| `panel-horizontal.png` | 真实引擎候选的横排面板（同一行、从左到右） |
| `panel-long-candidates-300.png` | **夹具**：超长候选 + 300% 字号，省略号生效、面板未超出屏幕、9 项都在 |
| `panel-narrow-360.png` | **夹具**：360px 上限 + 300% 字号，单行横向滚动视口（可见横向滚动条），9 项候选一个不少 |
| `panel-narrow-360-last-candidate.png` | **夹具**：滚到末尾后第 9 个候选可见（原先会被宽度丢弃的那一项） |
| `panel-narrow-360-highlight-scrolled.png` | **夹具**：高亮移到第 9 项后视口自动滚动到它 |
| `panel-narrow-360-multipage.png` | **夹具**：每页 9 项的第 3 页（20 项 / 9 项一页） |
| `panel-budget-9-3-0.png` / `panel-budget-9-3-9.png` | **夹具**：`page_size=9/max_visible=3`，视口 297/402px，整页 9 项靠横向滚动查看 |
| `panel-budget-5-1-0.png` / `panel-budget-5-1-5.png` | **夹具**：旧配置 `page_size=5/max_visible=1`，视口 160px，逐项滚动可达 |
| `panel-layout-reveal-9-3.png` / `panel-layout-reveal-5-1.png` | **夹具**：布局完成后高亮从页首跳到末项，自动滚动到 `la-8`/`la-4` |
| `panel-layout-mid-9-3.png` / `panel-layout-mid-5-1.png` | **夹具**：视口在末端时高亮跳到中间项，自动滚动回 `la-4`/`la-2`（布局前不误滚到 0） |
| `panel-short-page-before.png` | **夹具**：9 项整页切到 4 项末页后滚到末端，末项可见、无整页空白 |
| `panel-last-page.png` / `panel-last-page-only.png` | 真实引擎最后一页（全屏 / 面板窗口） |
| `panel-english-mode.png` | 英文模式（徽标变“英”） |
| `panel-focus-change.png` / `panel-second-entry.png` | 焦点切换：候选清空，另一输入框重新出候选 |
| `panel-scale-100.png` / `panel-scale-150.png` | 字号缩放对比 |
| `settings-real-capabilities.png` | 真实能力下的设置界面（无未支持开关） |
| `settings-shortcut-conflict.png` / `settings-illegal-binding.png` | 冲突与非法配置反馈 |
| `settings-saved.png` | 保存成功后的状态行 |
| `settings-fixture-capabilities.png` | **夹具**能力下的设置界面（出现双拼/学习控件） |

## 布局后自动滚动与短页收缩（本轮返工）

平台缺陷 `integration/defects/interface-layout-after-allocation.md`（0.2.8，固定构建）报告：
360px/300% 字号、真实上下键选中第 4 项并等待 4 秒后，行 `x=313,w=95`、视口 `x=26,w=326`、
`scroll=0`、`in_view=false`；另保留“`hao` 末页 4 项仍 upper=871、scroll=545、in_view=[]”的短页线索。
原始状态见 `integration/evidence/viewport-budget-0.2.8-stable/failure-state.json`。

**原因（在 interface/ 内复现并修复）**

1. **滚动早于分配**：`render()` 重建候选行后立即调用 `_reveal_selected()`；新行此时只有 1px 占位，
   旧代码把 `left=0` 当成真实位置，把视口从末端（640px）滚回 0；随后唯一的空闲回调若也早于
   `size-allocate` 运行，就再没有一次滚动，选中项 4 永久停在视口外（与平台观察一致）。
2. **旧宽度请求污染短页测量**：`rows_box` 在整页时被 `set_size_request(自然宽度)`；下一页
   `get_preferred_size()` 把该请求算进自然宽度，短页仍按整页宽度显示滚动条，滚到末端整页空白。

**修复**

* `reveal()` 在行未真正分配（`width/height <= 1` 或未 mapped）时返回 `None`，不移动视口；
  `render()` 不再同步滚动，改为等 `rows_box`/`scroller`/每一行的 `size-allocate` 之后再核对；
  用 render serial + 视口指纹（尺寸、page_size、upper、行数）决定是否重排，用户拖动滚动条不会
  被拽回高亮项，也没有固定等待。
* 每次进入 `_fit_to_screen()` 先撤销 `rows_box`/`scroller` 的旧 `size_request` 再测量；布局稳定后
  `_clamp_scroll()` 把滚动位置收敛到新的 `upper - page_size`，短页不会停在旧范围。
* 完整页候选、候选 ID、序号、数字映射与 `max_visible` 仅作视口宽度预算的约定不变。

**复现与修复后的数值**（下表是本目录用同一套夹具——“末端 640px → 高亮第 5 项”和
“9 项整页 → 4 项末页”——分别跑固定 0.2.8 面板与修复版得到的；平台原始 gedit 证据的
871/545 见上，两者夹具文本不同但失败形状一致）

| 状态 | 固定 0.2.8 面板 | 本轮修复 |
|---|---|---|
| 高亮变化后的第一个主循环回合 | 640 → **0**（按 1px 占位误滚） | 640（布局未完成，不动） |
| 真实分配完成后 | 210，中间项可见（若没有后续回调则停在 0，平台即如此） | 430，中间项 `in_view`+`selected` |
| 4 项短页 `content_natural_width` / `upper` | 967 / 967（旧请求） | 432 / 432 |
| 短页滚到末端 | `scroll=640`（=upper-page）、`in_view=[]`（整页空白） | `value=span`（正式证据 90）、末项在视口内 |
| 回到 9 项整页 | — | `upper=967`、9 个 ID/序号不变、页首高亮可见 |

正式检查证据 `evidence/run-20261029-131625/panel-checks.json`：
`keyboard-highlight-reveals-after-real-layout`（9/3：2→638、640→430；5/1：2→377、379→216）与
`short-page-shrinks-scroll-extent-and-end-not-blank`（967→432、末端 90=span、末项可见、回到 967）。
产品侧（`integration/`）的重新装配与真实应用复验由平台任务负责，本目录不修改其断言。

## 框架原生候选面板探针（未通过）

`python3 interface/tools/native_panel_probe.py`（不在 `run_checks.py` 的通过条件内）在同样的隔离
X/D-Bus/IBus 会话里**不**禁用面板，观察框架面板能否启动：

* 结果：**UNAVAILABLE** — `evidence/native-panel-20261028-173030/native-panel-probe.json`。
* daemon 用 `--config=disable` 时不会拉起 `ibus-ui-gtk3`；手工启动时面板立即退出：
  `IBUS:ERROR:panel.c:3284:panel_switch_engine: assertion failed: (i >= 0 && i < m_engines.length)`
  （动态注册的引擎没有进入面板的 engine 列表）。
* 想让面板拿到引擎列表要写 `org.gnome.desktop.input-sources`/`preload-engines`，但本机没有
  `ca.desrt.dconf` 服务，`gsettings set` 只打印 dconf-WARNING 且值不落盘。
* 结论：框架原生面板在本环境**未通过运行检查**，界面检查使用本包 GTK 面板（同样是真实组件）。
  启用原生面板需要平台集成任务配置 IBus 输入源，并具备 dconf 服务。

## 未覆盖

* 框架原生面板的外观（见上一节：本环境无法运行）。
* 真实桌面窗口管理器下的定位、多显示器、HiDPI 系统级缩放（只验证了面板自身 `font_scale`）。
* 快捷键与标点在框架提交路径的最终生效（配置和映射已就绪，接线在平台集成任务）。
* `panel.layout="vertical"` 旧式单列只做了单元检查（配置校验与方向切换），未再跑界面场景；
  产品装配（`integration/src/server_ime_product`）的横排断言由平台任务 56d6512a 在其检查里补充。
* 产品级“只有一个自绘候选窗、原生 lookup/auxiliary 不显示”属于平台/装配范围，本包只检查自己的面板。

## 复现注意

* 本机 `Gdk.pixbuf_get_from_window` 在进程尚未建立 Xlib 连接时会触发
  `cairo_surface_mark_dirty_rectangle` 断言并崩溃；步骤脚本因此先调用 `x11.X()`（`tests/x11.py`），
  随后再截图。这是本机 GTK3/cairo 行为，不影响产品功能。
* 两个 GTK 顶层窗口同进程时同样可能触发该断言，所以夹具能力检查放在独立进程
  `tests/settings_fixture_step.py` 中运行。
