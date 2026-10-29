"""Real-engine mixed typing, lifecycle, privacy and compatibility checks."""
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from server_ime_engine import Engine, EngineError
from server_ime_engine.platform_adapter import PlatformSession
from server_ime_engine.protocol import Service

EVIDENCE = {'employee_id': 'engine', 'verifies': [], 'cases': []}


def items(session, state=None):
    state = state or session.state()
    return [c for page in range((state['candidates']['total'] + session.config.page_size-1)//session.config.page_size)
            for c in session.candidates(page)['items']]


def hashes(path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(path).rglob('*') if p.is_file()}


class CompositionTests(unittest.TestCase):
    def test_actual_keystrokes_and_explicit_selection(self):
        cases = json.loads((ROOT/'data/mixed-keystrokes-v1.json').read_text())['cases']
        with Engine() as e, e.create_session() as s:
            for case in cases:
                with self.subTest(id=case['id']):
                    s.configure({'schema': case.get('schema', 'full_pinyin')})
                    s.set_composition('')
                    states = []
                    for ch in case['input']:
                        # Text insertion API distinguishes typed digits/spaces from selectors.
                        state = s.input_text(ch)
                        states.append(state)
                    self.assertEqual(case['input'], state['input']['text'])
                    candidate = next(c for c in items(s) if c['text'] == case['expected'])
                    result = s.select(candidate['id'])
                    self.assertEqual(case['expected'], result['commits'][0]['text'])
                    self.assertFalse(s.state()['commits'])
                    EVIDENCE['cases'].append({'case': case, 'per_key': states, 'selected': candidate,
                                              'result': result})

    def test_digits_select_or_insert_and_literal_override(self):
        with Engine() as e, e.create_session() as s:
            s.set_composition('nihao')
            self.assertEqual('你好', s.key('1')['commits'][0]['text'])
            s.set_composition('nihaoV')
            self.assertTrue(s.state()['composition']['literal_digits'])
            for key in '2.7':
                state = s.key(key)
                self.assertFalse(state['commits'])
            self.assertEqual('nihaoV2.7', state['input']['text'])
            self.assertEqual('你好V2.7', s.key('space')['commits'][0]['text'])
            s.set_composition('nihao')
            s.input_text('2')
            self.assertEqual('你好2', s.commit()['commits'][0]['text'])
            EVIDENCE['digit_policy'] = state

    def test_partial_selection_literal_span_and_once_only_commit(self):
        with Engine() as e, e.create_session() as s:
            s.set_composition('nihaoLinux6.1shijie')
            first = next(c for c in items(s) if c['text'] == '你好' and c['kind'] == 'phrase')
            state = s.select(first['id'])
            self.assertEqual([], state['commits'])
            self.assertEqual(5, state['input']['selected_length'])
            literal = next(c for c in items(s) if c['text'] == 'Linux6.1' and c['kind'] == 'phrase')
            state = s.select(literal['id'])
            self.assertFalse(state['commits'])
            self.assertEqual(13, state['input']['selected_length'])
            self.assertEqual('你好Linux6.1世界', s.commit()['commits'][0]['text'])
            self.assertFalse(s.commit()['commits'])
            with self.assertRaises(EngineError): s.select(first['id'])

    def test_edits_keep_raw_coordinates_and_expire_candidates(self):
        with Engine() as e, e.create_session() as s:
            state = s.set_composition('nihaoAPI2')
            stale = state['candidates']['items'][0]['id']
            s.key('Left'); s.key('BackSpace')
            s.input_text('X')
            self.assertEqual('nihaoAPX2', s.state()['input']['text'])
            s.edit(5, 8, 'HTTP')
            self.assertEqual('nihaoHTTP2', s.state()['input']['text'])
            s.key('Home'); s.key('Delete'); s.input_text('n')
            s.key('End')
            self.assertEqual('nihaoHTTP2', s.state()['input']['text'])
            self.assertEqual('nihaoHTTP2', s.key('Return')['commits'][0]['text'])
            with self.assertRaises(EngineError): s.select(stale)

    def test_literal_roundtrip_and_atomic_invalid_input(self):
        rng = random.Random(20261028)
        with Engine() as e, e.create_session() as s:
            for _ in range(24):
                raw = ''.join(rng.choice("abcXYZ012._/@-'汉") for _ in range(18))
                state = s.set_composition(raw)
                self.assertEqual(raw, state['input']['text'])
                self.assertEqual(raw, ''.join(p['text'] for p in state['composition']['spans']))
                self.assertEqual(raw, s.commit('literal')['commits'][0]['text'])
            state = s.set_composition('nihaoA2')
            for bad in ('\x00', '\n', '\ud800', 'x'*129, 123):
                with self.assertRaises(EngineError): s.input_text(bad)
                self.assertEqual(state, s.state())
            self.assertEqual('lvse', s.set_input('LÜSE')['input']['text'])
            with self.assertRaises(EngineError): s.set_input('nihao2')

    def test_learning_only_chinese_spans_and_privacy_after_cache(self):
        with tempfile.TemporaryDirectory(prefix='engine-mixed-learning-') as directory:
            path = Path(directory)
            with Engine(user_data_dir=path) as e, e.create_session({'learning': True}) as s:
                e.add_phrase('松湾试验台', "song'wan'shi'yan'tai")
                s.set_composition('songwanshiyantaiAPI7')
                event = s.commit()['commits'][0]
                self.assertEqual('松湾试验台API7', event['text'])
                self.assertTrue(event['learning']['recorded'])
                self.assertFalse(any('API' in r['text'] for r in e._store.snapshot()['entries']))
                s.configure({'learning': False})
                before = hashes(path)
                s.set_composition('nihaoSecret42')
                self.assertFalse(s.commit()['commits'][0]['learning']['recorded'])
                self.assertEqual(before, hashes(path))
                s.configure({'learning': True})
                before = hashes(path)
                for context in ({'purpose': 'password'}, {'purpose': 'pin'}, {'purpose': 8},
                                {'private': True}, {'hints': 1 << 11}):
                    s.set_composition('songwanshiyantaiAPI7')
                    old = s.state()['candidates']['items'][0]['id']
                    state = s.set_context(**context)
                    self.assertFalse(state['input']['text'])
                    with self.assertRaises(EngineError): s.select(old)
                    state = s.set_composition('songwanshiyantaiAPI7')
                    self.assertNotIn('松湾试验台API7', [c['text'] for c in items(s)])
                    event = s.commit()['commits'][0]
                    self.assertFalse(event['learning_eligible'])
                    self.assertFalse(event['learning']['recorded'])
                    self.assertEqual(before, hashes(path))
                    s.set_context()
                EVIDENCE['privacy'] = {'fingerprints_unchanged': True, 'last_event': event}
            with Engine(user_data_dir=path) as e, e.create_session() as s:
                self.assertEqual('松湾试验台API7', s.set_composition('songwanshiyantaiAPI7')['candidates']['items'][0]['text'])
                self.assertFalse(s.config.learning)

    def test_platform_port_prefix_remaining_and_context(self):
        p = PlatformSession()
        try:
            r = p.convert('nihaoAPI2shijie', 14)
            candidate = next(c for c in r.candidates if c.text == '你好')
            result = p.select(candidate.id)
            self.assertEqual(('你好', 'API2shijie', 0), (result.commit, result.remaining, result.cursor))
            r = p.convert(result.remaining, len(result.remaining))
            self.assertEqual('API2世界', p.select(r.candidates[0].id).commit)
            r = p.convert('nihaoA2', 7)
            self.assertTrue(r.literal_digits)
            p.reset()
            with self.assertRaises(EngineError): p.select(r.candidates[0].id)
        finally:
            p.close()

    def test_jsonl_additive_methods(self):
        service = Service()
        def call(op, args):
            r = service.handle({'api_version': '1.0', 'op': op, 'session_id': 'mixed', 'args': args})
            self.assertTrue(r['ok'], r)
            return r['result']
        try:
            call('create', {'session_id': 'mixed'})
            call('set_composition', {'text': 'nihaoHTTP'})
            call('input_text', {'text': '2'})
            self.assertEqual('你好HTTP2', call('commit', {})['commits'][0]['text'])
        finally:
            service.close()

    def test_apostrophe_reading_and_window_offsets(self):
        with tempfile.TemporaryDirectory(prefix='engine-apostrophe-') as directory:
            with Engine(user_data_dir=directory) as e, e.create_session({'learning': True}) as s:
                for raw in ("xi'an", "xi''an", "'xi'an'", "ni'hao'shi'jie'ni'hao'shi'jie"):
                    state = s.set_composition(raw)
                    event = s.commit()['commits'][0]
                    self.assertTrue(event['text'])
                    self.assertFalse(s.state()['commits'])
                s.set_input("xi'an")
                event = s.commit()['commits'][0]
                self.assertTrue(event['learning']['recorded'])
                self.assertEqual('西安', event['text'])


if __name__ == '__main__':
    result = unittest.main(verbosity=2, exit=False).result
    EVIDENCE.update(ok=result.wasSuccessful(), tests=result.testsRun,
                    failures=len(result.failures), errors=len(result.errors))
    if os.environ.get('SERVER_IME_COMPOSITION_EVIDENCE'):
        Path(os.environ['SERVER_IME_COMPOSITION_EVIDENCE']).write_text(
            json.dumps(EVIDENCE, ensure_ascii=False, indent=2) + '\n')
    sys.exit(not result.wasSuccessful())
