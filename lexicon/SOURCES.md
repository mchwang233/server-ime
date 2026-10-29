# 来源、许可与版本

本文件记录 `lexicon/` 内每一项数据的来源、版本、许可和重建方法。所有哈希为 SHA-256。

## 1. 转换引擎与基础模型

| 项目 | 版本/提交 | 许可 | 在本包中的角色 |
|---|---|---|---|
| [libpinyin](https://github.com/libpinyin/libpinyin/tree/19d8e9a1e577fb0d93dc9fb51ea982d677331755) | 2.6.0（提交 `19d8e9a1…`，Rocky `libpinyin-2.6.0-4.el9`） | GPL-3.0-or-later | 通过 ctypes 调用其公开的 `pinyin_init`、`pinyin_begin_add_phrases`、`pinyin_iterator_add_phrase`、`pinyin_save`、`pinyin_begin_get_phrases` 等接口，读写用户词库 |
| libpinyin-data | 2.6.0-4.el9，随 engine 的 `vendor/runtime/data` 固定 | GPL-3.0-or-later（上游数据包） | 只读系统模型；本包不复制、不修改、不重新发布这些 `.bin`/`bigram.db` |
| engine 组件 | 0.1.0，API 1.0 | GPL-3.0-or-later | 验证“词库可由已选引擎读取”；`lexicon` 不修改 `engine/` 中任何文件 |

`engine/vendor/runtime/data` 与运行库的哈希固定在 `dependencies.json`，`checks/summary.json` 会记录检查前后的完整目录指纹，证明检查过程没有训练或改写基础模型。

## 2. 基础词库增强数据（`data/base/`）

| 文件 | 内容 | 许可 | 说明 |
|---|---|---|---|
| `terms-v1.tsv` | 369 条自编领域词条（领域、词条、权重） | CC-BY-4.0 | 由本项目编写；不含评估语料答案 |
| `readings-v1.json` | 每条词条的拼音、生成器与校验信息 | CC-BY-4.0（数据编排） | 拼音由 pypinyin 0.55.0 生成，两条多音字人工覆盖；40 条有 CC-CEDICT 条目者已完成交叉核对 |
| `lexicon-v1.jsonl` | 最终逐条记录（含 `source`、`license`、`reading_source`、`domain`、`count`） | CC-BY-4.0 | 由 `tools/build_base.py` 从上述两个文件确定性生成 |
| `manifest.json` | 条数、领域分布、源文件哈希、许可、构建命令、校验结果 | — | 不含时间敏感内容以外的可变信息 |

**pypinyin**：0.55.0，MIT，wheel
`https://files.pythonhosted.org/packages/b9/7b/4cabc76fcc21c3c7d5c671d8783984d30ac9d3bb387c4ba784fca3cdfa3a/pypinyin-0.55.0-py2.py3-none-any.whl`，
SHA-256 `d53b1e8ad2cdb815fb2cb604ed3123372f5a28c6f447571244aca36fc62a286f`，许可副本在 `licenses/pypinyin-MIT.txt`。
它只用于一次性生成读音；正常构建和运行不需要安装 pypinyin。

**CC-CEDICT**：2026-10-28T00:15:09Z 快照，CC BY-SA 4.0，
`https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz`，
SHA-256 `366f39049fbcc9ca0cc414f319bfc56a33f6f9aba73aec1f609c5cb6502d2000`。
仅作读音交叉核对（40 条有对应条目，0 条不一致），未复制其释义或词条内容。

重新生成：

```sh
# 只在需要修改词条/读音时执行；需要 pypinyin 0.55.0 和可选的 CC-CEDICT 快照
python3 lexicon/tools/generate_readings.py --pypinyin-path /path/to/pypinyin --cedict /path/to/cedict_ts.u8.gz
python3 lexicon/tools/build_base.py
python3 lexicon/tools/build_native.py
```

## 3. 评估语料（`corpus/eval/`）

`cases-v1.jsonl` 的 200 条输入与参考答案由本项目独立编写，采用 CC0-1.0。它与基础词库增强数据分目录存放，构建脚本会拒绝任何与语料文本或读音完全相同的增强词条（`data/base/manifest.json` 的 `validation.corpus.overlap=0`）。评估器不读取用户数据、不训练、不写学习记录。

## 4. 个人数据

`meta.json`、`words.jsonl`、`audit.jsonl`、`backups/` 和 `native/` 属于用户本机数据，由用户拥有；本包不收集、不上传、不分发。导出的 bundle 由用户自行保管。`native/` 是从基础词库与个人条目派生的 libpinyin 用户表，可由 `lexicon native build` 重建。

## 5. 代码许可

`src/`、`tools/`、`bin/` 与本说明采用 GPL-3.0-or-later（见 `licenses/GPL-3.0.txt`），原因是运行时绑定 GPL 的 libpinyin。数据文件按上表各自许可发布。用户数据不适用本包许可。
