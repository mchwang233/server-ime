"""Behavior of extra candidates, outside the frozen evaluation answers."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from server_ime_engine import Engine, EngineError
from server_ime_engine.platform_adapter import PlatformSession

EVIDENCE = {'employee_id': 'engine', 'verifies': [], 'cases': []}


def top(state):
    return [c['text'] for c in state['candidates']['items']]


def fingerprint(path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(path).rglob('*') if p.is_file()}


class QualityRevision(unittest.TestCase):
    def test_platform_port_corrected_full_commit_has_no_remainder(self):
        port = PlatformSession()
        try:
            raw = 'shanghaiijiaotong'
            conversion = port.convert(raw, len(raw))
            selected = port.select(conversion.candidates[0].id)
            self.assertEqual('上海交通', selected.commit)
            self.assertEqual('', selected.remaining)
            self.assertEqual(0, selected.cursor)
            self.assertEqual((), port.convert('', 0).candidates)
        finally:
            port.close()

    def test_named_edit_rules_disable_and_commit(self):
        examples = [('transpose', 'huanyingguanglni', '欢迎光临'),
                    ('delete', 'shanghaiijiaotong', '上海交通'),
                    ('insert', 'shanghijiaotong', '上海交通'),
                    ('substitute', 'huanyingguanglim', '欢迎光临')]
        with Engine() as e, e.create_session() as s:
            for rule, raw, expected in examples:
                with self.subTest(rule=rule):
                    s.configure({'correction': {'enabled': False, 'rules': [rule]}})
                    before = s.set_input(raw)
                    s.configure({'correction': {'enabled': True, 'rules': [rule]}})
                    after = s.set_input(raw)
                    candidate = next(c for c in after['candidates']['items'] if c['text'] == expected)
                    self.assertTrue(candidate['annotation'].startswith('纠错'))
                    commit = s.select(candidate['id'])
                    self.assertEqual(expected, commit['commits'][0]['text'])
                    self.assertEqual(raw, commit['commits'][0]['input'])
                    self.assertEqual([], s.commit()['commits'])
                    self.assertNotEqual(top(before)[0], expected)
                    EVIDENCE['cases'].append({'rule': rule, 'before': before, 'after': after,
                                              'commit': commit})

    def test_unparsed_repair_literal_stale_and_partial(self):
        with Engine() as e, e.create_session() as s:
            raw = 'shanghaiijiaotong'
            r = s.set_input(raw)
            self.assertLess(r['input']['parsed_length'], len(raw))
            old = r['candidates']['items'][0]['id']
            self.assertEqual('上海交通', s.commit()['commits'][0]['text'])
            with self.assertRaises(EngineError):
                s.select(old)
            s.set_input(raw)
            self.assertEqual(raw, s.commit('literal')['commits'][0]['text'])
            r = s.set_input(raw)
            partial = next(c for c in r['candidates']['items'] if c['text'] == '上海')
            r = s.select(partial['id'])
            self.assertEqual([], r['commits'])
            self.assertEqual(raw[r['input']['selected_length']:], r['preedit']['text'][2:])
            self.assertTrue(r['preedit']['text'].endswith('jiaotong'))

    def test_corrected_reading_persists_learning_off_and_sensitive(self):
        with tempfile.TemporaryDirectory(prefix='engine-repair-learning-') as directory:
            path = Path(directory)
            with Engine(user_data_dir=path) as e, e.create_session({'learning': True}) as s:
                s.set_input('shanghaiijiaotong')
                event = s.commit()['commits'][0]
                self.assertTrue(event['learning']['recorded'])
                row = next(x for x in e._store.snapshot()['entries'] if x['text'] == '上海交通')
                self.assertEqual("shang'hai'jiao'tong", row['pinyin'])
                e.add_phrase('湖光试验台', "hu'guang'shi'yan'tai")
                self.assertIn('湖光试验台', top(s.set_input('huguangshiyanttai')))
                snapshot = fingerprint(path)
                for purpose in ('password', 'pin', 'unknown-purpose'):
                    s.set_context(purpose=purpose)
                    state = s.set_input('huguangshiyanttai')
                    self.assertNotIn('湖光试验台', top(state))
                    event = s.commit()['commits'][0]
                    self.assertFalse(event['learning']['recorded'])
                    self.assertFalse(event['learning_eligible'])
                    self.assertEqual(snapshot, fingerprint(path))
                s.set_context(purpose='text')
                s.configure({'learning': False})
                snapshot = fingerprint(path)
                s.set_input('huanyingguanglni')
                self.assertFalse(s.commit()['commits'][0]['learning']['recorded'])
                self.assertEqual(snapshot, fingerprint(path))
            with Engine(user_data_dir=path) as e, e.create_session() as s:
                self.assertFalse(s.config.learning)
                self.assertEqual('上海交通', top(s.set_input('shanghaijiaotong'))[0])
                self.assertEqual('湖光试验台', top(s.set_input('huguangshiyantai'))[0])

    def test_valid_spelling_and_double_pinyin_are_not_corrected(self):
        with Engine() as e, e.create_session() as s:
            for raw in ('shanghaijiaotong', 'huanyingguanglin', "shang'hai'jiao'tong"):
                r = s.set_input(raw)
                self.assertFalse(any(c['annotation'].startswith('纠错') for c in r['candidates']['items']))
            s.configure({'schema': 'double_pinyin'})
            r = s.set_input('nihkuijx')
            self.assertEqual('你好世界', top(r)[0])
            self.assertFalse(any(c['annotation'].startswith('纠错') for c in r['candidates']['items']))

    def test_alternative_sentence_selection_does_not_mutate_raw(self):
        with Engine() as e, e.create_session() as s:
            raw = 'shanghaijiaotong'
            r = s.set_input(raw)
            # libime's second whole-sentence reading (libpinyin needed 首音节约束 decoding for one).
            alternative = [c for c in r['candidates']['items'] if c['kind'] == 'sentence'][1]
            self.assertEqual(raw, r['input']['text'])
            committed = s.select(alternative['id'])['commits'][0]
            self.assertEqual(alternative['text'], committed['text'])
            self.assertEqual(raw, committed['input'])
            EVIDENCE['cases'].append({'alternative': r, 'committed': committed})


if __name__ == '__main__':
    result = unittest.main(verbosity=2, exit=False).result
    EVIDENCE.update(ok=result.wasSuccessful(), tests=result.testsRun,
                    failures=len(result.failures), errors=len(result.errors))
    if os.environ.get('SERVER_IME_REVISION_EVIDENCE'):
        Path(os.environ['SERVER_IME_REVISION_EVIDENCE']).write_text(
            json.dumps(EVIDENCE, ensure_ascii=False, indent=2) + '\n')
    sys.exit(not result.wasSuccessful())
