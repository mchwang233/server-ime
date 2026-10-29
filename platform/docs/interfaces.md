# 平台、引擎与界面接口 v1

employee_id: **platform**。实现源为 `server_ime/port.py`、`controller.py`、`ibus_adapter.py`、`state_service.py` 与 `ui_client.py`。

## 转换端口（供 employee_id=engine / 后续 platform 集成使用）

`--backend MODULE:FACTORY` 导入无参工厂，每个 IBus engine 实例创建一个 session。平台不读取引擎词库、学习文件或配置；引擎工厂自行传入其隔离数据目录。端口采用结构约定：返回对象可为引擎自己定义的 dataclass，不必依赖平台包，只需具备下表中的属性。平台校验结果并复制成自己的不可变快照。

| 成员 / 方法 | 参数与返回 | 行为约定 |
|---|---|---|
| `backend_id` | str | 可诊断的后端标识 |
| `deterministic` | bool | 固定测试后端为 true；真实转换后端为 false |
| `set_context(context)` | `purpose:int, hints:int, private:bool` | 原样传递框架用途和提示位；未知位保留 |
| `convert(composition, cursor)` | 返回 `preedit:str, cursor:int, candidates:Sequence[Candidate], literal_digits:bool=False` | composition 为原始输入串；输入和显示光标均按 Unicode 码点计数，非字节；原文位置的数字应插入 |
| `Candidate` | `id:str, text:str, annotation:str` | 本次列表内 ID 唯一；顺序为引擎排名；不含空 ID 或空文本 |
| `select(candidate_id)` | 返回 `commit:str, remaining:str, cursor:int` | 原子选择当前结果；可提交一段并保留剩余拼写；空 commit 允许 |
| `reset()` | 无返回 | 丢弃瞬态组合，不产生提交 |
| `close()` | 无返回 | 释放会话资源 |

原始组合上限 256 码点，每次转换最多 200 个候选。光标必须是整数且在对应字符串范围内。v1 是同步端口：调用发生在 IBus 主循环，真实引擎必须自行保证响应时间；没有伪装成异步的超时保证。后台/进程端口及超时恢复由后续集成在真实后端响应特性明确后决定。

转换异常或不合法结果会转为固定状态码 `backend-convert-failed`，保留已消耗的原始输入，供 Enter/Space 提交原文。候选选择失败保留组合并显示 `backend-select-failed`，不会伪造转换结果。异常正文不进入 UI 或默认日志。后端资源构造失败会使引擎创建失败，属于实际故障，不会隐式替换为测试后端。

## 按键与生命周期

下表描述基础 `Controller` 的兼容规则。完整产品使用 `ProductController`：保留组合中的
ASCII 大小写、数字及符号，调用引擎 0.4.0 的 `set_composition`，上限 128 码点。
`literal_digits=true` 时顶排数字插入；纯拼音位置的 1–9 选词；只有原文候选时继续插入数字。
数字小键盘的 `KP_0..KP_9` 总是插入数字，可处理 `abc123` 一类有歧义的原文。
无组合时的标点使用界面配置，组合中的标点原样保留；中文逗号可先选词再按逗号。
完整说明与实际应用复现见 `integration/docs/mixed-input.md`。

| 触发 | 行为 |
|---|---|
| 小写 a–z、非空组合中的 `'` | 在原始光标处插入并转换 |
| 空格 | 选择当前候选；无候选时提交原始拼写 |
| 1–9 | 选当前页对应项，受 page_size 限制；超出候选范围时按普通字符处理 |
| Up/Down、PageUp/PageDown | 移动候选/翻页，边界不循环 |
| Left/Right、Home/End、Backspace/Delete | 编辑原始组合，重新转换 |
| Enter / 小键盘 Enter | 提交原始拼写 |
| Escape、reset、disable、focus-out | 取消组合并清空预编辑和候选，不自动提交 |
| Tab | 取消组合，返回 false，让应用切换焦点 |
| Ctrl+Space | 切换中英；取消尚未提交的组合 |
| Ctrl/Alt/Super/Hyper/Meta 的其他组合 | 取消组合，返回 false |
| key release、英文模式、未聚焦、未启用 | 返回 false；不再额外 forward，避免重复按键 |
| 其他 ASCII 标点/大写 | 有组合时先提交原始拼写，再透传该键；中文标点配置归界面/集成后续任务 |

默认候选页为 5 项，controller 构造参数可设为 1–9；当前没有持久化设置写入口。面板原生候选点击使用当前页相对下标；自定义 UI 使用候选 ID 加版本号。

focus-in 开始空组合；focus-out、disable、reset 均调用后端 reset。IBus 预编辑使用 `PreeditFocusMode.CLEAR`，客户端失焦时不提交遗留拼写。无焦点时外部选择请求也返回 false。`context_id` 是 **engine 实例的随机不透明 ID**，不是应用窗口或 IBus InputContext 路径。IBus 全局引擎可以在输入框之间复用实例；每次生命周期变化都会增加 revision。本机 1.5.25 不提供本交付可用的 focus-id 虚函数，接口不声称能够识别应用身份。

输入用途 `DIGITS(2)`、`NUMBER(3)`、`PHONE(4)`、`PASSWORD(8)`、`PIN(9)` 直接透传。PASSWORD/PIN 还置 private。其余用途（包括 URL/Email/Terminal）继续传给后端，不强行禁用中文。提示值按整型原样传递，未知位不赋予自定义语义。本机 IBus 没有 PRIVATE hint；private 从 PASSWORD/PIN 用途派生。用途或提示改变时取消旧组合。敏感/直接输入下不把按键字符送给 convert，也不发布候选。平台不索取 surrounding text，不记录正常会话的输入内容；检查日志只包含固定测试数据。

IBus 原生事件映射依照 [IBusEngine API](https://ibus.github.io/docs/ibus-1.5/IBusEngine.html) 与 [IBusInputContext API](https://ibus.github.io/docs/ibus-1.5/IBusInputContext.html)：预编辑使用 update-preedit、候选使用 LookupTable、提交使用 commit-text，最终证据取自客户端接收事件。

## 候选 / 状态接口（供 employee_id=interface 使用）

接口位于**当前 IBus bus**，不是桌面的 session bus。Python 客户端先设置目标 `IBUS_ADDRESS` 并使用 `server_ime.ui_client.StateClient`；订阅需有 GLib 主循环。无明确地址时客户端与适配器都会拒绝自动发现宿主会话。

- Bus name：`org.freedesktop.IBus.ServerIME`
- Object path：`/org/freedesktop/IBus/ServerIME/State`
- Interface：`org.superpartner.ServerIME1`

| 方法 / 信号 | D-Bus 类型 | 含义 |
|---|---|---|
| `ListContexts()` | `() → (as)` | 所有已创建 engine 实例 ID |
| `GetState(context)` | `(s) → (s)` | 完整 JSON 快照；未知 ID 抛 UnknownContext |
| `SelectCandidate(context,id,revision)` | `(sst) → (b)` | 仅当前版本、聚焦且可输入时接受 |
| `Page(context,delta,revision)` | `(sit) → (b)` | delta 为 -1/+1 |
| `SetMode(context,mode,revision)` | `(sst) → (b)` | mode 为 zh/en；不写持久配置 |
| `StateChanged(context,json)` | `(ss)` | 每次更新完整快照，revision 单调增加 |
| `ContextRemoved(context)` | `(s)` | engine 销毁；UI 删除对应缓存 |

每份快照有 `schema_version:1`、`context_id`、`revision`、`focused`、`enabled`、`mode`、`purpose`、`hints`、`private`、`direct_input`、`backend`、`deterministic`、`status`、`error`。

展示字段为 `preedit:{text,cursor,visible}`、`candidates:[{id,text,annotation,index}]`、`candidate_visible`、`literal_digits`、`selected_index`、`page_start`、`page_size`、`page_count`。候选数组是完整有限列表；UI 显示 `candidates[page_start:page_start+page_size]`。不记录已提交文本到状态历史。取消后发送空预编辑和空候选。收到 false 时重新读取快照，不能对旧 revision 自动重试选择。

```python
from gi.repository import GLib
from server_ime.ui_client import StateClient

client = StateClient()
client.subscribe(on_state=render_snapshot, on_removed=forget_context)
for context_id in client.list_contexts():
    render_snapshot(client.get_state(context_id))

# 使用当前显示的同一份快照发动作；命令会在引擎进程重新检查焦点和版本。
accepted = client.select_candidate(displayed_snapshot, clicked_candidate_id)
# client.page(displayed_snapshot, 1)
# client.set_mode(displayed_snapshot, "en")
GLib.MainLoop().run()
```

原生 IBus LookupTable、InputMode/Backend 属性也同时更新，可直接复用框架面板。独立检查为了隔离运行禁用了原生面板；候选协议和 UI 客户端已测试，面板外观、DPI、鼠标窗口交互仍由界面任务检查。

## 启动与装配约定（供 employee_id=delivery 使用）

保留 `platform/launch.py` 与其旁边的 `server_ime/` 包即可运行。需要系统 Python 3.9+、GI IBus typelib 和 ibus-daemon；GTK3/Xvnc/XTest 只是本交付检查环境的额外依赖。引擎真实依赖由 engine 负责。

不要把 `evidence/`、`.runtime/`、tests 或测试词条作为用户运行配置；测试后端只能显式启用。manifest 生成器写绝对 Python 和启动脚本路径；安装/迁移后应在实际安装位置重新生成。XML 的 rank 为 0，生成动作不启用任何输入法。使用 daemon 自动启动的 `--ibus` 模式时，必须继承明确的 `IBUS_ADDRESS`；无地址时会报错而非自动连接宿主。该部署模式尚未做启动检查。

IBus 1.5.25 创建私有 daemon 时应传 `--address=unix:dir=<私有目录>`，并用私有 `IBUS_ADDRESS_FILE` 读取生成的客户端地址；直接 `unix:path=<socket>` 在本机会被创建成目录后导致绑定失败。原因可见 [1.5.25 server.c](https://github.com/ibus/ibus/blob/1.5.25/bus/server.c)，重现与修复后的日志保留在 evidence 中。
