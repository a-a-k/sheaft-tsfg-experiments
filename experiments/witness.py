"""Preserve selected full million-operation traces for public inspection."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.scale_run import run_one


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
    p=argparse.ArgumentParser()
    p.add_argument('--family',required=True,choices=['F1','F2'])
    p.add_argument('--density',required=True,choices=['DENSE','SPARSE'])
    args=p.parse_args()
    root=Path('artifacts/witness');dataset=root/'dataset'
    subprocess.run([sys.executable,'experiments/scale_data.py','--n','1000000','--family',args.family,
                    '--density',args.density,'--seed','101','--output',str(dataset)],check=True)
    manifest=json.loads((dataset/'manifest.json').read_text())
    frozen=json.loads(Path('reference/dataset/manifest.json').read_text())
    assert manifest['files']==frozen['files'] and manifest['dataset_id']==frozen['dataset_id']
    sc=json.loads((dataset/'scenarios-1000.json').read_text())
    selected=[dict(id='M0',failures=[],work_overrides=[]),sc[0],sc[3]]
    for engine in ('tsfg','des','dag'):
        result=run_one(dataset,engine,3,root/'measurements'/engine,label='public-full-witness',
                       scenarios_override=selected,retain_trace=True)
        assert result['status']=='OK' and result['scenarios_completed']==3
    subprocess.run([sys.executable,'validation/scale_results.py','--dataset',str(dataset),
                    '--results',str(root/'measurements')],check=True)
    validation=json.loads((root/'measurements/validation.json').read_text())
    assert validation['completed_correct']==3
    summary=dict(status='PASS',dataset_id=manifest['dataset_id'],scenarios=[s['id'] for s in selected],
        trajectories=9,operations_per_trajectory=1000000,validation=validation,
        input_matches_frozen_screen=True,scope='Full public control traces; not a replacement H3 timing')
    (root/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))


if __name__=='__main__':main()
