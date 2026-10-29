# 引擎接入说明

归属 `employee_id: lexicon`。本文件说明词库数据如何被 `engine`（libpinyin 2.6.0）读取、个人学习如何落到用户表，以及 engine 后续应补的正式接口。

## 1. 当前事实

- engine 0.1.0 的 `Engine.__init__` 调用 `Native.init(str(data_dir).encode(), None)`，即 `pinyin_init(system_dir, NULL)`；`INDEX 文档`明确 `dictionary_import=false`、`learning=false`。
- libpinyin 2.6.0 只有在 `pinyin_init` 第二个参数给出用户目录时，才会加载 `user.conf`、`user_pinyin_index.bin`、`user_phrase_index.bin`、`user_bigram.db`；传 `NULL` 时 `g_build_filename(NULL, …)` 得到空路径，不会读取任何用户表。
- 因此 engine 0.1.0 **不能**通过公开 API 加载个人词库。lexicon 不修改 engine 源码。

## 2. 兼容桥接（本阶段）

`lexicon/src/lexicon/engine.py:open_engine(user_dir=...)`：

1. 校验用户目录四类文件齐全；
2. 若 `Engine.__init__` 已有 `user_dir` 参数（未来版本），直接传入；
3. 否则在构造 `Engine` 的瞬间，把 `server_ime_engine.core.Native` 替换为捕获了用户目录的子类，使 `pinyin_init(system, user_dir)` 生效；构造完成立即恢复原类；
4. 校验 engine `API_VERSION=1.0` 和 capabilities，返回可正常使用的 `Engine`。

桥接不 edit `engine/`、不改变会话 API、不改变候选 ID 语义；只影响构造时的一次原生初始化。`engine.lexicon_bridge` 记录 `bridge` 类型、engine 版本、后端、用户目录，便于诊断。若 engine 内部结构改名，桥接会以 `engine_incompatible` 失败，而不是静默不加载。

## 3. 数据流

```text
data/base/lexicon-v1.jsonl ─┐
                            ├─ merged by (text,pinyin) ─ native/ (libpinyin USER_DICTIONARY)
user-data/words.jsonl ──────┘                                  │
                                                               ▼
engine.open_engine(user_dir=native) ── 候选排序/整句解码
```

- 基础词库和用户词条按 `(text, pinyin)` 合并；同键时个人频次加到基础频次上（上限 1,000,000），类型以个人条目为准；同文本不同读音保留两条。
- `native/` 是一次性加载的快照。用户数据变化后需 `lexicon native build` 重建，然后丢弃旧 engine 实例并新建；已有会话不会热更新。
- 建议平台在启动、登录、空闲或显式“应用设置”时重建；重建是原子替换，失败保留旧表。

## 4. 学习事件

engine 的提交事件含 `text`、`source`、`input`（原始拼音）、`candidate_id`、`event_id`、`learning_eligible`。平台/界面应：

1. 只把 `source=candidate` 且 `learning_eligible=true` 的事件交给 lexicon；
2. 另外检查用户开关、`private`/密码/PIN/凭据用途和输入目的；
3. 调用 `UserStore.record_commit(text, pinyin, event_id=..., private=..., purpose=...)`；
4. 使用 `event_id` 去重；不要保存 `candidate_id` 作为词库主键；
5. 拼音必须是音节分隔形式。平台可传 engine 提交的 `input`（若用户输入了分隔符），或由候选选择边界生成；无分隔且无法确定时 lexicon 返回 `invalid_record`，不会猜测。

关闭学习时不写任何学习记录，也不调用 `pinyin_train`/`pinyin_save`。lexicon 从不使用原生训练接口，频次更新是显式、可审计的 `words.jsonl` 变更。

## 5. 给 engine 的接口要求（后续）

1. `Engine(..., user_dir=None)` 或 `create_session(user_dir=...)`：把用户目录传给 `pinyin_init`，并在 capabilities 中声明 `user_dictionary=true`。
2. 可选的 `import_dictionary` 操作：输入按 `format/README.md` 的 JSONL/原生表版本，返回接受/拒绝明细、词库版本和新 revision；在临时用户模型导入、校验、原子切换；失败保留旧模型。
3. 明确 `pinyin_save`/`pinyin_train` 不会写入 lexicon 的用户目录；若 engine 自己要学习，必须使用独立目录和单写者锁。
4. 重建后旧候选 ID 失效、会话按既有规则重算；不要把词库 token/路径塞进候选 ID。
5. 若加载原生用户表失败，返回明确错误码，不要退化成“看似正常但无个人词”的状态。

## 6. 版本与校验

- 后端固定 libpinyin 2.6.0 / 数据 `binary format 6`、`model data 14`、BerkeleyDB；`native/` 不能跨 libpinyin 大版本复制。`tools/run_checks.py` 在前后比对 engine 数据目录完整指纹。
- 用户目录/基础词库版本不一致时，`UserStore.verify()` 给出 `native_stale` 警告；`native build` 会重建。
- 平台/交付必须保留用户数据目录；卸载不应删除它（除非用户显式选择清除）。
