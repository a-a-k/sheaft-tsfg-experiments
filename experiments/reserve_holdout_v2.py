"""Open 1000 new scenarios only after checking the frozen selection artifact."""
import argparse
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sys

import numpy as np
from scipy.stats import t

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.reserve_inputs_v2 import scenario,scaled_scenario,accelerated,evaluate,seed
from experiments.pbr_inputs_v2 import task_hash


def effect(values,indices):
    mean=float(values.mean());sd=0. if np.all(values==values[0]) else float(values.std(ddof=1));n=len(values)
    if sd==0:p=1. if mean<=0 else math.exp(-n*mean**2/2)
    else:p=float(t.sf(mean/(sd/math.sqrt(n)),n-1))
    boots=[]
    for first in range(0,len(indices),500):boots.extend(values[indices[first:first+500]].mean(axis=1).tolist())
    return dict(mean=mean,median=float(np.median(values)),improved_fraction=float(np.mean(values>0)),
        worsened_fraction=float(np.mean(values<0)),unchanged_fraction=float(np.mean(values==0)),
        ci95=np.quantile(boots,[.025,.975],method='linear').tolist(),p_raw=p,sd=sd,
        degenerate=sd==0,test='one-sided paired t-test' if sd else 'bounded conservative exp(-n*mean^2/2), or p=1',
        n=n,bootstrap_replicates=len(indices))


def holm32(values):
    assert len(values)==32 and all(0<=p<=1 for p in values)
    adjusted=[1.]*32;previous=0.
    for rank,index in enumerate(sorted(range(32),key=lambda i:(values[i],i))):
        previous=max(previous,min(1.,(32-rank)*values[index]));adjusted[index]=previous
    return adjusted


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    p=argparse.ArgumentParser();p.add_argument('--selection',type=Path,required=True);p.add_argument('--expected-sha',required=True)
    p.add_argument('--output',type=Path,default=Path('holdout'));args=p.parse_args();root=args.output;root.mkdir(parents=True,exist_ok=True)
    selection_file=args.selection/'selection.json'
    assert hashlib.sha256(selection_file.read_bytes()).hexdigest()==args.expected_sha
    selection=json.loads(selection_file.read_text());assert selection['execution_status']=='COMPLETE' and not selection['holdout_generated']
    assert hashlib.sha256(Path('Sheaft_Execution_Instructions_v2_2_RU.md').read_bytes()).hexdigest()==selection['statistics_spec_sha256']
    data=json.loads((args.selection/'input.json').read_text());assert task_hash(data)==selection['task_sha256']
    jobs=len(data['jobs']);c0=selection['C0']//11;law=selection['law'];configs=selection['configurations']
    deadline=selection['D_fixed'];d_cal=selection['D_cal'];horizon=max(deadline,d_cal or 0)
    bank=[];seeds=[]
    with gzip.open(root/'evaluation-bank.jsonl.gz','wt',compresslevel=1) as file:
        for index in range(1000):
            row,audit=scenario(data,c0,law,'evaluation',index);bank.append(scaled_scenario(row));seeds.append(audit)
            file.write(json.dumps(bank[-1],separators=(',',':'))+'\n')
    (root/'namespace.json').write_text(json.dumps(seeds,indent=2)+'\n')
    records={};status=dict(execution_status='PARTIAL',family=selection['family'],n=selection['n'],law=law,
        selected=selection['selected'],selection_sha256=args.expected_sha,configurations=configs,
        D_fixed=deadline,D_cal=d_cal,observations=0,primary_engine='DES-EXT-v2.2',statistics={},
        hypothesis_status='INCONCLUSIVE',holm_family_size=32)
    try:
        for machine in configs:
            changed=accelerated(data,machine);results=[]
            for start in range(0,1000,25):
                rows,process=evaluate(changed,bank[start:start+25],horizon,'MISSION',root/f'evaluation-{machine}-{start:04d}')
                assert len(rows)==25;results.extend(rows)
            records[str(machine)]=results
            diagnostic,process=evaluate(changed,bank[:5],10*horizon,'DIAGNOSTIC',root/f'diagnostic-{machine}',[row['id'] for row in bank[:5]])
            assert len(diagnostic)==5
        paired=[]
        for i in range(1000):
            item=dict(scenario_id=bank[i]['id'],configurations={})
            for machine in configs:
                row=records[str(machine)][i]
                assert row['scenario_id']==item['scenario_id'] and row['horizon']==horizon
                finishes=row['job_finish']
                item['configurations'][str(machine)]=dict(
                    Q_fixed=sum(value is not None and value<=deadline for value in finishes),
                    Q_cal=sum(value is not None and value<=d_cal for value in finishes) if d_cal is not None else None,
                    completion_known=row['completion_known'],cmax=row['cmax'],completion_lower_bound=row['completion_lower_bound'],
                    run_status=row['run_status'],full_state_sha256=row['full_state_sha256'])
            paired.append(item)
        (root/'paired-evaluation.json').write_text(json.dumps(paired,separators=(',',':'))+'\n')
        rng,bootstrap_seed=seed(selection['task_sha256'],f"reserve_bootstrap:{selection['family']}:{selection['n']}:{law}",'all')
        indices=rng.integers(0,1000,size=(10000,1000),dtype=np.uint16);np.save(root/'bootstrap-indices.npy',indices,allow_pickle=False)
        for name,key in [('D_fixed','Q_fixed'),('D_cal','Q_cal')]:
            if name=='D_cal' and d_cal is None:
                status['statistics'][name]=dict(status='CALIBRATION_UNRESOLVED',base=dict(p_raw=1),load=dict(p_raw=1));continue
            def vector(machine):return np.array([r['configurations'][str(machine)][key]/jobs for r in paired],dtype=float)
            selected=vector(selection['selected']);base=vector(None);load=vector(selection['load_control'])
            status['statistics'][name]=dict(status='COMPLETE',base=effect(selected-base,indices),load=effect(selected-load,indices),
                full_mission_counts={str(m):int(np.sum(vector(m)==1)) for m in configs},
                mean_produced_fraction={str(m):float(vector(m).mean()) for m in configs})
        status.update(execution_status='COMPLETE',observations=1000,bootstrap_seed=bootstrap_seed,
            hypothesis_status='PENDING_GLOBAL_HOLM',numpy_version=np.__version__)
    finally:
        (root/'reserve-statistics.json').write_text(json.dumps(status,indent=2)+'\n')
        print(json.dumps(status))


if __name__=='__main__':main()
