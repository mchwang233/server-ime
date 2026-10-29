#!/usr/bin/env python3
"""0.4.0 quality/performance evidence; frozen historical scoring stays unchanged.

employee_id=engine. Independent mixed key cases are never lexical input data.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

import evaluate_enhancement as ev
from evaluate_revision import compare

ROOT = ev.ROOT
OUT = ROOT/'checks/mixed-revision'
ev.OUT = OUT


def load_engine(variant):
    source = OUT/'v030-source/src' if variant == 'v030' else ROOT/'src'
    sys.path.insert(0, str(ROOT.parent/'lexicon/src'))
    sys.path.insert(0, str(source))
    from server_ime_engine import Engine
    return Engine


def create(variant, **options):
    return load_engine(variant)(runtime_dir=ROOT/'vendor/runtime',
                               base_lexicon=ROOT.parent/'lexicon/data/base/lexicon-v1.jsonl', **options)


ev.load_engine = load_engine
ev.create = create


def composition_quality(variant='composition'):
    """Same references, ranks and greedy cost rule through the new input API.

    Explicit select represents one candidate-selection action. It disambiguates
    numeric literal entry without counting typed digits as candidate selection.
    """
    class Actions:
        def __init__(self, session): self.session = session
        def __getattr__(self, name): return getattr(self.session, name)
        def key(self, key):
            if len(key) == 1 and key in '123456789':
                page = self.session.candidates()
                return self.session.select(page['items'][int(key)-1]['id'])
            return self.session.key(key)
    rows = []
    with create('enhanced') as e, (OUT/f'{variant}-quality-raw.jsonl').open('w') as output:
        session = e.create_session({'page_size': 5, 'learning': False})
        for case in ev.cases():
            session.reset()
            state = session.set_composition(case['input'])
            top = [c['text'] for c in state['candidates']['items']]
            ev.emit(output, {'id': case['id'], 'input': case['input'], 'state': state,
                             'first_200': ev.visible(session, state)})
            cost = ev.selection_cost(Actions(session), state, case['expected'])
            rows.append({**case, 'top': top, 'top1': bool(top) and top[0] == case['expected'],
                         'top5': case['expected'] in top, 'error': None, 'cost': cost})
        report = {'variant': variant, 'config': session.state()['config'], 'learning': False,
                  'corpus_sha256': ev.FROZEN_SHA, 'scoring': 'ime-eval-score/1 exact top1/top5',
                  'selection_policy': 'same longest-prefix/earliest-rank policy; page-down plus explicit select (one action), because mixed digits may be literals',
                  'overall': ev.score(rows), 'categories': {c: ev.score([r for r in rows if r['category'] == c])
                                                           for c in sorted({r['category'] for r in rows})}, 'rows': rows}
        ev.write(OUT/f'{variant}-quality.json', report)
        print(json.dumps(report['overall']))


def worker(*args):
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), *args],
                            cwd=ROOT.parent, text=True, capture_output=True, check=True)
    with (OUT/'workers.log').open('a') as log:
        log.write(repr(args)+'\n'+result.stdout+result.stderr+'\n')
    return result


def mixed_warm(profile, rounds):
    cases = (ev.cases() if profile.startswith('composition_corpus') else
             json.loads((ROOT/'data/mixed-keystrokes-v1.json').read_text())['cases'])
    options, config = {}, {}
    with tempfile.TemporaryDirectory(prefix='mixed-perf-', dir=OUT) as directory:
        if profile.endswith('all_features'):
            from server_ime_engine import lexicon_adapter as lx
            path = Path(directory)/'user'
            store = lx.UserStore(path, create=True)
            for entry in lx.base_entries(None)[0][:128]:
                store.add_phrase(entry['text'], entry['pinyin'], count=entry['count'])
            options['user_data_dir'] = path
            config = {'learning': True, 'fuzzy': {'enabled': True, 'rules': []}}
        before = ev.memory()
        with create('enhanced', **options) as e, e.create_session(config) as s:
            for case in cases:
                s.configure({'schema': case.get('schema', 'full_pinyin')})
                s.set_composition(case['input'])
            warmed = ev.memory()
            values, errors = [], []
            with (OUT/f'{profile}-keystrokes.jsonl').open('w') as handle:
                for iteration in range(rounds):
                    for case in cases:
                        s.reset()
                        s.configure({'schema': case.get('schema', 'full_pinyin')})
                        for i, key in enumerate(case['input']):
                            start = time.perf_counter_ns()
                            r = s.set_composition(case['input'][:i+1])
                            elapsed = (time.perf_counter_ns()-start)/1e6
                            values.append(elapsed)
                            ev.emit(handle, {'profile': profile, 'round': iteration, 'id': case['id'],
                                             'key_index': i, 'key': key, 'elapsed_ms': elapsed, 'error': None,
                                             'top': [c['text'] for c in r['candidates']['items']]})
            report = {'profile': profile, 'config': s.state()['config'], 'rounds': rounds,
                      'schema_per_case': True, 'candidate_ms': ev.stats(values),
                      'over_50ms': sum(x > 50 for x in values), 'target_p95_ms': 50,
                      'p95_gap_ms': max(0, ev.stats(values)['p95']-50),
                      'memory': {'before': before, 'after_warmup': warmed, 'after_measurement': ev.memory()}}
            ev.write(OUT/f'{profile}-performance.json', report)
            print(json.dumps(report))


def cold(variant):
    start = time.perf_counter_ns()
    Engine = load_engine(variant)
    loaded = time.perf_counter_ns()
    with Engine(runtime_dir=ROOT/'vendor/runtime', base_lexicon=ROOT.parent/'lexicon/data/base/lexicon-v1.jsonl') as e:
        initialized = time.perf_counter_ns()
        s = e.create_session()
        state = s.set_input('nihaoshijie')
        ready = time.perf_counter_ns()
        print(json.dumps({'import_ms': (loaded-start)/1e6, 'engine_init_ms': (initialized-loaded)/1e6,
                          'first_candidates_ms': (ready-initialized)/1e6, 'worker_ready_ms': (ready-start)/1e6,
                          'memory': ev.memory(), 'top1': state['candidates']['items'][0]['text']}))


def main(rounds, cold_count):
    OUT.mkdir(exist_ok=True)
    ev.cases()
    previous = ROOT/'checks/quality-revision'
    env = json.loads((previous/'environment.json').read_text())
    env.update(component_version='0.4.0', measured_at_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
               platform=platform.platform(), python=sys.version, cpuinfo=Path('/proc/cpuinfo').read_text(),
               meminfo=Path('/proc/meminfo').read_text(), logical_cpus=os.cpu_count(),
               affinity_cpus=len(os.sched_getaffinity(0)),
               source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted((ROOT/'src').rglob('*.py'))},
               mixed_keycases_sha256=hashlib.sha256((ROOT/'data/mixed-keystrokes-v1.json').read_bytes()).hexdigest(),
               cold_definition='new Python process, OS page cache not flushed; wall includes process exit',
               warm_definition='untimed corpus pass, per-key Session.set_input -> candidate state; mixed uses set_composition; no GUI/IPC',
               percentile='nearest rank ceil(N*p)', target_p95_ms=50)
    ev.write(OUT/'environment.json', env)
    quality = {}
    for variant in ('enhanced', 'repeat'):
        print('quality', variant, flush=True)
        worker('--quality', variant)
        quality[variant] = json.loads((OUT/f'{variant}-quality.json').read_text())
    for variant in ('composition', 'composition-repeat'):
        worker('--composition-quality', variant)
        quality[variant] = json.loads((OUT/f'{variant}-quality.json').read_text())
    def outcomes(q):
        return [(r['id'], r['top'], r['top1'], r['top5'], r['error'],
                 r['cost']['solved'], r['cost']['actions'], r['cost']['spent']) for r in q['rows']]
    repeated = outcomes(quality['enhanced']) == outcomes(quality['repeat'])
    assert outcomes(quality['composition']) == outcomes(quality['composition-repeat'])
    assert repeated
    comparisons = {}
    for variant, filename in (('v010', 'baseline-quality.json'), ('v020', 'v020-quality.json'),
                              ('v030', 'enhanced-quality.json')):
        quality[variant] = json.loads((previous/filename).read_text())
        comparisons[variant] = compare(quality[variant], quality['enhanced'])
    ev.write(OUT/'quality-comparison.json', comparisons)
    ev.write(OUT/'composition-comparison.json', {v: compare(quality[v], quality['composition'])
                                                for v in ('v010', 'v030', 'enhanced')})
    ev.write(OUT/'quality-repeat.json', {'identical_all_200_outcomes_and_costs': repeated})
    profiles = ('enhanced', 'personal', 'all_features', 'ziranma', 'mixed', 'mixed_all_features',
                'composition_corpus', 'composition_corpus_all_features')
    performance, tails = {}, []
    for profile in profiles:
        print('warm', profile, flush=True)
        worker('--warm', profile, '--rounds', str(rounds * (20 if profile in ('ziranma', 'mixed', 'mixed_all_features') else 1)))
        result = json.loads((OUT/f'{profile}-performance.json').read_text())
        samples = [json.loads(line) for line in (OUT/f'{profile}-keystrokes.jsonl').read_text().splitlines()]
        result['over_50ms'] = sum(r['elapsed_ms'] > 50 for r in samples if not r.get('event') and not r.get('error'))
        result['over_50ms_after_learning'] = sum(r['elapsed_ms'] > 50 for r in samples if r.get('event'))
        tails.extend(r for r in samples if r['elapsed_ms'] > 50)
        ev.write(OUT/f'{profile}-performance.json', result)
        performance[profile] = result
    cold_results = {}
    for variant in ('v030', 'enhanced'):
        print('cold', variant, flush=True)
        samples = []
        for index in range(cold_count):
            start = time.perf_counter_ns()
            result = worker('--cold', variant)
            samples.append({'variant': variant, 'index': index, 'process_wall_ms': (time.perf_counter_ns()-start)/1e6,
                            **json.loads(result.stdout)})
        with (OUT/f'{variant}-cold.jsonl').open('w') as handle:
            for sample in samples: ev.emit(handle, sample)
        cold_results[variant] = {k: ev.stats([r[k] for r in samples]) for k in
                                ('process_wall_ms', 'import_ms', 'engine_init_ms', 'first_candidates_ms', 'worker_ready_ms')}
        cold_results[variant]['rss_kib'] = ev.stats([r['memory']['VmRSS_kib'] for r in samples])
    print('historical tails', flush=True)
    result = subprocess.run([sys.executable, str(ROOT/'tools/replay_tails.py'), 'current'],
                            capture_output=True, text=True, check=True)
    (OUT/'tail-after.log').write_text(result.stdout+result.stderr)
    ev.write(OUT/'over-50ms.json', tails)
    ev.write(OUT/'cold-summary.json', cold_results)
    before = json.loads((OUT/'immutable-before.json').read_text())
    after = {p: hashlib.sha256((ROOT.parent/p).read_bytes()).hexdigest() for p in before}
    ev.write(OUT/'immutable-after.json', after)
    assert before == after, 'preserved evidence, package or lexical data changed'
    summary = {'employee_id': 'engine', 'verifies': [], 'component_version': '0.4.0',
               'api_version': '1.0', 'corpus_sha256': ev.FROZEN_SHA,
               'quality': {v: q['overall'] for v, q in quality.items()}, 'comparisons': comparisons,
               'performance': performance, 'cold': cold_results,
               'historical_tails': {v: json.loads((OUT/f'{v}-tail-summary.json').read_text()) for v in ('v030', 'current')},
               'immutable_data_unchanged': True, 'quality_repeat_identical': repeated}
    ev.write(OUT/'summary.json', summary)
    print(json.dumps({'quality': summary['quality'], 'warm_p95_ms': {p: x['candidate_ms']['p95'] for p, x in performance.items()}}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--quality'); parser.add_argument('--warm'); parser.add_argument('--cold')
    parser.add_argument('--composition-quality')
    parser.add_argument('--rounds', type=int, default=3); parser.add_argument('--cold-count', type=int, default=20)
    args = parser.parse_args()
    if args.quality:
        ev.quality(args.quality)
    elif args.composition_quality:
        composition_quality(args.composition_quality)
    elif args.warm:
        if args.warm.startswith(('mixed', 'composition_corpus')):
            load_engine('enhanced')
            mixed_warm(args.warm, args.rounds)
        else:
            ev.warm(args.warm, args.rounds)
    elif args.cold:
        cold(args.cold)
    else:
        main(args.rounds, args.cold_count)
