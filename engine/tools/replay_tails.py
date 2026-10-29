#!/usr/bin/env python3
"""Replay every historical >50ms sample, without selecting on new timings.

employee_id=engine. Native primitive timings are disjoint; expansion is inclusive.
"""
import argparse
import collections
import json
from pathlib import Path
import sys
import tempfile
import time

import evaluate_enhancement as ev

ROOT = ev.ROOT
OUT = ROOT / 'checks/mixed-revision'


def main(variant):
    source = OUT / 'v030-source/src' if variant == 'v030' else ROOT / 'src'
    sys.path.insert(0, str(ROOT.parent / 'lexicon/src'))
    sys.path.insert(0, str(source))
    from server_ime_engine import Engine, lexicon_adapter as lx
    from server_ime_engine.expansion import Expansion
    original = json.loads((ROOT / 'checks/quality-revision/over-50ms.json').read_text())
    corpus = ev.cases()
    cases = {c['id']: c for c in corpus}
    results = []
    for profile in ('enhanced', 'personal', 'all_features'):
        with tempfile.TemporaryDirectory(prefix='tail-replay-', dir=OUT) as tmp:
            options = {'base_lexicon': ROOT.parent / 'lexicon/data/base/lexicon-v1.jsonl'}
            config = {}
            if profile in ('personal', 'all_features'):
                options['user_data_dir'] = Path(tmp) / 'user'
                store = lx.UserStore(options['user_data_dir'], create=True)
                for entry in lx.base_entries(options['base_lexicon'])[0][:128]:
                    store.add_phrase(entry['text'], entry['pinyin'], count=entry['count'])
                config['learning'] = True
            if profile == 'all_features':
                config['fuzzy'] = {'enabled': True, 'rules': []}
            with Engine(runtime_dir=ROOT / 'vendor/runtime', **options) as engine:
                session = engine.create_session(config)
                for case in corpus:
                    try:
                        session.set_input(case['input'])
                    except ValueError:
                        pass
                stages = {}
                calls = {}
                def timed(name, method):
                    def wrapped(*args, **kwargs):
                        start = time.perf_counter_ns()
                        try:
                            return method(*args, **kwargs)
                        finally:
                            stages[name] = stages.get(name, 0) + (time.perf_counter_ns() - start) / 1e6
                            calls[name] = calls.get(name, 0) + 1
                    return wrapped
                n = engine._native
                names = ('parse_more_full_pinyins', 'guess_sentence', 'guess_candidates',
                         'phrase_segment', 'get_candidate', 'get_candidate_string', 'get_candidate_type',
                         'choose_candidate')
                for name in names:
                    setattr(n, name, timed(name, getattr(n, name)))
                original_generate = Expansion.generate
                Expansion.generate = timed('expansion_inclusive', original_generate)
                try:
                    for index, old in enumerate(original):
                        if old['profile'] != profile:
                            continue
                        text = cases[old['id']]['input'][:old['key_index'] + 1]
                        session.reset()
                        # Recreate the preceding key, then time precisely the historical key.
                        session.set_input(text[:-1])
                        stages.clear(); calls.clear()
                        start = time.perf_counter_ns()
                        state = session.set_input(text)
                        elapsed = (time.perf_counter_ns() - start) / 1e6
                        results.append({'sample_index': index, 'historical': old, 'input': text,
                                        'config': state['config'], 'elapsed_ms': elapsed,
                                        'stages_ms': dict(stages), 'stage_calls': dict(calls),
                                        'top': [c['text'] for c in state['candidates']['items']]})
                finally:
                    Expansion.generate = original_generate
        print(variant, profile, 'done', flush=True)
    results.sort(key=lambda r: r['sample_index'])
    assert len(results) == len(original)
    with (OUT / f'{variant}-tail-replay.jsonl').open('w') as handle:
        for row in results:
            ev.emit(handle, row)
    summary = {}
    for profile in ('all', 'enhanced', 'personal', 'all_features'):
        rows = [r for r in results if profile == 'all' or r['historical']['profile'] == profile]
        summary[profile] = {'latency_ms': ev.stats([r['elapsed_ms'] for r in rows]),
                            'over_50ms': sum(r['elapsed_ms'] > 50 for r in rows),
                            'stages_ms': {s: ev.stats([r['stages_ms'].get(s, 0) for r in rows])
                                          for s in results[0]['stages_ms']}}
    ev.write(OUT / f'{variant}-tail-summary.json', summary)
    print(json.dumps(summary['all']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('variant', choices=['v030', 'current'])
    main(parser.parse_args().variant)
