# 词库与用户数据格式 v1

本目录是词库学习对引擎、平台、界面和交付的稳定数据接口。所有文件均为 UTF-8；JSON 使用标准 JSON，JSONL 每行一个对象。当前版本只使用 Python 标准库。

## 1. 基础词库增强记录（`ime-lexicon-base/1`）

`data/base/lexicon-v1.jsonl` 每行一条：

```json
{
  "id": "w-5ee2dcc3736d01e4",
  "text": "词库增强",
  "pinyin": "ci'ku'zeng'qiang",
  "count": 160,
  "kind": "base",
  "domain": "ime",
  "source": "server-ime-curation-v1",
  "reading_source": "pypinyin-0.55.0",
  "license": "CC-BY-4.0"
}
```

- `id`：`w-` + `sha256(text + NUL + pinyin)` 前 16 位；不是磁盘偏移或引擎 token。
- `text`：仅 CJK，1–16 个码点；基础数据实际为 2–6 字。
- `pinyin`：小写 ASCII，`v` 表示 ü，音节之间一个 `'`；音节数必须等于 `text` 的码点数。
- `count`：1–1,000,000；传给 libpinyin 的频次。个人条目与基础条目同键时，编译原生表会把个人频次加到基础频次上（上限 1,000,000），避免一次学习反而降低基础词排名；类型以个人条目为准。
- `kind`：本版本基础数据为 `base`；用户数据为 `learned` 或 `custom`。
- `source`/`license`/`reading_source`/`domain`：来源追溯字段；`data/base/manifest.json` 保存源文件哈希、生成器、校验与构建命令。

基础数据按 `base-v1` 冻结；修改必须形成新版本并重新生成 manifest，不能直接编辑 `.jsonl` 后覆盖旧 manifest。

## 2. 个人数据目录（`ime-lexicon-user/1`）

```text
<data-dir>/
  meta.json                  # schema、store_id、revision、学习开关、基础库身份、计数、文件哈希
  words.jsonl                # 每个 (text, pinyin) 一条用户记录
  lock                       # flock 单写者锁；不要删除或手工写入
  audit.jsonl                # 管理操作审计（开关、导入、恢复、修复）；不含候选内容
  native/                    # 派生 libpinyin 用户表（user.conf、user_pinyin_index.bin、user_phrase_index.bin、user_bigram.db、user.bin 等）
  native-manifest.json       # native/ 的构建身份、文件哈希、基础库哈希、对应 store revision
  backups/<backup-id>/       # manifest.json + meta.json + words.jsonl
```

`meta.json` 主要字段：

```json
{
  "schema": "ime-lexicon-user/1",
  "store_id": "uuid",
  "created_at": "2026-10-28T09:30:27Z",
  "updated_at": "2026-10-28T09:30:27Z",
  "revision": 4,
  "writer": "lexicon",
  "learning": {"enabled": false, "updated_at": "...", "reason": "created disabled", "actor": "init"},
  "base": {"lexicon_version": "base-v1", "sha256": "…", "entry_count": 369},
  "limits": {"max_entries": 20000, "max_count": 1000000, "dedupe_window": 256},
  "last_event_ids": ["…"],
  "counts": {"base": 0, "learned": 1, "custom": 1, "total": 2},
  "files": {"words.jsonl": {"sha256": "…", "bytes": 1234}}
}
```

`words.jsonl` 每条：

```json
{
  "id": "w-3f72895fff0e847d",
  "text": "你好",
  "pinyin": "ni'hao",
  "count": 2,
  "kind": "learned",
  "source": "commit",
  "first_seen": "2026-10-28T09:30:27Z",
  "last_seen": "2026-10-28T09:31:02Z"
}
```

- 主键是 `(text, pinyin)`，不是候选 ID、事件 ID 或 libpinyin token。
- `kind=learned` 由提交事件增加 `count`；`kind=custom` 由用户显式添加，提交也继续增加频次。
- `count` 上限 1,000,000；达到上限后不再增加，不溢出。
- 时间戳为 UTC RFC 3339，秒级。
- 未知字段保留，供较新写入者的可选元数据在旧读取者读写后仍然存在。

### 兼容性

| 数据 | 当前版本 | 读取规则 |
|---|---|---|
| 个人数据目录 | `ime-lexicon-user/1` | 仅接受主版本 1；主版本不同返回 `incompatible_version`，不尝试猜测或覆盖 |
| 导出 bundle | `ime-lexicon-user-bundle/1` | 主版本 1 接受；`compatibility.min_reader` 高于 1 或 `max_reader` 不覆盖 1.x 时拒绝 |
| 备份 | `ime-lexicon-backup/1` | 仅接受 1；备份内 `meta.schema` 也必须是 `ime-lexicon-user/1` |
| 基础词库 | `ime-lexicon-base/1` / `base-v1` | manifest 的 SHA-256 必须与 `lexicon-v1.jsonl` 一致 |
| native 清单 | `ime-lexicon-native/1` | 记录基础库哈希与 store revision；过期只告警，不当作数据损坏 |
| 引擎 | API 1.0 / libpinyin 2.6.0 | 不兼容时明确报错，不改写用户数据 |

1.x 内的新增可选字段是兼容的；删除或改变既有字段含义必须升主版本。旧读者遇到新主版本必须报错并保持原数据不变。

## 3. 学习开关与记录规则

- 新建 store 默认**关闭**学习（`enabled=false`）；开关持久化在 `meta.json`。
- `record_commit(text, pinyin, learning_eligible=true, private=false, purpose="text", event_id=None)` 只有在以下条件全部满足时才写入：
  1. 用户开关为开；
  2. `learning_eligible=true`（只表示技术资格，不表示用户授权）；
  3. `private=false`；
  4. `purpose` 不在 `password`、`pin`、`secret`、`credential`、`private` 中；
  5. `(text, pinyin)` 通过 CJK、长度、音节和频次校验；
  6. 可选 `event_id` 未在最近 256 个事件中出现。
- 任一条件不满足时返回 `recorded=false` 及明确 `reason`（`learning_disabled`、`not_eligible`、`private_input`、`purpose_not_allowed`、`duplicate_event`、`invalid_record`、`limit_exceeded`），**不写 words、meta 或 audit**，进程重启后开关保持关闭。
- 关闭学习后，已有记录保留但不再增长；不会调用 `pinyin_train` 或 `pinyin_save`，也不会把 `native/` 当作训练入口。
- 学习只发生在本地；包内没有网络代码，导出文件由用户自行处理。
- 事件 ID 去重窗口 256；窗口外的旧 ID 可能再次计数，调用方仍应按自己的事件存储去重。

## 4. 导入 / 导出

`export` 生成 `ime-lexicon-user-bundle/1`：

```json
{
  "format": "ime-lexicon-user-bundle/1",
  "producer": {"component": "lexicon", "version": "0.1.0", "employee_id": "lexicon"},
  "exported_at": "…",
  "source": {"schema": "ime-lexicon-user/1", "store_id": "…", "revision": 4, "base": {…}},
  "compatibility": {"min_reader": "1.0", "max_reader": "1.x"},
  "learning": {"enabled": false},
  "entries": [ …用户记录… ],
  "entry_count": 2,
  "checksum": {
    "algorithm": "sha256",
    "scope": "format, compatibility, entries and entry_count; excludes checksum, producer, exported_at, source, learning",
    "value": "…"
  }
}
```

- 导出按 `(text, pinyin)` 排序；`entries`、`count`、`kind`、时间戳和来源均保留。
- 校验和覆盖载荷（格式、兼容声明、条目、条数），不覆盖本机 `store_id`/revision 与学习开关，所以导入到另一台机器后再导出仍得到相同载荷校验和。
- `import` 默认 `merge`：按主键合并，`count` 取较大值，`custom` 优于 `learned`，`first_seen` 取较早、`last_seen` 取较晚；`replace` 用 bundle 条目替换全部个人条目（基础词库不受影响），需要显式 `--mode replace`。
- 导入先完整校验，再在单写者锁内一次性提交；任何失败（JSON 损坏、校验和不符、版本不兼容、条目非法、超限）都不会改变现有 words/meta。
- `--dry-run` 只报告将新增/更新/不变的数量。

### 兼容旧格式（迁移）

`import` 还接受 `ime-user-words/0` 形态：

- JSON 数组：`[{"word":"词库增强","pinyin":"ci'ku'zeng'qiang","freq":4}]`；
- JSON 对象：`{"format":"ime-user-words/0","words":[…]}`；
- TSV（`.tsv`/`.txt`）：`text<TAB>pinyin[<TAB>count]`，`#` 开头为注释。

迁移结果统一为 `kind=learned`、`source=legacy-v0`、`migrated_from=ime-user-words/0`；缺省 count 为 1。非法条目整批拒绝，不部分导入。

## 5. 备份与恢复

- `backup` 在 `backups/<UTC 时间>-<label>-<随机>/` 写入 `manifest.json`、`meta.json`、`words.jsonl`，manifest 记录两个文件的 SHA-256、条数、store revision、许可/基础库身份与创建时间。
- `verify_backup` 校验 manifest schema、文件哈希、meta schema、逐条记录和条数；损坏或主版本不兼容时返回明确错误。
- `restore` 先完整校验，再自动创建 `pre-restore` 备份，然后原子替换 words/meta，并恢复备份中的学习开关。恢复后的 `native/` 是派生数据，`verify` 会提示 `native_stale`；执行 `native build`（CLI 的 `restore --rebuild`）后引擎即可看到恢复后的词条。
- `backups prune --keep N` 仅删除带有效 manifest 的旧备份，保留最新 N 个。
- 备份不含 `native/` 二进制表，以免把不同 libpinyin 版本或不同基础库的派生文件误当成用户数据恢复。

## 6. 持久化、原子性与写入所有权

| 路径 | 唯一写入者 | 其他组件 |
|---|---|---|
| `<data-dir>/meta.json`、`words.jsonl`、`audit.jsonl`、`backups/` | `lexicon`（CLI/库） | 只读；平台/界面不得直接改 |
| `<data-dir>/native/`、`native-manifest.json` | `lexicon native build` | engine 只读加载；不得调用 `pinyin_train`/`pinyin_save` 写入 |
| `engine/vendor/runtime/data` | engine 上游/安装包 | 本包只读；检查前后指纹必须一致 |
| `lexicon/data/base/*`、`lexicon/build/base-v1/*` | 构建工具 | 运行时只读 |
| bundle 文件 | 用户选择的路径 | 由用户保管；不自动上传 |

- 所有状态写入采用临时文件 + `fsync` + `os.replace`；目录项也执行 `fsync`。
- 变更加 `flock` 排他锁；读/导出加共享锁；跨进程单写者，第二个写者立即得到 `store_locked`，不会等待或覆盖。
- 极端崩溃可能落在 `words.jsonl` 与 `meta.json` 两次替换之间；`meta.json` 记录了 words 的哈希与计数，下次加载/`verify` 会报 `store_corrupt`，`repair` 可从 words 重算计数和哈希（不猜测丢失条目）。
- 数据目录创建为 `0700`；状态文件由 `mkstemp` 创建（`0600`）；审计文件显式 `0600`。用户应保证不把该目录交给其他账户写入。
- 写入所有权是单写者模型：`lexicon` 是唯一写入者；engine 只在初始化时读取 `native/`；平台负责把用户数据目录路径传给 lexicon，不直接写文件。

## 7. 错误码

| code | 含义 | 数据是否改变 |
|---|---|---|
| `invalid_record` / `invalid_text` / `invalid_pinyin` / `pinyin_length_mismatch` | 记录、文本、拼音或音节数非法 | 否 |
| `invalid_argument` | 参数类型/范围错误 | 否 |
| `store_missing` / `store_exists` | 未初始化 / 目标目录非空 | 否 |
| `store_locked` | 另一个进程持有写锁 | 否 |
| `store_corrupt` | 状态文件与哈希/计数不一致 | 否，需 `repair` |
| `incompatible_version` | 数据主版本或 bundle 读取者要求不兼容 | 否 |
| `checksum_mismatch` | bundle 或备份内容被改动/截断 | 否 |
| `invalid_json` / `invalid_format` | 文件不是 JSON 或缺少必需字段 | 否 |
| `limit_exceeded` | 条目数或频次超过上限 | 否 |
| `learning_disabled` / `private_input` / `purpose_not_allowed` / `not_eligible` / `duplicate_event` | 学习门控拒绝（返回 `recorded=false`，不是异常） | 否 |
| `native_unavailable` / `native_build_failed` | libpinyin 运行库/系统数据缺失或用户表构建失败 | 旧 native 保留 |
| `engine_unavailable` / `engine_incompatible` / `user_data_missing` | 引擎不可导入、API 不兼容或用户表不完整 | 否 |
| `unknown_backup` | 备份 ID 不存在或路径非法 | 否 |
| `contamination` | 基础词库与冻结语料存在完全相同的答案/读音 | 构建拒绝 |

## 8. 默认路径与集成

- CLI 与库接受显式 `--data-dir`；未给出时使用 `$XDG_DATA_HOME/server-ime/lexicon`，否则 `~/.local/share/server-ime/lexicon`。目录不会自动创建，需显式 `init`。
- 平台/交付负责把该路径作为用户数据目录传给 `lexicon`，并在安装/升级时保留它。
- 引擎集成见 `docs/engine-integration.md`：当前 engine 0.1.0 不接受 user_dir，`lexicon.engine.open_engine` 在构造时注入；不影响 engine 源码和接口。
