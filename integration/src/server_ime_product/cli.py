"""Product command line. No test-backend switch, no session auto-discovery."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from ime_interface import config


def main(argv=None):
    parser = argparse.ArgumentParser(description='服务器输入法 / employee_id=platform')
    parser.add_argument('--config', default=str(config.config_path()))
    parser.add_argument('--data-dir', default=str(config.data_dir()))
    parser.add_argument('--state-dir', default=str(config.data_dir() / 'run'))
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('start', 'run'):
        sub.add_parser(name).add_argument('--managed-ibus', action='store_true',
            help='Create and own a private IBus daemon for applications launched via exec')
    for name in ('stop', 'status', 'settings', 'capabilities', 'learning-status', 'reload-lexicon'):
        sub.add_parser(name)
    settings = sub.add_parser('config')
    settings.add_argument('action', choices=['get', 'apply', 'reset'])
    settings.add_argument('file', nargs='?')
    child = sub.add_parser('exec')
    child.add_argument('argv', nargs=argparse.REMAINDER)
    for name in ('_service', '_panel'):
        sub.add_parser(name).add_argument('--ready', required=True)
    args = parser.parse_args(argv)
    for name in ('config', 'data_dir', 'state_dir'):
        setattr(args, name, str(Path(getattr(args, name)).expanduser().resolve()))
    launcher = Path(__file__).resolve().parents[2] / 'bin/server-ime'
    from . import supervisor
    try:
        if args.command == 'capabilities':
            from server_ime_engine import Engine
            result = Engine.capabilities()
        elif args.command == '_service':
            from .runtime import run_service
            return run_service(args)
        elif args.command == '_panel':
            # Candidate popup has no editable input; do not let its pointer grabs
            # create an IBus input context and steal the application's focus.
            os.environ['GTK_IM_MODULE'] = 'simple'
            from .panel import run_panel
            return run_panel(args)
        elif args.command == 'run':
            return supervisor.run(args, launcher)
        elif args.command == 'start':
            try:
                existing = supervisor.request(args.state_dir, 'status')
            except (OSError, RuntimeError):
                existing = None
            if existing:
                raise RuntimeError('Product already running; use status')
            state = Path(args.state_dir)
            state.mkdir(parents=True, exist_ok=True, mode=0o700)
            command = [sys.executable, str(launcher), '--state-dir', args.state_dir,
                       '--config', args.config, '--data-dir', args.data_dir, 'run']
            if args.managed_ibus:
                command.append('--managed-ibus')
            with (state / 'supervisor.log').open('a') as log:
                child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                         start_new_session=True, close_fds=True)
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError('Startup failed; see ' + str(state / 'supervisor.log'))
                try:
                    result = supervisor.request(state, 'status')
                    if result['state'] == 'running':
                        break
                except (OSError, RuntimeError):
                    pass
                time.sleep(.1)
            else:
                # This is the child we just created; never signal a PID from a stale file.
                child.terminate()
                child.wait(timeout=15)
                raise RuntimeError('Startup timed out')
        elif args.command in ('stop', 'status'):
            try:
                result = supervisor.request(args.state_dir, args.command)
            except OSError:
                path = Path(args.state_dir) / 'status.json'
                result = json.loads(path.read_text()) if path.exists() else dict(state='stopped')
                if result.get('state') in {'running', 'starting', 'recovering'}:
                    result['state'] = 'unreachable'
            if args.command == 'stop':
                for _ in range(150):
                    if not (Path(args.state_dir) / 'control').exists():
                        break
                    time.sleep(.1)
                else:
                    raise RuntimeError('Stop timed out')
                path = Path(args.state_dir) / 'status.json'
                result = json.loads(path.read_text()) if path.exists() else dict(state='stopped')
        else:
            status = supervisor.request(args.state_dir, 'status')
            if status['state'] != 'running':
                raise RuntimeError('Product is not running')
            os.environ.update(status['env'])
            os.environ.pop('IBUS_USE_PORTAL', None)
            if args.command == 'exec':
                command = args.argv
                if command and command[0] == '--':
                    command = command[1:]
                if not command:
                    raise ValueError('exec requires an application command')
                os.execvpe(command[0], command, os.environ)
            from .rpc import Client
            client = Client()
            if args.command == 'settings':
                from .panel import settings_window
                from gi.repository import Gtk
                window = settings_window()
                Gtk.main()
                return 0
            elif args.command == 'config':
                if args.action == 'apply':
                    if not args.file:
                        raise ValueError('config apply requires a JSON file')
                    result = client.call('apply', settings=json.loads(Path(args.file).read_text()))
                else:
                    result = client.call(args.action)
            else:
                result = client.call(args.command)
        # Environment is returned only by the private control socket to exec,
        # never in diagnostics (addresses and auth path need not be copied).
        result.pop('env', None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps(dict(ok=False, error=str(exc), errors=getattr(exc, 'errors', [])),
                         ensure_ascii=False), file=sys.stderr)
        return 1
