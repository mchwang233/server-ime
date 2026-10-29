# 固定质量语料 v1

200 条独立编写的输入/参考答案，冻结在 `cases-v1.jsonl`。manifest 记录文件 SHA-256、分类计数、计分版本与不可变声明；`tools/freeze_corpus.py` 在内容变化后拒绝重新冻结（除非显式 `--force`，正式流程应改为新版本文件）。

## 分类

| 类别 | 条数 | 覆盖点 |
|---|---:|---|
| `common` | 60 | 常用词、问候、办公高频词 |
| `sentence` | 40 | 6–12 字自然短句、工作/生活表达 |
| `ambiguity` | 25 | 有/无音节分隔、同音词、地名与多音切分 |
| `long` | 25 | 11–16 字长句，含时间、动作、对象 |
| `mixed` | 25 | 中英、数字、邮箱、版本号等混合输入 |
| `typo` | 25 | 错字母、漏字母、多字母、换位，含正确输入对照 |

混合与拼写错误类按原样计分，不跳过、不替换；当前 engine 不具备拉丁/数字直通和纠错，相关失败计为错误或未命中。

## 计分（`ime-eval-score/1`）

1. 每个 case 使用新建 engine 会话、`page_size=5`，输入 `input`，取前五候选。
2. `top1_exact`：候选第一项与 `expected` 完全相等。
3. `top5_exact`：`expected` 出现在前五。
4. `mean_character_error_rate`：`Levenshtein(top1, expected) / max(len(top1), len(expected))`；没有候选时用 `len(expected)` 作分母。
5. 分母始终是全部 case；engine 拒绝输入记 `status=error` 并附错误码，不是丢弃。
6. 按类别和总体报告；浮点保留四位。

## 冻结与隔离

- 基础增强数据构建时检查：任何增强词条的 `text` 或 `pinyin` 不得与语料的 `expected`/`input` 完全相同；manifest 记录 `overlap=0`。
- 语料由本项目独立编写，未用于生成词条、读音、频次或用户数据；评估器不打开用户 store、不调用学习接口、不调用 `pinyin_train`/`pinyin_save`。
- 评估运行前后用户数据与基础模型哈希不变，见 `checks/summary.json`。
- 本语料用于版本对比和回归，不构成对 Windows 11 或任何商业输入法的等价声明。

## 复跑

```sh
python3 lexicon/tools/freeze_corpus.py
lexicon/bin/lexicon eval --out lexicon/checks/eval-base.json
lexicon/bin/lexicon --data-dir lexicon/checks/runtime/user eval --with-native --out lexicon/checks/eval-enhanced.json
```

`lexicon/tools/run_checks.py` 会自动执行 baseline 与基础增强表两种配置，并写出逐条失败例与对比。
