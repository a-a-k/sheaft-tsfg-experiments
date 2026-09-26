"""Hand arithmetic, independent observers, G1 identity and negative controls."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from validation.core import instance
from experiments.scale_data import make_dataset,scenarios,write_binary
from experiments.grouped_input import write_grouped
from experiments.aggregation import run,METRICS,assess
from validation.checks import SIGNATURE,validate_result


def observe(data,row,h):
    # Small independent direct boundary enumeration, avoiding shared observers.
    at=[];peaks=[]
    for m in range(len(data['queues'])):
        intervals=[]
        for o in data['operations']:
            if o['machine']!=m:continue
            finishes=[row['finish'][i] for i in o['predecessors']]
            if any(t is None for t in finishes):continue
            ready=max([o['release'],*finishes])
            start=row['start'][o['id']]
            end=start if start is not None else h+1
            if end>ready and ready<=h:intervals.append((ready,end))
        points={0,h,*[a for a,b in intervals],*[b for a,b in intervals if b<=h]}
        peaks.append(max(sum(a<=t<b for a,b in intervals) for t in points))
        at.append(sum(a<=h<b for a,b in intervals))
    integral=sum(max(0,min(h,t if t is not None else h)-j['release']) for j,t in zip(data['jobs'],row['job_finish']))
    return dict(queue_at_D=at,queue_max=peaks,wip_integral=integral,produced=sum(t is not None and t<=h for t in row['job_finish']))


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
    root=Path('artifacts/e3-gate');root.mkdir(parents=True,exist_ok=True)
    checks=0
    nominal=dict(id='M0',failures=[],work_overrides=[])
    simple=instance([(0,100,0,[],0,0),(0,100,100,[],1,0)])
    for label,h,sc,expected in [('fluid-half',50,nominal,(.5,87.5)),
        ('fluid-full',200,nominal,(2.,200.)),
        ('fluid-failure',150,dict(id='fault',failures=[[0,0,50]],work_overrides=[]),(1.,250.))]:
        source=root/f'{label}.json';source.write_text(json.dumps(simple))
        scenario=root/f'{label}-sc.json';scenario.write_text(json.dumps([sc]))
        rows,record=run('tsfg-agg',source,scenario,root/f'{label}-out.jsonl',h,delta=5)
        assert record['status']=='OK'
        row=rows[0]
        assert abs(row['fluid_produced']-expected[0])<1e-8,(label,row)
        assert abs(row['wip_integral']-expected[1])<1e-7,(label,row)
        assert row['material_balance_max_abs']<1e-8
        checks+=3
    # S1's internal epsilon must not discard legitimate sub-micro-job transfers.
    # One job, two equal stages sharing one machine: r=1/(2*1000001) jobs/tick.
    tiny=instance([(0,1000001,0,[],0,0),(0,1000001,1000001,[0],0,0)])
    source=root/'sub-epsilon.json';source.write_text(json.dumps(tiny))
    scenario=root/'sub-epsilon-sc.json';scenario.write_text(json.dumps([nominal]))
    rows,record=run('tsfg-agg',source,scenario,root/'sub-epsilon-out.jsonl',3,delta=1)
    assert record['status']=='OK'
    assert abs(rows[0]['fluid_produced']-1/1000001)<1e-15,rows[0]
    assert rows[0]['kernel_volume_scale']==2**20
    checks+=2
    for family in ('F1','F2'):
        for density in ('DENSE','SPARSE'):
            data=make_dataset(1000,family,density,902)
            folder=root/f'{family}-{density}';folder.mkdir(exist_ok=True)
            write_binary(data,folder/'g0.bin');write_grouped(data,folder/'g1.bin')
            scenario=folder/'scenarios.json'
            sc=[nominal,*scenarios(data,4)];scenario.write_text(json.dumps(sc))
            for h in (data['metadata']['D_ticks'],data['metadata']['C0_ticks']//2):
                reference=None
                for engine in ('des','dag','tsfg'):
                    for g in ('g0','g1'):
                        full,_=run(engine,folder/f'{g}.bin',scenario,folder/f'{engine}-{g}-{h}-full.jsonl',h,profile='SCHEDULE')
                        observed,_=run(engine,folder/f'{g}.bin',scenario,folder/f'{engine}-{g}-{h}-agg.jsonl',h)
                        if reference is None:reference=full
                        for s,row,ref,agg in zip(sc,full,reference,observed):
                            validate_result(data,s,row)
                            assert all(row[k]==ref[k] for k in SIGNATURE)
                            expected=observe(data,row,h)
                            assert all(agg[k]==v for k,v in expected.items())
                            assert all(agg[k]==row[k] for k in ('mission_success','completion_known','cmax','completion_lower_bound'))
                            checks+=4
                fluid,_=run('tsfg-agg',folder/'g0.bin',scenario,folder/f'fluid-{h}.jsonl',h)
                for row in fluid:
                    assert row['material_balance_max_abs']<1e-6
                    assert 0<=row['produced']<=100
                    checks+=2
    # A false success must fail the approximate admission regardless of metrics.
    example={k:0 for k in ('produced','incomplete_jobs','wip_integral')}
    example.update(scenario_id='negative',queue_at_D=[0],queue_max=[0],mission_success=False)
    assert assess(dict(example,mission_success=True),example,100,100)['mission_class']=='OUTSIDE'
    checks+=1
    summary=dict(status='PASS',checks=checks,individual_G1_identity=True,observer_comparison=True,hand_fluid_arithmetic=True)
    (root/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))


if __name__=='__main__':main()
