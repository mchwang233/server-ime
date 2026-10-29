#!/usr/bin/env python3
"""Render final measured results, including regressions and the selected slow cohort."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'checks/mixed-revision'


def load(name): return json.loads((OUT/name).read_text())
def nums(row): return ' / '.join(str(row[k]) for k in ('p50', 'p95', 'p99', 'max'))


def main():
    s = load('summary.json')
    comp = load('composition-comparison.json')
    cq = load('composition-quality.json')
    previous = json.loads((ROOT/'checks/quality-revision/summary.json').read_text())
    env = load('environment.json')
    cpu = next(line.split(':',1)[1].strip() for line in env['cpuinfo'].splitlines() if line.startswith('model name'))
    lines = ['# 0.4.0 组合输入与性能返工报告', '', 'employee_id: engine；verifies=[]。所有结果来自真实 libpinyin 2.6.0 接口。', '',
             '## 固定质量语料', '',
             '冻结的 200 条语料不变：common 60、sentence 40、ambiguity 25、long 25、mixed 25、typo 25。'
             '整串精确匹配，首选及前五使用实际初始候选；不删错误、不改期望、不把答案导入词库。SHA-256：`'+s['corpus_sha256']+'`。', '',
             '| 版本/入口 | 首选 | 前五 | 错误 | 可完成/200 | 成功项操作均值 / P95 / P99 / 最大 |',
             '|---|---:|---:|---:|---:|---|']
    for key, title in [('v010','0.1.0 原始'), ('v020','0.2.0 词库学习接入'), ('v030','0.3.0 返工前'),
                       ('enhanced','0.4.0 兼容 set_input'), ('composition','0.4.0 set_composition')]:
        q = s['quality'][key]; cost = q['selection_actions_solved_only']
        lines.append(f"| {title} | {q['top1']}/200 ({q['top1_rate']:.1%}) | {q['top5']}/200 ({q['top5_rate']:.1%}) | {q['errors']} | {q['selection_solved']} | {cost['mean']} / {cost['p95']} / {cost['p99']} / {cost['max']} |")
    c = comp['v030']
    lines += ['', '旧入口保留原评分口径。新入口使用同样的最长参考前缀/最早排名贪心策略：每翻一页一次操作，显式选候选一次操作；'
              '数字可能是原文，因此用 select 表达选词动作，不能把插入数字当选词。原始逐次轨迹保留在各 *-quality.json 的 cost.trace，'
              '失败项成本为 null，仍计入全部 200 条分母；这不是用户认知成本或最优选词路径。', '',
              f"相对 0.3.0，新入口共同成功 {c['same_solved_cases']} 条的操作均值 **{c['same_solved_before_actions']['mean']} → {c['same_solved_after_actions']['mean']}**；"
              f"P95/P99 **{c['same_solved_before_actions']['p95']}/{c['same_solved_before_actions']['p99']} → {c['same_solved_after_actions']['p95']}/{c['same_solved_after_actions']['p99']}**。"
              '这是实际退化，原文选项和片段候选占用位置，分段重算也改变部分词语排序；保留为未解决项。', '',
              f"新入口相对 0.3.0：首选退化 {len(c['top1_regressed'])} 条，前五退化 {len(c['top5_regressed'])} 条，"
              f"新增可完成 {len(c['newly_solved'])} 条，原可完成变失败 {len(c['no_longer_solved'])} 条。两个入口各独立进程重复 200 条结果及成本一致。", '',
              f"原 mixed 25 条仍保留旧入口 0/25 评分；新入口首选/前五 {cq['categories']['mixed']['top1']}/25、可完成 {cq['categories']['mixed']['selection_solved']}/25。"
              '语料中缺失的 @、点号、大小写及拼写歧义不会被凭空恢复。另有 12 条独立实际逐键用例全部通过；它们不进入原语料分母或词库。', '',
              '## 暖态逐键候选', '',
              f"硬件：{cpu}；可用 CPU affinity={env['affinity_cpus']} / 逻辑 CPU={env['logical_cpus']}；{env['platform']}。"
              'Python、系统 RPM、固定依赖清单散列、完整 /proc/cpuinfo 与 meminfo 在 environment.json。', '',
              '先无计时预热，再按原始输入逐个前缀调用，计时到候选状态返回，perf_counter_ns，百分位采用 nearest-rank。'
              '默认/个人/全部模糊音及组合全语料各 3 轮；自然码和独立混输短用例各 60 轮。个人配置用公共训练侧 128 条种子，'
              '不使用评估答案。默认纠错开启，all_features 开启全部 10 个模糊音及个人学习；没有关闭已声明功能。', '',
              '| 配置/入口 | 样本数 | P50 / P95 / P99 / 最大 ms | >50 ms | P95 差距 ms | 测后 RSS / HWM MiB |',
              '|---|---:|---|---:|---:|---|']
    for key, p in s['performance'].items():
        m = p['memory']['after_measurement']
        lines.append(f"| {key} | {p['candidate_ms']['samples']} | {nums(p['candidate_ms'])} | {p['over_50ms']} | {p['p95_gap_ms']:.4f} | {m['VmRSS_kib']/1024:.2f} / {m['VmHWM_kib']/1024:.2f} |")
    old_tails = json.loads((ROOT/'checks/quality-revision/over-50ms.json').read_text())
    lines += ['', '相同冻结语料及旧入口配置的返工前暖态记录（0.3.0，历史文件不重写）：', '',
              '| 配置 | P50 / P95 / P99 / 最大 ms | >50 ms | RSS MiB |', '|---|---|---:|---:|']
    for key in ('enhanced', 'personal', 'all_features'):
        p = previous['performance'][key]
        lines.append(f"| {key} | {nums(p['candidate_ms'])} | {sum(r['profile']==key for r in old_tails)} | {p['memory']['after_measurement']['VmRSS_kib']/1024:.2f} |")
    lines += ['', 'enhanced/personal/all_features 使用兼容 set_input；composition_corpus* 使用新组合入口及同一 200 条冻结语料；'
              'mixed* 只使用独立 12 条实际按键序列，不能用短样本指标替代全语料。所有样本、错误耗时及超过目标的样本均保存，未裁掉最大值。'
              f"旧入口 {s['performance']['enhanced']['rejected_input_ms']['samples']} 次拒绝输入耗时单列为 rejected_input_ms，不混入有效候选百分位。", '',
              '学习后首次按键包含个人模型重建，旧入口另外各测 20 次：', '']
    for profile in ('personal', 'all_features'):
        p = s['performance'][profile]
        lines.append(f"- {profile}：P50/P95/P99/max={nums(p['first_key_after_learning_ms'])} ms；>50 ms={p['over_50ms_after_learning']}。")
    lines += ['', '## 原慢调用逐条重放与阶段定位', '',
              '输入清单直接来自 quality-revision/over-50ms.json，共 338 条，保留 profile、round、id、key_index 及历史值。'
              '按各原配置预热，重建前一个前缀后计时目标键；没有按新耗时筛选样本。原版源码快照及模型使用相同配置和种子。'
              '分阶段包装计时有少量开销，扩展总时间包含原生子阶段，不能相加。', '',
              '| 阶段/版本 | 样本数 | P50 / P95 / P99 / 最大 ms | >50 ms |', '|---|---:|---|---:|']
    for version in ('v030', 'current'):
        for profile in ('all', 'enhanced', 'personal', 'all_features'):
            p = s['historical_tails'][version][profile]
            lines.append(f"| {version} / {profile} | {p['latency_ms']['samples']} | {nums(p['latency_ms'])} | {p['over_50ms']} |")
    before = s['historical_tails']['v030']['all']['stages_ms']; after = s['historical_tails']['current']['all']['stages_ms']
    lines += ['', f"原最慢调用约 1 秒，主要在 guess_candidates 的整串枚举。该阶段 P95 **{before['guess_candidates']['p95']} → {after['guess_candidates']['p95']} ms**；"
              f"整句 guess_sentence 阶段 P95 **{before['guess_sentence']['p95']} → {after['guess_sentence']['p95']} ms**。", '',
              '优化：整句 N-best 在解析末尾读取，避免纠错再枚举整串词语；全串原生前三保留，局部词语枚举限制为 24 码点；'
              '两条首音节约束用前两个音节取词，再约束全句；单编辑规则仍全部开放，按通用拼写先验最多解码四个读音。'
              '界限对所有输入相同，不包含质量语料或答案分支。原生调用不能中途取消，仍不是 50 ms 硬实时保证。', '',
              '慢例集合经过历史筛选，不能当成全语料 P95。其 P95 超过 50 ms 的差距仍是未解决项；全部原始/复测/阶段样本可逐条审计。', '',
              '## 新进程冷启动及内存', '',
              '每个版本 20 次独立 Python 进程。系统页缓存未清空，因此不是物理磁盘冷启动；wall 包含进程退出。', '',
              '| 版本/阶段 | P50 / P95 / P99 / 最大 ms |', '|---|---|']
    for version, p in s['cold'].items():
        for stage in ('process_wall_ms', 'import_ms', 'engine_init_ms', 'first_candidates_ms', 'worker_ready_ms'):
            lines.append(f"| {version} / {stage} | {nums(p[stage])} |")
        lines.append(f"| {version} / ready RSS KiB | {nums(p['rss_kib'])} |")
    lines += ['', 'RSS/HWM 包含该 Python 进程及原生模型，不是全桌面/IBus 产品的总内存。个人库规模只测到 128 条种子；'
              '未证明大个人库、低配硬件或 GUI/IPC 端到端延迟。未进行 Windows 11 同机对照，不宣称达到其质量水平。', '',
              '## 检查与证据', '',
              '运行 `python3 engine/tools/evaluate_mixed_revision.py` 与 `python3 engine/tools/report_mixed_revision.py`；'
              '构建/功能使用 README 的 CMake/CTest 入口。完整工作区证据位于 `engine/checks/mixed-revision/`：', '',
              '- enhanced/composition/repeat*-quality-raw.jsonl、*-quality.json：原始候选、精确评分、逐次选词轨迹。',
              '- quality-comparison.json、composition-comparison.json：基线和返工前的逐条变化与共同成功成本。',
              '- *-keystrokes.jsonl、*-performance.json、*-cold.jsonl、summary.json：全部原始性能/内存及汇总。',
              '- v030/current-tail-replay.jsonl、*-tail-summary.json：原 338 条慢例及阶段重放，无丢样本。',
              '- composition-features.json、feature-matrix.json、revision-features.json、ctest.log：真实接口功能及 12 条逐键用例。',
              '- immutable-before/after.json：原词库、音节表、冻结语料、0.1–0.3 包与历史证据散列不变。',
              '- install-relocation.json、reproducibility.json、package-inspection.json：搬迁、重启、隐私和确定性打包。',
              '- attempt-window-*、attempt-before-separator-fix/、composition-crash-localization.log：中间测量及已修复分隔符断言的原记录。', '',
              '原 0.3.0 源码/文档在 v030-source/；历史 quality-revision/、enhancement/ 与旧包未修改。'
              '测试数据只用于检查，不被运行时作为词库载入。后续平台需接入 literal_digits 及新片段入口并验证真实应用；本报告证明引擎与端口行为。']
    (ROOT/'docs/QUALITY-PERFORMANCE.md').write_text('\n'.join(lines)+'\n')


if __name__ == '__main__': main()
