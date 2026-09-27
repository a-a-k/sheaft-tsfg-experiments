"""Independent streamed physical validation and full state comparison by digest."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from validation.pbr_checks import validate
from validation.pbr_des_v2 import FIELDS


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--measured',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    root=args.output;root.mkdir(parents=True,exist_ok=True)
    nominal=json.loads((args.input/'nominal-admission.json').read_text())
    data=json.loads((args.input/'input.json').read_text())
    measured=json.loads((args.measured/'measurements.json').read_text());count=measured['count']
    scenarios=json.loads((args.input/f'scenarios-{count}.json').read_text());assert len(scenarios)==count
    signature_sets=[];metadata=[];all_valid=True
    for i,process in enumerate(measured['processes']):
        retained=root/str(i);retained.mkdir(exist_ok=True)
        path=args.measured/str(i)/'output.jsonl.gz';rows=[];hasher=hashlib.sha256()
        if path.exists():
            with (gzip.open(path,'rb') as file,
                  gzip.open(retained/'jobs-and-metrics.jsonl.gz','wt',compresslevel=1) as compact,
                  gzip.open(retained/'retained-traces.jsonl.gz','wb',compresslevel=1) as witnesses):
                for index,line in enumerate(file):
                    hasher.update(line)
                    if not line.endswith(b'\n'):break
                    row=json.loads(line);scenario=scenarios[index]
                    assert row['scenario_id']==scenario['id']
                    validate(data,scenario,row)
                    signature=hashlib.sha256(json.dumps({k:row[k] for k in FIELDS},sort_keys=True,separators=(',',':')).encode()).hexdigest()
                    metrics={k:row[k] for k in ('scenario_id','job_results','job_finish','mission_success','completion_known','cmax',
                        'completion_lower_bound','run_status','stopped','horizon','resource_wait_integral','blocked_machine_integral')}
                    metrics.update(full_state_sha256=signature,coupling_witnesses_count=len(row['coupling_witnesses']))
                    compact.write(json.dumps(metrics,separators=(',',':'))+'\n')
                    rows.append(dict(id=scenario['id'],sha256=signature,resource_wait_integral=row['resource_wait_integral'],
                        blocked_machine_integral=row['blocked_machine_integral'],coupling_count=len(row['coupling_witnesses'])))
                    if scenario['id'] in nominal['retained_scenario_ids'] or count==10:witnesses.write(line)
            # A timed-out process may leave a partial final line; all bytes still
            # contribute to the original-output digest and are retained upstream.
            assert hasher.hexdigest()==process['output_sha256']
        if process['performance_status']=='MEASURED':assert len(rows)==count
        assert len(rows)<=count
        signature_sets.append(rows)
        metadata.append(dict(process,scenarios_completed=len(rows),
            correctness_status='PHYSICAL_INVARIANTS_VALID' if rows else 'UNCHECKED'))
    # Compare every complete observed trajectory even when its process timed out.
    reference={}
    for rows in signature_sets:
        for row in rows:
            if row['id'] in reference:assert row['sha256']==reference[row['id']],'Independent engine mismatch: '+row['id']
            else:reference[row['id']]=row['sha256']
    compared=set.intersection(*[{r['id'] for r in rows} for rows in signature_sets])
    for record,rows in zip(metadata,signature_sets):
        record['correctness_status']='VALID' if len(rows)==count and all(r['id'] in compared for r in rows) else 'PARTIAL_VALIDATION'
    measured.update(processes=metadata,execution_status='COMPLETE' if all(r['performance_status']=='MEASURED' for r in metadata) else 'PARTIAL',
        correctness_status='VALID' if len(compared)==count else 'PARTIAL_VALIDATION',compared_scenarios=len(compared))
    controls=[r for rows in signature_sets for r in rows]
    metrics=dict(resource_wait_integral=sum(r['resource_wait_integral'] for r in controls),
        blocked_machine_integral=sum(r['blocked_machine_integral'] for r in controls),
        coupling_witnesses=sum(r['coupling_count'] for r in controls))
    measured['constraints']=metrics
    measured['control_status']='STRONG_CONTROL' if all(v>0 for v in metrics.values()) else 'WEAK_CONTROL'
    if count==10:
        measured['million_admitted']=len(compared)==10 and all(r['performance_status']=='MEASURED' and r['T_total_s']<=25 for r in metadata)
    elif all(r['performance_status']=='MEASURED' and r['correctness_status']=='VALID' for r in metadata):
        des=[r['T_total_s'] for r in metadata if r['engine']=='des'];tsfg=[r['T_total_s'] for r in metadata if r['engine']=='tsfg']
        measured['paired_speedup']=(des[0]*des[1]/(tsfg[0]*tsfg[1]))**.5
    else:measured['paired_speedup']=None
    (root/'validated.json').write_text(json.dumps(measured,indent=2)+'\n')
    (root/'signatures.json').write_text(json.dumps(signature_sets,indent=2)+'\n')
    print(json.dumps({k:v for k,v in measured.items() if k!='processes'}))


if __name__=='__main__':main()
