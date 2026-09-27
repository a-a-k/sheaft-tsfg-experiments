"""Prepare the 36 first-stage inputs from immutable original E2 data."""
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.scale_data import read_binary
from experiments.pbr_inputs_v2 import derive,task_hash
from scripts.collect_evidence import api,artifact_download
from scripts.preserve_e4_v2 import digest


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
    root=Path('artifacts/pbr-inputs');root.mkdir(parents=True,exist_ok=True)
    index=json.loads(Path('docs/results/full-study/inputs-index.json').read_text())
    entries=[]
    with tempfile.TemporaryDirectory() as temp:
        temp=Path(temp)
        for n in (1000,10000):
            for family in ('F1','F2'):
                for seed in (101,102,103):
                    identity=f'{family}-DENSE-N{n}-M200-s{seed}'
                    parent=next(r for r in index if r['dataset_id']==identity)
                    artifact=api(f'repos/a-a-k/sheaft-tsfg-experiments/actions/artifacts/{parent["artifact_id"]}')
                    assert artifact_download('a-a-k/sheaft-tsfg-experiments',artifact,temp/'original.zip')==parent['artifact_sha256']
                    with zipfile.ZipFile(temp/'original.zip') as archive:
                        (temp/'input.bin').write_bytes(archive.read('dataset/input.bin'))
                    assert digest(temp/'input.bin')==parent['files']['input.bin']
                    data=read_binary(temp/'input.bin')
                    data['dataset_id']=identity
                    for profile in ('PB','PR','PBR'):
                        case=identity+'-'+profile
                        derived,manifest=derive(data,parent['files']['input.bin'],profile)
                        folder=root/case;folder.mkdir()
                        path=folder/'original.json';path.write_text(json.dumps(derived,separators=(',',':')))
                        record=dict(**manifest,id=case,n=n,family=family,seed=seed,source_artifact=parent['artifact_id'],
                            source_archive_sha256=parent['artifact_sha256'],input_sha256=digest(path),
                            task_sha256=task_hash(derived),batch=len(entries)//6,order=len(entries))
                        (folder/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');entries.append(record)
    assert len(entries)==36
    (root/'pbr-inputs-index.json').write_text(json.dumps(dict(version='2.2',cases=entries,order='n, family, seed, PB/PR/PBR'),indent=2)+'\n')
    print('Prepared 36 fixed cases; pool capacity and demand frozen before nominal evaluation')


if __name__=='__main__':main()
