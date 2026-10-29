#!/usr/bin/env python3
"""employee_id=platform: candidate-channel regression on real Xvnc/xfwm4/IBus.

Default: reproduce the retained 0.2.1 product, then check the current product's
single candidate window and horizontal layout on managed and existing IBus
connections. --baseline runs only the retained product. Per the latest rework,
prediction development and Windows comparisons remain cancelled for this step.
Evidence lives in the project directory. Ephemeral sockets/config/auth/profile
use a newly created short /tmp path for Unix socket limits; never connect to an
inherited display/bus or change shared IBus settings.
"""
import argparse
import ctypes
import difflib
import hashlib
import http.server
import json
import os
from pathlib import Path
import re
import secrets
import select
import shutil
import signal
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()
PRODUCT = Path(os.environ.get('SERVER_IME_FEEDBACK_PRODUCT_ROOT', str(ROOT))).resolve()
PATHS = [PRODUCT / p for p in ('integration/src', 'platform', 'engine/src',
                             'interface/src', 'lexicon/src')]
PATHS += [ROOT / p for p in ('interface/tests', 'integration/checks')]
sys.path[:0] = list(map(str, PATHS))
FILES = ('platform/server_ime/ibus_adapter.py', 'platform/server_ime/product_controller.py',
         'integration/src/server_ime_product/runtime.py', 'integration/src/server_ime_product/panel.py',
         'integration/checks/test_feedback.py')


def save(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def until(fn, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(.05)
    raise RuntimeError('Timed out: ' + repr(fn))


def isolated(out, route, baseline=False, product=ROOT, narrow=False):
    out.mkdir()
    runtime = Path(tempfile.mkdtemp(prefix='ime-layout-', dir='/tmp'))
    processes, logs = [], []
    env = os.environ.copy()
    for k in ('DISPLAY', 'WAYLAND_DISPLAY', 'IBUS_ADDRESS', 'IBUS_ADDRESS_FILE',
              'DBUS_SESSION_BUS_ADDRESS', 'DBUS_STARTER_ADDRESS', 'DBUS_STARTER_BUS_TYPE',
              'SESSION_MANAGER', 'XDG_SESSION_ID', 'IBUS_USE_PORTAL', 'SERVER_IME_CONFIG', 'SERVER_IME_DATA'):
        env.pop(k, None)
    for key, folder in dict(XDG_CONFIG_HOME='config', XDG_DATA_HOME='data', XDG_CACHE_HOME='cache',
                            XDG_RUNTIME_DIR='run', XDG_STATE_HOME='state', TMPDIR='tmp').items():
        target = runtime / folder
        target.mkdir(mode=0o700)
        env[key] = str(target)
    env.update(GSETTINGS_BACKEND='memory', GDK_BACKEND='x11', GTK_IM_MODULE='ibus',
               QT_IM_MODULE='ibus', XMODIFIERS='@im=ibus', GTK_USE_PORTAL='0', NO_AT_BRIDGE='1',
               SERVER_IME_ISOLATED='1', XDG_SESSION_TYPE='x11', PYTHONDONTWRITEBYTECODE='1',
               PYTHONPATH=':'.join(map(str, PATHS)), FEEDBACK_OUT=str(out), FEEDBACK_RUNTIME=str(runtime))
    env['FEEDBACK_NARROW'] = '1' if narrow else '0'
    common = [str(ROOT/'integration/bin/server-ime'), '--state-dir', str(runtime/'r'),
              '--config', str(runtime/'settings.json'), '--data-dir', str(runtime/'personal')]
    if product != ROOT:
        common[0] = str(product / 'bin/server-ime')
    env['SERVER_IME_FEEDBACK_PRODUCT_ROOT'] = str(product)
    env['PYTHONPATH'] = ':'.join(str(product / p) for p in
        ('integration/src', 'platform', 'engine/src', 'interface/src', 'lexicon/src')) + ':' + ':'.join(
        str(ROOT / p) for p in ('interface/tests', 'integration/checks'))
    env['FEEDBACK_COMMAND'] = json.dumps(common)
    result = dict(employee_id='platform', verifies=[], route=route, baseline=baseline,
                  scope='task-created authenticated Xvnc + xfwm4 + private buses', result='FAIL',
                  screen=[360 if narrow else 1280, 960], narrow=narrow)
    def start(cmd, name, pass_fds=()):
        f = (out/(name+'.log')).open('w'); logs.append(f)
        p = subprocess.Popen(cmd, env=env, stdout=f, stderr=subprocess.STDOUT,
                             pass_fds=pass_fds, start_new_session=True)
        processes.append(p)
        return p
    def command(cmd, name, timeout=60):
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
        (out/(name+'.log')).write_text(r.stdout+r.stderr)
        assert r.returncode == 0, (name, r.returncode, r.stdout, r.stderr)
        return r.stdout
    try:
        auth = runtime/'auth'
        auth.write_bytes(struct.pack('!H', 65535) + b''.join(struct.pack('!H', len(v)) + v
            for v in (b'', b'', b'MIT-MAGIC-COOKIE-1', secrets.token_bytes(16))))
        env['XAUTHORITY'] = str(auth)
        read, write = os.pipe()
        try:
            start(['/usr/bin/Xvnc', '-displayfd', str(write), '-geometry',
                   '360x960' if narrow else '1280x960', '-depth', '24',
                   '-rfbport', '-1', '-rfbunixpath', str(runtime/'vnc'), '-localhost',
                   '-nolisten', 'unix', '-nolisten', 'local', '-listen', 'tcp', '-auth', str(auth), '-noreset'],
                  'xserver', (write,))
        finally:
            os.close(write)
        try:
            # Xvnc may write the number and newline separately. Closing the
            # pipe after only the digits can make its second write fail/EPIPE.
            data, deadline = b'', time.monotonic()+10
            while b'\n' not in data:
                remaining = deadline-time.monotonic()
                assert remaining > 0 and select.select([read], [], [], remaining)[0], 'Xvnc displayfd timeout'
                chunk = os.read(read, 32)
                assert chunk, 'Xvnc closed displayfd without a complete line'
                data += chunk
            number = data.decode().strip()
            assert number.isdecimal(), number
        finally:
            os.close(read)
        env['DISPLAY'] = '127.0.0.1:' + number
        result['display'] = env['DISPLAY']
        command(['xdpyinfo'], 'display')
        address = 'unix:path=' + str(runtime/'bus')
        cfg = runtime/'dbus.conf'
        cfg.write_text('<busconfig><type>session</type><listen>'+address+'</listen><auth>EXTERNAL</auth>'
            '<policy context="default"><allow send_destination="*"/>'
            '<allow receive_sender="*"/><allow own="*"/></policy></busconfig>')
        start(['dbus-daemon', '--nofork', '--config-file='+str(cfg)], 'dbus')
        until(lambda: (runtime/'bus').exists())
        env['DBUS_SESSION_BUS_ADDRESS'] = address
        wm = start(['xfwm4', '--compositor=off', '--sm-client-disable'], 'xfwm4')
        time.sleep(.8)
        assert wm.poll() is None, 'xfwm4 exited'
        # Both routes have a real stock panel available. All preload/registry
        # setup belongs to this fresh test session, never the user's settings.
        env['GSETTINGS_BACKEND'] = 'keyfile'
        components = runtime / ('r/components' if route == 'managed' else 'components')
        components.mkdir(parents=True)
        (components/'server-ime.xml').write_text("""<component>
<name>org.freedesktop.IBus.ServerIME</name><description>Feedback isolated product</description>
<exec>/bin/false</exec><version>test</version><author>platform</author><license>GPL-3.0-or-later</license>
<engines><engine><name>server-ime</name><longname>服务器输入法</longname><description>feedback</description>
<language>zh_CN</language><license>GPL-3.0-or-later</license><author>platform</author><layout>us</layout>
</engine></engines></component>""")
        env['IBUS_COMPONENT_PATH'] = str(components)
        command(['gsettings','set','org.freedesktop.ibus.general','preload-engines',"['server-ime']"], 'private-preload')
        command(['gsettings','set','org.freedesktop.ibus.general','engines-order',"['server-ime']"], 'private-order')
        settings_schemas = ('org.freedesktop.ibus.general', 'org.gnome.desktop.input-sources')
        def settings_snapshot(phase):
            return {schema: command(['gsettings', 'list-recursively', schema],
                                    phase+'-'+schema).strip() for schema in settings_schemas}
        settings_seeded = settings_snapshot('settings-seeded')
        if route == 'existing':
            env['IBUS_ADDRESS_FILE'] = str(runtime/'ibus-address')
            existing_bus=start(['ibus-daemon', '--single', '--panel=disable', '--config=disable',
                   '--emoji-extension=disable', '--cache=none', '--address=unix:dir='+str(runtime)], 'existing-ibus')
            until(lambda: (runtime/'ibus-address').exists())
            def bus_address():
                for line in (runtime/'ibus-address').read_text().splitlines():
                    if line.startswith('IBUS_ADDRESS='):
                        return line.partition('=')[2]
            env['IBUS_ADDRESS'] = until(bus_address)
            # Initialise the stock panel with a real registered engine. Retain
            # that panel and bus across a detach, then attach the product under
            # test. A panel launched without an available factory may stay alive
            # but fail to initialise its candidate window (not a useful check).
            command(common+['start'], 'register-for-stock-panel')
            panel = start(['/usr/libexec/ibus-ui-gtk3'], 'native-panel')
            time.sleep(.8)
            assert panel.poll() is None, 'Stock panel failed to initialise'
            command(common+['stop'], 'detach-before-check')
            assert panel.poll() is None and existing_bus.poll() is None
            result['stock_panel_started_before_product'] = True
        command(common+['start']+(['--managed-ibus'] if route=='managed' else []), 'start')
        from server_ime_product.supervisor import request
        running = request(runtime/'r', 'status')
        env.update(running['env'])
        save(out/'running.json', running)
        monitor = start(['dbus-monitor', '--address', env['IBUS_ADDRESS'],
                         "type='signal',interface='org.freedesktop.IBus.Engine'",
                         "type='method_call',interface='org.freedesktop.IBus.Panel'"], 'framework')
        if route == 'managed':
            panel = start(['/usr/libexec/ibus-ui-gtk3'], 'native-panel')
            time.sleep(.8)
        result['native_panel_pid'] = panel.pid
        result['native_panel_exit_before_apps'] = panel.poll()
        assert panel.poll() is None, 'Stock IBus panel failed to start'
        settings_before = settings_snapshot('settings-before-apps')
        # Stock ibus-ui-gtk3 records its version on first launch in the private
        # keyfile. Keep that setup observation; no other input setting may change.
        def without_panel_version(values):
            return {k: re.sub(r'^org.freedesktop.ibus.general version .*$', '', v,
                              flags=re.M) for k, v in values.items()}
        assert without_panel_version(settings_seeded) == without_panel_version(settings_before)
        command([sys.executable, '-B', str(SELF), '--session', 'baseline' if baseline else 'fixed'],
                'applications', 300)
        observations = json.loads((out/'observations.json').read_text())
        result['application_checks'] = sum('application' in row for row in observations)
        result['horizontal_checks'] = sum(row['check'].endswith('-horizontal-single-row')
                                          for row in observations)
        result['narrow_checks'] = sum(row['check'].startswith('narrow-') for row in observations)
        result['window_observations'] = sum(row['check'] == 'windows' for row in observations)
        result['window_tree_retries'] = sum(row['check'] == 'window-tree-query-error'
                                            for row in observations)
        if not baseline:
            if narrow:
                required = {
                    'narrow-nine-candidates-retained',
                    'narrow-page-all-ids-reachable',
                    'narrow-logical-pages-complete',
                    'narrow-scrolled-tail-mouse-full-text',
                    'narrow-scrolled-tail-digit-full-text',
                    'narrow-last-page-mouse-full-text',
                    'narrow-last-page-digit-full-text',
                    'narrow-short-page-range-roundtrip',
                    'narrow-focus-hides-and-rejects-stale-candidate',
                }
                covered = {row['check'] for row in observations
                           if row.get('application') == 'editor' and row.get('result') == 'PASS'
                           and row.get('fixture') is False}
                assert required <= covered, sorted(required - covered)
                pages = [row for row in observations if row['check'] == 'narrow-page-all-ids-reachable']
                coverage = next(row for row in observations if row['check'] == 'narrow-logical-pages-complete')
                visited = [candidate_id for page in pages for candidate_id in page['ids']]
                assert visited == coverage['all_ids'] == coverage['visited_ids'], coverage
                assert len(visited) == len(set(visited)) and len(pages) > 1, coverage
                result['viewport_coverage'] = dict(required_checks=sorted(required),
                    candidate_count=len(visited), page_sizes=[len(page['ids']) for page in pages],
                    all_ids_reachable_in_order=True, fixture=False)
                budget_checks = {row['check']: row for row in observations
                                 if row.get('result') == 'PASS' and row.get('fixture') is False}
                budget_evidence = []
                for page_size, max_visible in ((9, 3), (5, 1)):
                    label = f'narrow-budget-{page_size}-{max_visible}'
                    assert label+'-settings-saved' in budget_checks
                    assert label+'-paging-preserves-size' in budget_checks
                    assert label+'-short-page-range-roundtrip' in budget_checks
                    assert label+'-highlight-after-manual-scroll' in budget_checks
                    for page in (0, 1):
                        for method in ('mouse', 'digit'):
                            row = budget_checks[label+f'-page-{page}-'+method+'-full-text']
                            assert row['ids'] == row['visited_ids'] and len(row['ids']) == page_size, row
                            assert row['candidate_id'] == row['ids'][-1], row
                    saved = budget_checks[label+'-settings-saved']
                    highlight = budget_checks[label+'-highlight-after-manual-scroll']
                    short = budget_checks[label+'-short-page-range-roundtrip']
                    budget_evidence.append(dict(page_size=page_size, max_visible=max_visible,
                        saved_revision=saved['revision'],
                        highlight_scroll_before=highlight['before']['metrics']['scroll']['value'],
                        highlight_scroll_after=highlight['after']['metrics']['scroll']['value'],
                        short_page_count=short['short_page_count'],
                        full_page_width=short['full']['metrics']['content_natural_width'],
                        short_page_width=short['short']['metrics']['content_natural_width'],
                        application_readbacks=[budget_checks[label+f'-page-{page}-'+method+'-full-text']['check']
                                               for page in (0, 1) for method in ('mouse', 'digit')]))
                result['viewport_budget_coverage'] = dict(
                    settings_saved=True, fixture=False, combinations=[[9, 3], [5, 1]],
                    pages_per_combination=2, selection_methods=['mouse', 'digit'],
                    full_page_ids_reachable=True, evidence=budget_evidence)
            else:
                assert result['horizontal_checks'] == 8, result
            result['framework_signals'] = json.loads((out/'framework-summary.json').read_text())
        assert monitor.poll() is None
        assert panel.poll() is None, 'Product stopped the stock panel'
        command(common+['stop'], 'stop')
        if route == 'existing':
            assert panel.poll() is None, 'Product stop killed existing stock panel'
            assert existing_bus.poll() is None, 'Product stop killed existing IBus daemon'
            preload=command(['gsettings','get','org.freedesktop.ibus.general','preload-engines'],'private-preload-after')
            order=command(['gsettings','get','org.freedesktop.ibus.general','engines-order'],'private-order-after')
            assert preload.strip()==order.strip()=="['server-ime']",(preload,order)
            result['existing_panel_and_bus_survive_product_stop']=True
            result['private_input_source_settings_preserved']=True
            if not baseline:
                command([sys.executable, '-B', str(SELF), '--native-adapter'], 'native-adapter')
        settings_after = settings_snapshot('settings-after')
        # The private keyfile also holds gedit's preferences. Compare the IBus
        # and input-source schemas, not unrelated editor window/preferences data.
        assert settings_before == settings_after, (settings_before, settings_after)
        result['seeded_private_settings_unchanged'] = True
        save(out/'private-settings.json', dict(seeded=settings_seeded, before=settings_before, after=settings_after,
             setup_note='The stock panel writes its own version at first launch; all other seeded input settings are identical.'))
        result['result'] = 'PASS'
    except Exception:
        result['error'] = traceback.format_exc()
        print(result['error'], flush=True)
    finally:
        try:
            command(common+['stop'], 'cleanup-stop', 25)
        except Exception as exc:
            result['cleanup_stop_error'] = str(exc)
        if (runtime/'r').exists():
            (out/'product-state').mkdir(exist_ok=True)
            for item in (runtime/'r').iterdir():
                if item.is_file():shutil.copyfile(item,out/'product-state'/item.name)
        for p in reversed(processes):
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(4)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL); p.wait(4)
        for f in logs:
            f.close()
        result['reaped'] = [dict(pid=p.pid, rc=p.returncode) for p in processes]
        save(out/'summary.json', result)
        shutil.rmtree(runtime)
    print(route, result['result'], out, flush=True)
    return result['result'] == 'PASS'


def session(baseline):
    from x11 import pump, wait_for, screenshot
    from xinput import X
    from gi.repository import Gtk, Gio
    from server_ime.ui_client import StateClient
    from server_ime_product.rpc import Client
    out, runtime = Path(os.environ['FEEDBACK_OUT']), Path(os.environ['FEEDBACK_RUNTIME'])
    assert os.environ['SERVER_IME_ISOLATED'] == '1'
    x, states, rpc = X(), StateClient(), Client()
    trace, observations, processes, logs = [], [], [], []
    states.subscribe(trace.append)
    x.x11.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    def start(cmd, name):
        f = (out/(name+'.log')).open('w'); logs.append(f)
        p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(p); return p
    def windows():
        # Chrome can destroy a startup window during xwininfo's recursive walk.
        # Retry only that X11 race, retain each error, and require a complete
        # successful tree. A partial tree cannot prove the absence of a popup.
        for attempt in range(1, 6):
            result = subprocess.run(['xwininfo', '-root', '-tree'], text=True,
                                    capture_output=True, timeout=5)
            if result.returncode == 0:
                return result.stdout
            retry = attempt < 5 and bool(re.search(r'Bad (?:Window|Drawable)', result.stderr))
            observations.append(dict(check='window-tree-query-error', attempt=attempt,
                                     retry=retry, stderr=result.stderr))
            if not retry:
                result.check_returncode()
            pump(.05)
    def focus(title):
        def find():
            return next((int(w,16) for w,n in re.findall(r'(0x[0-9a-f]+) "([^\"]*)"',windows()) if title in n),None)
        wid = wait_for(find,25)
        if not wid:
            (out/'missing-window-tree.txt').write_text(windows())
            screenshot(out/'missing-window.png')
        assert wid, title
        x.x11.XRaiseWindow(x.display,wid)
        x.x11.XSetInputFocus(x.display,wid,2,0);x.x11.XSync(x.display,False);pump(.5)
        return wid
    def snap():
        return next((s for cid in states.list_contexts() if (s:=states.get_state(cid))['focused'] and s['enabled']),None)
    def geometry():
        reply=rpc.connection.call_sync('org.freedesktop.IBus.ServerIME.Panel',
            '/org/freedesktop/IBus/ServerIME/Panel','org.superpartner.ServerIME.Panel1','Geometry',
            None,None,Gio.DBusCallFlags.NONE,3000,None)
        return json.loads(reply.unpack()[0])
    def capture(name):
        pump(.2)
        tree=windows()
        (out/(name+'-windows.txt')).write_text(tree)
        mapped=[]
        for wid,title,w,h in re.findall(r'(0x[0-9a-f]+) "(server-ime|ibus-ui-gtk3)".*?\s(\d+)x(\d+)\+',tree):
            if int(w)<30 or int(h)<30:
                continue  # stock tray/status icons and GTK leader windows
            detail=subprocess.check_output(['xwininfo','-id',wid],text=True)
            (out/(name+'-'+wid+'.txt')).write_text(detail)
            if 'Map State: IsViewable' in detail:
                mapped.append(dict(xid=wid,title=title,width=int(w),height=int(h)))
        screenshot(out/(name+'.png'))
        state,geom=snap(),geometry()
        save(out/(name+'.json'), dict(state=state, geometry=geom,visible_candidate_windows=mapped))
        observations.append(dict(check='windows',name=name,windows=mapped,geometry=geom))
        if not baseline:
            assert not any(w['title']=='ibus-ui-gtk3' for w in mapped), mapped
            assert len(mapped)==(1 if geom['panel'] else 0), (mapped,geom)
            if name == 'idle':
                assert not mapped and not geom['panel'], (mapped, geom)
                assert state and not state['candidate_visible'] and not state['preedit']['visible'], state
        elif name=='composition':
            assert {w['title'] for w in mapped}=={'server-ime','ibus-ui-gtk3'}, mapped
    def ctrl(key):
        x.press(0xffe3,True);x.key(key);x.press(0xffe3,False);pump(.2)
    try:
        document=runtime/'Feedback-editor.txt';document.write_text('')
        start(['gedit','--standalone','--new-window',str(document)],'gedit')
        focus('Feedback-editor.txt')
        assert wait_for(snap,5)
        capture('idle')
        x.type_text('nihao');assert wait_for(lambda:snap()['candidate_visible'],5)
        capture('composition')
        native=(out/'framework.log').read_text()
        lookup=re.findall(r'member=UpdateLookupTable\n(.*?)(?=\n(?:signal|method call)|\Z)',native,re.S)
        auxiliary=re.findall(r'member=UpdateAuxiliaryText\n(.*?)(?=\n(?:signal|method call)|\Z)',native,re.S)
        flags=dict(lookup_visible=any(v.rstrip().endswith('boolean true') for v in lookup),
                   auxiliary_visible=any(v.rstrip().endswith('boolean true') for v in auxiliary))
        assert flags['lookup_visible']==baseline and flags['auxiliary_visible']==baseline, flags
        assert geometry()['panel']
        observations.append(dict(check='native-custom-channels',baseline=baseline,**flags))
        if baseline:
            x.key('space');ctrl('s')
            assert wait_for(lambda:document.read_text()=='你好\n',4),document.read_text()
            capture('after-commit')
            observations.append(dict(check='original-app-commit',actual=document.read_text(),
                diagnosis_scope='Product duplicate publishing reproduced in isolated session only; user app/style unknown'))
        else:
            checks = narrow_checks if os.environ.get('FEEDBACK_NARROW') == '1' else application_checks
            checks(x, states, rpc, snap, geometry, capture, ctrl, focus, start,
                   document, out, runtime, observations)
            ids={w['xid'] for o in observations for w in o.get('windows',[]) if w['title']=='server-ime'}
            assert len(ids)==1,ids
            observations.append(dict(check='single-custom-popup-through-compose-page-select',xids=sorted(ids)))
            pump(.2)
            raw=(out/'framework.log').read_text()
            counts={}
            for member in ('UpdateLookupTable','UpdateAuxiliaryText'):
                blocks=re.findall(r'member='+member+r'\n(.*?)(?=\n(?:signal|method call)|\Z)',raw,re.S)
                assert blocks,member
                assert all(b.rstrip().endswith('boolean false') for b in blocks),member
                counts[member]=dict(count=len(blocks),visible_true=0)
            assert 'member=HideLookupTable' in raw and 'member=HideAuxiliaryText' in raw
            preedit=re.findall(r'member=UpdatePreeditText(?:WithMode)?\n(.*?)(?=\n(?:signal|method call)|\Z)',raw,re.S)
            assert any('boolean true' in b for b in preedit), 'No real application preedit signals'
            counts['visible_application_preedit']=sum('boolean true' in b for b in preedit)
            counts['scope'] = 'Product engine signals only; application preedit is expected'
            save(out/'framework-summary.json',counts)
        return 0
    finally:
        save(out/'state-events.json',trace)
        save(out/'observations.json',observations)
        for p in reversed(processes):
            if p.poll() is None:
                os.killpg(p.pid,signal.SIGTERM)
                try:p.wait(4)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait(4)
        for f in logs:f.close()
        states.close();x.close()


def application_checks(x, states, rpc, snap, geometry, capture, ctrl, focus, start,
                       document, out, runtime, observations):
    from x11 import pump, wait_for
    def record(app, name, **data):
        observations.append(dict(application=app,check=name,result='PASS',**data))
        save(out/'observations.json',observations)
        print(app,name,'PASS',flush=True)
    def chinese(raw='nihao'):
        assert snap()['mode']=='zh'
        x.type_text(raw)
        s=wait_for(lambda: (s if (s:=snap()) and s['candidate_visible'] else None),4)
        assert s and s['preedit']['visible'] and not s['error'],s
        assert s['candidate_presentation']=='custom'
        assert not {'next_word','candidate_kind'} & s.keys(),s
        assert wait_for(lambda:geometry()['panel'],3)
        return s
    def idle():
        assert wait_for(lambda:not geometry()['panel'],3),geometry()
        s=snap()
        assert not s or (not s['candidate_visible'] and not s['preedit']['visible']),s
    def stale(s):
        assert not states.select_candidate(s,s['candidates'][0]['id'])
    def horizontal(app, name, s):
        page = s['candidates'][s['page_start']:s['page_start']+s['page_size']]
        ids = [c['id'] for c in page]
        def settled():
            g = geometry()
            rows = g['rows']
            if not g['panel'] or [r['id'] for r in rows] != ids:
                return None
            if len(rows) < 2 or len({r['y'] for r in rows}) != 1:
                return None
            if not all(a['x'] + a['w'] <= b['x'] for a,b in zip(rows,rows[1:])):
                return None
            return g
        g = wait_for(settled, 4)
        assert g, (name, geometry(), s)
        assert g['context_id'] == s['context_id'] and g['candidate_presentation'] == 'custom', g
        assert g['metrics']['layout'] == 'horizontal', g
        assert g['metrics']['dropped_for_width'] == [], g
        assert g['metrics']['ids'] == g['metrics']['in_view'] == ids, g
        assert all(r['in_view'] for r in g['rows']), g
        assert not g['metrics']['scroll']['scrollbar_visible'], g
        assert [r['index'] for r in g['rows']] == list(range(s['page_start'], s['page_start']+len(page))), g
        from gi.repository import Gdk
        screen = Gdk.Screen.get_default()
        p = g['panel']
        assert p['w'] <= g['metrics']['width_limit'], g
        assert 0 <= p['x'] and p['x']+p['w'] <= screen.get_width(), g
        assert 0 <= p['y'] and p['y']+p['h'] <= screen.get_height(), g
        assert all(p['x'] <= r['x'] and r['x']+r['w'] <= p['x']+p['w']
                   and p['y'] <= r['y'] and r['y']+r['h'] <= p['y']+p['h']
                   for r in g['rows']), g
        record(app, name+'-horizontal-single-row', page_start=s['page_start'],
               candidate_ids=ids, geometry=g)
        return g
    def flow(app, readback):
        expected=''
        s=chinese();capture(app+'-composition')
        assert s['candidates'][0]['text']=='你好',s
        row=horizontal(app,'default-mouse',s)['rows'][0]
        x.click(row['x']+row['w']//2,row['y']+row['h']//2)
        expected+='你好';idle();stale(s);readback(expected);capture(app+'-after-mouse')
        record(app,'mouse-select-once-and-idle-hidden',actual=expected)
        s=chinese('ni');horizontal(app,'default-digit',s)
        chosen=s['candidates'][1];x.key('2');expected+=chosen['text']
        idle();stale(s);readback(expected);capture(app+'-after-default-digit')
        record(app,'default-digit-selects-corresponding-text',actual=expected,
               candidate_id=chosen['id'],selected_text=chosen['text'])
        before=chinese('ni');x.key('Page_Down');after=snap()
        assert after['page_start']>before['page_start'],after
        g=horizontal(app,'page-mouse',after);capture(app+'-page-mouse')
        chosen=after['candidates'][after['page_start']+1];row=g['rows'][1]
        assert row['id']==chosen['id']
        x.click(row['x']+row['w']//2,row['y']+row['h']//2);expected+=chosen['text']
        idle();stale(after);readback(expected);capture(app+'-after-page-mouse')
        record(app,'page-mouse-selects-corresponding-text',actual=expected,
               candidate_id=chosen['id'],selected_text=chosen['text'],page_start=after['page_start'])
        before=chinese('ni');x.key('Page_Down');after=snap()
        assert after['page_start']>before['page_start'],after
        assert wait_for(lambda:geometry()['rows'] and geometry()['rows'][0]['id']==
                        after['candidates'][after['page_start']]['id'],3)
        horizontal(app,'page-digit',after)
        capture(app+'-page')
        text=after['candidates'][after['page_start']+1]['text'];x.key('2');expected+=text
        idle();stale(after);readback(expected)
        record(app,'page-and-digit-select-once',actual=expected,page_start=after['page_start'])
        chinese('nihao');x.key('space');expected+='你好';idle();readback(expected)
        x.key('space');expected+=' '
        chinese('raw');x.key('Return');expected+='raw';idle();readback(expected)
        x.key('Return');expected+='\n';readback(expected)
        record(app,'space-selects-return-commits-raw-idle-keys-pass',actual=expected)
        original=rpc.call('get')['settings']
        try:
            for enabled,marks in [(True,'，。？！'),(False,',.?!')]:
                settings=rpc.call('get')['settings'];settings['punctuation']['chinese']=enabled
                rpc.call('apply',settings=settings)
                for raw,text in zip(',.?!',marks):
                    x.type_text('nihao'+raw);expected+='你好'+text;idle()
            readback(expected)
        finally:
            rpc.call('apply',settings=original)
        record(app,'direct-pinyin-punctuation-on-and-off',actual=expected)
        for raw,text in [('nihao@example.org','nihao@example.org'),
                         ('https://example.org/a?v=2','https://example.org/a?v=2'),
                         ('v2.0','v2.0'),('AbC123','AbC123'),('nihaoAPI2shijie','你好API2世界')]:
            x.key('space');expected+=' '
            s=chinese(raw);assert s['candidates'][0]['text']==text,s
            x.key('space');expected+=text;idle()
        x.key('space');expected+=' '
        chinese('abc');x.key('Num_Lock');x.key('KP_1');x.key('Num_Lock');x.type_text('23')
        assert snap()['preedit']['text']=='abc123',snap()
        x.key('Return');expected+='abc123';idle();readback(expected)
        record(app,'address-mixed-keypad-digit-regression',actual=expected)
        chinese('nihaoAPI2shijix');old=snap();x.key('BackSpace');x.key('e')
        x.key('Home');x.key('Delete');x.key('n');x.key('End');x.key('Left');x.key('Right')
        assert wait_for(lambda:snap()['candidates'][0]['text']=='你好API2世界',3),snap()
        stale(old);x.key('space');expected+='你好API2世界';idle();readback(expected)
        record(app,'composition-edit-and-stale-revision',actual=expected)
        chinese('nihao')
        i=next(i for i,c in enumerate(snap()['candidates']) if c['text']=='你')
        for _ in range(i):x.key('Down')
        x.key('space');expected+='你'
        assert snap()['preedit']['visible'] and snap()['preedit']['text']=='hao',snap()
        capture(app+'-remaining-suffix')
        i=next(i for i,c in enumerate(snap()['candidates']) if c['text']=='好')
        for _ in range(i):x.key('Down')
        x.key('space');expected+='好';idle();readback(expected)
        record(app,'partial-selection-keeps-existing-suffix',actual=expected)
        old=chinese('ni');x.key('Escape');idle();stale(old);readback(expected)
        old=chinese('ni');ctrl('space');idle();stale(old);assert snap()['mode']=='en'
        x.type_text('ok');expected+='ok';ctrl('space');idle();readback(expected)
        record(app,'escape-and-mode-switch-cancel-composition',actual=expected)
        return expected
    def editor_read(expected):
        ctrl('s')
        # gedit appends its implicit trailing newline to the saved file.
        target=expected+'\n'
        assert wait_for(lambda:document.read_text()==target,4),(repr(document.read_text()),repr(target))
        (out/'editor-actual.txt').write_text(document.read_text())
    x.key('Escape');ctrl('a');x.key('BackSpace');idle()
    expected_editor=flow('editor',editor_read)
    old=chinese('ni')  # An active composition must not cross application focus.
    chrome=ROOT/'integration/browser-runtime/chrome-linux64/chrome'
    assert chrome.is_file(), 'Real browser runtime missing'
    events=[]
    page=b'''<!doctype html><meta charset="utf-8"><title>Feedback-browser</title>
<style>body{margin:60px}textarea,input{display:block;width:800px;font:22px sans-serif;margin:20px}</style>
<textarea id="a" rows="5" autofocus></textarea><input id="b"><input id="p" type="password">
<script>let seq=0;for(let e of document.querySelectorAll('input,textarea'))for(let type of
['keydown','keyup','beforeinput','input','compositionstart','compositionupdate','compositionend','focus','blur'])
e.addEventListener(type,ev=>fetch('/event',{method:'POST',body:JSON.stringify({seq:++seq,id:e.id,type,
value:e.value,data:ev.data||'',key:ev.key||'',isTrusted:ev.isTrusted,isComposing:ev.isComposing||false})}));</script>'''
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
            self.end_headers();self.wfile.write(page)
        def do_POST(self):
            events.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(204);self.end_headers()
    httpd=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
    save(out/'browser-binary.json',dict(path=str(chrome),sha256=hashlib.sha256(chrome.read_bytes()).hexdigest(),
        version=subprocess.check_output([str(chrome),'--version'],text=True).strip()))
    (out/'browser-page.html').write_bytes(page)
    def value(field):
        return next((e['value'] for e in sorted(events,key=lambda e:e['seq'],reverse=True)
                     if e['id']==field and e['type']=='input'),'')
    try:
        start([str(chrome),'--user-data-dir='+str(runtime/'profile'),'--no-first-run','--no-default-browser-check',
               '--ozone-platform=x11','--window-size=1100,850','--window-position=30,40',
               'http://127.0.0.1:'+str(httpd.server_port)],'chrome')
        focus('Feedback-browser')
        assert wait_for(lambda:any(e['id']=='a' and e['type']=='focus' for e in events),6),events[-5:]
        idle();stale(old)
        assert value('a')==''
        record('editor-browser','focus-transfer-no-composition-leak',browser_value=value('a'))
        settings=rpc.call('get')['settings'];settings['input']['learning']=True
        assert rpc.call('apply',settings=settings)['engine_config']['learning']
        def browser_read(expected):
            assert wait_for(lambda:value('a')==expected,5),(repr(value('a')),repr(expected),events[-5:])
            (out/'browser-actual.txt').write_text(value('a'))
        expected_browser=flow('browser',browser_read)
        old=chinese('ni');x.key('Tab')
        assert wait_for(lambda:any(e['id']=='b' and e['type']=='focus' for e in events),4)
        idle();stale(old);browser_read(expected_browser)
        chinese('nihao');x.key('space')
        assert wait_for(lambda:value('b')=='你好',5)
        record('browser','field-focus-cancels-composition',a=value('a'),b=value('b'))
        old=chinese('ni');x.key('Tab')
        assert wait_for(lambda:any(e['id']=='p' and e['type']=='focus' for e in events),4)
        idle();stale(old)
        start_seq=max(e['seq'] for e in events)
        learning=runtime/'personal/learning/words.jsonl'
        before=learning.read_bytes() if learning.exists() else b''
        assert before, 'Ordinary commits must exercise enabled learning before password input'
        x.type_text('AbC123@Example.org');pump(.3)
        assert value('p')=='AbC123@Example.org',events[-5:]
        assert not any(e['type'].startswith('composition') for e in events if e['seq']>start_seq)
        assert before==(learning.read_bytes() if learning.exists() else b'')
        idle();capture('browser-password')
        record('browser','password-direct-no-popup-no-learning',synthetic_value=value('p'),
               handling='Observed browser direct entry; no IBus password-purpose assumption')
        preedit=[e for e in events if e['type']=='compositionupdate' and e['data']]
        assert any(e['data']=='nihao' for e in preedit),preedit
        assert all(e['isTrusted'] for e in events if e['type']!='compositionend')
        record('browser','normal-in-application-preedit',composition_events=len(preedit),
               distinction='DOM composition and underlined application text are expected, not a second candidate popup')
        focus('Feedback-editor.txt');editor_read(expected_editor)
        capture('final-idle');idle()
    finally:
        save(out/'browser-events.json',sorted(events,key=lambda e:e['seq']))
        httpd.shutdown();httpd.server_close();thread.join(2)


def narrow_checks(x, states, rpc, snap, geometry, capture, ctrl, focus, start,
                  document, out, runtime, observations):
    """Real 360px X screen, 300% font and real engine IDs; no fixture panel."""
    from x11 import pump, wait_for
    from gi.repository import Gdk
    assert Gdk.Screen.get_default().get_width() == 360
    original = rpc.call('get')['settings']
    expected = ''
    active_page_size, active_max_visible = 9, 9

    def record(name, **data):
        observations.append(dict(application='editor', check='narrow-'+name, result='PASS',
                                 fixture=False, **data))
        save(out/'observations.json', observations)
        print('editor narrow-'+name, 'PASS', flush=True)

    def idle():
        assert wait_for(lambda: not geometry()['panel'], 3), geometry()
        s = snap()
        assert not s or not (s['candidate_visible'] or s['preedit']['visible']), s

    def readback():
        ctrl('s')
        assert wait_for(lambda: document.read_text() == expected+'\n', 4), (document.read_text(), expected)
        (out/'editor-actual.txt').write_text(document.read_text())

    def page_geometry(s, revealed=False):
        page = s['candidates'][s['page_start']:s['page_start']+s['page_size']]
        ids = [c['id'] for c in page]
        def settled():
            g = geometry()
            if (g['panel'] and g.get('revision') == s['revision'] and
                    [r['id'] for r in g['rows']] == ids and
                    [r['index'] for r in g['rows'] if r['selected']] == [s['selected_index']] and
                    len({r['y'] for r in g['rows']}) == 1 and
                    (not revealed or all(r['in_view'] for r in g['rows'] if r['selected'])) and
                    all(a['x']+a['w'] <= b['x'] for a, b in zip(g['rows'], g['rows'][1:]))):
                return g
        g = wait_for(settled, 4)
        assert g, (s, geometry())
        p, m = g['panel'], g['metrics']
        assert g['candidate_presentation'] == 'custom' and g['context_id'] == s['context_id'], g
        assert not s['deterministic'] and s['preedit']['visible'] and not s['error'], s
        assert m['layout'] == 'horizontal' and m['font_scale'] == 3.0 and m['screen'] == [360, 960], m
        assert m['ids'] == ids and m['dropped_for_width'] == [], m
        assert [r['index'] for r in g['rows']] == list(range(s['page_start'], s['page_start']+len(page))), g
        assert g['page_start'] == s['page_start'] and g['page_size'] == s['page_size'] == active_page_size, g
        assert m['page_size'] == active_page_size and m['max_visible'] == active_max_visible, m
        assert p['w'] <= m['width_limit'] <= 344, g
        assert 0 <= p['x'] and p['x']+p['w'] <= 360 and 0 <= p['y'] and p['y']+p['h'] <= 960, g
        viewport = m['viewport']
        assert viewport and p['x'] <= viewport['x'] and viewport['x']+viewport['w'] <= p['x']+p['w'], g
        for row in g['rows']:
            assert row['text_w'] > 0, row
            if row['in_view']:
                assert viewport['x']-1 <= row['x'] and row['x']+row['w'] <= viewport['x']+viewport['w']+1, g
        if m['scroll']['scrollable']:
            bar = m['scrollbar']
            assert bar and bar['w'] > 30 and bar['h'] > 0, g
            assert p['x'] <= bar['x'] and bar['x']+bar['w'] <= p['x']+p['w'], g
        return g

    def compose(raw='ni'):
        x.type_text(raw)
        s = wait_for(lambda: (s if (s := snap()) and s['candidate_visible'] else None), 4)
        assert s and s['page_start'] == 0 and len(s['candidates']) > 9, s
        page_geometry(s, revealed=True)
        return s

    def scroll_end(s):
        # Click the real visible scrollbar trough; no RPC to move the viewport.
        samples = [page_geometry(s)]
        for _ in range(15):
            g = samples[-1]
            if g['rows'][-1]['in_view']:
                break
            bar = g['metrics']['scrollbar']
            assert bar, g
            previous = g['metrics']['scroll']['value']
            x.click(bar['x']+bar['w']-3, bar['y']+bar['h']//2)
            assert wait_for(lambda: geometry()['metrics']['scroll']['value'] > previous, 3), geometry()
            fresh = snap()
            assert fresh['revision'] == s['revision'] and fresh['selected_index'] == s['selected_index'], (s, fresh)
            samples.append(page_geometry(s))
        assert samples[-1]['rows'][-1]['in_view'], samples
        return samples

    def chosen_click(s):
        g = scroll_end(s)[-1]
        row = g['rows'][-1]
        chosen = s['candidates'][row['index']]
        assert row['id'] == chosen['id'] and row['in_view'], (row, chosen)
        x.click(row['x']+row['w']//2, row['y']+row['h']//2)
        idle()
        assert not states.select_candidate(s, chosen['id'])
        return chosen, g

    def short_page_roundtrip(label):
        # Use real hao candidates and actual page keys. Start on the full page
        # immediately before the short page with its scrollbar at the tail.
        s = compose('hao')
        all_ids = [c['id'] for c in s['candidates']]
        tail_count = len(all_ids) % active_page_size
        assert 0 < tail_count < active_page_size, s
        last_start = len(all_ids)-tail_count
        while s['page_start'] < last_start-active_page_size:
            x.key('Page_Down'); s = snap()
        full = scroll_end(s)[-1]
        assert len(full['rows']) == active_page_size
        x.key('Page_Down'); short_state = snap()
        assert short_state['page_start'] == last_start
        short = page_geometry(short_state, revealed=True)
        assert len(short['rows']) == tail_count
        assert short['metrics']['ids'] == all_ids[last_start:]
        for field in ('content_natural_width',):
            assert short['metrics'][field] < full['metrics'][field], (full, short)
        assert short['metrics']['scroll']['upper'] < full['metrics']['scroll']['upper'], (full, short)
        end = scroll_end(short_state)[-1]
        scroll = end['metrics']['scroll']
        assert scroll['upper'] == max(scroll['page_size'], end['metrics']['content_natural_width']), end
        assert 0 <= scroll['value'] <= max(0, scroll['upper']-scroll['page_size']), end
        assert end['rows'][-1]['in_view'] and end['metrics']['in_view'], end
        capture('narrow-'+label+'-short-page-end')
        x.key('Page_Up'); returned_state = snap()
        returned = page_geometry(returned_state, revealed=True)
        assert returned_state['page_start'] == last_start-active_page_size
        assert [c['id'] for c in returned_state['candidates']] == all_ids
        assert returned['metrics']['ids'] == full['metrics']['ids']
        assert returned['rows'][0]['selected'] and returned['rows'][0]['in_view'], returned
        assert returned['metrics']['content_natural_width'] == full['metrics']['content_natural_width']
        assert returned['metrics']['scroll']['upper'] == full['metrics']['scroll']['upper']
        record(label+'short-page-range-roundtrip', page_size=active_page_size,
               max_visible=active_max_visible, short_page_count=tail_count,
               full=full, short=short, end=end, returned=returned)
        x.key('Escape'); idle()

    try:
        x.key('Escape'); ctrl('a'); x.key('BackSpace'); idle()
        settings = rpc.call('get')['settings']
        settings['input'].update(page_size=9, learning=False)
        settings['panel'].update(font_scale=3.0, max_visible=9, layout='horizontal')
        view = rpc.call('apply', settings=settings)
        assert view['engine_config']['page_size'] == 9
        s = compose(); g = page_geometry(s)
        assert len(g['rows']) == 9 and g['metrics']['scroll']['scrollable'], g
        assert g['rows'][0]['in_view'] and not g['rows'][-1]['in_view'], g
        assert g['anchored'] and g['cursor_rect'], g
        capture('narrow-first-page')
        record('nine-candidates-retained', candidate_count=len(s['candidates']), geometry=g)

        all_ids = [c['id'] for c in s['candidates']]
        seen, pages = [], []
        while True:
            s = snap(); start_index = s['page_start']
            ids = [c['id'] for c in s['candidates'][start_index:start_index+9]]
            samples = scroll_end(s)
            capture('narrow-page-'+str(start_index)+'-scroll-end')
            # Return to the first highlight by a real keyboard event, then
            # visit every index, including candidates straddling trough steps.
            if s['selected_index'] == 0:
                x.key('Up')
            while snap()['selected_index'] > start_index:
                x.key('Up')
            # On later pages the first item is still selected after scrolling.
            # Move to item 2 then back so automatic reveal must bring item 1 in.
            if start_index and len(ids) > 1:
                x.key('Down'); x.key('Up')
            visited = []
            for offset, candidate_id in enumerate(ids):
                if offset: x.key('Down')
                active = snap()
                assert active['selected_index'] == start_index+offset and active['page_start'] == start_index, active
                g = page_geometry(active, revealed=True)
                assert g['rows'][offset]['id'] == candidate_id and g['rows'][offset]['in_view'], g
                visited.append(dict(id=candidate_id, index=start_index+offset, geometry=g))
            assert [r['id'] for r in visited] == ids
            pages.append(dict(page_start=start_index, ids=ids, scrollbar_samples=samples, highlights=visited))
            seen.extend(ids)
            record('page-all-ids-reachable', page_start=start_index, ids=ids, details=pages[-1])
            if start_index+len(ids) == len(all_ids):
                break
            for _ in range(len(ids)-1): x.key('Up')
            returned = page_geometry(snap(), revealed=True)
            assert returned['rows'][0]['selected'] and returned['rows'][0]['in_view'], returned
            pages[-1]['return_to_first'] = returned
            previous = snap(); x.key('Page_Down'); current = snap()
            assert current['page_start'] == start_index+9, (previous, current)
            assert [c['id'] for c in current['candidates']] == all_ids, current
        assert seen == all_ids and len(set(seen)) == len(all_ids)
        assert len(pages) > 1 and 0 < len(pages[-1]['ids']) <= 9
        # Page_Up is still logical paging, never horizontal scrolling.
        last = snap(); x.key('Page_Up'); previous = snap()
        assert previous['page_start'] == last['page_start']-9, (previous, last)
        record('logical-pages-complete', all_ids=all_ids, visited_ids=seen,
               page_sizes=[len(p['ids']) for p in pages], last_page=last['page_start'])
        x.key('Escape'); idle()

        s = compose(); samples = scroll_end(s); capture('narrow-hidden-tail-before-mouse')
        chosen, g = chosen_click(s); expected += chosen['text']; readback()
        record('scrolled-tail-mouse-full-text', candidate_id=chosen['id'], selected_text=chosen['text'],
               actual=expected, geometry=g, scrollbar_samples=samples)
        s = compose(); samples = scroll_end(s); chosen = s['candidates'][8]
        x.key('9'); expected += chosen['text']; idle(); readback()
        record('scrolled-tail-digit-full-text', candidate_id=chosen['id'], selected_text=chosen['text'],
               actual=expected, geometry=samples[-1])

        short_page_roundtrip('')
        for selection in ('mouse', 'digit'):
            # hao has a partial final page in the pinned real dictionary. This
            # also checks digit offsets when the final page has fewer than nine.
            s = compose('hao')
            assert 0 < len(s['candidates']) % 9 < 9, s
            while s['page_start']+9 < len(s['candidates']):
                x.key('Page_Down'); s = snap()
            samples = scroll_end(s); capture('narrow-last-page-'+selection)
            if selection == 'mouse':
                chosen, g = chosen_click(s)
            else:
                chosen = s['candidates'][-1]; g = samples[-1]
                offset = len(s['candidates'])-s['page_start']
                assert 1 <= offset <= 9
                x.key(str(offset)); idle()
            expected += chosen['text']; readback()
            record('last-page-'+selection+'-full-text', candidate_id=chosen['id'],
                   selected_text=chosen['text'], actual=expected, geometry=g,
                   page_size=len(s['candidates'])-s['page_start'])

        # Save through the same product transaction used by SettingsWindow.
        # A viewport budget must not truncate the logical page or renumber it.
        for active_page_size, active_max_visible in ((9, 3), (5, 1)):
            label = f'budget-{active_page_size}-{active_max_visible}'
            settings = rpc.call('get')['settings']
            settings['input']['page_size'] = active_page_size
            settings['panel']['max_visible'] = active_max_visible
            view = rpc.call('apply', settings=settings)
            persisted = json.loads(Path(view['config_path']).read_text())
            assert persisted == view['settings'] == rpc.call('get')['settings'], view
            assert view['engine_config']['page_size'] == active_page_size, view
            assert persisted['panel']['max_visible'] == active_max_visible, persisted
            assert wait_for(lambda: geometry()['settings_revision'] == view['revision'], 4), geometry()
            record(label+'-settings-saved', page_size=active_page_size,
                   max_visible=active_max_visible, revision=view['revision'],
                   persisted_settings=persisted)
            # No reveal RPC: a real keyboard change must recover the highlight
            # after the user has manually moved the scrollbar to the tail.
            s = compose(); before = scroll_end(s)[-1]
            target = active_page_size//2
            for _ in range(target): x.key('Down')
            current = snap(); after = page_geometry(current, revealed=True)
            assert current['selected_index'] == target
            assert after['rows'][target]['in_view'] and after['rows'][target]['selected'], after
            assert after['metrics']['scroll']['value'] < before['metrics']['scroll']['value'], (before, after)
            record(label+'-highlight-after-manual-scroll', target=target, before=before, after=after)
            x.key('Escape'); idle()
            short_page_roundtrip(label+'-')
            for page_number in (0, 1):
                for selection in ('mouse', 'digit'):
                    s = compose()
                    if page_number:
                        original_ids = [c['id'] for c in s['candidates']]
                        x.key('Page_Down'); s = snap()
                        assert s['page_start'] == active_page_size, s
                        assert [c['id'] for c in s['candidates']] == original_ids, s
                    g = page_geometry(s, revealed=True)
                    ids = [c['id'] for c in s['candidates'][s['page_start']:s['page_start']+active_page_size]]
                    assert len(g['rows']) == len(ids) == active_page_size, g
                    assert g['metrics']['scroll']['scrollable'] and not g['rows'][-1]['in_view'], g
                    # Every ID is reached with real key events; wait for GTK's
                    # deferred layout before asserting highlight visibility.
                    visited = []
                    for offset, candidate_id in enumerate(ids):
                        if offset: x.key('Down')
                        current = snap()
                        assert current['page_start'] == s['page_start'], current
                        assert current['selected_index'] == s['page_start']+offset, current
                        g = page_geometry(current, revealed=True)
                        assert g['rows'][offset]['id'] == candidate_id and g['rows'][offset]['in_view'], g
                        visited.append(candidate_id)
                    assert visited == ids
                    for _ in range(active_page_size-1): x.key('Up')
                    s = snap(); page_geometry(s, revealed=True)
                    samples = scroll_end(s)
                    capture(label+f'-page-{page_number}-'+selection)
                    if selection == 'mouse':
                        chosen, g = chosen_click(s)
                    else:
                        chosen = s['candidates'][s['page_start']+active_page_size-1]
                        g = samples[-1]
                        x.key(str(active_page_size)); idle()
                    assert chosen['id'] == ids[-1], (chosen, ids)
                    expected += chosen['text']; readback()
                    record(label+f'-page-{page_number}-'+selection+'-full-text',
                           page_size=active_page_size, max_visible=active_max_visible,
                           ids=ids, visited_ids=visited, candidate_id=chosen['id'],
                           selected_text=chosen['text'], actual=expected,
                           geometry=g, scrollbar_samples=samples)
            s = compose(); x.key('Page_Down'); paged = snap()
            x.key('Page_Up'); returned = snap()
            assert paged['page_start'] == active_page_size and returned['page_start'] == 0
            page_geometry(returned, revealed=True); x.key('Escape'); idle()
            record(label+'-paging-preserves-size', page_size=active_page_size,
                   max_visible=active_max_visible)

        old = compose(); scroll_end(old); capture('narrow-before-focus-transfer')
        other = runtime/'Narrow-other.txt'; other.write_text('')
        start(['gedit', '--standalone', '--new-window', str(other)], 'narrow-other-editor')
        focus('Narrow-other.txt'); idle()
        assert not states.select_candidate(old, old['candidates'][-1]['id'])
        assert other.read_text() == ''
        capture('narrow-after-focus-transfer')
        focus('Feedback-editor.txt'); idle(); readback()
        record('focus-hides-and-rejects-stale-candidate', actual=expected)
    finally:
        rpc.call('apply', settings=original)


def controller_checks(out):
    """Real engine regressions for the key/commit policy retained from 0.2.1."""
    import unittest
    from ime_interface import config
    from server_ime.product_controller import ProductController
    from server_ime_engine.platform_adapter import PlatformSession
    from server_ime.controller import CONTROL, RELEASE, ESCAPE
    class Feedback(unittest.TestCase):
        def setUp(self):
            self.session=PlatformSession()
            self.commits=[];self.states=[]
            self.c=ProductController(self.session,'feedback',self.states.append,self.commits.append,settings=config.defaults())
            self.c.enable();self.c.focus_in()
        def tearDown(self):self.c.close()
        def type(self,text):
            for char in text:self.c.key(ord(char),0,0)
        def test_complete_commit_clears_candidates(self):
            self.type('zhongguo');self.c.key(32,0,0)
            self.assertEqual(self.commits,['中国']);self.assertFalse(self.c.snapshot()['candidate_visible'])
            self.assertFalse(self.c.snapshot()['preedit']['visible'])
            self.assertEqual(self.c.snapshot()['candidate_presentation'],'custom')
            self.assertFalse({'next_word','candidate_kind'} & self.c.snapshot().keys())
            self.assertFalse(hasattr(self.c,'surrounding_changed'))
        def test_partial_commit_retains_suffix(self):
            self.type('nihao');c=next(c for c in self.c.conversion.candidates if c.text=='你')
            self.assertTrue(self.c.select(c.id));self.assertEqual(self.c.composition,'hao')
            c=next(c for c in self.c.conversion.candidates if c.text=='好')
            self.assertTrue(self.c.select(c.id));self.assertEqual(self.commits,['你','好'])
            self.assertEqual(self.c.composition,'')
        def test_page_digit_and_revision(self):
            self.type('ni');old=self.c.snapshot();self.c.move(1,page=True)
            s=self.c.snapshot();self.assertGreater(s['page_start'],0)
            expected=s['candidates'][s['page_start']+1]['text']
            self.assertTrue(self.c.key(ord('2'),0,0));self.assertEqual(self.commits,[expected])
            self.assertFalse(self.c.select(old['candidates'][0]['id'],old['revision']))
        def test_raw_return_and_idle_space(self):
            self.type('nihao');self.assertTrue(self.c.key(0xFF0D,0,0))
            self.assertEqual(self.commits,['nihao']);self.assertFalse(self.c.key(32,0,0))
            self.assertFalse(self.c.key(0xFF0D,0,0));self.assertEqual(self.commits,['nihao'])
        def test_cancel_focus_mode_reset_and_sensitive(self):
            for action in ('escape','reset','focus_out','disable','english','digits','password','pin'):
                self.c.focus_in();self.c.enable();self.c.set_content_type(0,0);self.c.set_mode('zh')
                self.type('ni');old=self.c.snapshot()
                if action=='escape':self.c.key(ESCAPE,0,0)
                elif action=='english':self.c.set_mode('en')
                elif action in ('digits','password','pin'):self.c.set_content_type(dict(digits=2,password=8,pin=9)[action],0)
                else:getattr(self.c,action)()
                self.assertFalse(self.c.snapshot()['candidate_visible']);self.assertEqual(self.c.composition,'')
                self.assertFalse(self.c.select(old['candidates'][0]['id'],old['revision']))
                self.assertEqual(self.commits,[])
        def test_release_and_application_shortcuts(self):
            self.type('ni');old=self.c.snapshot()
            self.assertFalse(self.c.key(32,0,RELEASE));self.assertEqual(self.c.snapshot(),old)
            self.assertFalse(self.c.key(ord('a'),0,CONTROL));self.assertEqual(self.c.composition,'')
            self.assertEqual(self.commits,[])
        def test_punctuation_and_literal_routing(self):
            for enabled,marks in [(True,'，。？！'),(False,',.?!')]:
                settings=config.defaults();settings['punctuation']['chinese']=enabled
                self.c.configure_platform(settings,2)
                for char,mapped in zip(',.?!',marks):
                    self.type('nihao'+char);self.assertEqual(''.join(self.commits[-2:]),'你好'+mapped)
                    self.assertFalse(self.c.snapshot()['candidate_visible'])
            for raw in ('nihao@example.org','https://example.org/a?v=2','AbC123','v2.0'):
                self.type(raw);self.c.key(32,0,0);self.assertEqual(self.commits[-1],raw)
            self.type('abc');self.c.key(0xFFB1,0,0);self.type('23');self.assertEqual(self.c.composition,'abc123')
            self.c.key(0xFF0D,0,0);self.assertEqual(self.commits[-1],'abc123')
        def test_highlight_and_suffix_punctuation(self):
            for raw,choice,mark,expected in [('nihaoma','你号码','.','你号码。'),('nihao','尼',',','尼号，'),('nihaov','你','?','你号v？')]:
                self.type(raw);self.c.selected=next(i for i,c in enumerate(self.c.conversion.candidates) if c.text==choice)
                before=len(self.commits);self.type(mark)
                self.assertEqual(''.join(self.commits[before:]),expected)
                self.assertFalse(self.c.snapshot()['candidate_visible'])
    with (out/'controller.log').open('w') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Feedback))
    save(out/'controller-summary.json',dict(tests=result.testsRun,passed=result.wasSuccessful()))
    print('controller:',result.testsRun,'PASS' if result.wasSuccessful() else 'FAIL',flush=True)
    if not result.wasSuccessful():print((out/'controller.log').read_text(),flush=True)
    return result.wasSuccessful()


def native_adapter_check():
    """Exercise the current standalone default on the real bus, with real signals.

    This is an adapter signal check, not an application/window observation.
    Product application signals are captured separately before product stop.
    """
    import gi
    gi.require_version('IBus','1.0')
    from gi.repository import IBus, Gio, GLib
    from server_ime.ibus_adapter import ServerIME
    from server_ime.state_service import StateService
    from server_ime_engine.platform_adapter import PlatformSession
    IBus.init();bus=IBus.Bus.new();conn=bus.get_connection()
    assert bus.is_connected() and ServerIME.candidate_presentation=='native'
    events=[]
    def observed(c,sender,path,interface,name,params):
        events.append(dict(member=name,parameters=params.unpack(),wire=params.print_(True)))
    sub=conn.signal_subscribe(None,'org.freedesktop.IBus.Engine',None,
        '/org/freedesktop/IBus/Engine/FeedbackNative',None,Gio.DBusSignalFlags.NONE,observed)
    service=StateService(conn)
    ServerIME.backend_factory=staticmethod(PlatformSession);ServerIME.state_service=service
    engine=ServerIME(connection=conn,object_path='/org/freedesktop/IBus/Engine/FeedbackNative')
    def pump():
        end=time.monotonic()+.3
        while time.monotonic()<end:
            while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
            time.sleep(.01)
    try:
        engine.do_enable();engine.do_focus_in()
        for c in 'nihao':assert engine.do_process_key_event(ord(c),0,0)
        pump()
        for member in ('UpdateLookupTable','UpdateAuxiliaryText'):
            assert any(e['member']==member and e['parameters'][-1] is True for e in events),(member,events)
        assert any(e['member']=='UpdatePreeditText' and e['parameters'][2] is True for e in events),events
        engine.do_process_key_event(32,0,0);pump()
        assert any(e['member']=='CommitText' and '你好' in e['wire'] for e in events),events
        save(Path(os.environ['FEEDBACK_OUT'])/'native-adapter-signals.json',dict(
            employee_id='platform',result='PASS',mode='native',scope='real standalone adapter framework signals',
            signals=[dict(member=e['member'],wire=e['wire']) for e in events]))
    finally:
        engine.destroy();service.close();conn.signal_unsubscribe(sub)
    return 0


def runtime_hashes(product):
    rows=[]
    for folder in ('integration/src','engine/src','lexicon/src','platform/server_ime','interface/src','interface/config'):
        for p in sorted((product/folder).rglob('*')):
            if p.is_file() and (p.suffix=='.py' or folder=='interface/config'):
                rows.append(dict(path=str(p.relative_to(product)),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    entry='integration/bin/server-ime' if product==ROOT else 'bin/server-ime'
    rows.append(dict(path=entry,sha256=hashlib.sha256((product/entry).read_bytes()).hexdigest()))
    return rows


def baseline_product(out):
    archive=ROOT/'integration/build/server-ime-product-0.2.1.tar.gz'
    assert archive.is_file(), 'Retained 0.2.1 baseline is required for real reproduction'
    destination=out/'retained-0.2.1';destination.mkdir()
    with tarfile.open(archive,'r:gz') as tar:
        tar.extractall(destination,filter='data')
    entries=list(destination.glob('*/bin/server-ime'))+list(destination.glob('bin/server-ime'))
    assert len(entries)==1,entries
    product=entries[0].parent.parent
    changed=[]
    for relative in FILES[:-1]:
        before=(product/relative).read_text();after=(ROOT/relative).read_text()
        if before!=after:
            changed.append(relative)
            (out/(Path(relative).name+'.vs-0.2.1.diff')).write_text(''.join(difflib.unified_diff(
                before.splitlines(True),after.splitlines(True),fromfile='0.2.1/'+relative,tofile='current/'+relative)))
    # A removed prediction layer must not change the established key/commit policy.
    relative='platform/server_ime/product_controller.py'
    restored=(ROOT/relative).read_text().replace("        state['candidate_presentation'] = 'custom'\n",'')
    assert restored==(product/relative).read_text(), 'Controller differs beyond presentation metadata; inspect diff'
    before=runtime_hashes(product)
    save(out/'baseline.json',dict(archive=str(archive),sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        product_root=str(product),runtime_files=before,presentation_files_changed=changed,
        key_commit_policy_identical_to_0_2_1=True))
    return product


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',action='store_true')
    parser.add_argument('--session',choices=['baseline','fixed'])
    parser.add_argument('--route',choices=['managed','existing'])
    parser.add_argument('--native-adapter',action='store_true')
    parser.add_argument('--skip-baseline',action='store_true',
                        help='Retain the existing duplicate-window reproduction; check only current product')
    parser.add_argument('--narrow-only',action='store_true',
                        help='Only the real 360px/300%% candidate viewport checks')
    parser.add_argument('--output',type=Path,
                        help='New evidence directory (default: under integration/evidence)')
    args=parser.parse_args()
    if args.native_adapter:return native_adapter_check()
    if args.session:return session(args.session=='baseline')
    os.umask(0o077)
    if args.output:
        out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    else:
        out=Path(tempfile.mkdtemp(prefix='candidate-layout-',dir=ROOT/'integration/evidence'))
    hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in FILES}
    tested=runtime_hashes(PRODUCT)
    save(out/'source-hashes.json',hashes)
    save(out/'tested-runtime-hashes.json',dict(employee_id='platform',product_root=str(PRODUCT),
        phase='before-launch',runtime_files=tested,check_scripts=[dict(path=FILES[-1],sha256=hashes[FILES[-1]])]))
    print('Evidence:',out,flush=True)
    passed=False
    try:
        passed=True
        if args.baseline or (not args.skip_baseline and not args.narrow_only):
            product=baseline_product(out)
            passed=isolated(out/'baseline',args.route or 'existing',True,product)
        if not args.baseline:
            passed=controller_checks(out) and passed
            routes=[args.route] if args.route else ['managed','existing']
            # Gate the general regressions on both real narrow sessions first.
            # This is sequential: no build or other graphical run is concurrent.
            for route in routes:
                if not passed: break
                passed=isolated(out/(route+'-narrow'),route,product=PRODUCT,narrow=True)
            if passed and not args.narrow_only:
                for route in routes:
                    if not passed: break
                    passed=isolated(out/route,route,product=PRODUCT)
    except Exception:
        passed=False
        (out/'failure.txt').write_text(traceback.format_exc());print(traceback.format_exc(),flush=True)
    after=runtime_hashes(PRODUCT)
    save(out/'runtime-hashes-after.json',dict(employee_id='platform',product_root=str(PRODUCT),
        phase='after-process-exit',runtime_files=after))
    unchanged=(all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in hashes.items())
               and after==tested)
    passed=passed and unchanged
    save(out/'summary.json',dict(employee_id='platform',verifies=[],result='PASS' if passed else 'FAIL',
        scope='single candidate window; full horizontal page and 360px/300% viewport',baseline_only=args.baseline,
        narrow_only=args.narrow_only,
        baseline_reused=args.skip_baseline and not args.baseline,
        runtime_unchanged_during_run=unchanged,source_unchanged_during_run=unchanged,
        evidence=str(out),user_desktop_root_cause='NOT_CONFIRMED',user_desktop_deployed=False))
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())
