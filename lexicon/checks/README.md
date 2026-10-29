# 检查证据与复跑

所有结果由 `python3 lexicon/tools/run_checks.py` 生成。运行器把临时用户数据放在 `checks/runtime/`（运行前清空），把结果写入本目录，并在开始/结束比对：

- `engine/vendor/runtime/data` 全部 22 个文件的 SHA-256（基础模型未被训练或改写）；
- `engine/src/**/*.py` 的 SHA-256（未修改 engine 源码）；
- `data/base/lexicon-v1.jsonl`、`corpus/eval/cases-v1.jsonl` 的 SHA-256（未被检查过程改动）。

## 文件

| 文件 | 内容 |
|---|---|
| `summary.json` | 总结果、环境、各步骤、指纹、产物哈希、边界说明 |
| `engine-read.json` | 真实 engine 读取原生词库的覆盖探测：原配模型 282/369 首选，加入基础增强表后 369/369，提升 87、回退 0；含逐条失败例与 native manifest |
| `persistence.json` | 学习关闭不写入、学习/去重、重启保留、原生表重建、engine 看到个人词、导出再导入、旧格式迁移、备份恢复、损坏 bundle/备份拒绝、关闭后重启仍关闭、store verify |
| `eval-base.json` | 200 条冻结语料在原配模型上的逐条结果 |
| `eval-enhanced.json` | 同一语料在“原配模型 + 基础增强表”上的逐条结果 |
| `eval-compare.json` | 两类配置的分类与总体差值 |
| `unittest.log` | 25 项单元测试的完整输出 |
| `logs/*.log` | 每个检查步骤与构建工具的输出、stderr、异常栈 |

## 本次结果（摘要）

- 8 个步骤全部通过，运行约 6 秒；engine 数据、engine 源码、基础词库、语料哈希前后一致。
- 基础词库 369 条可回读、可被 engine 加载；逐条探测 369/369 首选。
- 个人数据：默认关闭；关闭时 words/meta 哈希不变；开启后写入、重启保留、engine 可见；导出→导入→再导出校验和一致；损坏 bundle 与损坏备份均返回 `checksum_mismatch` 且不改数据；恢复后重建原生表，store verify 无 issue。
- 冻结语料 200 条：原配模型 113/200 首选、136/200 前五；加入基础增强表后完全一致（无污染），错误输入 5 条计入分母。`mixed` 与 `typo` 的失败是已知能力缺口。
- 单元测试：`Ran 25 tests ... OK`。

## 复跑

```sh
cd <project-root>
python3 lexicon/tools/run_checks.py
```

单独运行：

```sh
python3 lexicon/tools/build_base.py --check
python3 lexicon/tools/build_native.py
python3 lexicon/tools/freeze_corpus.py
python3 -m unittest discover -s lexicon/tests -v
```

`checks/runtime/` 是临时用户数据，可安全删除；`checks/*.json` 是本次检查的证据。不要把 `checks/runtime/` 当作正式用户目录长期使用。
