"""Install one pinned SciPy wheel and retain its authoritative package digest."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

assert os.environ.get('GITHUB_ACTIONS')=='true'
root=Path('artifacts/stats-environment');root.mkdir(parents=True,exist_ok=True)
subprocess.run(['python','-m','pip','download','--no-deps','--only-binary=:all:','scipy==1.16.3','--dest',str(root)],check=True)
wheel=next(root.glob('scipy-1.16.3-*.whl'))
with urllib.request.urlopen('https://pypi.org/pypi/scipy/1.16.3/json',timeout=60) as response:metadata=json.load(response)
entry=next(r for r in metadata['urls'] if r['filename']==wheel.name)
with wheel.open('rb') as file:digest=hashlib.file_digest(file,'sha256').hexdigest()
assert digest==entry['digests']['sha256']
subprocess.run(['python','-m','pip','install','--no-deps',str(wheel)],check=True)
import numpy,scipy
assert numpy.__version__=='2.5.3' and scipy.__version__=='1.16.3'
from scipy.stats import t
assert abs(t.sf(0,999)-.5)<1e-15
(root/'versions.json').write_text(json.dumps(dict(numpy=numpy.__version__,scipy=scipy.__version__,
    wheel=wheel.name,sha256=digest,source='https://pypi.org/pypi/scipy/1.16.3/json'),indent=2)+'\n')
