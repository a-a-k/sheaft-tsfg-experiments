"""Frozen E1X regressions and the 135 predeclared combined Mk01 cases."""
import copy
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.extended_campaign import full_scenarios
from experiments.pbr_cases_v2 import r5
from references.pbr_ref import simulate
from validation.pbr_des_v2 import FIELDS
from validation.pbr_checks import validate


def convert(old,capacity,shared=False):
    data=copy.deepcopy(old)
    data['semantics']='PBR-EXACT-v2.2'
    data['extended_profile']=True
    data['buffer_capacities']=[capacity]*len(data['queues'])
    data['resource_pools']=[dict(id=0,capacity=1)] if shared else []
    selected=(data.get('shared_operations',[]) if shared else [])
    data.pop('shared_operations',None)
    for op in data['operations']:op['resource_pool']=0 if op['id'] in selected else None
    return data


def engines(data,scenarios,folder,horizon,mode='DIAGNOSTIC'):
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'input.json').write_text(json.dumps(data,separators=(',',':')))
    (folder/'scenarios.json').write_text(json.dumps(scenarios,separators=(',',':')))
    result={}
    commands={'des':['artifacts/build/des-ext'], 'tsfg':['.private/runtime/tsfg','tsfg-ext']}
    for name,prefix in commands.items():
        output=folder/f'{name}.jsonl'
        command=[*prefix,str(folder/'input.json'),str(folder/'scenarios.json'),str(output),mode,str(horizon)]
        if name=='tsfg':command.append('5')
        subprocess.run(command,check=True,timeout=300,env={**os.environ,'TSFG_OP_DRIVER':'true','GOMAXPROCS':'1'})
        rows=[json.loads(line) for line in output.read_text().splitlines()]
        assert len(rows)==len(scenarios)
        result[name]=rows
    return result


def series(data,scenarios,folder,missions=False):
    horizon=10*r5(data['C0']*125,100)
    results=engines(data,scenarios,folder,horizon)
    references=[]
    for k,sc in enumerate(scenarios):
        ref=simulate(data,sc,horizon)
        references.append(ref)
        for name,rows in results.items():
            validate(data,sc,rows[k])
            assert rows[k]['scenario_id']==sc['id']
            for field in FIELDS:
                assert rows[k][field]==ref[field],(data['dataset_id'],sc['id'],name,field,rows[k][field],ref[field])
    (folder/'fraction.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in references))
    deadline_checks=0
    for deadline in (r5(data['C0']),r5(data['C0']*110,100),r5(data['C0']*125,100)):
        if missions:
            actual=engines(data,scenarios,folder/f'mission-{deadline}',deadline,'MISSION')
            for k,sc in enumerate(scenarios):
                ref=simulate(data,sc,deadline,'MISSION')
                for name,rows in actual.items():
                    validate(data,sc,rows[k])
                    for field in FIELDS:assert rows[k][field]==ref[field],(sc['id'],name,deadline,field)
        for k,ref in enumerate(references):
            expected=ref['cmax'] is not None and ref['cmax']<=deadline
            for rows in results.values():assert (rows[k]['cmax'] is not None and rows[k]['cmax']<=deadline)==expected
            deadline_checks+=1
    return dict(status='PASS',scenarios=len(scenarios),deadline_checks_per_engine=deadline_checks,
                mission_state_comparisons=deadline_checks if missions else 0)


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
    root=Path('artifacts/pbr-mk01');root.mkdir(parents=True,exist_ok=True)
    source=Path('artifacts/mk01-source-v2/e1x')
    summary=dict(status='RUNNING',buffer_regression={},shared_regression=None,combined={})
    for capacity in (1,2,4):
        old=json.loads((source/f'buffer-{capacity}/baseline.json').read_text())
        data=convert(old,capacity)
        summary['buffer_regression'][str(capacity)]=series(data,full_scenarios(old),root/f'buffer-{capacity}')
        shared=copy.deepcopy(data)
        shared['resource_pools']=[dict(id=0,capacity=1)]
        selected=[min(o['id'] for o in shared['operations'] if o['job']==j['id']) for j in shared['jobs'] if j['id']%2==0]
        for op in shared['operations']:op['resource_pool']=0 if op['id'] in selected else None
        folder=root/f'combined-{capacity}';folder.mkdir()
        nominal=dict(id='M0',failures=[],work_overrides=[],resource_failures=[])
        probe=simulate(shared,nominal,20*shared['C0'])
        (folder/'original-nominal.json').write_text(json.dumps(probe,indent=2))
        reason='Freeze exact nominal execution of saved PB plan plus shared pool'
        if not probe['completion_known']:
            reason='Regression-only serial replacement after preserved original deadlock/censoring'
            shared['queues']=[[] for _ in shared['queues']]
            t=0
            for op in sorted(shared['operations'],key=lambda o:(o['job'],o['id'])):
                op['planned_start']=t;op['planned_end']=t+op['work'];t+=op['work']
                shared['queues'][op['machine']].append(op['id'])
            probe=simulate(shared,nominal,t*2)
            assert probe['completion_known']
        for op,start in zip(shared['operations'],probe['start']):op['planned_start']=start;op['planned_end']=start+op['work']
        shared['C0']=probe['cmax']
        replay=simulate(shared,nominal,shared['C0']*2)
        assert replay['start']==probe['start'] and replay['finish']==probe['finish']
        target_machine=min(o['machine'] for o in shared['operations'] if o['resource_pool']==0)
        target_op=min(o['id'] for o in shared['operations'] if o['machine']==target_machine and o['resource_pool']==0)
        scenarios=[]
        for a,b,kind in itertools.product((10,30,50,70,90),(5,10,20),(0,1,2)):
            start=r5(a*shared['C0'],100);duration=max(5,r5(b*shared['C0'],100))
            resource_start=r5(2*start+duration,2) if kind==1 else start
            scenarios.append(dict(id=f'PBR-{capacity}-{a}-{b}-{kind}',failures=[[target_machine,start,start+duration]],
                resource_failures=[[0,0,resource_start,resource_start+duration]],
                work_overrides=[[target_op,max(5,r5(shared['operations'][target_op]['work']*150,100))]] if kind==2 else []))
        (folder/'manifest.json').write_text(json.dumps(dict(capacity=capacity,C0=shared['C0'],reason=reason,
            pool=0,unit=0,machine=target_machine,operation=target_op,scenarios=45,
            parent=f'core-38a1d0e827b2fda2119a53aec1e4e1c41823c555/e1x/buffer-{capacity}/baseline.json'),indent=2)+'\n')
        summary['combined'][str(capacity)]=series(shared,scenarios,folder/'series',missions=True)
    old=json.loads((source/'shared/baseline.json').read_text())
    shared=convert(old,'unbounded',True)
    scenarios=[]
    for a,b in itertools.product((10,30,50,70,90),(5,10,20)):
        start=old['C0']*a//100;duration=old['C0']*b//100
        scenarios.append(dict(id=f'shared-{a}-{b}',failures=[],work_overrides=[],resource_failures=[[0,0,start,start+duration]]))
    summary['shared_regression']=series(shared,scenarios,root/'shared-regression')
    summary['status']='PASS'
    summary['combined_trajectories_per_engine']=sum(s['scenarios'] for s in summary['combined'].values())
    summary['combined_deadline_checks_per_engine']=sum(s['deadline_checks_per_engine'] for s in summary['combined'].values())
    assert summary['combined_trajectories_per_engine']==135 and summary['combined_deadline_checks_per_engine']==405
    (root/'pbr-admission.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
