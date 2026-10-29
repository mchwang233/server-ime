"""Focused real-engine regression checks of assembly policy and rollback."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
PRODUCT=Path(os.environ.get('SERVER_IME_PRODUCT_ROOT', str(ROOT))).resolve()
sys.path[:0]=[str(PRODUCT/p) for p in ('integration/src','engine/src','lexicon/src','platform','interface/src')]
from server_ime_product.runtime import Manager

class Assembly(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'integration')
        self.root=Path(self.tmp.name)
        self.m=Manager(self.root/'settings.json',self.root/'data')
        self.commits=[]
        self.c=self.m.create_controller(self.m.create_session(),'own-check',lambda s:None,self.commits.append)
        self.c.enable();self.c.focus_in()
        self.m.state_service=type('State',(),{'controllers':{'own-check':self.c}})()
    def tearDown(self):
        self.c.close();self.m.probe.close();self.tmp.cleanup()
    def type(self,text):
        for ch in text:self.c.key(ord(ch),0,0)
    def test_plain_space_and_mode_modifiers(self):
        self.type('nihao');self.c.key(32,0,0)
        self.assertEqual(self.commits,['你好']);self.assertEqual(self.c.mode,'zh')
        self.assertFalse(self.c.composition)
        self.assertFalse(self.c.snapshot()['candidate_visible'])
        self.c.key(32,0,4);self.assertEqual(self.c.mode,'en')
        self.assertFalse(self.c.snapshot()['candidate_visible'])
        self.assertFalse(self.c.key(ord('a'),0,0))
        self.assertFalse(self.c.key(32,0,4|8));self.assertEqual(self.c.mode,'en')
    def test_failed_save_rolls_back_live_and_learning_switch(self):
        old=copy.deepcopy(self.m.settings);new=copy.deepcopy(old)
        new['input'].update(learning=True,page_size=3)
        # Existing directory at config path makes replace fail after engine apply.
        self.m.path.mkdir()
        with self.assertRaises(OSError):self.m.apply(new)
        self.assertEqual(self.m.settings,old)
        self.assertEqual(self.c.session._session.state()['config']['page_size'],5)
        self.assertFalse(self.m.probe._engine.learning_status()['enabled'])
    def test_existing_and_new_contexts_receive_configuration(self):
        new=copy.deepcopy(self.m.settings);new['input']['page_size']=3
        self.type('ni');self.m.apply(new)
        self.assertFalse(self.c.composition);self.assertEqual(self.c.page_size,3)
        session=self.m.create_session()
        try:self.assertEqual(session._session.state()['config']['page_size'],3)
        finally:session.close()
    def test_legacy_panel_layout_load_save_and_restart(self):
        legacy=copy.deepcopy(self.m.settings);legacy['panel'].pop('layout',None)
        self.m.path.write_text(json.dumps(legacy))
        restored=Manager(self.m.path,self.root/'data')
        try:
            self.assertEqual(restored.settings['panel']['layout'],'horizontal')
            self.assertNotIn('layout',json.loads(self.m.path.read_text())['panel'])
            updated=copy.deepcopy(restored.settings);updated['panel']['font_scale']=1.5
            restored.apply(updated)
            self.assertEqual(json.loads(self.m.path.read_text())['panel']['layout'],'horizontal')
        finally:restored.probe.close()
        restarted=Manager(self.m.path,self.root/'data')
        try:
            self.assertEqual(restarted.settings['panel']['layout'],'horizontal')
            self.assertEqual(restarted.settings['panel']['font_scale'],1.5)
        finally:restarted.probe.close()
    def test_return_binding_and_punctuation_toggle(self):
        new=copy.deepcopy(self.m.settings);new['shortcuts']['commit_raw']='KP_Enter'
        new['punctuation']['chinese']=False;self.m.apply(new)
        self.type('hello');self.assertFalse(self.c.key(0xff0d,0,0));self.assertEqual(self.commits,[])
        self.type('hello');self.assertTrue(self.c.key(0xff8d,0,0));self.assertEqual(self.commits,['hello'])
        self.assertFalse(self.c.key(ord(','),0,0))
    def test_corrupt_config_is_not_overwritten(self):
        self.m.path.write_text('{invalid')
        with self.assertRaises(Exception):Manager(self.m.path,self.root/'data')
        self.assertEqual(self.m.path.read_text(),'{invalid')

    def test_pinyin_sentence_punctuation_without_prior_selection(self):
        for chinese in (True, False):
            settings=copy.deepcopy(self.m.settings)
            settings['punctuation']['chinese']=chinese;self.m.apply(settings)
            for key, mapped in [(',', '，'), ('.', '。'), ('?', '？'), ('!', '！')]:
                with self.subTest(chinese=chinese, key=key):
                    self.c.reset();self.commits.clear();self.type('nihao')
                    self.assertTrue(self.c.key(ord(key),0,1 if key in '?!' else 0))
                    self.assertEqual(self.commits,['你好',mapped if chinese else key],self.c.composition)
                    self.assertFalse(self.c.composition)
                    self.assertFalse(self.c.snapshot()['candidate_visible'])
                    # The release must neither repeat the punctuation nor select.
                    self.assertFalse(self.c.key(ord(key),0,1<<30))
                    self.assertEqual(len(self.commits),2)

    def test_punctuation_respects_highlighted_sentence(self):
        self.type('nihaoma')
        self.c.move(1)
        self.assertEqual(self.c.conversion.candidates[self.c.selected].text,'你号码')
        self.c.key(ord('.'),0,0)
        self.assertEqual(self.commits,['你号码','。'])
        self.assertFalse(self.c.composition)

    def test_punctuation_finishes_partial_candidate_and_suffix_once(self):
        self.type('nihao')
        index=next(i for i,c in enumerate(self.c.conversion.candidates) if c.text=='尼')
        self.c.move(index)
        self.c.key(ord(','),0,0)
        # Fresh hao context ranks 号 first in this pinned engine/lexicon.
        self.assertEqual(self.commits,['尼','号','，'])
        self.assertFalse(self.c.composition)
        self.type('ma');self.c.key(ord('!'),0,1)
        self.assertEqual(''.join(self.commits),'尼号，马！')

    def test_punctuation_keeps_unconvertible_suffix(self):
        self.type('nihaov')
        index=next(i for i,c in enumerate(self.c.conversion.candidates) if c.text=='你')
        self.c.move(index)
        self.c.key(ord('?'),0,1)
        self.assertEqual(''.join(self.commits),'你号v？')
        self.assertFalse(self.c.composition)

    def test_apostrophe_is_a_syllable_separator_before_punctuation(self):
        self.type("xi'an")
        self.assertFalse(self.commits)
        self.assertEqual(self.c.composition,"xi'an")
        self.c.key(ord(','),0,0)
        self.assertEqual(self.commits,['西安','，'])

    def test_address_symbols_and_versions_remain_literal(self):
        for raw in ['nihao@example.org','https://example.org/a?v=2',
                    'User+Tag@Example.org','v2.0','1.2.3']:
            with self.subTest(raw=raw):
                self.commits.clear();self.type(raw)
                self.assertEqual(self.c.composition,raw)
                self.assertFalse(self.commits)
                self.c.key(32,0,0)
                self.assertEqual(self.commits,[raw])

    def test_ambiguous_dot_has_explicit_raw_path(self):
        # KP_Decimal inserts a literal dot even after a valid pinyin syllable.
        self.type('ni');self.c.key(0xFFAE,0,16);self.type('hao@example.org')
        self.assertEqual(self.c.composition,'ni.hao@example.org')
        self.assertFalse(self.commits)
        self.c.key(0xFF0D,0,0)
        self.assertEqual(self.commits,['ni.hao@example.org'])
        self.type('nihao');self.c.key(0xFF0D,0,0)
        self.assertEqual(self.commits[-1],'nihao')
        self.type('nihao')
        index=next(i for i,c in enumerate(self.c.conversion.candidates) if c.text=='nihao')
        self.c.move(index);self.c.key(ord(','),0,0)
        self.assertEqual(self.commits[-2:],['nihao','，'])

    def test_punctuation_inside_edited_composition_does_not_commit(self):
        self.type('nihao');self.c.key(0xFF50,0,0);self.c.key(ord('.'),0,0)
        self.assertFalse(self.commits)
        self.assertEqual(self.c.composition,'.nihao')
        self.c.key(0xFF0D,0,0);self.assertEqual(self.commits,['.nihao'])

    def test_mixed_case_numbers_symbols_without_mode_switch(self):
        for raw, expected in [('nihaoAPI2shijie','你好API2世界'), ('v2.0','v2.0'),
                              ('AbC123','AbC123'), ('User+Tag@Example.org','User+Tag@Example.org'),
                              ('https://Example.org/A?v=2','https://Example.org/A?v=2')]:
            with self.subTest(raw=raw):
                self.type(raw)
                self.assertEqual(self.c.composition, raw)
                self.assertFalse(self.c.error)
                self.c.key(32,0,0)
                self.assertEqual(self.commits[-1], expected)
                self.assertEqual(self.c.mode, 'zh')

    def test_digits_and_explicit_keypad_insertion(self):
        self.type('nihao')
        self.assertFalse(self.c.snapshot()['literal_digits'])
        self.c.key(ord('1'),0,0)
        self.assertEqual(self.commits, ['你好'])
        self.type('nihaoAPI')
        self.assertTrue(self.c.snapshot()['literal_digits'])
        self.type('2');self.assertEqual(self.c.composition,'nihaoAPI2')
        self.c.key(32,0,0);self.assertEqual(self.commits[-1],'你好API2')
        self.type('abc');self.c.key(0xFFB1,0,16);self.type('23')
        self.assertEqual(self.c.composition,'abc123')
        literal=next(c for c in self.c.conversion.candidates if c.text=='abc123')
        self.assertTrue(self.c.select(literal.id));self.assertEqual(self.commits[-1],'abc123')

    def test_raw_coordinate_edits_reject_stale_candidate(self):
        self.type('nihaoAPI2shijix');old=self.c.snapshot()
        self.c.key(0xFF08,0,0);self.type('e')
        self.c.key(0xFF50,0,0);self.c.key(0xFFFF,0,0);self.type('n')
        self.c.key(0xFF57,0,0);self.c.key(0xFF51,0,0);self.c.key(0xFF53,0,0)
        self.assertEqual(self.c.composition,'nihaoAPI2shijie')
        self.assertFalse(self.c.select(old['candidates'][0]['id'],old['revision']))
        self.c.key(32,0,0);self.assertEqual(self.commits,['你好API2世界'])

    def test_partial_prefix_remaining_and_focus_cancellation(self):
        self.type('nihaoLinux6.1shijie')
        for expected,remaining in [('你好','Linux6.1shijie'),('Linux6.1','shijie'),('世界','')]:
            candidate=next(c for c in self.c.conversion.candidates if c.text==expected)
            self.assertTrue(self.c.select(candidate.id))
            self.assertEqual(self.c.composition,remaining)
            self.assertEqual(self.c.cursor,0)
        self.assertEqual(self.commits,['你好','Linux6.1','世界'])
        self.type('nihaoAPI2');old=self.c.snapshot()
        self.c.focus_out();self.c.focus_in()
        self.assertFalse(self.c.select(old['candidates'][0]['id'],old['revision']))
        self.assertFalse(self.c.composition)
        self.assertEqual(self.commits,['你好','Linux6.1','世界'])

    def test_sensitive_mixed_input_bypasses_conversion_and_learning(self):
        new=copy.deepcopy(self.m.settings);new['input']['learning']=True;self.m.apply(new)
        self.type('nihaoAPI2');self.c.key(32,0,0)
        learned=self.root/'data/learning/words.jsonl';before=learned.read_bytes()
        self.type('nihaoAPI2');old=self.c.snapshot()
        self.c.set_content_type(8,0)
        for ch in 'nihaoUser+Tag@Example.org123':
            self.assertFalse(self.c.key(ord(ch),0,0))
        self.assertFalse(self.c.key(0xFFB2,0,16))
        self.assertFalse(self.c.select(old['candidates'][0]['id'],old['revision']))
        self.assertFalse(self.c.composition)
        self.assertFalse(self.c.snapshot()['candidates'])
        self.assertEqual(learned.read_bytes(),before)

    def test_mixed_input_limit_keeps_consumed_text(self):
        self.type('A'*128);self.type('2.@B')
        self.assertEqual(self.c.composition,'A'*128)
        self.assertEqual(self.c.error,'composition-limit-128')
        self.c.key(0xFF0D,0,0);self.assertEqual(self.commits,['A'*128])

if __name__=='__main__':unittest.main(verbosity=2)
