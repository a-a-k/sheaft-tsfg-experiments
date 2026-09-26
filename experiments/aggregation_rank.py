"""G2 sensitivity versus the frozen E4 exact ranking; independent of H5."""
import argparse
import gc
import json
import os
from pathlib import Path
import sys
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.scale_data import make_dataset,write_binary,sha256
from experiments.aggregation import run

def average_ranks(values):
    order=sorted(range(len(values)),key=lambda i:values[i])
    ranks=np.zeros(len(values),dtype=float)
    i=0
    while i<len(order):
        end=i+1
        while end<len(order) and values[order[end]]==values[order[i]]:end+=1
        for k in order[i:end]:ranks[k]=(i+end-1)/2
        i=end
    return ranks

def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
    p=argparse.ArgumentParser()
    p.add_argument('--family',required=True,choices=['F1','F2'])
    p.add_argument('--reference',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args();root=args.output;root.mkdir(parents=True,exist_ok=True)
    reference=json.loads((args.reference/'ranking.json').read_text())
    frozen=json.loads((args.reference/'frozen-interventions.json').read_text())
    assert reference['status']=='PASS'
    data=make_dataset(100000,args.family,'DENSE',101)
    write_binary(data,root/'input.bin')
    assert sha256(root/'input.bin')==frozen['dataset_sha256']
    c0=reference['C0_ticks'];deadline=reference['D_ticks']
    cases=[]
    for row in reference['ranking_rows']:
        m=row['machine']
        for case in row['cases']:
            a,b=case['a'],case['b']
            begin=((c0*a+5000)//10000)*100
            end=max(begin+100,((c0*(a+b)+5000)//10000)*100)
            cases.append(dict(id=f'{m}-{a}-{b}',failures=[[m,begin,end]],work_overrides=[]))
    del data;gc.collect()
    sc=root/'baseline.json';sc.write_text(json.dumps([dict(id='M0',failures=[],work_overrides=[])]))
    baseline,base_measurement=run('tsfg-agg',root/'input.bin',sc,root/'baseline.jsonl',10*deadline,'DIAGNOSTIC')
    assert len(baseline)==1 and baseline[0]['completion_known']
    fluid_c0=baseline[0]['cmax']
    sc=root/'ranking-scenarios.json';sc.write_text(json.dumps(cases))
    rows,measurement=run('tsfg-agg',root/'input.bin',sc,root/'ranking.jsonl',10*deadline,'DIAGNOSTIC',limit=1800)
    summary=dict(family=args.family,exact_C0_ticks=c0,fluid_C0_ticks=fluid_c0,requested=3000,completed=len(rows),
        baseline_measurement=base_measurement,measurement=measurement,status='INSUFFICIENT_COMPLETED',
        exact_T=reference['T'],reference_sha256=sha256(args.reference/'ranking.json'))
    if measurement['status']=='OK' and len(rows)==3000 and all(r['completion_known'] for r in rows):
        delays=[0]*200;misses=[0]*200
        for row in rows:
            machine=int(row['scenario_id'].split('-')[0])
            delays[machine]+=row['cmax']-fluid_c0
            misses[machine]+=row['cmax']>deadline
        order=sorted(range(200),key=lambda m:(-delays[m],-misses[m],m))
        exact=[r['sum_delay_ticks'] for r in sorted(reference['ranking_rows'],key=lambda r:r['machine'])]
        a,b=average_ranks(exact),average_ranks(delays)
        rho=float(np.corrcoef(a,b)[0,1]) if a.std()>0 and b.std()>0 else None
        summary.update(status='PASS',fluid_T=order[:3],top3_overlap=len(set(order[:3])&set(reference['T'])),
            spearman_average_ties=rho,sum_delays_ticks=delays,deadline_misses=misses,
            scope='Descriptive ranking agreement; does not substitute H5 intervention holdout')
    (root/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k not in ('sum_delays_ticks','deadline_misses')}))

if __name__=='__main__':main()
