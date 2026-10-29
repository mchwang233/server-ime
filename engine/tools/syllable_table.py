#!/usr/bin/env python3
"""Reproduce/check the parser alphabet from the pinned source archive, read-only."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'src/storage/pinyin_parser_table.h'
COMMIT = '19d8e9a1e577fb0d93dc9fb51ea982d677331755'


def expected():
    with tarfile.open(ROOT / 'vendor/libpinyin-2.6.0.tar.gz') as tar:
        member = next(m for m in tar.getmembers() if m.name.endswith('/' + SOURCE))
        data = tar.extractfile(member).read()
    section = data.decode().split('const pinyin_index_item_t pinyin_index[] = {', 1)[1].split('};', 1)[0]
    syllables = sorted(set(word for word, flags in re.findall(r'\{"([a-z]+)", ([^,]+),', section)
                           if 'IS_PINYIN' in flags and 'INCOMPLETE' not in flags and 'CORRECT' not in flags))
    return {'schema': 'server-ime-syllables/1', 'source': f'libpinyin/libpinyin@{COMMIT}/{SOURCE}',
            'source_sha256': hashlib.sha256(data).hexdigest(), 'license': 'GPL-3.0-or-later',
            'derivation': 'pinyin_index entries with IS_PINYIN, excluding INCOMPLETE and CORRECT flags; sorted unique spellings; no word or corpus data',
            'syllables': syllables}


def check():
    path = ROOT / 'data/syllables-v1.json'
    assert json.loads(path.read_text()) == expected(), 'syllable data differs from pinned source'
    dependencies = json.loads((ROOT / 'dependencies.json').read_text())
    record = next(r for r in dependencies['derived_data'] if r['file'] == 'data/syllables-v1.json')
    assert record['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    return {'syllables': len(expected()['syllables']), 'ok': True, 'source_commit': COMMIT}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true', help='regenerate from pinned upstream, never from a corpus')
    args = parser.parse_args()
    if args.write:
        (ROOT / 'data/syllables-v1.json').write_text(json.dumps(expected(), ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(check()))
