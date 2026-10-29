"""delivery: nondefault product data path and real CLI roundtrip, no desktop."""
import json, os, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
PRODUCT=Path(os.environ.get('SERVER_IME_PRODUCT_ROOT', str(ROOT/'delivery/build/0.1.0/payload')))
sys.path[:0]=[str(PRODUCT/p) for p in ('integration/src','engine/src','lexicon/src','platform','interface/src')]
from server_ime_product.runtime import Manager

def main():
    records=[]
    with tempfile.TemporaryDirectory(dir=ROOT/'delivery/.check',prefix='learning-roundtrip-') as tmp:
        root=Path(tmp); data=root/'nondefault-product-data'; learning=data/'learning'
        manager=Manager(root/'settings.json',data)
        controller=manager.create_controller(manager.create_session(),'delivery-roundtrip',lambda s:None,lambda t:None)
        controller.enable(); controller.focus_in()
        manager.state_service=type('State',(),{'controllers':{'delivery':controller}})()
        def cli(*args):
            cmd=[sys.executable,str(ROOT/'lexicon/bin/lexicon'),'--data-dir',str(learning),*args]
            r=subprocess.run(cmd,capture_output=True,text=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
            records.append({'command':cmd,'returncode':r.returncode,'output':r.stdout,'stderr':r.stderr})
            assert r.returncode==0,records[-1]
        def candidates():
            manager.dispatch({'op':'reload-lexicon'})
            for ch in 'ce shi xing he'.replace(' ',''): controller.key(ord(ch),0,0)
            result=[c.text for c in controller.conversion.candidates]
            records.append({'candidates':result})
            controller.reset()
            return result
        try:
            phrase='测式星河'
            cli('phrase','add',phrase,'ce shi xing he','--count','500')
            assert phrase in candidates()
            cli('export','--out',str(root/'export.json'))
            cli('phrase','remove',phrase)
            assert phrase not in candidates()
            cli('import',str(root/'export.json'))
            assert phrase in candidates()
            cli('verify')
        finally: controller.close();manager.probe.close()
    print(json.dumps({'employee_id':'delivery','result':'PASS','scope':'real product Manager/controller reload and CLI; no GUI','steps':records},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
