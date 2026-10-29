#!/usr/bin/env python3
"""End-to-end engine/lexicon feature and privacy contracts (real libpinyin)."""
import hashlib
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from server_ime_engine import Engine, EngineError
from server_ime_engine.platform_adapter import PlatformSession
from server_ime_engine.protocol import Service
from server_ime_engine import lexicon_adapter as lx

FUZZY = [('c_ch','cifan','吃饭'), ('s_sh','sijie','世界'), ('z_zh','zongwen','中文'),
         ('f_h','fanguo','韩国'), ('g_k','geji','科技'), ('l_n','lihao','你好'),
         ('l_r','lemen','热门'), ('an_ang','banmang','帮忙'),
         ('en_eng','shenri','生日'), ('in_ing','beijin','北京')]
CORRECTION = [('gn_ng','zhognwen','中文'), ('mg_ng','zhomgwen','中文'),
              ('iou_iu','liou','六'), ('uei_ui','shuei','水'), ('uen_un','luen','论'),
              ('ue_ve','nue','虐'), ('v_u','jv','据'), ('on_ong','zhonwen','中文')]


EVIDENCE = {"employee_id":"engine", "rules":[], "cases":[]}


def fingerprint(directory):
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(directory).rglob('*') if p.is_file()}


def items(session, raw=None):
    state = session.set_input(raw) if raw is not None else session.state()
    return [item for page in range((state['candidates']['total']+session.config.page_size-1)//session.config.page_size)
            for item in session.candidates(page)['items']]


def choose(session, text):
    return session.select(next(x['id'] for x in items(session) if x['text'] == text))


class Features(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = Engine()

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def setUp(self):
        self.s = self.engine.create_session()

    def tearDown(self):
        self.s.close()

    def test_ziranma_sentence_and_zero_initials(self):
        self.s.configure({'schema':'double_pinyin', 'double_pinyin_scheme':'ziranma'})
        for raw, text in [('nihk','你好'), ('vswf','中文'), ('uurufa','输入法'),
                          ('nihkuijx','你好世界'), ('xian','西安'), ('aa','啊'), ('ee','额')]:
            with self.subTest(raw=raw):
                result = self.s.set_input(raw)
                self.assertEqual(len(raw),result['input']['parsed_length'])
                self.assertIn(text, [x['text'] for x in items(self.s)])
                self.assertEqual(text,choose(self.s,text)['commits'][0]['text'])

    def test_ziranma_partial_edit_and_unparsed_suffix(self):
        self.s.configure({'schema':'double_pinyin'})
        self.s.set_input('nihkuijx')
        choose(self.s,'你好')
        self.assertEqual('你好uijx',self.s.state()['preedit']['text'])
        self.assertEqual('你好世界',choose(self.s,'世界')['commits'][0]['text'])
        self.s.set_input('nihk')
        self.s.edit(2,4,'ui')
        self.assertEqual('niui',self.s.state()['input']['text'])
        self.s.set_input('nihkz')
        self.assertEqual('nihkz',self.s.commit('literal')['commits'][0]['text'])

    def test_every_fuzzy_rule_changes_real_candidates(self):
        for rule, raw, target in FUZZY:
            with self.subTest(rule=rule):
                self.s.configure({'fuzzy':{'enabled':False,'rules':[rule]}})
                before = [x['text'] for x in self.s.set_input(raw)['candidates']['items']]
                self.s.configure({'fuzzy':{'enabled':True,'rules':[rule]}})
                after = self.s.set_input(raw)
                self.assertNotIn(target,before)
                self.assertIn(target,[x['text'] for x in after['candidates']['items']])
                committed=choose(self.s,target)['commits'][0]
                self.assertEqual(target,committed['text'])
                EVIDENCE['rules'].append({'rule':rule,'raw':raw,'expected':target,
                    'before':before,'after':after,'commit':committed})

    def test_every_correction_rule_and_disable(self):
        for rule, raw, target in CORRECTION:
            with self.subTest(rule=rule):
                self.s.configure({'correction':{'enabled':False,'rules':[rule]}})
                before = self.s.set_input(raw)
                self.s.configure({'correction':{'enabled':True,'rules':[rule]}})
                after = self.s.set_input(raw)
                self.assertNotIn(target,[x['text'] for x in before['candidates']['items']])
                self.assertIn(target,[x['text'] for x in after['candidates']['items']])
                self.assertEqual(len(raw),after['input']['parsed_length'])
                committed=choose(self.s,target)['commits'][0]
                self.assertEqual(target,committed['text'])
                EVIDENCE['rules'].append({'rule':rule,'raw':raw,'expected':target,
                    'before':before,'after':after,'commit':committed})

    def test_configuration_session_isolation(self):
        with self.engine.create_session({'correction':{'enabled':False}}) as other:
            self.s.configure({'fuzzy':{'enabled':True,'rules':['l_n']},'schema':'double_pinyin'})
            for _ in range(10):
                self.assertEqual('你好',self.s.set_input('lihk')['candidates']['items'][0]['text'])
                self.assertNotEqual('中文',other.set_input('zhognwen')['candidates']['items'][0]['text'])

    def test_invalid_patch_is_atomic(self):
        before=self.s.set_input('nihao')
        for patch in [{'double_pinyin_scheme':'mspy'}, {'fuzzy':{'rules':['unknown']}},
                      {'correction':{'enabled':1}}, {'fuzzy':True},
                      {'fuzzy':{'enabled':True,'rules':['l_n','l_n']}}]:
            with self.assertRaises(EngineError): self.s.configure(patch)
            self.assertEqual(before,self.s.state())

    def test_import_invalidates_ids_and_failure_is_atomic(self):
        with Engine() as e:
            s=e.create_session(); old=s.set_input('tianhedingbiao')['candidates']['items'][0]['id']
            row={'text':'天河定标','pinyin':"tian'he'ding'biao",'count':1000,'kind':'base','source':'functional test only'}
            self.assertEqual(1,e.import_dictionary([row])['accepted'])
            with self.assertRaises(EngineError): s.select(old)
            self.assertIn(row['text'],[x['text'] for x in items(s,'tianhedingbiao')])
            before=s.state()
            with self.assertRaises(EngineError): e.import_dictionary([row,dict(row,pinyin='invalid')])
            self.assertEqual(before,s.state())

    def test_base_data_all_loaded_without_modification(self):
        self.assertEqual(369,self.engine.base_identity['entry_count'])
        # Read the native user table through its iterator, not just capability flags.
        import ctypes as C
        n=self.engine._native.lib
        n.pinyin_begin_get_phrases.argtypes=[C.c_void_p,C.c_uint];n.pinyin_begin_get_phrases.restype=C.c_void_p
        n.pinyin_iterator_has_next_phrase.argtypes=[C.c_void_p];n.pinyin_iterator_has_next_phrase.restype=C.c_bool
        n.pinyin_iterator_get_next_phrase.argtypes=[C.c_void_p,C.POINTER(C.c_void_p),C.POINTER(C.c_void_p),C.POINTER(C.c_int)]
        n.pinyin_iterator_get_next_phrase.restype=C.c_bool
        n.pinyin_end_get_phrases.argtypes=[C.c_void_p]
        it=n.pinyin_begin_get_phrases(self.engine._context,7); pairs=set()
        try:
            while n.pinyin_iterator_has_next_phrase(it):
                text,reading,count=C.c_void_p(),C.c_void_p(),C.c_int()
                self.assertTrue(n.pinyin_iterator_get_next_phrase(it,C.byref(text),C.byref(reading),C.byref(count)))
                pairs.add((C.string_at(text).decode(),C.string_at(reading).decode()))
                self.engine._native.glib.g_free(text);self.engine._native.glib.g_free(reading)
        finally: n.pinyin_end_get_phrases(it)
        self.assertEqual({(x['text'],x['pinyin']) for x in self.engine._base},pairs)


class Personal(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ime-features-')
        self.path=Path(self.tmp.name)/'user'
        self.e=Engine(user_data_dir=self.path)
        self.s=self.e.create_session()

    def tearDown(self):
        self.e.close();self.tmp.cleanup()

    def test_learning_changes_next_ranking_and_restart(self):
        self.s.configure({'learning':True})
        before=self.s.set_input('shishi')
        target=before['candidates']['items'][1]
        event=self.s.select(target['id'])['commits'][0]
        self.assertTrue(event['learning']['recorded'])
        self.assertEqual(target['text'],self.s.set_input('shishi')['candidates']['items'][0]['text'])
        self.e.close()
        with Engine(user_data_dir=self.path) as e:
            state=e.create_session().set_input('shishi')
            self.assertFalse(state['config']['learning'])
            self.assertEqual(target['text'],state['candidates']['items'][0]['text'])

    def test_learning_double_and_correction_canonical_reading(self):
        self.s.configure({'learning':True,'schema':'double_pinyin'})
        self.s.set_input('nihk')
        event=self.s.commit()['commits'][0]
        self.assertEqual("ni'hao",event['learning']['entry']['pinyin'])
        self.s.configure({'schema':'full_pinyin'})
        self.s.set_input('zhognwen')
        event=self.s.commit()['commits'][0]
        self.assertEqual("zhong'wen",event['learning']['entry']['pinyin'])

    def test_learning_off_no_files_change_and_stale_commit_rejected(self):
        self.s.configure({'learning':True})
        state=self.s.set_input('shishi');self.s.select(state['candidates']['items'][1]['id'])
        self.s.configure({'learning':False});before=fingerprint(self.path)
        for raw in ['nihao','zhongwen','shurufa']:
            state=self.s.set_input(raw);cid=state['candidates']['items'][0]['id']
            self.assertFalse(self.s.select(cid)['commits'][0]['learning']['recorded'])
            with self.assertRaises(EngineError): self.s.select(cid)
            self.s.state();self.s.reset()
        self.assertEqual(before,fingerprint(self.path))
        with Engine(user_data_dir=self.path) as e:
            self.assertFalse(e.learning_status()['enabled'])

    def test_master_off_blocks_other_sessions(self):
        self.s.configure({'learning':True})
        with self.e.create_session({'learning':True}) as other:
            other.configure({'learning':False})
            before=fingerprint(self.path)
            self.s.set_input('shishi');event=self.s.commit()['commits'][0]
            self.assertFalse(event['learning']['recorded'])
            self.assertEqual(before,fingerprint(self.path))

    def test_private_password_pin_unknown_and_hint_isolate_and_do_not_write(self):
        self.e.add_phrase('醒禾试研栈',"xing'he'shi'yan'zhan")
        self.s.configure({'learning':True})
        contexts=[{'private':True},{'purpose':'password'},{'purpose':'pin'}, {'purpose':8}, {'purpose':9},
                  {'purpose':'credential'}, {'purpose':99}, {'hints':1<<11}]
        for context in contexts:
            with self.subTest(context=context):
                self.s.set_context()
                old=self.s.set_input('xingheshiyanzhan')['candidates']['items'][0]['id']
                self.assertEqual('醒禾试研栈',self.s.state()['preedit']['preview'])
                self.s.set_context(**context)
                self.assertFalse(self.s.state()['preedit']['visible'])
                with self.assertRaises(EngineError): self.s.select(old)
                before=fingerprint(self.path)
                self.assertNotIn('醒禾试研栈',[x['text'] for x in items(self.s,'xingheshiyanzhan')])
                event=self.s.commit()['commits'][0]
                self.assertFalse(event['learning_eligible'])
                self.assertFalse(event['learning']['recorded'])
                self.assertEqual(before,fingerprint(self.path))

    def test_phrases_live_external_remove_and_sixteen_characters(self):
        phrase='醒禾试研栈醒禾试研栈醒禾试研栈点'
        reading="xing'he'shi'yan'zhan'xing'he'shi'yan'zhan'xing'he'shi'yan'zhan'dian"
        self.e.add_phrase(phrase,reading)
        self.assertEqual(phrase,self.s.set_input(reading.replace("'",''))['candidates']['items'][0]['text'])
        self.assertEqual(phrase,self.s.commit()['commits'][0]['text'])
        external=lx.UserStore(self.path)
        external.add_phrase('醒禾试研栈',"xing'he'shi'yan'zhan")
        self.assertEqual('醒禾试研栈',self.s.set_input('xingheshiyanzhan')['candidates']['items'][0]['text'])
        external.remove_phrase('醒禾试研栈')
        self.assertNotEqual('醒禾试研栈',self.s.set_input('xingheshiyanzhan')['candidates']['items'][0]['text'])

    def test_literal_cancel_preview_partial_do_not_learn(self):
        self.s.configure({'learning':True});before=fingerprint(self.path)
        self.s.set_input('nihaoshijie');choose(self.s,'你好')
        self.assertEqual(before,fingerprint(self.path))
        self.s.reset();self.s.set_input('nihao');self.s.commit('literal')
        self.assertEqual(before,fingerprint(self.path))

    def test_storage_lock_failure_keeps_commit_text(self):
        self.s.configure({'learning':True});self.s.set_input('nihao')
        external=lx.UserStore(self.path)
        with external.lock():
            # No sync needed: underlying data did not change; record_commit fails.
            event=self.s.commit()['commits'][0]
        self.assertEqual('你好',event['text'])
        self.assertFalse(event['learning']['recorded'])
        self.assertEqual('store_locked',event['learning']['error'])

    def test_native_rejected_custom_phrase_does_not_poison_store(self):
        before=fingerprint(self.path)
        with self.assertRaises(EngineError): self.e.add_phrase('嗯','hm')
        self.assertEqual(before,fingerprint(self.path))
        self.assertEqual('你好',self.s.set_input('nihao')['candidates']['items'][0]['text'])

    def test_native_bridge_copies_and_preserves_original(self):
        native=ROOT.parent/'lexicon/build/base-v1/native'
        before=fingerprint(native)
        with Engine(user_dir=native) as e:
            self.assertTrue(e.create_session().set_input('nihao')['candidates']['items'])
        self.assertEqual(before,fingerprint(native))

    def test_platform_context_and_partial_commit_learning(self):
        with tempfile.TemporaryDirectory(prefix='ime-port-') as path:
            session=PlatformSession(user_data_dir=Path(path)/'store',config={'learning':True})
            try:
                c=session.convert('nihaoshijie',11)
                chosen=next(x for x in c.candidates if x.text=='你好')
                self.assertEqual('你好',session.select(chosen.id).commit)
                self.assertEqual(1,session._engine.learning_status()['entries'])
                session.set_context(type('C',(),{'private':False,'purpose':8,'hints':0})())
                before=fingerprint(Path(path)/'store')
                c=session.convert('shishi',6);session.select(c.candidates[1].id)
                self.assertEqual(before,fingerprint(Path(path)/'store'))
            finally: session.close()

    def test_jsonl_new_operations_and_old_fields(self):
        service=Service(user_data_dir=self.path)
        def call(op,args=None,sid=None):
            return service.handle({'api_version':'1.0','op':op,'args':args or {},'session_id':sid})
        try:
            self.assertTrue(call('add_phrase',{'text':'醒禾试研栈','pinyin':"xing'he'shi'yan'zhan"})['ok'])
            self.assertTrue(call('create',{'session_id':'s','config':{'learning':True}})['ok'])
            r=call('set_input',{'text':'xingheshiyanzhan'},'s')['result']
            self.assertEqual('醒禾试研栈',r['candidates']['items'][0]['text'])
            self.assertTrue(call('set_context',{'purpose':'pin'},'s')['ok'])
            self.assertTrue(call('remove_phrase',{'text':'醒禾试研栈'})['ok'])
            self.assertTrue(call('reload_lexicon')['ok'])
            self.assertTrue(call('learning_status')['ok'])
            self.assertFalse(call('import_dictionary',{'entries':[{}]})['ok'])
        finally: service.close()


class MatrixResult(unittest.TextTestResult):
    def addSuccess(self,test):
        super().addSuccess(test)
        EVIDENCE['cases'].append({'case':test.id(),'status':'passed'})
    def addFailure(self,test,error):
        super().addFailure(test,error)
        EVIDENCE['cases'].append({'case':test.id(),'status':'failed'})
    def addError(self,test,error):
        super().addError(test,error)
        EVIDENCE['cases'].append({'case':test.id(),'status':'error'})


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result=unittest.TextTestRunner(verbosity=2,resultclass=MatrixResult).run(suite)
    EVIDENCE.update(ok=result.wasSuccessful(),tests=result.testsRun,
                    failures=len(result.failures),errors=len(result.errors))
    if os.environ.get('SERVER_IME_FEATURE_EVIDENCE'):
        Path(os.environ['SERVER_IME_FEATURE_EVIDENCE']).write_text(json.dumps(EVIDENCE,ensure_ascii=False,indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
