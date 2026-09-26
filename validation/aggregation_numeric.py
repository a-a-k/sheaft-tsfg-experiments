"""Reproduce and repair the G2/S1 unit mismatch on a preserved million-op input."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.aggregation import run
from experiments.scale_data import sha256


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
    source=Path('reference/dataset/input.bin')
    manifest=json.loads(Path('reference/dataset/manifest.json').read_text())
    assert manifest['dataset_id']=='F1-DENSE-N1000000-M200-s101'
    assert sha256(source)==manifest['files']['input.bin']
    root=Path('artifacts/g2-numeric');root.mkdir(parents=True,exist_ok=True)
    scenario=root/'scenario.json';scenario.write_text(json.dumps([dict(id='M0',failures=[],work_overrides=[])]))
    results={};measurements=[]
    for variant,binary in (('v1','.private/runtime/tsfg-g2-v1'),('v2','.private/runtime/tsfg')):
        for mode in ('MISSION','DIAGNOSTIC'):
            horizon=manifest['metadata']['D_ticks']*(10 if mode=='DIAGNOSTIC' else 1)
            rows,record=run('tsfg-agg',source,scenario,root/f'{variant}-{mode}.jsonl',horizon,mode,
                            binary_override=binary)
            assert record['status']=='OK' and len(rows)==1
            results[variant+'-'+mode]=rows[0];measurements.append(dict(record,variant=variant))
    for mode in ('MISSION','DIAGNOSTIC'):
        old,new=results['v1-'+mode],results['v2-'+mode]
        assert old['cmax'] is None and not old['completion_known'],'Legacy defect did not reproduce'
        assert new['completion_known'] and new['mission_success']
        assert new['produced']==100000 and new['incomplete_jobs']==0
        assert new['cmax']<=manifest['metadata']['D_ticks']
        assert abs(new['fluid_produced']-100000)<1e-8
        assert new['material_balance_max_abs']<1e-3
    assert results['v2-MISSION']['cmax']==results['v2-DIAGNOSTIC']['cmax']
    summary=dict(status='PASS',dataset_id=manifest['dataset_id'],input_sha256=sha256(source),
        failure='S1 epsilon 1e-6 dropped sub-micro-job external transfers in G2 v1',
        correction='Power-of-two internal volume rescaling; sum work before dividing by jobs',
        original_kernel_changed=False,results=results,measurements=measurements)
    (root/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(dict(status=summary['status'],old_cmax=results['v1-DIAGNOSTIC']['cmax'],
                         corrected_cmax=results['v2-DIAGNOSTIC']['cmax'])))


if __name__=='__main__':main()
