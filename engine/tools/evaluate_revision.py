#!/usr/bin/env python3
"""Compare 0.1.0 / preserved 0.2.0 / 0.3.0 with unchanged scoring and corpus."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import evaluate_enhancement as ev

ROOT = ev.ROOT
OUT = ROOT / 'checks/quality-revision'
ev.OUT = OUT


def load_engine(variant):
    source = {'baseline': ROOT / 'checks/enhancement/baseline-source/src',
              'v020': OUT / 'v020-source'}.get(variant, ROOT / 'src')
    sys.path.insert(0, str(ROOT.parent / 'lexicon/src'))
    sys.path.insert(0, str(source))
    from server_ime_engine import Engine
    return Engine


def create(variant, **options):
    if variant == 'v020':
        options['base_lexicon'] = ROOT.parent / 'lexicon/data/base/lexicon-v1.jsonl'
    return load_engine(variant)(runtime_dir=ROOT / 'vendor/runtime', **options)


ev.load_engine = load_engine
ev.create = create


def worker(*args):
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), *args],
                            cwd=ROOT.parent, text=True, capture_output=True, check=True)
    with (OUT / 'workers.log').open('a') as log:
        log.write(repr(args) + '\n' + result.stdout + result.stderr + '\n')
    return result


def compare(before, after):
    pairs = list(zip(before['rows'], after['rows']))
    changes = {}
    for metric in ('top1', 'top5'):
        for direction in ('improved', 'regressed'):
            changes[metric + '_' + direction] = [
                {'id': a['id'], 'category': a['category'], 'input': a['input'], 'expected': a['expected'],
                 'before': a['top'], 'after': b['top']}
                for a, b in pairs if a[metric] != b[metric] and b[metric] == (direction == 'improved')]
    common = [(a, b) for a, b in pairs if a['cost']['solved'] and b['cost']['solved']]
    changes.update(same_solved_cases=len(common),
                   same_solved_before_actions=ev.stats([a['cost']['actions'] for a, b in common]),
                   same_solved_after_actions=ev.stats([b['cost']['actions'] for a, b in common]),
                   newly_solved=[b['id'] for a, b in pairs if not a['cost']['solved'] and b['cost']['solved']],
                   no_longer_solved=[b['id'] for a, b in pairs if a['cost']['solved'] and not b['cost']['solved']])
    changes['categories'] = {cat: {'before': before['categories'][cat], 'after': after['categories'][cat]}
                              for cat in before['categories']}
    return changes


def main(rounds, cold_count):
    OUT.mkdir(exist_ok=True)
    ev.cases()
    env = json.loads((ROOT / 'checks/enhancement/environment.json').read_text())
    env.update(platform=platform.platform(), python=sys.version, uname=list(platform.uname()),
               logical_cpus=os.cpu_count(), affinity_cpus=len(os.sched_getaffinity(0)),
               meminfo=Path('/proc/meminfo').read_text(), cpuinfo=Path('/proc/cpuinfo').read_text(),
               dependency_rpms=subprocess.run(['rpm', '-q', 'libpinyin', 'libpinyin-data', 'glib2',
                   'libdb', 'pcre', 'glibc', 'libstdc++'], capture_output=True, text=True).stdout,
               component_versions=['0.1.0', '0.2.0', '0.3.0'],
               source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted((ROOT / 'src').rglob('*.py'))},
               dependencies_manifest_sha256=hashlib.sha256((ROOT/'dependencies.json').read_bytes()).hexdigest(),
               measured_at_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    ev.write(OUT / 'environment.json', env)
    quality = {}
    for variant in ('baseline', 'v020', 'enhanced', 'repeat'):
        print('quality', variant, flush=True)
        worker('--quality', variant)
        quality[variant] = json.loads((OUT / f'{variant}-quality.json').read_text())
    # Nonces intentionally differ across processes; compare all observable quality
    # outcomes and operation costs rather than random candidate/event IDs.
    def outcomes(q):
        return [(r['id'], r['top'], r['top1'], r['top5'], r['error'],
                 r['cost']['solved'], r['cost']['actions'], r['cost']['spent']) for r in q['rows']]
    repeat_ok = outcomes(quality['enhanced']) == outcomes(quality['repeat'])
    old = json.loads((ROOT / 'checks/enhancement/enhanced-quality.json').read_text())
    ev.write(OUT / 'quality-repeat.json', {'identical_all_200_outcomes': repeat_ok,
             'v020_matches_preserved_report': outcomes(quality['v020']) == outcomes(old),
             'score': quality['repeat']['overall']})
    assert repeat_ok
    comparisons = {v: compare(quality[v], quality['enhanced']) for v in ('baseline', 'v020')}
    ev.write(OUT / 'quality-comparison.json', comparisons)
    for profile in ('baseline', 'v020', 'enhanced', 'personal', 'all_features', 'ziranma'):
        print('warm', profile, flush=True)
        worker('--warm', profile, '--rounds', str(rounds * (20 if profile == 'ziranma' else 1)))
    cold = {}
    for variant in ('baseline', 'v020', 'enhanced'):
        print('cold', variant, flush=True)
        samples = []
        for index in range(cold_count):
            start = time.perf_counter_ns()
            r = worker('--cold-worker', variant)
            samples.append({'variant': variant, 'index': index,
                            'process_wall_ms': (time.perf_counter_ns() - start) / 1e6, **json.loads(r.stdout)})
        with (OUT / f'{variant}-cold.jsonl').open('w') as f:
            for sample in samples:
                ev.emit(f, sample)
        cold[variant] = {key: ev.stats([s[key] for s in samples]) for key in
                        ('process_wall_ms', 'import_ms', 'engine_init_ms', 'first_candidates_ms', 'worker_ready_ms')}
        cold[variant]['rss_kib'] = ev.stats([s['memory']['VmRSS_kib'] for s in samples])
    ev.write(OUT / 'cold-summary.json', cold)
    performance, tails = {}, []
    for profile in ('baseline', 'v020', 'enhanced', 'personal', 'all_features', 'ziranma'):
        performance[profile] = json.loads((OUT / f'{profile}-performance.json').read_text())
        for line in (OUT / f'{profile}-keystrokes.jsonl').read_text().splitlines():
            row = json.loads(line)
            if row['elapsed_ms'] > 50:
                tails.append(row)
    ev.write(OUT / 'over-50ms.json', tails)
    before = json.loads((OUT / 'immutable-before.json').read_text())
    after = {p: hashlib.sha256((ROOT.parent / p).read_bytes()).hexdigest() for p in before}
    ev.write(OUT / 'immutable-after.json', after)
    if before != after:
        raise RuntimeError('preserved package, baseline evidence, corpus or lexicon was modified')
    summary = {'employee_id': 'engine', 'verifies': [], 'component_version': '0.3.0', 'api_version': '1.0',
               'corpus_sha256': ev.FROZEN_SHA, 'quality': {v: q['overall'] for v, q in quality.items()},
               'comparisons': comparisons, 'performance': performance, 'cold': cold,
               'quality_repeat_identical': repeat_ok, 'immutable_data_unchanged': True}
    ev.write(OUT / 'summary.json', summary)
    print(json.dumps({'quality': summary['quality'], 'warm_p95_ms': {
        k: v['candidate_ms']['p95'] for k, v in performance.items()}}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--quality'); parser.add_argument('--warm'); parser.add_argument('--cold-worker')
    parser.add_argument('--rounds', type=int, default=3); parser.add_argument('--cold-count', type=int, default=20)
    args = parser.parse_args()
    if args.quality:
        ev.quality(args.quality)
    elif args.warm:
        if args.warm == 'v020':
            # The preserved source resolves lexicon data relative to its old root.
            OriginalEngine = load_engine('v020')
            def old_engine(**kwargs):
                return OriginalEngine(base_lexicon=ROOT.parent / 'lexicon/data/base/lexicon-v1.jsonl', **kwargs)
            ev.load_engine = lambda _: old_engine
        ev.warm(args.warm, args.rounds, 'v020' if args.warm == 'v020' else None)
    elif args.cold_worker:
        if args.cold_worker == 'v020':
            def load_old(_):
                OriginalEngine = load_engine('v020')
                def old_engine(**kwargs):
                    return OriginalEngine(base_lexicon=ROOT.parent / 'lexicon/data/base/lexicon-v1.jsonl', **kwargs)
                return old_engine
            ev.load_engine = load_old
        ev.cold_worker(args.cold_worker)
    else:
        main(args.rounds, args.cold_count)
