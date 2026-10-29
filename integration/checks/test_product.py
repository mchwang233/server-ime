"""Real IBus input context plus settings UI callback, persistence and recovery."""
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import gi
gi.require_version('IBus', '1.0')
from gi.repository import IBus, GLib
from server_ime_product.rpc import Client
from server_ime_product.supervisor import request
from server_ime.ui_client import StateClient
from ime_interface import config
from lexicon.store import UserStore
from x11 import pump, wait_for, screenshot

E = Path(os.environ['SERVER_IME_EVIDENCE'])
COMMAND = json.loads(os.environ['SERVER_IME_CHECK_COMMAND'])
STATE = Path(COMMAND[2])
checks = []

def record(name, **data):
    checks.append(dict(name=name, result='PASS', **data))
    (E/'product-contract.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2))
    print(name, flush=True)


def context():
    bus = IBus.Bus.new()
    ctx = bus.create_input_context('server-ime-product-contract')
    ctx.set_capabilities(int(IBus.Capabilite.PREEDIT_TEXT | IBus.Capabilite.LOOKUP_TABLE | IBus.Capabilite.FOCUS))
    ctx.focus_in()
    ctx.set_engine('server-ime')
    pump(.3)
    received = []
    ctx.connect('commit-text', lambda c, text: received.append(text.get_text()))
    return bus, ctx, received


def type_keys(ctx, text):
    for char in text:
        ctx.process_key_event(ord(char), 0, 0)
        pump(.01)
    pump(.1)


def active(client):
    states = [client.get_state(cid) for cid in client.list_contexts()]
    return next(s for s in states if s['focused'] and s['enabled'])


def main():
    rpc, states = Client(), StateClient()
    original = rpc.call('get')
    assert not original['deterministic'] and original['capabilities']['component_version'] == '0.4.0'
    bus, ctx, commits = context()
    type_keys(ctx, 'nihao')
    snap = active(states)
    assert snap['candidates'] and not snap['deterministic']
    ctx.process_key_event(32,0,0); pump(.2)
    assert commits == ['你好'], commits
    record('real-engine-commit', commits=commits[:], backend=snap['backend'])
    # The actual SettingsWindow callback is the same service RPC as CLI.
    from server_ime_product.panel import settings_window
    window = settings_window()
    updated = copy.deepcopy(original['settings'])
    updated['input'].update(page_size=4, learning=True)
    updated['panel']['font_scale'] = 1.25
    window.refresh_controls(updated)
    assert window.save()
    window.window.hide()
    pump(.2)
    live = rpc.call('get')
    assert live['settings']['input']['learning'] and live['engine_config']['learning']
    assert live['engine_config']['page_size'] == 4
    assert Path(live['config_path']).stat().st_mode & 0o777 == 0o600
    record('settings-window-service-transaction', config=live['settings'], revision=live['revision'])
    ctx.focus_in(); pump(.2)
    type_keys(ctx, 'nihao'); ctx.process_key_event(32,0,0); pump(.2)
    store = UserStore(Path(live['data_dir'])/'learning')
    words = store.list_words()
    record('learning-before-restart', words=words)
    assert '你好' in json.dumps(words, ensure_ascii=False)
    type_keys(ctx, 'ni')
    current = active(states)
    target = next(c for c in current['candidates'] if c['text'] == '泥')
    assert current['candidates'][0]['text'] != '泥'
    assert states.select_candidate(current, target['id']); pump(.2)
    type_keys(ctx, 'ni'); ranked = active(states)
    assert ranked['candidates'][0]['text'] == '泥'
    ctx.reset(); pump(.1)
    record('nonfirst-selection-learned-ranking', selected='泥', first_after='泥')
    before_words = (Path(live['data_dir'])/'learning/words.jsonl').read_bytes()
    ctx.set_content_type(8, 0); pump(.1)
    for char in 'nihaoUser+Tag@Example.org123':
        assert not ctx.process_key_event(ord(char), 0, 0)
    assert not ctx.process_key_event(0xFFB2, 0, 16)
    assert not ctx.process_key_event(32, 0, 4)
    assert not active(states)['candidates']
    ctx.set_content_type(0, 0); pump(.1)
    assert before_words == (Path(live['data_dir'])/'learning/words.jsonl').read_bytes()
    record('sensitive-purpose-no-learning', attempted='nihaoUser+Tag@Example.org123',
           purpose=8, keypad_digit_bypassed=True, words_unchanged=True)
    for name, patch, raw, expected in [
        ('double-pinyin', {'schema':'double_pinyin', 'double_pinyin_scheme':'ziranma'}, 'nihk', '你好'),
        ('fuzzy', {'fuzzy':{'enabled':True,'rules':['z_zh']}}, 'zongwen', '中文'),
        ('correction', {'correction':{'enabled':True,'rules':['transpose']}}, 'nihoa', '你好')]:
        settings = copy.deepcopy(updated); settings['input'].update(patch)
        applied = rpc.call('apply', settings=settings)
        type_keys(ctx,raw); snapshot = active(states)
        candidate = next(c for c in snapshot['candidates'] if c['text']==expected)
        assert states.select_candidate(snapshot,candidate['id']);pump(.1)
        assert commits[-1]==expected
        record('live-'+name, engine_config=applied['engine_config'], raw=raw, received=commits[-1])
    live=rpc.call('apply',settings=updated)
    before = Path(live['config_path']).read_bytes()
    invalid = copy.deepcopy(updated); invalid['input']['double_pinyin_scheme']='mspy'
    try:
        rpc.call('apply', settings=invalid)
        raise AssertionError('invalid configuration accepted')
    except config.ConfigError:
        pass
    assert Path(live['config_path']).read_bytes() == before
    assert rpc.call('get')['settings'] == live['settings']
    record('invalid-config-no-change')
    # Ordinary program restart with the same persistent data and fresh IBus bus.
    ctx.focus_out(); ctx.destroy(); pump(.1)
    subprocess.run(COMMAND+['stop'], check=True, capture_output=True)
    subprocess.run(COMMAND+['start','--managed-ibus'], check=True, capture_output=True)
    os.environ.update(request(STATE, 'status')['env'])
    # IBus.Bus.new() caches its connection in this process: run restart checks
    # in a new process, as applications themselves do after a full daemon restart.
    child = subprocess.run([sys.executable, __file__, 'after-restart'], env=os.environ.copy(),
                           text=True, capture_output=True, timeout=50)
    (E/'after-restart.log').write_text(child.stdout+child.stderr)
    assert child.returncode == 0, child.stderr
    record('program-restart', recovered=json.loads((E/'after-restart.json').read_text()))
    return 0


def after_restart():
    rpc, states = Client(), StateClient()
    live = rpc.call('get')
    assert live['engine_config']['learning'] and live['engine_config']['page_size']==4
    words = UserStore(Path(live['data_dir'])/'learning').list_words()
    assert '你好' in json.dumps(words,ensure_ascii=False)
    bus, ctx, commits = context()
    type_keys(ctx,'ni')
    learned=active(states)
    assert learned['candidates'][0]['text']=='泥'
    ctx.reset();pump(.1)
    type_keys(ctx,'nihao')
    snap=active(states)
    assert snap['candidates'][0]['text']=='你好'
    ctx.process_key_event(32,0,0);pump(.2)
    assert commits==['你好']
    ctx.focus_out(); ctx.destroy(); pump(.1)
    recoveries=[]
    for name in ('panel','service','ibus'):
        before=request(STATE,'status')
        pid=before['children'][name]
        os.kill(pid,signal.SIGKILL)
        until=time.monotonic()+18
        while time.monotonic()<until:
            time.sleep(.2)
            try:
                after=request(STATE,'status')
                if after['state']=='running' and after['children'].get(name)!=pid:
                    break
            except OSError: pass
        else: raise AssertionError('No recovery: '+name)
        recoveries.append(dict(child=name,old_pid=pid,new_pid=after['children'][name],restarts=after['restarts']))
    os.environ.update(request(STATE,'status')['env'])
    child=subprocess.run([sys.executable,__file__,'final-probe'],env=os.environ.copy(),capture_output=True,text=True,timeout=15)
    assert child.returncode==0,child.stderr
    (E/'after-restart.json').write_text(json.dumps(dict(config=live['engine_config'],words=words,
        recovered_first_candidate=learned['candidates'][0]['text'], recoveries=recoveries,post_crash=json.loads(child.stdout)),ensure_ascii=False,indent=2))
    return 0


def final_probe():
    rpc=Client(); bus,ctx,commits=context()
    type_keys(ctx,'zhongwen'); ctx.process_key_event(32,0,0);pump(.2)
    assert commits==['中文'],commits
    print(json.dumps(dict(commits=commits,config=rpc.call('get')['engine_config']),ensure_ascii=False))
    return 0

if __name__=='__main__':
    raise SystemExit(after_restart() if sys.argv[-1]=='after-restart' else
                     final_probe() if sys.argv[-1]=='final-probe' else main())
