#!/usr/bin/env python3
"""Targeted release regressions; writes only delivery. employee_id=delivery."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tarfile
import tempfile
import shutil

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / 'delivery'
E = D / 'evidence/punctuation-closeout-20261029'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args, log):
    p = subprocess.run([str(a) for a in args], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (E / log).write_bytes(p.stdout)
    return p

def main():
    E.mkdir(parents=True, exist_ok=True)
    lock = D / 'manifest/lock.json'
    before = lock.read_bytes()
    info = json.loads(before)
    out = D / 'build/closeout-repeat-dist'
    work = D / 'build/closeout-repeat'
    cmd = [sys.executable,D/'bin/ime-build','--out',out,'--work',work,'--note',info['release_note'],'--json']
    p = run(cmd, 'repeat-build.json')
    assert p.returncode == 0, p.stdout.decode()
    assert before == lock.read_bytes(), 'independent output changed official lock'
    for suffix in ['.tar.gz', '-sources.tar.gz', '.component-manifest.json']:
        n = 'server-ime-0.1.0'+suffix
        assert sha(D/'dist'/n) == sha(out/n), n
    checks = ['independent output preserves official lock', 'repeat package/source/manifest hashes match']
    verify = runpy.run_path(str(D/'tests/verify_release_content.py'))
    with tempfile.TemporaryDirectory(prefix='closeout-', dir=D/'build') as tmp:
        tmp = Path(tmp)
        # Private copies with deliberately dangling lock and manifest paths; no originals moved.
        (tmp/'manifest').mkdir()
        for name in ['lock.json','product-manifest.json']:
            shutil.copyfile(D/'manifest'/name,tmp/'manifest'/name)
        bad = json.loads(before)
        bad['package']['path'] = 'missing/server-ime-0.1.0.tar.gz'
        (tmp/'manifest/lock.json').write_text(json.dumps(bad))
        report = verify['Report']()
        verify['check_records'](report, {}, tmp)
        assert report.failures(), 'dangling path was accepted'
        checks.append('dangling lock path rejected')
        # Rebuild using only extracted delivered sources, not workspace source files.
        source = tmp/'source'
        source.mkdir()
        with tarfile.open(D/'dist/server-ime-0.1.0-sources.tar.gz') as tar:
            tar.extractall(source)
        result = run([sys.executable,source/'delivery/bin/ime-build','--note',info['release_note'],'--json'], 'source-rebuild.json')
        assert result.returncode == 0, result.stdout.decode()
        for suffix in ['.tar.gz','-sources.tar.gz']:
            n='server-ime-0.1.0'+suffix
            assert sha(source/'delivery/dist'/n)==sha(D/'dist'/n), n
        checks.append('standalone delivered sources rebuild identical package and sources')
        for member in ('interface/LICENSE', 'interface/SOURCES.md'):
            path = source/member
            original = path.read_bytes()
            path.unlink()
            result=run([sys.executable,source/'delivery/bin/ime-build','--out',tmp/'missing-out','--work',tmp/'missing-work'], 'missing-'+path.name+'.log')
            assert result.returncode==5 and not list((tmp/'missing-out').glob('*.tar.gz'))
            path.write_bytes(original)
        assert before == lock.read_bytes()
        checks.append('missing interface LICENSE or SOURCES.md fails rc=5 before package emission')
    (E/'regressions.json').write_text(json.dumps({'employee_id':'delivery','result':'PASS','checks':checks,'repeat_work':str(work.relative_to(ROOT))},ensure_ascii=False,indent=2)+'\n')
    print('PASS',len(checks),'targeted regressions')
if __name__=='__main__': main()
