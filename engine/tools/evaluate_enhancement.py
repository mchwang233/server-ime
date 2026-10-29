#!/usr/bin/env python3
"""Frozen-corpus quality, reproducible selection actions and process/keystroke timing.

employee_id=engine. No evaluator answer is passed to a dictionary/learning API.
Quality workers never open UserStore. Feature/performance stores are isolated.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'checks/enhancement'
CORPUS = ROOT.parent / 'lexicon/corpus/eval/cases-v1.jsonl'
MANIFEST = CORPUS.parent / 'manifest.json'
BASELINE = OUT / 'baseline-source/src'
FROZEN_SHA = '0f8c1c371872e28ef2b1b39c28e092a21090d58144b81800276ae48527a69ae3'


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')


def emit(handle, data):
    handle.write(json.dumps(data, ensure_ascii=False)+'\n')


def stats(values):
    values = sorted(values)
    if not values:
        return {'samples':0, 'p50':None, 'p95':None, 'p99':None, 'max':None, 'mean':None}
    return {'samples':len(values), **{f'p{p}':round(values[math.ceil(len(values)*p/100)-1],4)
                                    for p in (50,95,99)},
            'max':round(values[-1],4), 'mean':round(statistics.mean(values),4)}


def memory():
    fields = {}
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith(('VmRSS:', 'VmHWM:', 'VmSize:')):
            key, value = line.split(':',1)
            fields[key+'_kib'] = int(value.split()[0])
    fields['ru_maxrss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return fields


def load_engine(variant):
    sys.path.insert(0,str(BASELINE if variant=='baseline' else ROOT/'src'))
    from server_ime_engine import Engine
    return Engine


def create(variant, **options):
    return load_engine(variant)(runtime_dir=ROOT/'vendor/runtime', data_dir=ROOT/'vendor/runtime/data', **options)


def cases():
    payload=CORPUS.read_bytes()
    if hashlib.sha256(payload).hexdigest()!=FROZEN_SHA:
        raise RuntimeError('frozen evaluation corpus changed')
    return [json.loads(line) for line in payload.splitlines()]


def visible(session, state):
    # Match the platform adapter's 200-candidate bound, five per page.
    result=[]
    for page in range(min(40,(state['candidates']['total']+4)//5)):
        result.extend(session.candidates(page)['items'])
    return result[:200]


def selection_cost(session, state, expected):
    """Fixed greedy policy, not a claim of optimal or human cognitive cost.

    From the current list choose the longest candidate matching the remaining
    reference prefix (tie: earliest rank), then PageDown*floor(index/5)+digit.
    Each partial selection resets the page. Stop on no match or 32 selections.
    Unsolved has cost=None and is reported in the all-case denominator.
    """
    selected, actions, trace = '', 0, []
    for _ in range(32):
        remainder=expected[len(selected):]
        matching=[x for x in visible(session,state) if x['text'] and remainder.startswith(x['text'])]
        if not matching:
            return {'solved':False,'actions':None,'spent':actions,'reason':'no_matching_candidate','trace':trace}
        item=min(matching,key=lambda x:(-len(x['text']),x['index']))
        pages=item['index']//5
        for _ in range(pages):
            state=session.key('Page_Down')
        state=session.key(str(item['index']%5+1))
        actions+=pages+1
        trace.append({'text':item['text'],'index':item['index'],'page_down':pages,'select_keys':1,
                      'commits':state['commits'],'selected_length':state['input']['selected_length']})
        if state['commits']:
            actual=''.join(x['text'] for x in state['commits'])
            solved=actual==expected
            return {'solved':solved,'actions':actions if solved else None,'spent':actions,
                    'reason':'committed' if solved else 'wrong_commit','trace':trace}
        selected+=item['text']
    return {'solved':False,'actions':None,'spent':actions,'reason':'selection_limit','trace':trace}


def score(rows):
    solved=[r['cost']['actions'] for r in rows if r['cost']['solved']]
    n=len(rows)
    return {'cases':n,'top1':sum(x['top1'] for x in rows),'top5':sum(x['top5'] for x in rows),
            'top1_rate':sum(x['top1'] for x in rows)/n,'top5_rate':sum(x['top5'] for x in rows)/n,
            'errors':sum(x['error'] is not None for x in rows),
            'selection_solved':len(solved),'selection_unsolved':n-len(solved),
            'selection_actions_solved_only':stats(solved)}


def quality(variant):
    rows=[]
    with create(variant) as engine, (OUT/f'{variant}-quality-raw.jsonl').open('w') as raw:
        session=engine.create_session({'page_size':5,'learning':False})
        config=session.state()['config']
        for case in cases():
            session.reset()
            try:
                state=session.set_input(case['input'])
                top=[x['text'] for x in state['candidates']['items']]
                emit(raw,{'id':case['id'],'input':case['input'],'state':state,
                          'first_200':visible(session,state)})
                cost=selection_cost(session,state,case['expected'])
                error=None
            except Exception as exc:
                top=[];error=getattr(exc,'code',type(exc).__name__)
                cost={'solved':False,'actions':None,'spent':0,'reason':error,'trace':[]}
                emit(raw,{'id':case['id'],'input':case['input'],'error':error})
            rows.append({**case,'top':top,'top1':bool(top) and top[0]==case['expected'],
                         'top5':case['expected'] in top,'error':error,'cost':cost})
    summary={'variant':variant,'config':config,'learning':False,'corpus_sha256':FROZEN_SHA,
             'scoring':'ime-eval-score/1 exact top1/top5; engine-selection-actions/1',
             'overall':score(rows),'categories':{cat:score([r for r in rows if r['category']==cat])
                                                for cat in sorted({x['category'] for x in rows})},'rows':rows}
    write(OUT/f'{variant}-quality.json',summary)
    print(json.dumps(summary['overall']))


def warm(profile, rounds, variant=None):
    variant=variant or ('baseline' if profile=='baseline' else 'enhanced')
    Engine=load_engine(variant)
    options={};config={};temporary=None
    if profile in ('personal','all_features'):
        from server_ime_engine import lexicon_adapter as lx
        temporary=tempfile.TemporaryDirectory(prefix='ime-perf-')
        directory=Path(temporary.name)/'user'
        store=lx.UserStore(directory,create=True)
        seed,_=lx.base_entries(None)
        # Only training-side public domain entries; never evaluation references.
        for entry in seed[:128]:
            store.add_phrase(entry['text'],entry['pinyin'],count=entry['count'])
        options['user_data_dir']=directory;config['learning']=True
    if profile=='all_features':
        config['fuzzy']={'enabled':True,'rules':[]}
    if profile=='ziranma':
        config={'schema':'double_pinyin','double_pinyin_scheme':'ziranma',
                'fuzzy':{'enabled':True,'rules':['c_ch','s_sh','z_zh']}}
    corpus=cases()
    if profile=='ziranma':
        corpus=[{'id':f'D{i:03}','category':'ziranma','input':x} for i,x in enumerate([
            'nihk','vswf','uurufa','nihkuijx','xian','bjky','womfxvzdu','aa',
            'jnjmdeuirufa','womfxvzduwomfxvzdu','fuwuqi','nihkuijxnihkuijxnihkuijx'])]
    values=[];errors=[];categories={};post_learning=[]
    before=memory()
    t=time.perf_counter_ns()
    engine=Engine(runtime_dir=ROOT/'vendor/runtime',data_dir=ROOT/'vendor/runtime/data',**options)
    init_ms=(time.perf_counter_ns()-t)/1e6
    try:
        session=engine.create_session(config)
        for row in corpus:  # explicit untimed warm-up; no training
            try: session.set_input(row['input'])
            except ValueError: pass
        warmed=memory()
        with (OUT/f'{profile}-keystrokes.jsonl').open('w') as output:
            for iteration in range(rounds):
                for case in corpus:
                    session.reset()
                    for key_index,key in enumerate(case['input']):
                        start=time.perf_counter_ns();error=None
                        try: session.set_input(case['input'][:key_index+1])
                        except ValueError as exc: error=getattr(exc,'code',type(exc).__name__)
                        elapsed=(time.perf_counter_ns()-start)/1e6
                        emit(output,{'profile':profile,'round':iteration,'id':case['id'],
                                     'category':case['category'],'key_index':key_index,'key':key,
                                     'elapsed_ms':elapsed,'error':error})
                        (errors if error else values).append(elapsed)
                        if not error: categories.setdefault(case['category'],[]).append(elapsed)
            if config.get('learning'):
                for iteration in range(20):
                    state=session.set_input('shishi')
                    event=session.select(state['candidates']['items'][1]['id'])['commits'][0]
                    start=time.perf_counter_ns();session.input('s');elapsed=(time.perf_counter_ns()-start)/1e6
                    post_learning.append(elapsed)
                    emit(output,{'profile':profile,'event':'first_key_after_learning','round':iteration,
                                 'elapsed_ms':elapsed,'recorded':event['learning']['recorded']})
        after=memory()
        summary={'profile':profile,'config':session.state()['config'],'rounds':rounds,'init_ms':init_ms,
                 'candidate_ms':stats(values),'rejected_input_ms':stats(errors),
                 'categories':{k:stats(v) for k,v in categories.items()},
                 'first_key_after_learning_ms':stats(post_learning),
                 'memory':{'before':before,'after_warmup':warmed,'after_measurement':after},
                 'target_p95_ms':50,'p95_gap_ms':max(0,stats(values)['p95']-50),
                 'personal_seed_entries':128 if temporary else 0}
        write(OUT/f'{profile}-performance.json',summary)
        print(json.dumps(summary))
    finally:
        engine.close()
        if temporary: temporary.cleanup()


def cold_worker(variant):
    start=time.perf_counter_ns();Engine=load_engine(variant);loaded=time.perf_counter_ns()
    with Engine(runtime_dir=ROOT/'vendor/runtime',data_dir=ROOT/'vendor/runtime/data') as e:
        initialized=time.perf_counter_ns()
        s=e.create_session();state=s.set_input('nihaoshijie');ready=time.perf_counter_ns()
        print(json.dumps({'import_ms':(loaded-start)/1e6,'engine_init_ms':(initialized-loaded)/1e6,
                          'first_candidates_ms':(ready-initialized)/1e6,'worker_ready_ms':(ready-start)/1e6,
                          'memory':memory(),'top1':state['candidates']['items'][0]['text']}),flush=True)


def run_worker(args):
    result=subprocess.run([sys.executable,str(Path(__file__).resolve()),*args],cwd=str(ROOT.parent),
                          capture_output=True,text=True,check=True)
    with (OUT/'workers.log').open('a') as log:
        log.write('COMMAND '+repr(args)+'\n'+result.stdout+result.stderr+'\n')
    return result


def main(rounds,cold_count):
    OUT.mkdir(parents=True,exist_ok=True)
    cases()
    cpu={}
    for line in Path('/proc/cpuinfo').read_text().splitlines():
        if ':' in line:
            key,value=(x.strip() for x in line.split(':',1))
            if key in ('model name','cpu MHz','cpu cores','siblings') and key not in cpu: cpu[key]=value
    versions=subprocess.run(['rpm','-q','libpinyin','libpinyin-data','glib2','libdb','pcre','glibc','libstdc++'],capture_output=True,text=True)
    write(OUT/'environment.json',{'employee_id':'engine','platform':platform.platform(),'uname':list(platform.uname()),
          'python':sys.version,'cpu':cpu,'logical_cpus':os.cpu_count(),'affinity_cpus':len(os.sched_getaffinity(0)),
          'meminfo':Path('/proc/meminfo').read_text(),'dependency_rpms':versions.stdout,
          'dependencies_manifest_sha256':hashlib.sha256((ROOT/'dependencies.json').read_bytes()).hexdigest(),
          'timer':'perf_counter_ns CLOCK_MONOTONIC','percentile':'nearest rank ceil(N*p)',
          'cold_definition':'new Python process, OS page cache not flushed; wall includes process exit',
          'warm_definition':'untimed full-corpus pass, then per-keystroke prefix Session.set_input -> candidate state, no GUI/IPC',
          'baseline_sources':{str(p.relative_to(BASELINE)):hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in BASELINE.rglob('*.py')}})
    for variant in ('baseline','enhanced'): run_worker(['--quality',variant])
    baseline=json.loads((OUT/'baseline-quality.json').read_text()); enhanced=json.loads((OUT/'enhanced-quality.json').read_text())
    deltas={}
    for cat in ['overall',*baseline['categories']]:
        a=baseline['overall'] if cat=='overall' else baseline['categories'][cat]
        b=enhanced['overall'] if cat=='overall' else enhanced['categories'][cat]
        deltas[cat]={key:b[key]-a[key] for key in ('top1','top5','top1_rate','top5_rate','selection_solved','selection_unsolved')}
    common=[(a,b) for a,b in zip(baseline['rows'],enhanced['rows']) if a['cost']['solved'] and b['cost']['solved']]
    comparison={'corpus_sha256':FROZEN_SHA,'deltas':deltas,
                'same_solved_cases':len(common),
                'same_solved_baseline_actions':stats([a['cost']['actions'] for a,b in common]),
                'same_solved_enhanced_actions':stats([b['cost']['actions'] for a,b in common]),
                'top1_regressions':[b['id'] for a,b in zip(baseline['rows'],enhanced['rows']) if a['top1'] and not b['top1']],
                'top5_regressions':[b['id'] for a,b in zip(baseline['rows'],enhanced['rows']) if a['top5'] and not b['top5']]}
    write(OUT/'quality-comparison.json',comparison)
    for profile in ('baseline','enhanced','personal','all_features','ziranma'):
        run_worker(['--warm',profile,'--rounds',str(rounds if profile!='ziranma' else rounds*20)])
    cold={}
    for variant in ('baseline','enhanced'):
        samples=[]
        for index in range(cold_count):
            t=time.perf_counter_ns();r=run_worker(['--cold-worker',variant]);wall=(time.perf_counter_ns()-t)/1e6
            samples.append({'variant':variant,'index':index,'process_wall_ms':wall,**json.loads(r.stdout)})
        with (OUT/f'{variant}-cold.jsonl').open('w') as out:
            for row in samples: emit(out,row)
        cold[variant]={key:stats([x[key] for x in samples]) for key in (
            'process_wall_ms','import_ms','engine_init_ms','first_candidates_ms','worker_ready_ms')}
        cold[variant]['rss_kib']=stats([x['memory']['VmRSS_kib'] for x in samples])
    write(OUT/'cold-summary.json',cold)
    before=json.loads((OUT/'immutable-before.json').read_text())
    after={p:hashlib.sha256((ROOT.parent/p).read_bytes()).hexdigest() for p in before}
    write(OUT/'immutable-after.json',after)
    if before!=after: raise RuntimeError('model, enhancement data or fixed corpus was modified')
    summary={'employee_id':'engine','verifies':[],'quality':{'baseline':baseline['overall'],'enhanced':enhanced['overall'],
             'comparison':comparison},'performance':{p:json.loads((OUT/f'{p}-performance.json').read_text()) for p in (
                 'baseline','enhanced','personal','all_features','ziranma')},'cold':cold,'immutable_data_unchanged':before==after}
    write(OUT/'summary.json',summary)
    print(json.dumps({'quality':summary['quality'],'warm_p95_ms':{k:v['candidate_ms']['p95'] for k,v in summary['performance'].items()}},ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--quality');parser.add_argument('--warm')
    parser.add_argument('--cold-worker');parser.add_argument('--rounds',type=int,default=3);parser.add_argument('--cold-count',type=int,default=20)
    args=parser.parse_args()
    if args.quality: quality(args.quality)
    elif args.warm: warm(args.warm,args.rounds)
    elif args.cold_worker: cold_worker(args.cold_worker)
    else: main(args.rounds,args.cold_count)
