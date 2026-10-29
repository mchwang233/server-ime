"""Record actual native behavior before defining the public adapter."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from server_ime_engine.native import Native

root = Path(__file__).resolve().parents[1]
n = Native(root / "vendor/runtime")
c = n.init(str(root / "vendor/runtime/data").encode(), None)
assert c
n.set_options(c, 8 | 128 | 256 | 512)
i = n.alloc_instance(c)
for raw in ["nihao", "woaibeijingtiananmen", "jintiantianqihenhao", "nihaoshijie", "xi'an", "lve", "vv", "a''b", "'"]:
    n.reset(i)
    parsed = n.parse_more_full_pinyins(i, raw.encode())
    if parsed and n.guess_sentence(i):
        n.guess_candidates(i, 0, 1)
        print(raw, 'parsed=', parsed, 'sentence=', n.sentence(i), 'count=',n.count(i))
        print([(k,n.candidate(i,k)[1:]) for k in range(min(10,n.count(i)))])
        if raw == 'nihaoshijie':
            index = next(k for k in range(n.count(i)) if n.candidate(i,k)[1] == '你好')
            p,text,kind=n.candidate(i,index)
            offset=n.choose_candidate(i,0,p)
            n.guess_sentence(i)
            n.guess_candidates(i,offset,1)
            print('partial choose:',text,'offset=',offset,'sentence=',n.sentence(i),'candidates=',[(k,n.candidate(i,k)[1:]) for k in range(min(8,n.count(i)))])
    else: print(raw, 'parsed=', parsed, 'no sentence')
n.free_instance(i)
n.fini(c)
