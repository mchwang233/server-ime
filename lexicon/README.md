# server-ime 词库学习组件 0.1.0

负责人 `employee_id: lexicon`。本组件交付可追溯的基础词库增强数据、用户词频与自定义短语、导入导出、备份恢复、禁用学习控制，以及冻结的 200 条质量语料。运行时只依赖 Python 3.9+ 标准库和 engine 已固定的 libpinyin 2.6.0；不修改 `engine/`、不联网、不启动服务。

## 目录

| 路径 | 内容 |
|---|---|
| `data/base/` | 369 条基础词库增强数据、词条源表、读音源、manifest（来源/许可/哈希/构建命令） |
| `corpus/eval/` | 200 条冻结评估语料、冻结 manifest、计分方法 |
| `format/` | 基础/用户/bundle/语料格式说明、版本兼容、写入所有权、错误码；JSON Schema |
| `src/lexicon/` | 库：记录校验、libpinyin 原生用户表、用户数据、导入导出、备份、语料评分、引擎桥接、CLI |
| `bin/lexicon` | 可执行 CLI |
| `tools/` | 基础词库构建、原生表构建、语料冻结、读音生成、全量检查 |
| `build/base-v1/` | 由基础词库编译的 libpinyin 用户表及构建 manifest（派生数据） |
| `checks/` | 检查结果、环境与复跑入口；临时用户数据位于 `checks/runtime/` |
| `licenses/` | GPL-3.0 与 pypinyin MIT 许可副本 |

## 快速开始

在工程根目录执行（CLI 的全局 `--data-dir` 放在子命令之前）：

```sh
# 1. 可复现地生成基础词库与原生用户表
python3 lexicon/tools/build_base.py
python3 lexicon/tools/build_native.py

# 2. 初始化个人数据（默认关闭学习）
lexicon/bin/lexicon --data-dir lexicon/checks/runtime/user init
lexicon/bin/lexicon --data-dir lexicon/checks/runtime/user learning status

# 3. 打开学习并记录一次候选提交（event_id 用于幂等）
lexicon/bin/lexicon --data-dir lexicon/checks/runtime/user learning on --reason "user enabled"
lexicon/bin/lexicon --data-dir lexicon/checks/runtime/user learn 词库增强 "ci'ku'zeng'qiang" --event-id demo-1

# 4. 添加自定义短语，重建引擎可读的原生表
lexicon/bin/lexicon --data-dir lexicon/checks/runtime/user phrase add 芷若词库 "zhi'ruo'ci'ku" --count 500
lexicon/bin/lexicon --data-dir lexicon/checks/runtime/user native build --probe 3
lexicon/bin/lexicon --data-dir lexicon/checks/runtime/user engine-probe zhiruociku

# 5. 导出、备份、恢复、关闭学习
lexicon/bin/lexicon --data-dir lexicon/checks/runtime/user export --out /tmp/user.lexicon.json
lexicon/bin/lexicon --data-dir lexicon/checks/runtime/user backup --label before-test
lexicon/bin/lexicon --data-dir lexicon/checks/runtime/user backups list
lexicon/bin/lexicon --data-dir lexicon/checks/runtime/user learning off --reason "private session"
```

直接使用 Python：

```python
from lexicon.store import UserStore
from lexicon import service, transfer, engine as bridge

store = UserStore("/path/to/user-data", create=True,
                  base_manifest="lexicon/data/base/manifest.json")
store.set_learning(True, reason="user enabled")
store.record_commit("词库增强", "ci'ku'zeng'qiang", event_id="evt-1")
store.add_phrase("芷若词库", "zhi'ruo'ci'ku", 500)
service.rebuild_native(store, "lexicon/data/base/lexicon-v1.jsonl",
                       base_manifest="lexicon/data/base/manifest.json")
engine = bridge.open_engine(user_dir=store.native_dir)
state = engine.create_session().set_input("zhiruociku")   # 候选首位为“芷若词库”
engine.close()
```

完整接口、字段、版本兼容、写入所有权和错误码见 [format/README.md](format/README.md)；来源与许可见 [SOURCES.md](SOURCES.md)。

## 基础词库增强数据

- 369 条，7 个领域：`ime` 127、`science` 68、`office` 49、`medical` 35、`edu` 30、`legal` 30、`life` 30。
- 每条包含 `text`、音节分隔拼音、频次、领域、`source=server-ime-curation-v1`、`license=CC-BY-4.0`、`reading_source=pypinyin-0.55.0`。
- 词条由本项目编写；拼音由 pypinyin 0.55.0 生成，`去重策略`、`重试机制` 两个上下文多音字人工覆盖；有 CC-CEDICT 条目的 40 条读音交叉核对全部一致（只作核对，不复制其内容）。
- `data/base/manifest.json` 记录源文件哈希、生成器版本/许可、条目数、构建命令、校验规则与语料隔离结果。
- 编译后的 `build/base-v1/native/` 使用 libpinyin 的 `USER_DICTIONARY` 机制，包含 369 条；构建脚本从原生表导出回读并逐条比对，`lexicon/tools/build_native.py` 还会让真实 engine 逐一探测（当前 369/369 首选命中）。用同一批词条对原配模型探测为 282/369 首选，加入增强表后 369/369，提升 87 条、回退 0 条；这是词表覆盖探测，不是通用准确率。
- 基础模型和 `engine/` 不被修改；所有检查记录 engine 数据目录在检查前后的完整 SHA-256 指纹。

## 引擎集成（重要）

engine 0.1.0 的 `Engine` 把 `pinyin_init(data_dir, NULL)` 写死，没有用户目录参数，因此不能通过现有公开 API 加载个人词表。`lexicon.engine.open_engine(user_dir=...)` 在**构造 engine 实例时**临时替换其 `Native` 类，把词库目录传给 `pinyin_init`；构造完成后立即恢复，不修改 `engine/` 中任何文件，也不影响后续会话。

- 若未来 engine 的 `Engine.__init__` 增加 `user_dir`，桥接会自动改用该参数（通过签名检测），无需修改 lexicon。
- 这是本阶段让“词库可由已选引擎读取”成立的兼容层；engine 后续应把 `user_dir`/`import_dictionary` 纳入正式 API 与 capabilities。
- 原生表在引擎初始化时一次性加载；**个人数据变化后需重建 `native/` 并重新创建 engine 上下文**，已有会话看不到新词条。建议在空闲时批量重建并重启引擎上下文。
- 写入所有权：lexicon 写用户目录；engine 只读加载；engine 不得调用 `pinyin_train`/`pinyin_save` 写该目录。详见 [docs/engine-integration.md](docs/engine-integration.md)。

## 学习与个人数据

- 新建数据目录默认关闭学习。关闭时 `record_commit` 返回 `recorded=false, reason=learning_disabled`，不写 words/meta/audit，重启后仍为关闭；测试用文件哈希证明。
- `private=true`、`purpose` 为密码/凭据类、`learning_eligible=false`、重复 `event_id`、非法文本/拼音均不写入，并返回明确原因。
- 用户词频按 `(text, pinyin)` 累加，频次上限 1,000,000；自定义短语 `kind=custom`，同一词条重复添加取较大频次。
- 事件 ID 去重窗口 256；调用方应使用 engine 提交事件的 `event_id`，不要保存候选 ID 作为词库主键。
- 用户数据格式、兼容版本、原子写入、锁与恢复规则见 [format/README.md](format/README.md)。

## 导入、导出、备份恢复

- 导出 `ime-lexicon-user-bundle/1`，保留词条、频次、类型、时间戳、来源；载荷 SHA-256 校验；导入到另一数据目录后再导出校验和一致。
- 导入支持 `merge`（默认）与 `replace`；先完整校验后一次性提交，损坏/不兼容/非法输入不会改变现有数据；`--dry-run` 预览。
- 兼容旧 `ime-user-words/0`：JSON 数组、带 `words` 的对象、`text<TAB>pinyin[<TAB>count]` TSV。
- 备份写入 manifest + meta + words 及逐文件哈希；恢复先校验、自动生成 pre-restore 备份、原子替换，并恢复学习开关；`restore --rebuild` 重建原生表。损坏备份返回 `checksum_mismatch` 且不改数据。
- 所有管理操作写入 `audit.jsonl`（不含输入内容）。

## 固定质量语料

- 200 条，6 类：常用 60、句子 40、歧义 25、长句 25、中英/数字混合 25、拼写错误 25。
- 已冻结：`corpus/eval/manifest.json` 记录 `cases-v1.jsonl` 的 SHA-256、分类计数、计分版本 `ime-eval-score/1` 和不可变声明；`freeze_corpus.py` 在哈希变化时拒绝覆盖（需显式 `--force`，且新版本应换文件名）。
- 计分：首选精确匹配、前五精确匹配、平均字符错误率（Levenshtein/最大长度）；错误输入计入分母，不跳过；`mixed` 与 `typo` 作为能力缺口单独按类别报告，不伪装为通过。
- 与训练/增强数据严格分离：基础词库构建会拒绝与语料答案文本或输入读音完全相同的词条；`data/base/manifest.json` 记录 `overlap=0`；评估器不读取用户数据、不训练、不写学习记录。
- 结果与逐条失败例在 `checks/eval-*.json`；当前 baseline 与“加入基础增强表”在 200 条上都是 113/200 首选、136/200 前五（增强表与语料无重叠，故不改变语料成绩），这只说明隔离有效，不表示已达到 Windows 11 水平。

## 检查

```sh
python3 lexicon/tools/run_checks.py      # 构建、原生表、engine 读取、持久化、导入导出、恢复、评估、单元测试
python3 -m unittest discover -s lexicon/tests -v
```

`run_checks.py` 把用户数据与临时目录放在 `lexicon/checks/runtime/`，把结果写入 `lexicon/checks/`，并在前后比对 engine 数据目录指纹。结果索引见 [checks/README.md](checks/README.md)。

## 明确边界

- 只覆盖全拼词库/学习；双拼、模糊音、纠错由 engine 负责，本包不宣称可用。
- `mixed` 需要中英/数字混合提交通道，`typo` 需要引擎纠错；当前 engine API 不支持，语料照实计分。
- engine 0.1.0 没有用户目录参数，桥接依赖其内部 `core.Native` 名称；engine 升级后必须复跑 `run_checks.py`。
- 未实现实时在线服务、GUI、跨设备同步；用户数据默认本地处理，包内无网络调用。
- 不修改 `engine/`；不重新训练 libpinyin 二元模型，不覆盖基础 `.bin`/`bigram.db`。
