"""Frozen holdout law, exact speed intervention and independently checked output."""
import copy
from fractions import Fraction
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from experiments.pbr_cases_v2 import r5
from experiments.pbr_inputs_v2 import task_hash
from experiments.pbr_measure_v2 import run_one
from validation.pbr_checks import validate
from validation.pbr_des_v2 import FIELDS


def seed(task,purpose,identity):
    raw=f'20260927|2.2|{task}|{purpose}|{identity}'
    value=int.from_bytes(hashlib.sha256(raw.encode()).digest()[:8],'little')
    return np.random.Generator(np.random.PCG64(value)),dict(seed_text=raw,seed=value)


def rounded(value):
    value=Fraction(str(value));return r5(value.numerator,value.denominator)


def merge(intervals):
    result=[]
    for a,b in sorted(intervals):
        if result and a<=result[-1][1]:result[-1][1]=max(result[-1][1],b)
        else:result.append([a,b])
    return result


def scenario(data,c0,law,purpose,index):
    task=task_hash(data);identity=f'{index:04d}'
    source,audit=seed(task,f'reserve_{purpose}:{law}',identity)
    horizon=100*r5(c0*110,100);machine=[[] for _ in data['queues']]
    pools={(pool['id'],u):[] for pool in data['resource_pools'] for u in range(pool['capacity'])}
    def calendar(common=False):
        clock=0;rows=[]
        while True:
            start=rounded(clock+float(source.exponential((2 if common else 10)*c0)))
            if start>=horizon:return rows
            duration=max(5,rounded((.02 if common else float(source.uniform(.01,.03)))*c0))
            rows.append([start,start+duration]);clock=start+duration
    for i in range(len(machine)):machine[i]=calendar()
    for key in sorted(pools):pools[key]=calendar()
    if law=='common-cause':
        common=calendar(True)
        for i in range(min(5,len(machine))):machine[i].extend(common)
        pools[(0,0)].extend(common)
    row=dict(id=f'{purpose}-{law}-{identity}',failures=[[i,a,b] for i,rows in enumerate(machine) for a,b in merge(rows)],
        resource_failures=[[r,u,a,b] for (r,u),rows in sorted(pools.items()) for a,b in merge(rows)],work_overrides=[])
    return row,audit


def accelerated(data,machine=None):
    result=copy.deepcopy(data)
    for op in result['operations']:
        op['release']*=11;op['planned_start']*=11
        op['work']*=10 if op['machine']==machine else 11
        op['planned_end']=op['planned_start']+op['work']
        assert all(op[k]%5==0 for k in ('release','planned_start','work'))
    result['tick_unit']='0.01/11 second';return result


def scaled_scenario(row):
    result=copy.deepcopy(row)
    result['failures']=[[m,11*a,11*b] for m,a,b in row['failures']]
    result['resource_failures']=[[r,u,11*a,11*b] for r,u,a,b in row['resource_failures']]
    result['work_overrides']=[[i,11*w] for i,w in row['work_overrides']]
    return result


def evaluate(data,scenarios,horizon,mode,root,retain_ids=()):
    root.mkdir(parents=True,exist_ok=True)
    (root/'input.json').write_text(json.dumps(data,separators=(',',':')))
    (root/'scenarios.json').write_text(json.dumps(scenarios,separators=(',',':')))
    begin=time.monotonic()
    process=run_one(root/'input.json',root/'scenarios.json',horizon,'des',root/'process',300,root.name,mode)
    records=[];raw=root/'process/output.jsonl'
    try:
        if process['performance_status']!='MEASURED':return [],dict(process,validation_status='INCOMPLETE')
        with raw.open('rb') as source,gzip.open(root/'checked-records.jsonl.gz','wt',compresslevel=1) as compact:
            for index,line in enumerate(source):
                row=json.loads(line);assert row['scenario_id']==scenarios[index]['id']
                validate(data,scenarios[index],row)
                kept={k:row[k] for k in ('scenario_id','job_results','job_finish','mission_success','completion_known',
                    'cmax','completion_lower_bound','run_status','horizon','stopped','resource_wait_integral','blocked_machine_integral')}
                kept['full_state_sha256']=hashlib.sha256(json.dumps({k:row[k] for k in FIELDS},sort_keys=True,separators=(',',':')).encode()).hexdigest()
                kept['produced_jobs']=sum(j['produced'] for j in row['job_results'])
                compact.write(json.dumps(kept,separators=(',',':'))+'\n');records.append(kept)
                if row['scenario_id'] in retain_ids:
                    with gzip.open(root/(row['scenario_id']+'-trace.json.gz'),'wb',compresslevel=1) as output:output.write(line)
        assert len(records)==len(scenarios)
        process.update(validation_status='PHYSICAL_INVARIANTS_VALID',scenario_count=len(records),
            time_with_validation_s=time.monotonic()-begin)
        (root/'validation.json').write_text(json.dumps(process,indent=2)+'\n')
        # Complete native output has been independently checked. Required job
        # times, metrics, hashes and predeclared traces remain in checked records.
        raw.unlink();(root/'process/output.jsonl.gz').unlink()
        return records,process
    finally:
        # Input/scenario hashes are in process.json; the immutable bank is also
        # retained once by the caller, instead of duplicating it per chunk.
        (root/'input.json').unlink();(root/'scenarios.json').unlink()
