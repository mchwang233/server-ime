"""Bounded child recovery, explicit bus ownership, private local control socket."""
import ctypes
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import time


def write_json(path, value):
    tmp = path.with_suffix('.new')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.chmod(0o600)
    tmp.replace(path)


def ibus_daemon_options():
    """Options to turn off what this ibus-daemon has: 1.5.17 (EL7) has no emoji extension."""
    try:
        usage = subprocess.run(['ibus-daemon', '--help'], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        usage = ''
    return ['--emoji-extension=disable'] if '--emoji-extension' in usage else []


def request(state_dir, op):
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(5)
    try:
        sock.connect(str(Path(state_dir) / 'control'))
        sock.sendall((json.dumps(dict(op=op)) + '\n').encode())
        data = b''
        while not data.endswith(b'\n'):
            part = sock.recv(65536)
            if not part:
                raise RuntimeError('Supervisor disconnected')
            data += part
        return json.loads(data)
    finally:
        sock.close()


def run(args, launcher):
    os.umask(0o077)
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_dir.chmod(0o700)
    lock = (state_dir / 'lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Product already running for this state directory')
    if len(os.fsencode(state_dir / 'control')) >= 104:
        raise RuntimeError('--state-dir is too long for a UNIX socket; use a shorter writable path')
    env = os.environ.copy()
    if not env.get('DISPLAY') or not env.get('DBUS_SESSION_BUS_ADDRESS'):
        raise RuntimeError('Explicit DISPLAY and DBUS_SESSION_BUS_ADDRESS are required')
    if not args.managed_ibus and not env.get('IBUS_ADDRESS'):
        raise RuntimeError('Supply IBUS_ADDRESS or --managed-ibus')
    env.update(GTK_IM_MODULE='ibus', QT_IM_MODULE='ibus', XMODIFIERS='@im=ibus',
               GTK_USE_PORTAL='0', PYTHONDONTWRITEBYTECODE='1')
    env.pop('SERVER_IME_UI_EVENTS', None)
    # IBus 1.5.25 treats even IBUS_USE_PORTAL=0 as enabled.
    env.pop('IBUS_USE_PORTAL', None)
    control = state_dir / 'control'
    control.unlink(missing_ok=True)
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(control))
    listener.listen(4)
    children, logfiles = {}, []
    status = dict(employee_id='platform', state='starting', pid=os.getpid(), children={},
                  restarts=dict(service=0, panel=0, ibus=0), managed_ibus=args.managed_ibus,
                  config=args.config, data_dir=args.data_dir, session='explicit', error=None)
    stopping = False
    failures = []
    def stop_signal(*_):
        nonlocal stopping
        stopping = True
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop_signal)
    def save():
        status['children'] = {name: child.pid for name, child in children.items() if child.poll() is None}
        write_json(state_dir / 'status.json', status)
    def stop_child(name):
        child = children.pop(name, None)
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=4)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)
    def start_child(name, command):
        log = (state_dir / (name + '.log')).open('a')
        logfiles.append(log)
        parent_pid = os.getpid()
        def parent_death():
            # Linux: if this supervisor is killed, its owned workers must exit.
            ctypes.CDLL(None).prctl(1, signal.SIGTERM, 0, 0, 0)
            if os.getppid() != parent_pid:
                os.kill(os.getpid(), signal.SIGTERM)
        child = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, close_fds=True, preexec_fn=parent_death)
        children[name] = child
        return child
    def wait_ready(name, ready, predicate=None):
        until = time.monotonic() + 12
        while time.monotonic() < until and not stopping:
            if children[name].poll() is not None:
                raise RuntimeError(name + ' exited before ready; see ' + name + '.log')
            if ready.exists() and (predicate is None or predicate(ready)):
                return
            time.sleep(.05)
        raise RuntimeError(name + ' readiness timed out')
    def start_ibus():
        address_file = state_dir / 'ibus-address'
        address_file.unlink(missing_ok=True)
        env.pop('IBUS_ADDRESS', None)
        env['IBUS_ADDRESS_FILE'] = str(address_file)
        components = state_dir / 'components'
        components.mkdir(exist_ok=True)
        env['IBUS_COMPONENT_PATH'] = str(components)
        start_child('ibus', ['ibus-daemon', '--single', '--panel=disable', '--config=disable',
            *ibus_daemon_options(), '--cache=none', '--address=unix:tmpdir=' + str(state_dir)])
        def address(p):
            for line in p.read_text().splitlines():
                if line.startswith('IBUS_ADDRESS='):
                    env['IBUS_ADDRESS'] = line.partition('=')[2]
            return bool(env.get('IBUS_ADDRESS'))
        wait_ready('ibus', address_file, address)
    def start_worker(name):
        ready = state_dir / (name + '.ready')
        ready.unlink(missing_ok=True)
        start_child(name, [sys.executable, str(launcher), '--state-dir', str(state_dir),
            '--config', args.config, '--data-dir', args.data_dir, '_' + name, '--ready', str(ready)])
        wait_ready(name, ready)
    def client_env():
        keys = ['DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'IBUS_ADDRESS', 'IBUS_ADDRESS_FILE',
                'GTK_IM_MODULE', 'QT_IM_MODULE', 'XMODIFIERS', 'IBUS_USE_PORTAL', 'GTK_USE_PORTAL']
        return {key: env[key] for key in keys if key in env}
    try:
        if args.managed_ibus:
            start_ibus()
        else:
            previous = subprocess.run(['ibus', 'engine'], env=env, capture_output=True, text=True, timeout=5)
            status['previous_engine'] = previous.stdout.strip() if previous.returncode == 0 else None
        start_worker('service')
        start_worker('panel')
        status['state'] = 'running'
        save()
        while not stopping:
            readable, _, _ = select.select([listener], [], [], .2)
            if readable:
                conn, _ = listener.accept()
                with conn:
                    conn.settimeout(1)
                    try:
                        payload = conn.recv(4096)
                        op = json.loads(payload)['op']
                        if op == 'stop':
                            stopping = True
                        reply = dict(status, env=client_env()) if op in {'status', 'stop'} else dict(error='Unknown operation')
                        conn.sendall((json.dumps(reply) + '\n').encode())
                    except (OSError, ValueError, KeyError):
                        pass
            failed = next((name for name, p in children.items() if p.poll() is not None), None)
            if failed and not stopping:
                now = time.monotonic()
                failures = [t for t in failures if now-t < 60] + [now]
                status['state'] = 'recovering'
                status['restarts'][failed] += 1
                save()
                if len(failures) > 3:
                    raise RuntimeError('Recovery limit exceeded (3 crashes / 60 seconds)')
                if failed in {'ibus', 'service'}:
                    stop_child('panel')
                    stop_child('service')
                stop_child(failed)
                if failed == 'ibus':
                    start_ibus()
                if failed in {'ibus', 'service'}:
                    start_worker('service')
                start_worker('panel')
                status['state'] = 'running'
                save()
    except Exception as exc:
        status['error'] = str(exc)
        status['state'] = 'failed'
        print(str(exc), file=sys.stderr, flush=True)
    finally:
        for name in ('panel', 'service', 'ibus'):
            stop_child(name)
        previous = status.get('previous_engine')
        if not args.managed_ibus and previous and previous != 'server-ime':
            try:
                restored = subprocess.run(['ibus', 'engine', previous], env=env, capture_output=True, timeout=5)
                status['previous_engine_restored'] = restored.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                status['previous_engine_restored'] = False
        listener.close()
        control.unlink(missing_ok=True)
        if status['state'] != 'failed':
            status['state'] = 'stopped'
        save()
        for logfile in logfiles:
            logfile.close()
        lock.close()
    return 1 if status['state'] == 'failed' else 0
