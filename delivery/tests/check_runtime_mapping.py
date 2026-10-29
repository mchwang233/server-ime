"""Map release runtime to application-tested integration inventory."""
import hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parents[2]
payload=R/'delivery/build/0.1.0/payload'
tested=R/'integration/build/product'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
evidence=R/'integration/evidence/run-20261029-000050/tested-runtime-hashes.json'
rows=[{'path':r['path'],'tested_sha256':r['sha256'],'release_sha256':sha(payload/r['path'])}
      for r in json.loads(evidence.read_text())['runtime_files']]
assert rows and all(r['tested_sha256']==r['release_sha256'] for r in rows)
print(json.dumps({'employee_id':'delivery','result':'PASS','evidence':'integration/evidence/run-20261029-000050','inventory_evidence':'integration/checks/punctuation-inventory.json','files':rows},indent=2))
