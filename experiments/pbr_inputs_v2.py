"""Predeclared derived PBR inputs and a separate K=10 scenario bank."""
import hashlib
import json

import numpy as np

from experiments.pbr_cases_v2 import r5


def task_hash(data):
    fields=('semantics','tick_unit','operations','queues','jobs','buffer_capacities','resource_pools')
    return hashlib.sha256(json.dumps({k:data[k] for k in fields},sort_keys=True,separators=(',',':')).encode()).hexdigest()


def derive(parent,parent_hash,profile):
    data=json.loads(json.dumps(parent))
    strata={}
    positions={}
    for op in data['operations']:
        pos=positions.get(op['job'],0);positions[op['job']]=pos+1
        strata.setdefault((op['machine']//20,pos),[]).append(op['id'])
    selected=set();audit=[]
    for (group,pos),ids in sorted(strata.items()):
        ordered=sorted(ids,key=lambda i:(hashlib.sha256(f'v2.2|pool-demand|{parent_hash}|{i}'.encode()).digest(),i))
        chosen=ordered[:len(ids)//4];selected.update(chosen)
        audit.append(dict(group=group,route_position=pos,operations=len(ids),selected=len(chosen),
            fraction=len(chosen)/len(ids),status='ZERO_SMALL_STRATUM' if len(ids)<4 else 'PREDECLARED_QUARTER',
            selected_ids_sha256=hashlib.sha256(json.dumps(chosen,separators=(',',':')).encode()).hexdigest()))
    c0=max(o['planned_end'] for o in data['operations'])
    workloads=[0]*10
    for op in data['operations']:
        if op['id'] in selected:workloads[op['machine']//20]+=op['work']
        op['resource_pool']=op['machine']//20 if op['id'] in selected and profile!='PB' else None
    pools=[dict(id=g,capacity=max(1,(5*w+4*c0-1)//(4*c0))) for g,w in enumerate(workloads)]
    data.update(semantics='PBR-EXACT-v2.2',extended_profile=True,tick_unit='0.01 second',
        resource_pools=pools if profile!='PB' else [],buffer_capacities=[2 if profile!='PR' else 'unbounded']*len(data['queues']))
    data.pop('metadata',None)
    return data,dict(parent_task_sha256=parent_hash,parent_hash_definition='SHA256 of original fixed-plan input.bin',
        C0_parent=c0,profile=profile,strata=audit,pool_nominal_work=workloads,frozen_pool_capacities=pools,
        capacity_rule='max(1,ceil(5*W/(4*C0_parent))); never recalibrated after M0')


def screen_scenarios(data,c0,profile):
    task=task_hash(data)
    kinds=['machine']*4+['work']*2+['separated']*2+['common']*2 if profile=='PB' else [kind for kind in ('machine','work','resource','separated','common') for _ in range(2)]
    result=[];seeds=[]
    for i,kind in enumerate(kinds):
        identity=f'SCREEN-K10-{i:02d}-{kind}'
        purpose=f'pbr_screen:{profile}:K10'
        raw=f'20260927|2.2|{task}|{purpose}|{identity}'
        seed=int.from_bytes(hashlib.sha256(raw.encode()).digest()[:8],'little')
        source=np.random.Generator(np.random.PCG64(seed))
        start=r5(int(source.integers(100000,900001))*c0,1000000)
        duration=max(5,r5(int(source.choice([1,5,20]))*c0,100))
        machine=int(source.integers(len(data['queues'])))
        pool=int(source.integers(len(data['resource_pools']))) if data['resource_pools'] else None
        unit=int(source.integers(data['resource_pools'][pool]['capacity'])) if pool is not None else None
        row=dict(id=identity,kind=kind,failures=[],work_overrides=[],resource_failures=[])
        if kind=='machine':row['failures']=[[machine,start,start+duration]]
        elif kind=='work':
            op=int(source.integers(len(data['operations'])));increase=int(source.choice([25,50,100]))
            row['work_overrides']=[[op,max(5,r5(data['operations'][op]['work']*(100+increase),100))]]
        elif kind=='resource':row['resource_failures']=[[pool,unit,start,start+duration]]
        elif kind=='separated':
            first=r5(int(source.integers(100000,400001))*c0,1000000)
            second=r5(int(source.integers(600000,900001))*c0,1000000)
            row['failures']=[[machine,first,first+duration]]
            if pool is not None:row['resource_failures']=[[pool,unit,second,second+duration]]
            else:row['failures'].append([(machine+1+int(source.integers(len(data['queues'])-1)))%len(data['queues']),second,second+duration])
        else:
            group=int(source.integers(10));machines=[group*20+int(k) for k in source.choice(20,5,replace=False)]
            row['failures']=[[k,start,start+duration] for k in sorted(machines)]
            if pool is not None:row['resource_failures']=[[group,0,start,start+duration]]
        result.append(row);seeds.append(dict(id=identity,seed_text=raw,seed=seed))
    return result,dict(task_sha256=task,scenarios=seeds,numpy_version=np.__version__,
        draw_rule='PCG64; start integer uniform in [100000,900000]/1e6*C0; duration choice 1/5/20%; work increase 25/50/100%; half-up R5',
        separate_bank='K10 has its own purpose; M0 excluded; K100 will use a different purpose')
