#!/usr/bin/python3
"""Product-owned checks in a new, cookie-authenticated X11 session only."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
PRODUCT = Path(os.environ.get('SERVER_IME_PRODUCT_ROOT', str(ROOT))).resolve()
ENTRY = PRODUCT / ('bin/server-ime' if PRODUCT != ROOT else 'integration/bin/server-ime')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window-manager', choices=('none','xfwm4'), default='none')
    parser.add_argument('--output', type=Path, help='New evidence directory; must not already exist')
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--browser-startup-only', action='store_true')
    scope.add_argument('--browser-only', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    evidence = (args.output.resolve() if args.output else
                ROOT / 'integration/evidence' / ('run-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S')))
    evidence.mkdir(parents=True)
    parent = ROOT / 'integration/.runtime'
    parent.mkdir(exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix='r-', dir=parent))
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
    env.update(GSETTINGS_BACKEND='memory', GDK_BACKEND='x11', GTK_IM_MODULE='ibus', QT_IM_MODULE='ibus',
               XMODIFIERS='@im=ibus', GTK_USE_PORTAL='0', NO_AT_BRIDGE='1',
               SERVER_IME_ISOLATED='1', XDG_SESSION_TYPE='x11', PYTHONDONTWRITEBYTECODE='1',
               PYTHONPATH=':'.join([str(PRODUCT / p) for p in
                   ('integration/src', 'platform', 'interface/src', 'engine/src', 'lexicon/src')] + [str(ROOT/'interface/tests')]),
               SERVER_IME_EVIDENCE=str(evidence), SERVER_IME_CHECK_RUNTIME=str(runtime))
    state = runtime / 'r'
    common = [str(ENTRY), '--state-dir', str(state), '--data-dir', str(runtime / 'personal'),
              '--config', str(runtime / 'settings.json')]
    env['SERVER_IME_CHECK_COMMAND'] = json.dumps(common)
    if args.browser_only:
        env['SERVER_IME_CHECK_APPS'] = 'browser'
    processes, logs = [], []
    result = dict(employee_id='platform', result='FAIL', product_root=str(PRODUCT), session=dict(scope='isolated', protocol='X11',
                  server='Xvnc', injection='XTest', real_engine=True), checks=[], verifies=[],
                  scope='browser-startup' if args.browser_startup_only else 'browser' if args.browser_only else 'full')
    # Capture bytes before process launch, then check them again after exit.
    runtime_files=[]
    for folder in ('integration/src','engine/src','lexicon/src','platform/server_ime','interface/src','interface/config'):
        for p in sorted((PRODUCT/folder).rglob('*')):
            if p.is_file() and (p.suffix=='.py' or folder=='interface/config'):
                runtime_files.append(dict(path=str(p.relative_to(PRODUCT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    for name in ('bin/server-ime','integration/bin/server-ime'):
        if (PRODUCT/name).exists():
            runtime_files.append(dict(path=name,sha256=hashlib.sha256((PRODUCT/name).read_bytes()).hexdigest()))
    (evidence/'tested-runtime-hashes.json').write_text(json.dumps(dict(employee_id='platform',
        product_root=str(PRODUCT),phase='before-launch',runtime_files=runtime_files,
        check_scripts=[dict(path=str(p.relative_to(ROOT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                       for p in sorted((ROOT/'integration/checks').glob('*.py'))]),indent=2)+'\n')
    def start(argv, name, pass_fds=()):
        f = (evidence / (name + '.log')).open('w'); logs.append(f)
        p = subprocess.Popen(argv, env=env, stdout=f, stderr=subprocess.STDOUT, pass_fds=pass_fds)
        processes.append(p)
        return p
    def check(argv, name, timeout=180):
        r = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
        (evidence / (name + '.log')).write_text(r.stdout + r.stderr)
        result['checks'].append(dict(name=name, exit_code=r.returncode, command=argv))
        print(name + ': ' + str(r.returncode), flush=True)
        if r.returncode:
            raise RuntimeError(name + ' failed; see ' + str(evidence / (name + '.log')))
        return r
    try:
        auth = runtime / 'auth'
        auth.write_bytes(struct.pack('!H', 65535) + b''.join(struct.pack('!H', len(v)) + v
            for v in (b'', b'', b'MIT-MAGIC-COOKIE-1', secrets.token_bytes(16))))
        env['XAUTHORITY'] = str(auth)
        read, write = os.pipe()
        try:
            start(['/usr/bin/Xvnc', '-displayfd', str(write), '-geometry', '1280x960', '-depth', '24',
                   '-rfbport', '-1', '-rfbunixpath', str(runtime / 'vnc'), '-localhost',
                   '-nolisten', 'unix', '-nolisten', 'local', '-listen', 'tcp', '-auth', str(auth), '-noreset'],
                  'xserver', (write,))
        finally:
            os.close(write)
        data, end = b'', time.monotonic()+10
        while b'\n' not in data and time.monotonic() < end:
            if select.select([read], [], [], 1)[0]:
                data += os.read(read, 32)
        os.close(read)
        number = data.decode().strip()
        if not number.isdecimal(): raise RuntimeError('Isolated display unavailable')
        env['DISPLAY'] = '127.0.0.1:' + number
        result['session']['display'] = env['DISPLAY']
        check(['xdpyinfo'], 'display')
        address = 'unix:path=' + str(runtime / 'bus')
        cfg = runtime / 'dbus.conf'
        cfg.write_text('<busconfig><type>session</type><listen>' + address + '</listen><auth>EXTERNAL</auth>'
            '<policy context="default"><allow send_destination="*"/><allow receive_sender="*"/>'
            '<allow own="*"/></policy></busconfig>')
        start(['dbus-daemon', '--nofork', '--config-file=' + str(cfg)], 'dbus')
        for _ in range(100):
            if (runtime / 'bus').exists(): break
            time.sleep(.03)
        env['DBUS_SESSION_BUS_ADDRESS'] = address
        if args.window_manager == 'xfwm4':
            wm = start(['xfwm4','--compositor=off','--sm-client-disable'], 'window-manager')
            time.sleep(1)
            if wm.poll() is not None:
                raise RuntimeError('xfwm4 could not start; see window-manager.log')
            result['session']['window_manager'] = 'xfwm4'
        check(common + ['start', '--managed-ibus'], 'product-start', 50)
        from server_ime_product.supervisor import request
        env.update(request(state, 'status')['env'])
        if args.browser_startup_only:
            check([sys.executable, str(ROOT / 'integration/checks/browser_startup.py')], 'browser-startup', 100)
        elif not args.browser_only and os.environ.get('SERVER_IME_SKIP_CONTRACT') != '1':
            check([sys.executable, str(ROOT / 'integration/checks/test_product.py')], 'product-contract', 90)
        env.update(request(state, 'status')['env'])
        if not args.browser_startup_only and os.environ.get('SERVER_IME_SKIP_APPS') != '1':
            check([sys.executable, str(ROOT / 'integration/checks/applications.py')], 'applications', 600)
        application_file=evidence/'applications.json'
        unverified=[]
        if application_file.exists():
            unverified=[r for r in json.loads(application_file.read_text())['observations'] if r['result']=='UNVERIFIED']
        result['unverified_applications']=unverified
        result['result'] = 'PARTIAL' if unverified else 'PASS'
        if args.browser_startup_only:
            result['browser_startup'] = json.loads((evidence/'browser-startup.json').read_text())
            result['result'] = 'PASS' if any(r['page_ready'] for r in result['browser_startup']['cases']) else 'PARTIAL'
    except Exception as exc:
        result['error'] = str(exc)
        print(exc, file=sys.stderr, flush=True)
    finally:
        try:
            stopped = subprocess.run(common + ['stop'], env=env, capture_output=True, text=True, timeout=20)
            (evidence / 'product-stop.log').write_text(stopped.stdout + stopped.stderr)
            result['stop_exit_code'] = stopped.returncode
        except Exception as exc:
            result['stop_error'] = str(exc)
        if state.exists():
            for p in state.glob('*.log'):
                shutil.copyfile(p, evidence / p.name)
            if (state / 'status.json').exists(): shutil.copyfile(state / 'status.json', evidence / 'final-status.json')
        for p in reversed(processes):
            if p.poll() is None:
                p.terminate()
                try: p.wait(timeout=4)
                except subprocess.TimeoutExpired: p.kill(); p.wait(timeout=4)
        for f in logs: f.close()
        result['support_processes_reaped'] = [dict(pid=p.pid, rc=p.returncode) for p in processes]
        # Retain only our synthetic configuration/learning inputs as proof.
        if (runtime / 'settings.json').exists(): shutil.copyfile(runtime / 'settings.json', evidence / 'settings.json')
        if (runtime / 'personal').exists(): shutil.copytree(runtime / 'personal', evidence / 'synthetic-personal-data')
        shutil.rmtree(runtime)
        changed=[row['path'] for row in runtime_files if not (PRODUCT/row['path']).is_file()
                 or hashlib.sha256((PRODUCT/row['path']).read_bytes()).hexdigest()!=row['sha256']]
        (evidence/'runtime-hashes-after.json').write_text(json.dumps(dict(employee_id='platform',
            product_root=str(PRODUCT),phase='after-process-exit',
            runtime_files=[dict(path=row['path'],sha256=hashlib.sha256((PRODUCT/row['path']).read_bytes()).hexdigest())
                           for row in runtime_files if (PRODUCT/row['path']).is_file()]),indent=2)+'\n')
        result['runtime_unchanged_during_run']=not changed
        if changed:
            result.update(result='FAIL',changed_runtime_files=changed)
        (evidence / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
        (ROOT / 'integration/evidence/latest.json').write_text(json.dumps(dict(path=str(evidence), result=result['result']), indent=2)+'\n')
        print(evidence, flush=True)
    return result['result'] not in {'PASS','PARTIAL'}

if __name__ == '__main__':
    sys.path.insert(0, str(PRODUCT / 'integration/src'))
    raise SystemExit(main())
