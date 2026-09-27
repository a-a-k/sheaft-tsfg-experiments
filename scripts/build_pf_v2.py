"""Add one public PF policy after the pinned, audited S1 adapter build."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

assert os.environ.get('GITHUB_ACTIONS')=='true'
subprocess.run(['python','scripts/build_tsfg.py','--upstream-test-evidence','docs/results/mk01/tsfg-provenance.json'],check=True)
source=Path('engines/tsfg_op/fluid_adapter_v2.go')
engine=Path('.private/upstream/engine')
shutil.copyfile(source,engine/'cmd/ozon-engine/fluid_adapter_v2.go')
binary=Path('.private/runtime/tsfg-pf').resolve()
result=subprocess.run(['go','build','-trimpath','-o',str(binary),'./cmd/ozon-engine'],cwd=engine,capture_output=True,text=True)
if result.returncode:
    for line in result.stderr.splitlines():
        if 'fluid_adapter_v2.go:' in line:print(line)
    raise SystemExit('PF build failed; private diagnostics omitted')
root=Path('artifacts/pf');root.mkdir(parents=True,exist_ok=True)
(root/'build.json').write_text(json.dumps(dict(status='PASS',upstream='8510baf28673758f1e437d2dbc5a51ead9843a3b',
    public_policy_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    source_sha=os.environ['GITHUB_SHA'],go_version=subprocess.check_output(['go','version'],text=True).strip(),
    private_executable_published=False),indent=2)+'\n')
