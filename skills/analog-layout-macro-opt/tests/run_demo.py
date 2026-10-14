"""Export a synthetic CLI smoke test, not user-layout or PDK evidence."""
import json
import sys
from pathlib import Path
from test_macro_opt import fixture
from macro_opt import digest, optimize, preview

out=Path(sys.argv[1])
if out.exists(): raise ValueError('Choose a new demo directory')
s,r=fixture()
r['align']=[{'axis':'x','macros':['PAIR','MIRROR']}]
r['order']=[{'axis':'y','before':'PAIR','after':'MIRROR','gap_um':1}]
out.mkdir(parents=True)
for name,obj in [('snapshot.json',s),('request.json',r)]:
    (out/name).write_text(json.dumps(obj,indent=2),encoding='utf-8')
result=optimize(s,r)
(out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
(out/'preview.svg').write_text(preview(s,result['candidates'][0]),encoding='utf-8')
print(json.dumps({'case':'SYNTHETIC_NOT_PDK','baseline_area':result['baseline']['area_um2'],
                  'candidate_area':result['candidates'][0]['metrics']['area_um2'],
                  'positions':result['candidates'][0]['positions_um']}))
