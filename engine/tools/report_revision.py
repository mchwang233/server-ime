#!/usr/bin/env python3
"""Render all measured successes and regressions, without changing denominators."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'checks/quality-revision'


def load(name):
    return json.loads((OUT / name).read_text())


def main():
    summary = load('summary.json')
    env = load('environment.json')
    quality = {k: load(k + '-quality.json') for k in ('baseline', 'v020', 'enhanced')}
    change = summary['comparisons']['v020']
    lines = [
        '# 固定语料质量与性能：0.3.0', '',
        'employee_id: engine；API 1.0；verifies=[]。0.2.0 包和原 checks/enhancement 证据保留不变。', '',
        '本次重点为实际转换质量。全部结果由真实 libpinyin 2.6.0 和公开 Session 接口产生，没有模拟转换、按答案补词、删困难用例或调整 50 ms 目标。', '',
        '## 错误定位与采用的通用改进', '',
        '0.2.0 的拼写错误类只有 4/25 首选命中，简拼会把多余字母解释成新的汉字；短句/长句常有多个 N-best 仅改变句尾，错误的首词始终不变。优先处理这两类问题。混合类仍全部失败，保留在分母内。', '',
        '试验一：直接关闭简拼，首选 113→115、前五 136→131，得不偿失，未采用；完整输出在 attempt-strict-native.json。试验二：完整音节约束的单编辑候选生成，原始读音尝试在 attempt-edit-generation.json；采用后仅在无完整音节路径时启用，保留原生简拼候选。', '',
        '发布算法：从固定上游 pinyin_parser_table.h 机械提取 405 个完整音节；前后音节路径复用，枚举一个音节内的相邻换位、重复/多余字母删除、缺字母插入、QWERTY 邻键替换。拼写代价和后端词频先验用于排序，最多解码 8 个读音，至多两项排在原生前三前。有效完整拼写不改写。完整全拼另用两个不同首音节汉字作约束，重新整句解码，在原生前三之后增加候选。所有读音/词频均来自已有后端，未新增中文词条、用户答案或外部语言模型。', '',
        '边界：单编辑仅用于 5–64 个无分隔字母；显式音节分隔、双拼、有效完整拼写不启用该修复。原接口 128 字符、原生纠错、全部模糊音和自然码保持可用。扩展实例跟随会话公共/个人上下文，切换敏感用途或词库时释放重建，禁止跨用途复用个人候选。', '',
        '## 200 条固定质量评分', '',
        f"语料 SHA-256 `{summary['corpus_sha256']}`，仍使用 ime-eval-score/1 精确首选/前五和 engine-selection-actions/1 操作成本。0.1.0、原封不动的 0.2.0 源码、新 0.3.0 在同机新进程分别复测；质量进程不开个人目录、不学习。200 条新版本再跑一次，所有 top/分数/错误/成本相同；0.2.0 复测与历史报告一致。", '',
        '| 指标 | 0.1.0 | 0.2.0 | 0.3.0 |', '|---|---:|---:|---:|']
    for key, title in [('top1', '首选精确命中'), ('top5', '前五精确命中'),
                       ('selection_solved', '固定策略可完成'), ('selection_unsolved', '固定策略不能完成'),
                       ('errors', '输入拒绝（仍计入分母）')]:
        values = [quality[v]['overall'][key] for v in quality]
        lines.append('| ' + title + ' | ' + ' | '.join(str(v) + '/200' for v in values) + ' |')
    a, b = quality['v020']['overall'], quality['enhanced']['overall']
    lines += ['', f"首选 {a['top1_rate']:.1%}→{b['top1_rate']:.1%}（+{(b['top1_rate']-a['top1_rate'])*100:.1f} 个百分点）；前五 {a['top5_rate']:.1%}→{b['top5_rate']:.1%}（+{(b['top5_rate']-a['top5_rate'])*100:.1f} 个百分点）。", '',
              '| 类别 | 条数 | 首选 0.2→0.3 | 前五 0.2→0.3 | 可完成 0.2→0.3 |', '|---|---:|---:|---:|---:|']
    for cat, pair in change['categories'].items():
        a, b = pair['before'], pair['after']
        lines.append(f"| {cat} | {a['cases']} | {a['top1']}→{b['top1']} | {a['top5']}→{b['top5']} | {a['selection_solved']}→{b['selection_solved']} |")
    lines += ['', '### 新增正确与退化（逐条保留）', '',
              '| ID | 参考文字 | 新增首选 | 新增前五 | 原首选 → 新首选 |', '|---|---|---|---|---|']
    gains1 = {r['id'] for r in change['top1_improved']}
    gains5 = {r['id'] for r in change['top5_improved']}
    before_by_id = {r['id']: r for r in quality['v020']['rows']}
    for row in quality['enhanced']['rows']:
        if row['id'] in gains1 | gains5:
            before = before_by_id[row['id']]
            lines.append(f"| {row['id']} | {row['expected']} | {'是' if row['id'] in gains1 else '—'} | {'是' if row['id'] in gains5 else '—'} | {before['top'][0]} → {row['top'][0]} |")
    lines += ['', f"首选退化：{[r['id'] for r in change['top1_regressed']]}；前五退化：{[r['id'] for r in change['top5_regressed']]}；原可完成变不可完成：{change['no_longer_solved']}。常用词 60 条与歧义 25 条的首选/前五不退化，短句/长句首选保持、前五增加。完整输入、前五及前 200 项和逐次选择/提交轨迹均在 *-quality-raw.jsonl、*-quality.json，差分含原始输入与前后候选。", '',
              '## 选词操作成本及退步', '',
              '完全沿用每页 5 项、最多前 200 候选的固定贪心策略：选与剩余目标匹配的最长候选，同长度选靠前者；翻页和数字选择各记一次，最多 32 次选择。使用实际 Page_Down/数字键及实际提交。不可完成的成本为 null，绝不按零计算；不代表人类认知成本或理论最优路径。', '']
    a, b = change['same_solved_before_actions'], change['same_solved_after_actions']
    lines += [f"共同可完成 {change['same_solved_cases']} 条的均值 {a['mean']}→{b['mean']}，P50/P95/P99 {a['p50']}/{a['p95']}/{a['p99']}→{b['p50']}/{b['p95']}/{b['p99']}。这是退步：新增整句候选会把部分原词语候选移到下一页，虽然增加了可一次整句完成的用例，不能用各自成功集合均值下降掩盖共同集合成本上升。", '',
              f"按各自成功集合计算的均值为 {quality['v020']['overall']['selection_actions_solved_only']['mean']}→{quality['enhanced']['overall']['selection_actions_solved_only']['mean']}，成功数量不同，仅作补充。新完成 ID：{change['newly_solved']}。", '',
              '## 暖态逐键延迟与内存', '',
              '每配置独立进程，先整套输入预热，然后三轮逐键追加，计时 Session.set_input(prefix) 到返回候选，包含拼写候选生成、辅助解码、排序、store 版本检查和状态构造；不含 GUI/IPC。全拼每配置 9972 次成功候选计算；拒绝输入单列，不混入百分位。自然码为原有独立 12 条键码、60 轮，不计入 200 条全拼质量分母。使用 nearest-rank ceil(N*p)，没有删除慢样本。', '',
              '| 配置 | P50 ms | P95 ms | P99 ms | 最大 ms | RSS / HWM MiB | P95 距 50 ms 超标量 |', '|---|---:|---:|---:|---:|---:|---:|']
    names = {'baseline': '0.1.0', 'v020': '0.2.0', 'enhanced': '0.3.0 默认',
             'personal': '0.3.0 + 128 条个人词 + 学习', 'all_features': '上述 + 全部 10 组模糊音', 'ziranma': '自然码 + c_ch/s_sh/z_zh'}
    for profile, p in summary['performance'].items():
        s, mem = p['candidate_ms'], p['memory']['after_measurement']
        lines.append(f"| {names[profile]} | {s['p50']:.4f} | {s['p95']:.4f} | {s['p99']:.4f} | {s['max']:.4f} | {mem['VmRSS_kib']/1024:.2f} / {mem['VmHWM_kib']/1024:.2f} | {p['p95_gap_ms']:.4f} ms |")
    first = load('attempt-before-reuse/summary.json')
    lines += ['', '性能优化没有减少规则、读音上限或语料：通过公开 pinyin_clear_constraint 复用同一解析矩阵和词语候选，仅重算首音节约束后的整句。优化前完整数据保留在 attempt-before-reuse/；200 条候选/命中/成本等价检查见 reuse-equivalence.json。', '',
              '优化前→后 P95：' + '；'.join(
                  f"{names[p]} {first['performance'][p]['candidate_ms']['p95']}→{summary['performance'][p]['candidate_ms']['p95']} ms"
                  for p in ('enhanced', 'personal', 'all_features')) + '。']
    lines += ['', '个人性能种子只取公共训练侧词条，不含评估答案。成功学习后首次按键含内存个人模型重建，另列 20 次：', '',
              '| 配置 | P50/P95/P99 ms |', '|---|---:|']
    for name in ('personal', 'all_features'):
        s = summary['performance'][name]['first_key_after_learning_ms']
        lines.append(f"| {names[name]} | {s['p50']}/{s['p95']}/{s['p99']} |")
    tails = load('over-50ms.json')
    lines += ['', f"共保留 {len(tails)} 次 >50 ms 调用，按配置分别为 " +
              '、'.join(f"{names[p]} {sum(r['profile']==p for r in tails)}" for p in names) +
              f"。最慢 {max((r['elapsed_ms'] for r in tails), default=0):.4f} ms，全部原始行见 over-50ms.json。目标是暖态 P95≤50 ms，不是每次调用均≤50 ms；实测超标量原样报告。", '',
              '## 新进程冷启动', '',
              '每版本 20 个新 Python 进程，固定首次输入 nihaoshijie。未清 OS 页缓存，不是断电后的磁盘冷缓存。完整墙钟包括解释器、导入、首次候选及进程退出；另报 worker 导入到首屏与细项。', '',
              '| 项目（P50/P95/P99 ms） | 0.1.0 | 0.2.0 | 0.3.0 |', '|---|---:|---:|---:|']
    for key, label in [('process_wall_ms', '进程墙钟'), ('worker_ready_ms', 'worker 导入到首屏'),
                       ('engine_init_ms', '引擎初始化'), ('first_candidates_ms', '会话及首次候选')]:
        vals = [summary['cold'][v][key] for v in quality]
        lines.append('| ' + label + ' | ' + ' | '.join(f"{s['p50']}/{s['p95']}/{s['p99']}" for s in vals) + ' |')
    lines += ['', f"硬件：{env['cpu']['model name']}；系统/允许 CPU {env['logical_cpus']}/{env['affinity_cpus']}；{env['platform']}；Python {env['python'].split()[0]}。内存为 /proc/self/status 的 RSS/HWM，另存 ru_maxrss，不是 Python 堆。依赖实际版本：", '',
              '```text', env['dependency_rpms'].strip(), '```', '',
              '## 仍未解决', '',
              '- 新版本首选仍有 72/200 不命中，前五 49/200 不命中，固定策略仍有 31/200 无法完成，不能宣称达到 Windows 11 水平。',
              '- 共同可完成用例的平均选词操作数和 P95/P99 上升；默认逐键延迟明显高于 0.2.0，慢调用仍存在，表中保留全部差距。',
              '- 混合输入 0/25，字母数字/符号边界仍沿用 API 1.0；有效但语义不符的拼音、多处错误、跨音节换位不作任意修正。',
              '- 后端只暴露有限 N-best、不能直接取得句子概率；首音节约束能补充候选，不能解决中部同音词的语义排序。用于纠错读音排序的词频先验不是现代神经语言模型。',
              '- 冻结语料中 S011 输入含 de 但答案省略的、S015 输入缺 ge、L020 qingkuang 对应答案状况等不一致也保持原分母与原评分，未据此删例或添加答案。',
              '- 个人模型仅测 128 条，非最大 20000 条；16 字个人短语仍只精确匹配，更长或读音不确定的整句不作为单条学习记录。', '',
              '## 复跑与产物', '',
              '```sh', 'python3 engine/tools/evaluate_revision.py', 'python3 engine/tools/report_revision.py',
              'cmake -S engine -B engine/build', 'cmake --build engine/build -j 8',
              'ctest --test-dir engine/build --output-on-failure --output-junit revision-junit.xml',
              'python3 engine/tools/check_install.py', '```', '',
              '新包 build/server-ime-engine-0.3.0.tar.gz；保留 0.2.0 包、checks/enhancement、0.1.0 baseline-source 和 checks/quality-revision/v020-source。质量复跑依赖工作树的 lexicon/corpus/eval；生产运行不读取语料。immutable-before/after 核对原模型、词库、冻结语料、0.2.0 包和历史证据未变。完整检查索引见 checks/README.md。', '',
              'REFERENCE: libpinyin/libpinyin@19d8e9a1e577fb0d93dc9fb51ea982d677331755 license=GPL-3.0-or-later score=75 use=reuse what=existing runtime/model/C ABI plus mechanically extracted syllable alphabet; notices and corresponding source retained.', '']
    (ROOT / 'docs/QUALITY-PERFORMANCE.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
