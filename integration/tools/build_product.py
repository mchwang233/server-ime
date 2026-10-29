#!/usr/bin/python3
"""Assemble existing component deliveries, excluding every test runtime. employee_id=platform."""
import ast
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

ROOT=Path(__file__).resolve().parents[2]
BUILD=ROOT/'integration/build'
OUT=BUILD/'product'
VERSION=ast.literal_eval((ROOT/'integration/src/server_ime_product/__init__.py').read_text().split('__version__ =',1)[1].strip())

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    handoff=json.loads((ROOT/'integration/handoff.json').read_text())
    assert handoff['version']==VERSION, 'Handoff/runtime version mismatch'
    interface_handoff=json.loads((ROOT/'interface/handoff.json').read_text())
    interface_version=interface_handoff['version']
    assert next(c['version'] for c in handoff['runtime_components']
                if c['employee_id']=='interface')==interface_version, 'Interface handoff version mismatch'
    for row in handoff['historical_packages']:
        assert sha(ROOT/row['path'])==row['sha256'], row['path']
    # Verify the engine's pinned runtime and source bundle before copying.
    lock=json.loads((ROOT/'engine/vendor.lock.json').read_text())
    for row in lock['files']:
        source=ROOT/'engine'/row['path']
        if sha(source)!=row['sha256']:raise RuntimeError('Engine dependency hash mismatch: '+row['path'])
    if OUT.exists():shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    directories=['integration/src','integration/bin','integration/docs','platform/server_ime','interface/src',
                 'interface/config','engine/src','engine/data','engine/docs','engine/vendor/runtime',
                 'engine/vendor/libime','engine/native',
                 'engine/vendor/sources','lexicon/src','lexicon/data/base','lexicon/licenses']
    def ignore(directory,names):
        return [n for n in names if n in {'__pycache__','capabilities-fixture.json'}
                or (Path(directory).name == 'server_ime' and n in {'deterministic.py','service.py'})
                or n.endswith('.pyc')]
    for folder in directories:
        shutil.copytree(ROOT/folder,OUT/folder,ignore=ignore)
    files=['engine/LICENSE','engine/dependencies.json','engine/vendor.lock.json',
           'engine/vendor/libpinyin-2.6.0-4.el9.src.rpm','engine/vendor/libpinyin-2.6.0.tar.gz',
           'platform/LICENSE','lexicon/SOURCES.md','interface/docs/config-format.md',
           'interface/LICENSE','interface/SOURCES.md',
           'integration/README.md','integration/LICENSE','integration/compatibility.json']
    for filename in files:
        target=OUT/filename;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/filename,target)
    handoff=json.loads((ROOT/'integration/handoff.json').read_text())
    compatibility=json.loads((ROOT/'integration/compatibility.json').read_text())
    compatibility.update(dict(
        schema='server-ime.application-compatibility/1',employee_id='platform',verifies=[],
        version=VERSION,product_version=VERSION,checks=handoff['checks'],
        candidate_presentation='custom-only; application preedit retained',
        candidate_layout='horizontal; complete logical page retained in a visible scrolling viewport when narrow',
        gaps=handoff['gaps'],actual_user_session=handoff['actual_user_session'],
        user_desktop_root_cause='NOT_CONFIRMED',
        deployment_status='NOT_DEPLOYED_TO_USER_SESSION',
        documentation='integration/docs/application-compatibility.md'))
    (OUT/'integration/compatibility.json').write_text(json.dumps(compatibility,ensure_ascii=False,indent=2)+'\n')
    (OUT/'bin').mkdir()
    (OUT/'bin/server-ime').write_text('#!/usr/bin/python3\nimport runpy\nfrom pathlib import Path\n'
        'runpy.run_path(str(Path(__file__).resolve().parents[1]/"integration/bin/server-ime"),run_name="__main__")\n')
    inventory=[]
    for p in sorted(OUT.rglob('*')):
        if not p.is_file():continue
        rel=str(p.relative_to(OUT));owner=rel.split('/')[0]
        if owner in {'integration','bin'}:owner='platform'
        p.chmod(0o755 if rel in {'bin/server-ime','integration/bin/server-ime'} else 0o644)
        inventory.append(dict(path=rel,employee_id=owner,bytes=p.stat().st_size,sha256=sha(p),mode=oct(p.stat().st_mode&0o777)))
    manifest=dict(schema='server-ime.product-assembly/1',employee_id='platform',version=VERSION,
        verifies=[],entrypoint='bin/server-ime',assembly_root='product',
        feedback_fixes=['custom-only-candidate-presentation','horizontal-candidate-layout',
                        'complete-page-scrollable-viewport','viewport-budget-keeps-all-candidates',
                        'highlight-reveal-after-size-allocation','short-page-scroll-range-shrinks'],
        production_backend='server_ime_engine.platform_adapter.PlatformSession',deterministic=False,
        components=[dict(employee_id='engine',version='0.4.0',path='engine',license='GPL-3.0-or-later'),
                    dict(employee_id='lexicon',format='ime-lexicon-user/1',path='lexicon',
                         code_license='GPL-3.0-or-later',data_license='CC-BY-4.0'),
                    dict(employee_id='interface',version=interface_version,settings_version=1,path='interface',
                         license='GPL-3.0-or-later',license_file='interface/LICENSE',sources_file='interface/SOURCES.md'),
                    dict(employee_id='platform',path='platform',license='MIT'),
                    dict(employee_id='platform',path='integration',license='GPL-3.0-or-later')],
        dependencies=['Python >=3.9','Python GI: IBus 1.0, Gtk 3.0, Gdk 3.0, Gio, GLib',
                      'ibus-daemon >=1.5.25 (managed mode)','X11 display and session D-Bus',
                      'x86_64/glibc 2.34 compatible runtime','Chinese fonts'],
        persistent_paths={'config':'--config / SERVER_IME_CONFIG / XDG_CONFIG_HOME/server-ime/settings.json',
                          'learning':'--data-dir/learning (UserStore sole writer)',
                          'state':'--state-dir (private control socket, status, process logs)'},
        preserve_on_upgrade=['configuration','learning'], files=inventory,
        deployment_status='NOT_DEPLOYED_TO_USER_SESSION',
        application_compatibility='product/integration/compatibility.json',
        check_browser_included=False,
        downstream_employee_id='delivery',
        downstream_contract='Wrap this product root in delivery ime-bundle/1; this inventory is not an installer manifest.')
    (BUILD/'component-delivery.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    archive=BUILD/f'server-ime-product-{VERSION}.tar.gz'
    with archive.open('wb') as raw,gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=1793145600) as gz:
        with tarfile.open(fileobj=gz,mode='w') as tar:
            for p in [BUILD/'component-delivery.json']+sorted(OUT.rglob('*')):
                if not p.is_file():continue
                info=tar.gettarinfo(str(p),str(p.relative_to(BUILD)))
                info.uid=info.gid=0;info.uname=info.gname='';info.mtime=1793145600
                with p.open('rb') as stream:tar.addfile(info,stream)
    archive.with_suffix('.gz.sha256').write_text(sha(archive)+'  '+archive.name+'\n')
    print(json.dumps(dict(employee_id='platform',archive=str(archive),sha256=sha(archive),files=len(inventory))))

if __name__=='__main__':main()
