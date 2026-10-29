#!/usr/bin/env python3
"""Render the measured evidence without changing scores or thresholds."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'checks/enhancement'
s=json.loads((OUT/'summary.json').read_text())
env=json.loads((OUT/'environment.json').read_text())
b=json.loads((OUT/'baseline-quality.json').read_text())
e=json.loads((OUT/'enhanced-quality.json').read_text())
q=s['quality'];c=q['comparison']
lines=['# 冻结质量语料与性能报告', '',
       'employee_id: engine；组件 0.2.0；API 1.0；verifies=[]。所有数值来自真实 libpinyin 调用，未用模拟转换结果。', '',
       '## 质量与操作成本', '',
       '沿用 lexicon 冻结的 200 条语料，SHA-256 `'+c['corpus_sha256']+'`。增强前为保留的 0.1.0 源码，在同一运行库/机器上重新测量；增强后为公共 369 条词库 + 默认全拼纠错，模糊音关闭。两者都不打开个人目录、不训练。原配数据、公共词条、语料及 manifest 的 29 个文件哈希前后相同。没有添加评估答案、修改词频或排除失败用例。', '',
       '| 指标 | 0.1.0 基线 | 0.2.0 增强 | 变化 |', '|---|---:|---:|---:|']
for key,label in [('top1','首选精确命中'),('top5','前五精确命中')]:
 a=b['overall'][key];z=e['overall'][key]
 lines.append(f'| {label} | {a}/200（{a/2:.1f}%） | {z}/200（{z/2:.1f}%） | {(z-a)/2:+.1f} 个百分点 |')
lines += [f"| 可按固定选词策略完成 | {b['overall']['selection_solved']}/200 | {e['overall']['selection_solved']}/200 | +1 |",
          f"| 无法按该策略完成 | {b['overall']['selection_unsolved']} | {e['overall']['selection_unsolved']} | -1 |",'','分类结果（所有分母固定）：','',
          '| 类别 | 数量 | 首选：前→后 | 前五：前→后 | 可选完：前→后 |','|---|---:|---:|---:|---:|']
for name,a in b['categories'].items():
 z=e['categories'][name]
 lines.append(f"| {name} | {a['cases']} | {a['top1']}→{z['top1']} | {a['top5']}→{z['top5']} | {a['selection_solved']}→{z['selection_solved']} |")
lines += ['', '选词成本 `engine-selection-actions/1`：每页 5 项，最多检查平台可见的前 200 项；每步选取能匹配剩余目标文字的最长候选，同长度取更靠前者，用实际 Page_Down 和数字键调用核心，直到整句提交。每次翻页或选词均记 1 次操作。此策略可复跑，但不是对人类认知成本或最优路径的估计；不把中文重打假定为每字一个按键。未成功条目的成本为 null，并单列失败数量，绝不按 0 计入平均值。', '',
          f"共同可完成的 {c['same_solved_cases']} 条，平均操作数 {c['same_solved_baseline_actions']['mean']} → {c['same_solved_enhanced_actions']['mean']}；P50/P95/P99 均为 1/5/7，未改善。按各自成功集合计算平均值 {b['overall']['selection_actions_solved_only']['mean']} → {e['overall']['selection_actions_solved_only']['mean']}，增幅来自多完成的一条用例，不能用不同集合暗示成本降低。",
          '',f"首选回退用例：{c['top1_regressions']}；前五回退用例：{c['top5_regressions']}。输入拒绝前后均 {b['overall']['errors']} 条，已计入 200 条分母。", '',
          '原始初始状态与前 200 候选：`baseline-quality-raw.jsonl`、`enhanced-quality-raw.jsonl`；逐条答案、分数及真实选择/提交轨迹：`baseline-quality.json`、`enhanced-quality.json`；差分：`quality-comparison.json`。这些文件均位于 `checks/enhancement/`。', '',
          '## 暖态逐键计算', '',
          '每个配置使用独立进程，先进行一遍整套输入的未计时预热，再测量每次追加一个字符后的 Session.set_input(prefix) 到返回候选状态。全拼每配置 3 轮、9972 次成功候选计算；对不支持字符的拒绝另存并单独统计，未把快速报错混入成功调用的百分位。包含切分、原生整句解码、排序、个人数据版本检查及状态构造；不包含 GUI、远程桌面、IPC、候选窗口绘制。每次原始时延保留在 `*-keystrokes.jsonl`，百分位为 nearest-rank ceil(N*p)。', '',
          '| 配置 | P50 ms | P95 ms | P99 ms | 最大 ms | RSS MiB | 峰值 RSS MiB | P95 超过 50ms 的差距 |',
          '|---|---:|---:|---:|---:|---:|---:|---:|']
labels={'baseline':'0.1.0 基线','enhanced':'0.2.0 默认','personal':'默认 + 128 个人条目 + 学习','all_features':'上述 + 全部 10 组模糊音','ziranma':'自然码 + c_ch/s_sh/z_zh'}
for p,v in s['performance'].items():
 t=v['candidate_ms'];m=v['memory']['after_measurement']
 lines.append(f"| {labels[p]} | {t['p50']:.4f} | {t['p95']:.4f} | {t['p99']:.4f} | {t['max']:.4f} | {m['VmRSS_kib']/1024:.2f} | {m['VmHWM_kib']/1024:.2f} | {v['p95_gap_ms']:.4f} ms |")
lines += ['', '自然码使用单独列明的 12 条键码序列，60 轮、6060 次调用；不把它与全拼 200 条语料合并计算命中率。双拼的全拼拼写纠错按设计不适用。128 条个人种子只来自训练侧公共词库，不来自评估答案；性能进程中的学习与质量评估进程完全隔离。', '',
          '每次成功学习后的首次按键（包含用户模型重建）另测 20 次：','',
          '| 配置 | P50 ms | P95 ms | P99 ms |', '|---|---:|---:|---:|']
for p in ('personal','all_features'):
 t=s['performance'][p]['first_key_after_learning_ms']
 lines.append(f"| {labels[p]} | {t['p50']:.4f} | {t['p95']:.4f} | {t['p99']:.4f} |")
tails={}
for p in s['performance']:
 vals=[json.loads(x) for x in (OUT/f'{p}-keystrokes.jsonl').read_text().splitlines()]
 tails[p]=[x for x in vals if not x.get('error') and x['elapsed_ms']>50]
write_tail=OUT/'over-50ms.json'
write_tail.write_text(json.dumps(tails,ensure_ascii=False,indent=2)+'\n')
lines += ['', 'P95 达标不表示每次都达标。全部模糊音配置仍有 '+str(len(tails['all_features']))+' 次超过 50 ms，最慢 '+str(s['performance']['all_features']['candidate_ms']['max'])+' ms，逐条保留在 `over-50ms.json`；没有删掉这些样本、关掉功能或放宽阈值。', '',
          '## 冷启动与资源', '',
          '每版本启动 20 个新 Python 进程，使用同一个固定首次输入 nihaoshijie。进程冷启动包括解释器、脚本导入、引擎初始化、首次候选和退出；另报库初始化及首次候选的独立耗时。操作系统页缓存未清空，因此这不是机器重启/磁盘完全冷缓存实验。', '',
          '| 项目 | 基线 P50/P95/P99 ms | 增强 P50/P95/P99 ms |', '|---|---:|---:|']
for key,label in [('process_wall_ms','新进程完整墙钟'),('worker_ready_ms','worker 开始导入到首屏'),('engine_init_ms','引擎初始化'),('first_candidates_ms','会话及首次候选')]:
 def fmt(v):return '/'.join(f'{v[f"p{p}"]:.4f}' for p in (50,95,99))
 lines.append(f"| {label} | {fmt(s['cold']['baseline'][key])} | {fmt(s['cold']['enhanced'][key])} |")
lines += ['', f"硬件：{env['cpu']['model name']}；系统可见/允许 CPU 均为 {env['affinity_cpus']}；{env['platform']}；Python {env['python'].split()[0]}。RSS/HWM 来自 /proc/self/status，ru_maxrss 也保存；不是 Python 堆大小。CPU/内存/依赖实际版本在 environment.json，原生文件哈希锁在 vendor.lock.json。", '',
          '依赖：libpinyin 与 data 2.6.0-4.el9；GLib 2.68.4-19.el9_8.1；BerkeleyDB 5.3.28-57.el9_6；PCRE 8.44-4.el9；glibc 2.34-270.el9_8；libstdc++ 11.5.0-14.el9。', '',
          '## 保留的差距', '',
          '- 首选/前五命中率没有提升；仍有 87 条非首选命中、64 条未进入前五，48 条不能由固定选词策略完成。不能据此宣称达到 Windows 11 的输入质量。',
          '- 自然短句、长句、混合输入和常见插删/任意换位错误仍有失败。8 组纠错是明确的音节别名规则，不是通用拼写纠错。混合中文/数字/标点由既有 API 边界拒绝或产生错误候选，评估照常计分。',
          '- 默认增强版进程冷启动和 RSS 高于基线；个人模型增加内存和学习后重建时间。当前 128 条个人记录的性能不代表最大 20000 条时的结果。',
          '- 开启全部模糊音的个别按键仍超过 50 ms；保留全部长尾，后续可继续优化。',
          '- 16 字个人短语只能精确匹配，长于 16 字的整句不作为单条词频保存；未确认完整读音时不学习。', '',
          '## 复跑', '',
          '在包含 engine/ 与 lexicon/ 的工作树执行 `python3 engine/tools/evaluate_enhancement.py`（默认 3 轮暖态、20 次进程冷启动），随后 `python3 engine/tools/report_enhancement.py`。脚本验证固定语料 SHA、读取保留的 0.1.0 源码、写原始状态/时延/评分及最终 summary.json；词库和语料在前后哈希检查中必须一致。安装包的运行与检查不需要评估答案；完整评估复跑需工作树中的 lexicon/corpus/eval 与 checks/enhancement/baseline-source。', '']
(ROOT/'docs/QUALITY-PERFORMANCE.md').write_text('\n'.join(lines))
print('wrote docs/QUALITY-PERFORMANCE.md and checks/enhancement/over-50ms.json')
