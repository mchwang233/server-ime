#!/usr/bin/python3
"""employee_id=platform. Reproduce actual engine/interface config disagreement."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'interface/src'), str(ROOT / 'engine/src')]
from ime_interface import config
from server_ime_engine import Engine

def main():
    caps = config.Capabilities(Engine.capabilities())
    evidence = {'employee_id': 'platform', 'owner': 'interface', 'cases': []}
    cases = [('unsupported-double-scheme', {'schema': 'double_pinyin', 'double_pinyin_scheme': 'mspy'}),
             ('unknown-fuzzy-rule', {'fuzzy': {'enabled': True, 'rules': ['not-a-rule']}}),
             ('learning-without-data-directory', {'learning': True})]
    for name, patch in cases:
        settings = config.defaults()
        settings['input'].update(patch)
        normalized, errors = config.validate(settings, caps)
        row = {'case': name, 'interface_errors': errors, 'patch': config.engine_patch(normalized, caps)}
        try:
            config.apply_engine(normalized, caps=caps)
            row['engine_accepted'] = True
        except config.ConfigError as exc:
            row['engine_accepted'] = False
            row['engine_errors'] = exc.errors
        evidence['cases'].append(row)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
