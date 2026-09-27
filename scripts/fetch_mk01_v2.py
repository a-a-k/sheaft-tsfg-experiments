"""Recover frozen Mk01 plans/scenarios; never rerun CP-SAT for revision tests."""
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.collect_evidence import api, artifact_download


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true': raise SystemExit('Actions only')
    repo='a-a-k/sheaft-tsfg-experiments'
    artifact=api(f'repos/{repo}/actions/artifacts/10909740037')
    assert artifact['name']=='core-38a1d0e827b2fda2119a53aec1e4e1c41823c555' and not artifact['expired']
    root=Path('artifacts/mk01-source-v2');root.mkdir(parents=True, exist_ok=True)
    archive=root/'original-core.zip'
    digest=artifact_download(repo,artifact,archive)
    assert digest=='c80a62bf6f12cd7c9ebf236643f4eab7a7c0707466e408ce5b9c7cd282e8994a'
    selected=[]
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if not ((name.startswith('mk01/input/') or name.startswith('e1x/')) and name.endswith('.json')):continue
            assert '..' not in Path(name).parts and not Path(name).is_absolute()
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
            content=bundle.read(name);path.write_bytes(content)
            selected.append(dict(path=name,sha256=hashlib.sha256(content).hexdigest()))
            if name.startswith('mk01/input/'):
                target=Path('artifacts')/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
    assert (root/'mk01/input/dataset.json').is_file()
    assert all((root/f'e1x/buffer-{cap}/baseline.json').is_file() for cap in (1,2,4))
    (root/'provenance.json').write_text(json.dumps(dict(status='REUSED_UNCHANGED',run_id=36251071903,
        source_commit='38a1d0e827b2fda2119a53aec1e4e1c41823c555',artifact_id=artifact['id'],
        archive_sha256=digest,files=selected),indent=2)+'\n')
    print('Recovered frozen Mk01 and E1X plans:',len(selected),'JSON files')


if __name__=='__main__':main()
