#!/usr/bin/env python3
"""Install/relocate and exercise the real bundled protocol in isolated storage."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'checks/mixed-revision'

def req(op,args=None,sid='portable'):
    return {'api_version':'1.0','op':op,'session_id':sid,'args':args or {}}


def run(exe,store,requests,cwd):
    env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
    env['PYTHONNOUSERSITE']='1';env['PYTHONDONTWRITEBYTECODE']='1'
    result=subprocess.run([str(exe),'--user-data-dir',str(store)],input=''.join(json.dumps(x)+'\n' for x in requests),
                          cwd=cwd,env=env,text=True,capture_output=True,timeout=30,check=True)
    responses=[json.loads(x) for x in result.stdout.splitlines()]
    assert len(responses)==len(requests)
    assert all(x['ok'] for x in responses),responses
    return responses,result.stderr


def main():
    with tempfile.TemporaryDirectory(prefix='engine-install-',dir=ROOT/'build') as directory:
        scratch=Path(directory);prefix=scratch/'prefix';moved=scratch/'moved'
        install=subprocess.run(['cmake','--install',str(ROOT/'build'),'--prefix',str(prefix)],
                               capture_output=True,text=True,check=True)
        (OUT/'cmake-install.log').write_text(install.stdout+install.stderr)
        prefix.rename(moved)
        exe=moved/'bin/server-ime-engine';store=scratch/'user'
        requests=[req('capabilities'),req('create',{'session_id':'portable','config':{'learning':True}}),
                  req('set_input',{'text':'shishi'}),req('key',{'key':'2'}),req('set_input',{'text':'shishi'}),
                  req('add_phrase',{'text':'星河试验站','pinyin':"xing'he'shi'yan'zhan"}),
                  req('set_input',{'text':'xingheshiyanzhan'}),req('set_context',{'purpose':'password'}),
                  req('set_input',{'text':'xingheshiyanzhan'})]
        rows,stderr=run(exe,store,requests,scratch)
        chosen=rows[3]['result']['commits'][0]
        assert chosen['learning']['recorded']
        assert rows[4]['result']['candidates']['items'][0]['text']==chosen['text']
        assert rows[6]['result']['candidates']['items'][0]['text']=='星河试验站'
        assert rows[8]['result']['candidates']['items'][0]['text']!='星河试验站'
        repeat,stderr2=run(exe,store,[req('create',{'session_id':'portable'}),req('set_input',{'text':'shishi'}),
                                     req('configure',{'patch':{'schema':'double_pinyin'}}),
                                     req('set_input',{'text':'nihk'}),req('commit'),
                                     req('configure',{'patch':{'schema':'full_pinyin'}}),
                                     req('set_input',{'text':'shanghaiijiaotong'}),req('commit')],scratch)
        assert repeat[1]['result']['candidates']['items'][0]['text']==chosen['text']
        assert repeat[4]['result']['commits'][0]['text']=='你好'
        assert repeat[-1]['result']['commits'][0]['text']=='上海交通'
        assert not repeat[0]['result']['config']['learning']
        mixed,stderr3=run(exe,store,[req('create',{'session_id':'portable'}),
                                    req('set_composition',{'text':'nihaoHTTP'}),
                                    req('input_text',{'text':'2'}),req('commit'),
                                    req('set_context',{'purpose':'password'}),
                                    req('set_composition',{'text':'xingheshiyanzhanAPI7'}),req('commit')],scratch)
        assert mixed[3]['result']['commits'][0]['text']=='你好HTTP2'
        assert '星河试验站' not in mixed[-1]['result']['commits'][0]['text']
        assert not mixed[-1]['result']['commits'][0]['learning_eligible']
        assert not prefix.exists()
        result={'employee_id':'engine','ok':True,'relocated':True,'separate_process_restart':True,
                'base_path':str(moved/'share/server-ime/engine/data/lexicon'),
                'personal_store_outside_payload':True,'requests':requests,'responses':rows,'restart_responses':repeat,
                'mixed_restart_responses':mixed,'native_diagnostic':stderr+stderr2+stderr3,
                'bundle_sha256':hashlib.sha256((ROOT/'build/server-ime-engine-0.4.0.tar.gz').read_bytes()).hexdigest()}
        (OUT/'install-relocation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'employee_id':'engine','ok':True,'checks':['cmake_install','relocation','bundled_lexicon',
                     'jsonl_api1','learning','privacy','separate_process_persistence','ziranma','correction']}))


if __name__=='__main__':main()
