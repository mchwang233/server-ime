"""Minimal distribution-wrapper/ELF comparison; never uses the user's profile."""
import hashlib
import http.server
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from x11 import pump, screenshot

E = Path(os.environ['SERVER_IME_EVIDENCE'])
R = Path(os.environ['SERVER_IME_CHECK_RUNTIME'])
COMMAND = json.loads(os.environ['SERVER_IME_CHECK_COMMAND'])


def main():
    assert os.environ['SERVER_IME_ISOLATED'] == '1'
    assert os.environ['DISPLAY'].startswith('127.0.0.1:')
    reports = []
    requests = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'<!doctype html><title>IME-browser-startup</title>Browser startup probe'
                             b'<script>fetch("/ready")</script>')
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    env = os.environ.copy()
    env.update(MOZ_DISABLE_LANGPACKS='1', MOZ_ENABLE_WAYLAND='0', MOZ_CRASHREPORTER_DISABLE='1')
    cases = [('wrapper', ['/bin/bash', '-x', '/usr/bin/firefox']),
             ('elf', ['/usr/lib64/firefox/firefox']),
             ('firefox-bin', ['/usr/lib64/firefox/firefox-bin'])]
    try:
        for name, program in cases:
            requests.clear()
            profile = R / ('probe-profile-' + name)
            profile.mkdir(mode=0o700)
            argv = program + ['--no-remote', '--profile', str(profile), '--new-instance',
                              'http://127.0.0.1:' + str(httpd.server_port)]
            trace = E / (name + '.strace')
            launch = ['strace', '-f', '-s', '1024', '-e',
                      'trace=execve,openat,newfstatat,access,mkdir,readlink,symlink', '-o', str(trace)] + COMMAND + ['exec', '--'] + argv
            with (E/(name+'.log')).open('w') as log:
                child = subprocess.Popen(launch, env=env, stdout=log, stderr=subprocess.STDOUT,
                                         start_new_session=True)
                try:
                    end = time.monotonic()+10
                    while child.poll() is None and '/ready' not in requests and time.monotonic()<end:
                        pump(.1)
                    tree = subprocess.run(['xwininfo', '-root', '-tree'], capture_output=True, text=True, check=True).stdout
                    (E/(name+'-windows.txt')).write_text(tree)
                    screenshot(E/(name+'.png'))
                    files = [str(p.relative_to(profile)) for p in profile.rglob('*') if p.is_file()]
                    reports.append(dict(name=name, command=argv, page_ready='/ready' in requests,
                                        http_requests=list(requests), profile_files=files,
                                        process_exit_before_cleanup=child.poll(),
                                        profile_missing_dialog='Profile Missing' in tree))
                finally:
                    if child.poll() is None:
                        os.killpg(child.pid, signal.SIGTERM)
                        try: child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL); child.wait(timeout=5)
                    reports[-1]['cleanup_returncode'] = child.returncode
            lines = trace.read_text().splitlines()
            errors = [s for s in lines if any(x in s for x in ('EACCES', 'EROFS', 'execve(', 'probe-profile-', '.mozilla'))]
            (E/(name+'-relevant.txt')).write_text('\n'.join(errors)+'\n')
            print(json.dumps(reports[-1]), flush=True)
    finally:
        httpd.shutdown(); httpd.server_close()
        binaries = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                    map(Path, ['/usr/bin/firefox', '/usr/lib64/firefox/firefox', '/usr/lib64/firefox/firefox-bin'])}
        version = subprocess.run(['/usr/lib64/firefox/firefox', '--version'], capture_output=True, text=True).stdout.strip()
        (E/'browser-startup.json').write_text(json.dumps(dict(employee_id='platform', verifies=[],
            version=version, binaries_sha256=binaries, cases=reports, session='isolated-X11-Xvnc',
            profile_policy='Explicit fresh workspace profile per case; HOME unchanged; browser sandbox unchanged'), indent=2)+'\n')


if __name__ == '__main__': main()
