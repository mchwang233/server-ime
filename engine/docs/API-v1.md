# 转换接口 1.0

归属 `employee_id: engine`。组件 0.4.0，后端 libpinyin 2.6.0。Python 实现、JSON Lines 服务和平台端口适配器随本文交付；接口不含 IBus/Gtk 类型。

## 立即调用

在工程根目录运行 `python3 engine/examples/python_client.py`，或 `engine/bin/server-ime-engine < engine/examples/requests.jsonl`。第二种方式一行请求对应一行响应；UTF-8 JSON 中汉字可能使用标准 `\u` 转义。

Python：设置 `PYTHONPATH=engine/src` 后 `from server_ime_engine import Engine, EngineError`。`with Engine() as e:`，`s = e.create_session()`，`r = s.input("nihao")`，`r = s.select(r["candidates"]["items"][0]["id"])`，取 `r["commits"][0]["text"]`，得到“你好”。`engine/examples/python_client.py` 是完整可执行例子。

## 会话与配置

`Engine(runtime_dir=None, data_dir=None, user_dir=None, *, user_data_dir=None, base_lexicon=None)` 默认使用组件相对路径 `vendor/runtime/` 和 lexicon 公共增强词库。`user_data_dir` 显式指定个人 UserStore 根目录，省略时不读取个人目录；`user_dir` 仅为兼容旧词库桥的可信 native 表快照入口。`create_session(config=None, session_id=None)` 返回 Session；session_id 可由调用方提供 1–64 个字母、数字、`_` 或 `-`，否则生成 UUID。同一 Engine 最多 64 个会话；共享模型，预编辑、选择约束、光标、页码和配置独立。`session(id)` 查找；`destroy_session(id)` 释放。Engine/Session 的 `close()` 幂等，也支持 with。全部公开方法串行化原生调用，可以跨线程使用；不要 fork 后继续使用原生对象。

配置保留原字段及默认值 `{"schema":"full_pinyin","page_size":5,"incomplete":true,"learning":false}`，新增 `double_pinyin_scheme:"ziranma"`、`fuzzy:{enabled:false,rules:[]}`、`correction:{enabled:true,rules:[]}`。`configure(patch)` 原子校验、合并；page_size 为 1–9，布尔值必须是 JSON boolean。修改配置保留原始拼音但撤销选词并重算候选。schema 可选 full_pinyin/double_pinyin；双拼只开放明确命名的自然码 ziranma。模糊音/纠错 rule 名单由 capabilities 返回；enabled=true、rules=[] 表示全开该类规则。未知键/方案/规则拒绝，不静默降级。learning=true 需要显式 user_data_dir；没有目录时报 learning_unavailable。`incomplete` 允许输入尚未完整的声母时出现候选；不是模糊音或纠错开关。

## Session 方法

| 方法 | 参数与结果 |
|---|---|
| `state()` | 只读状态，commits 始终为空，不重放提交 |
| `input(text)` | 在原始拼音光标处插入；返回状态 |
| `set_composition(text, cursor=None)` | 新增：设置保留大小写、数字、符号的组合输入，详见 MIXED-INPUT.md |
| `input_text(text)` | 新增：在光标处插入组合文本，数字始终为原文 |
| `set_input(text, cursor=None)` | 替换整段拼音；默认光标在末尾 |
| `edit(start, end, text="")` | 替换原始拼音 `[start,end)`；新光标为 start + 插入长度 |
| `key(key)` | 可选便捷按键入口，见下文；框架也可直接调用 edit/select |
| `candidates(page=None)` | 只读指定页候选页对象；不改变当前页 |
| `select(candidate_id)` | 选择最近一次转换的候选；选满时提交并清空，部分选词保留在预编辑 |
| `commit(mode="best")` | best 选首个整句；literal 提交已选汉字加剩余原始拼音 |
| `reset()` | 取消输入，清空预编辑、候选和约束；保留配置，不提交 |
| `configure(patch)` | 修改配置；返回状态 |
| `set_context(private=False,purpose="text",hints=0)` | 切换用途，清空预编辑/失效候选；敏感用途只用公共模型 |

旧入口 set_input/input（尚未进入组合模式时）支持字母、音节分隔符 `'`，大写转小写、ü 转 v。归一化后最多 128 字符。声调数字、空格、标点和混合中文由框架处理，旧拼音入口拒绝并保持原状态。不完整拼音可保留并继续编辑；若有未解析尾部且没有覆盖全串的纠错候选，best 提交报 `incomplete_input`。纠错候选的 annotation 显示规范读音；选择它提交完整纠正结果，但 input.text/parsed_length/preedit.unparsed 仍保留原始输入及原生解析事实，literal 仍逐字保留原文。直接选中已解析部分不会丢弃尾部，例如 nihaovv 选“你好”后仍显示“你好vv”。

`key` 支持字母、ü、`'`、BackSpace、Delete、Left、Right、Home、End、Escape、Return、space/空格、Page_Up、Page_Down、1–9。Return 是 literal 提交；space 选当前页第一项；数字选当前页对应项。未处理的按键返回 handled=false，由平台决定后续行为。页码变化不使候选 ID 失效。

所有编辑位置按**原始拼音字符串 Unicode 码点**计数，所有预编辑光标及样式范围按**显示文本 Unicode 码点**计数；不是 UTF-8 字节。编辑或移动光标撤销全部部分选词约束，但保留并编辑原始拼音。当前候选始终针对首个尚未选定的音节位置，移动光标用于改字，不自动将候选锚定到光标所在音节。

## 状态与提交

状态字段如下，完整机器可读定义见 `../api-v1.schema.json`。

- `api_version`, `session_id`, `revision`, `handled`, `config`。
- `input`: text、cursor、parsed_length、selected_length。后两者都是原始拼音位置。
- `preedit`: text、cursor、visible、segments、preview、unparsed。segments 的 kind 为 selected/pinyin；preview 是整句最佳猜测；unparsed 显式保留未解析尾部。
- `candidates`: page、page_size、total、has_previous、has_next、items。items 含 id、index（全局从 0 起）、text、annotation、kind（sentence/phrase）。分页读取有界；total 为排序及去重后的候选总数。
- `commits`: 本次操作新增提交事件列表，每项含 text、source（candidate/literal）、input（原始拼音）、candidate_id（可能 null）、event_id、learning_eligible，新增 learning（recorded/reason 等实际记录结果）。敏感上下文 learning_eligible=false；普通上下文的技术资格仍不等于允许学习。
- 新增 `context`（private/purpose/hints）与 `personalization`（active/learning_effective），便于确认当前策略。

候选 ID 是不透明、会话绑定且带版本的凭据。输入、编辑、选择、重置、配置变化使旧 ID 失效；销毁再创建相同 session_id 也不能复用旧 ID。返回对象为独立快照，可由调用方保存。`state()` 不会重放提交；网络式重试并无请求幂等保障，请按 event_id 去重并仅在事件首次到达时向应用提交一次。

部分选词不向应用发送文本。例如 nihaoshijie 选“你好”得到预编辑“你好shijie”，再选“世界”仅提交一次“你好世界”。原生整句候选带整个前缀，封装会裁去显示中的重复前缀。

## JSON Lines 协议

请求 `{"api_version":"1.0","id":1,"op":"create","args":{"session_id":"s1"}}`。id 可省略、为 null、字符串或整数。之后请求增加顶层 `session_id:"s1"`。op 有 capabilities、create、destroy，以及与 Session 同名的 state/configure/input/set_input/edit/key/candidates/select/commit/reset/set_context/set_composition/input_text；args 的键就是上表参数名。destroy 不需要 args。create 的 session_id 放在 args 内；其他操作放在顶层。

引擎级新增操作不要求 session_id：add_phrase 的 args={text,pinyin,count?}；remove_phrase 的 args={text,pinyin?}；import_dictionary 的 args={entries}；reload_lexicon 和 learning_status 的 args={}。Python 上对应 Engine 同名方法。新增操作只由 capabilities 声明，旧操作及返回字段保留。

JSONL 可用 `--user-data-dir /explicit/writable/path`；还支持 --base-lexicon、--user-dir、原有 --runtime-dir/--data-dir。没有用户目录时仍可转换、导入公共内存词条，但学习及个人短语管理报 learning_unavailable。学习/数据文件错误有结构化错误码；提交阶段的学习写入失败附在 learning 字段，不把已选文字丢掉。

成功响应 `{"api_version":"1.0","id":1,"ok":true,"result":...}`；create 的 result 是初始状态，destroy 为 null，candidates 为候选页，其余会话操作返回状态。错误响应 `{"api_version":"1.0","id":1,"ok":false,"error":{"code":"stale_candidate","message":"..."}}`。错误不终止服务。每条请求最多 65536 字节（含换行），拒绝非有限数值，超长行会丢弃至换行。EOF 释放全部会话。stdin/stdout 是唯一传输，没有监听端口、账号或云服务。

主要错误码：invalid_request、invalid_json、unsupported_version、unknown_operation、invalid_argument、invalid_input、input_too_long、invalid_config、unsupported_config、session_exists、unknown_session、session_limit、closed、stale_candidate、invalid_candidate、incomplete_input、dependency_missing、incompatible_data、native_error。Python 使用带 `code` 属性的 EngineError。底层库自身损坏或 ABI 不兼容可能导致原生进程退出；不加载不可信二进制词库。

## 平台端口对接

`PYTHONPATH=engine/src:platform`，工厂 `server_ime_engine.platform_adapter:create_session`，实现当前 `platform/server_ime/port.py` 的 set_context/convert/select/reset/close。backend_id 为 libpinyin-2.6.0-api1，deterministic=false（真实引擎，不是测试 fixture）。接口通过结构化属性兼容，不依赖平台包。该端口允许**部分应用提交**，适配器会把核心的部分预编辑选择映射为 `Selection(commit="你好", remaining="shijie", cursor=0)`；与核心的整句一次提交语义不同，已单独检查。按键、焦点、用途信号的识别与实际应用提交仍由 platform 拥有；适配器现将 private/purpose/hints 传给核心，核心再次执行个人数据隔离。工厂可选接收 config 和 Engine 参数；原有无参调用仍有效。

## 兼容扩展

1.x 保留现有字段、方法、坐标单位、候选 ID 生命周期及提交语义。响应可以添加字段；消费者忽略未知字段。新操作与配置必须先由 capabilities 声明；当前实现仅接受 1.0，未来服务器可协商/兼容旧客户端。删除或改变既有字段的含义需升主版本。

组合输入、双拼、模糊音、纠错、导入及学习均已由 capabilities 声明为 true；能力位不代表所有会话都有持久目录。方案/规则边界见 FEATURES.md，持久化与用途策略见 EXTENSIONS.md。原生指针、模型 token 或磁盘路径不进入候选 ID。

0.3.0 引入的四个新增纠错规则为 transpose/delete/insert/substitute；旧规则名及禁用行为保留，rules=[] 自动包含全部新旧规则。完整有效拼写不做单编辑改写。首音节约束整句候选属于一般候选扩展，不受拼写纠错开关控制；它保留原生前三候选的顺序。算法边界与证据见 FEATURES.md、QUALITY-PERFORMANCE.md。

0.4.0 新增 set_composition/input_text 和 state.composition，旧 set_input 的校验与归一化保持原样；新增入口、片段学习、数字选择和平台端口约定见 [MIXED-INPUT.md](MIXED-INPUT.md)。0.3.0 引入的纠错规则仍全部开放，单次实际解码最多四个修正读音；长串词语枚举只搜索局部 24 码点窗口，全串 N-best 仍保留。
