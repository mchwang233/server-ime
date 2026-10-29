#!/usr/bin/python3
"""Validate assembly bytes, tested runtime identity and a relocated real engine."""
import ast
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'integration/build'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'integration/checks/mixed-revision-inventory.json')
    args = parser.parse_args()
    evidence = dict(employee_id='platform', verifies=[], result='FAIL', checks=[])
    try:
        manifest = json.loads((BUILD/'component-delivery.json').read_text())
        root = BUILD/'product'
        expected = {r['path']: r for r in manifest['files']}
        actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
        assert actual == set(expected), (actual-set(expected), set(expected)-actual)
        for name, row in expected.items():
            p = root/name
            assert sha(p) == row['sha256'] and p.stat().st_size == row['bytes'], name
            assert oct(p.stat().st_mode & 0o777) == row['mode'], name
        evidence['checks'].append(dict(name='full-file-inventory', result='PASS', files=len(actual)))
        for required in ['interface/LICENSE', 'interface/SOURCES.md', 'engine/LICENSE',
                         'platform/LICENSE', 'integration/LICENSE', 'bin/server-ime',
                         'engine/vendor/libpinyin-2.6.0.tar.gz', 'lexicon/SOURCES.md']:
            assert required in actual, required
        assert all(not any(part in {'tests','checks','evidence','__pycache__','browser-runtime'}
                           for part in Path(name).parts) for name in actual)
        assert not {'platform/server_ime/deterministic.py', 'platform/server_ime/service.py',
                    'interface/config/capabilities-fixture.json'} & actual
        for name in actual:
            if name.endswith('.py'):
                tree = ast.parse((root/name).read_text(), filename=name)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        assert not node.module or 'deterministic' not in node.module, name
                    if isinstance(node, ast.Import):
                        assert all('deterministic' not in alias.name for alias in node.names), name
        evidence['checks'].append(dict(name='licenses-and-production-only-runtime', result='PASS'))
        handoff = json.loads((ROOT/'integration/handoff.json').read_text())
        assert handoff['version'] == manifest['version'], 'Handoff/manifest version mismatch'
        compatibility = json.loads((root/'integration/compatibility.json').read_text())
        assert compatibility['version'] == compatibility['product_version'] == manifest['version']
        assert compatibility['evidence'] == handoff['checks']['assembled']
        assert compatibility['checks'] == compatibility['current_checks'] == handoff['checks']
        source_runtime = [name for name in actual if name.endswith('.py') or
                          name.startswith('interface/config/') or name == 'integration/bin/server-ime']
        for name in source_runtime:
            assert sha(ROOT/name) == expected[name]['sha256'], ('source-runtime-drift', name)
        evidence['checks'].append(dict(name='source-runtime-and-metadata-consistent', result='PASS',
                                      files=len(source_runtime)))
        run = ROOT/handoff['checks']['assembled']
        run_summary = json.loads((run/'summary.json').read_text())
        assert run_summary['result'] == 'PASS' and run_summary['runtime_unchanged_during_run']
        tested = json.loads((run/'tested-runtime-hashes.json').read_text())['runtime_files']
        assert tested == json.loads((run/'runtime-hashes-after.json').read_text())['runtime_files']
        for row in tested:
            assert sha(root/row['path']) == row['sha256'], row['path']
        evidence['checks'].append(dict(name='same-runtime-as-successful-application-run', result='PASS',
                                      files=len(tested), evidence=str(run.relative_to(ROOT))))
        feedback = ROOT/handoff['checks']['feedback']['path']
        feedback_summary = json.loads((feedback/'summary.json').read_text())
        assert feedback_summary['result'] == 'PASS' and feedback_summary['runtime_unchanged_during_run']
        feedback_tested = json.loads((feedback/'tested-runtime-hashes.json').read_text())['runtime_files']
        assert feedback_tested == json.loads((feedback/'runtime-hashes-after.json').read_text())['runtime_files']
        for row in feedback_tested:
            assert sha(root/row['path']) == row['sha256'], row['path']
        for route in ('managed', 'existing'):
            assert json.loads((feedback/route/'summary.json').read_text())['result'] == 'PASS'
            observations = json.loads((feedback/route/'observations.json').read_text())
            for app in ('editor', 'browser'):
                for selection in ('default-mouse', 'default-digit', 'page-mouse', 'page-digit'):
                    assert any(r.get('application') == app and r.get('check') ==
                               selection+'-horizontal-single-row' and r.get('result') == 'PASS'
                               for r in observations), (route, app, selection)
        evidence['checks'].append(dict(name='same-runtime-as-successful-horizontal-feedback',
            result='PASS', files=len(feedback_tested), evidence=str(feedback.relative_to(ROOT))))
        for route in ('managed-narrow', 'existing-narrow'):
            summary = json.loads((feedback/route/'summary.json').read_text())
            assert summary['result'] == 'PASS' and summary['screen'] == [360, 960], summary
            observations = json.loads((feedback/route/'observations.json').read_text())
            checks = {r['check']: r for r in observations if r.get('result') == 'PASS'}
            for name in ('nine-candidates-retained', 'logical-pages-complete',
                         'scrolled-tail-mouse-full-text', 'scrolled-tail-digit-full-text',
                         'last-page-mouse-full-text', 'last-page-digit-full-text',
                         'short-page-range-roundtrip',
                         'focus-hides-and-rejects-stale-candidate'):
                assert 'narrow-'+name in checks, (route, name)
                assert checks['narrow-'+name]['fixture'] is False
            complete = checks['narrow-logical-pages-complete']
            assert complete['all_ids'] == complete['visited_ids']
            assert complete['page_sizes'][0] == 9 and len(complete['page_sizes']) > 1
            channels = summary['framework_signals']
            assert channels['UpdateLookupTable']['visible_true'] == 0
            assert channels['UpdateAuxiliaryText']['visible_true'] == 0
            assert channels['visible_application_preedit'] > 0
            for page_size, max_visible in ((9, 3), (5, 1)):
                label = f'narrow-budget-{page_size}-{max_visible}'
                saved = checks[label+'-settings-saved']['persisted_settings']
                assert saved['input']['page_size'] == page_size and saved['panel']['max_visible'] == max_visible
                assert label+'-paging-preserves-size' in checks
                highlight = checks[label+'-highlight-after-manual-scroll']
                selected = highlight['after']['rows'][highlight['target']]
                assert highlight['fixture'] is False and selected['selected'] and selected['in_view']
                assert highlight['after']['metrics']['scroll']['value'] < highlight['before']['metrics']['scroll']['value']
                for page in (0, 1):
                    for method in ('mouse', 'digit'):
                        row = checks[label+f'-page-{page}-'+method+'-full-text']
                        assert row['fixture'] is False and row['ids'] == row['visited_ids']
                        assert len(row['ids']) == page_size and row['candidate_id'] == row['ids'][-1]
            for label in ('narrow-', 'narrow-budget-9-3-', 'narrow-budget-5-1-'):
                row = checks[label+'short-page-range-roundtrip']
                assert row['fixture'] is False
                full, short, end, returned = (row[k] for k in ('full','short','end','returned'))
                assert short['metrics']['content_natural_width'] < full['metrics']['content_natural_width']
                assert short['metrics']['scroll']['upper'] < full['metrics']['scroll']['upper']
                assert returned['metrics']['ids'] == full['metrics']['ids']
                assert returned['metrics']['scroll']['upper'] == full['metrics']['scroll']['upper']
                assert returned['rows'][0]['selected'] and returned['rows'][0]['in_view']
                scroll = end['metrics']['scroll']
                assert scroll['upper'] == max(scroll['page_size'], end['metrics']['content_natural_width'])
                assert 0 <= scroll['value'] <= max(0, scroll['upper']-scroll['page_size'])
                assert end['rows'][-1]['in_view'] and end['metrics']['in_view']
        evidence['checks'].append(dict(name='real-narrow-viewport-and-complete-logical-pages',
            result='PASS', screen=[360,960], font_scale=3.0, fixture=False,
            evidence=str(feedback.relative_to(ROOT))))
        evidence['checks'].append(dict(name='saved-viewport-budgets-preserve-full-page-and-selection',
            result='PASS', combinations=[[9,3],[5,1]], pages_per_combination=2,
            routes=['managed','existing'], selection_methods=['mouse','digit'], fixture=False))
        evidence['checks'].append(dict(name='layout-highlight-and-short-page-range', result='PASS',
            routes=['managed','existing'], combinations=[[9,9],[9,3],[5,1]], fixture=False))
        frozen = json.loads((ROOT/handoff['fixed_assembly']['audit']).read_text())
        assert frozen['result'] == 'PASS' and frozen['all_pinned_files_unchanged']
        assert frozen['historical_packages_unchanged'] and frozen['failure_evidence_unchanged']
        pinned = json.loads((ROOT/handoff['fixed_assembly']['before']).read_text())
        pinned_files = {r['path']: r for r in pinned['files']}
        assert set(expected) == set(pinned_files)
        metadata_only = {'integration/README.md', 'integration/docs/application-compatibility.md',
                         'integration/compatibility.json'}
        finalized_changes = {name for name, row in expected.items() if row != pinned_files[name]}
        assert finalized_changes <= metadata_only, ('changed-after-successful-run', finalized_changes)
        evidence['checks'].append(dict(name='final-archive-runtime-identical-to-fixed-assembly',
            result='PASS', unchanged_files=len(expected)-len(finalized_changes),
            metadata_changes=sorted(finalized_changes)))
        for path in (run, feedback):
            recorded = json.loads((path/'tested-runtime-hashes.json').read_text())
            assert recorded['product_root'] == frozen['product_root']
        evidence['checks'].append(dict(name='build-completed-before-fixed-runtime-checks', result='PASS',
            product_root=frozen['product_root'], audit=handoff['fixed_assembly']['audit']))
        for row in handoff['historical_packages']:
            assert sha(ROOT/row['path']) == row['sha256'], row['path']
        evidence['checks'].append(dict(name='historical-packages-preserved', result='PASS',
                                      files=len(handoff['historical_packages'])))
        archive = BUILD / ('server-ime-product-' + manifest['version'] + '.tar.gz')
        archive_hash = sha(archive)
        assert archive_hash == archive.with_suffix('.gz.sha256').read_text().split()[0]
        with tarfile.open(archive) as tar:
            members = tar.getmembers()
            names = [m.name for m in members]
            assert len(names) == len(set(names))
            assert set(names) == {'product/'+p for p in expected} | {'component-delivery.json'}
            for member in members:
                assert member.isfile() and not PurePosixPath(member.name).is_absolute()
                assert '..' not in PurePosixPath(member.name).parts
                data = tar.extractfile(member).read()
                if member.name == 'component-delivery.json':
                    assert data == (BUILD/member.name).read_bytes()
                else:
                    row = expected[member.name.removeprefix('product/')]
                    assert hashlib.sha256(data).hexdigest() == row['sha256'], member.name
                    assert member.mode == int(row['mode'], 8), member.name
            with tempfile.TemporaryDirectory(prefix='relocate-', dir=ROOT/'integration/.runtime') as tmp:
                target = Path(tmp)
                tar.extractall(target)
                relocated = target/'product'
                help_result = subprocess.run([str(relocated/'bin/server-ime'), '--help'],
                                             capture_output=True, text=True, timeout=10)
                assert help_result.returncode == 0, help_result.stderr
                code = '''from pathlib import Path
import sys,json
root=Path(sys.argv[1]);data=Path(sys.argv[2])
sys.path[:0]=[str(root/p) for p in ('integration/src','engine/src','lexicon/src','platform','interface/src')]
import server_ime_engine
from server_ime_product import __version__
from server_ime_product.runtime import Manager
assert Path(server_ime_engine.__file__).is_relative_to(root)
m=Manager(data/'settings.json',data/'personal');commits=[]
c=m.create_controller(m.create_session(),'relocated',lambda s:None,commits.append)
try:
 c.enable();c.focus_in()
 for ch in 'nihaoAPI2shijie':assert c.key(ord(ch),0,0)
 assert c.key(32,0,0) and commits==['你好API2世界'],commits
 for ch in 'nihao?':assert c.key(ord(ch),0,0)
 assert commits==['你好API2世界','你好','？'],commits
 assert not c.composition
 assert not c.session.deterministic
 print(json.dumps(dict(version=m.view()['capabilities']['component_version'],product_version=__version__,commits=commits,mode=c.mode),ensure_ascii=False))
finally:c.close();m.probe.close()
'''
                probe = subprocess.run([sys.executable, '-B', '-I', '-c', code, str(relocated), str(target/'data')],
                                       capture_output=True, text=True, timeout=20)
                assert probe.returncode == 0, probe.stdout+probe.stderr
                outcome = json.loads(probe.stdout)
                assert outcome['version'] == '0.4.0'
                assert outcome['product_version'] == manifest['version']
                evidence['checks'].append(dict(name='relocated-entry-and-real-engine', result='PASS',
                                              scope='programmatic smoke, not a GUI run', **outcome))
        evidence['checks'].append(dict(name='archive-members-and-checksum', result='PASS',
                                      archive=str(archive.relative_to(ROOT)), sha256=archive_hash))
        evidence.update(result='PASS', runtime_files=len(tested), files=len(actual), archive_sha256=archive_hash)
    except Exception as exc:
        evidence['error'] = str(exc)
        raise
    finally:
        args.output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps(evidence, ensure_ascii=False))


if __name__ == '__main__':
    main()
