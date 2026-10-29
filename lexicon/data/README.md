# 基础词库增强数据

本目录只放词库增强（训练侧）数据，**不含评估语料**。评估语料在 `corpus/eval/`，两者构建和运行时互不读取。

| 文件 | 角色 |
|---|---|
| `terms-v1.tsv` | 人工编写的领域、词条、频次源表（369 行） |
| `readings-v1.json` | 词条读音、生成器（pypinyin 0.55.0，MIT）、人工覆盖、CC-CEDICT 核对摘要 |
| `lexicon-v1.jsonl` | 最终逐条记录（JSONL），由 `tools/build_base.py` 确定性生成 |
| `manifest.json` | 条数、领域、源文件 SHA-256、许可、构建命令、校验与语料隔离结果 |

字段定义、版本规则和许可见 `format/README.md` 与 `SOURCES.md`。修改数据必须：

1. 修改 `terms-v1.tsv` 或 `readings-v1.json`；
2. 运行 `python3 lexicon/tools/generate_readings.py`（仅在读音变化时，需要 pypinyin 0.55.0）；
3. 运行 `python3 lexicon/tools/build_base.py`；
4. 运行 `python3 lexicon/tools/build_native.py`，确认原生表回读和 engine 探测；
5. 更新 `data/base/manifest.json` 并复跑 `tools/run_checks.py`。

不要手改 `lexicon-v1.jsonl`、`build/` 下的二进制表或 manifest 哈希。评估答案不得加入本目录；构建脚本会在任何词条文本或读音与冻结语料完全相同时以 `contamination` 中止。
