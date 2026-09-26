"""E3: exact shared types and explicitly approximate S1 fluid stages."""
import argparse
import gc
import json
import math
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.scale_data import make_dataset, scenarios, write_binary, sha256
from experiments.grouped_input import write_grouped

METRICS=('produced','released','incomplete_jobs','queue_at_D','queue_max','wip_integral',
         'mission_success','completion_known','cmax','completion_lower_bound')


def run(engine,source,scenario_file,target,horizon,mode='MISSION',limit=300,profile='AGG-MISSION',delta=100):
    binary='.private/runtime/tsfg' if engine.startswith('tsfg') else 'artifacts/build/simulator'
    target.parent.mkdir(parents=True,exist_ok=True)
    command=[binary,engine,str(source),str(scenario_file),str(target),mode,str(horizon),str(delta)]
    record=dict(engine=engine,source_sha256=sha256(source),scenario_sha256=sha256(scenario_file),
                binary_sha256=sha256(binary),commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],
                mode=mode,horizon=horizon,output_profile=profile,process_limit_s=limit)
    begin=time.monotonic()
    with Path('.private/aggregate-last.stderr').open('wb') as log:
        process=subprocess.Popen(command,stdout=log,stderr=log,start_new_session=True,
            env={**os.environ,'TSFG_OP_DRIVER':'true','GOMAXPROCS':'1','TSFG_OUTPUT_PROFILE':profile})
        fd=os.pidfd_open(process.pid)
        ready,_,_=select.select([fd],[],[],max(0,limit-(time.monotonic()-begin)))
        if not ready:os.killpg(process.pid,signal.SIGKILL)
        _,status,usage=os.wait4(process.pid,0)
        os.close(fd)
        process.returncode=os.waitstatus_to_exitcode(status)
    elapsed=time.monotonic()-begin
    record.update(status='TIMEOUT' if not ready else ('OK' if process.returncode==0 else 'ERROR'),
        T_total_s=elapsed if ready and process.returncode==0 else None,
        T_total_lower_bound_s=limit if not ready else None,process_wall_observed_s=elapsed,
        rss_peak_bytes=usage.ru_maxrss*1024,cpu_s=usage.ru_utime+usage.ru_stime,exit_code=process.returncode)
    rows=[]
    if target.exists():
        with target.open() as f:
            for line in f:
                if not line.endswith('\n'):break
                rows.append(json.loads(line))
    record['scenarios_completed']=len(rows)
    for suffix,key in (('.meta.json','engine_meta'),('.progress.json','progress')):
        path=Path(str(target)+suffix)
        if path.exists():record[key]=json.loads(path.read_text())
    target.with_suffix('.measurement.json').write_text(json.dumps(record,indent=2))
    if record['status']=='ERROR':raise AssertionError(f'{engine} failed; private process diagnostics retained on runner')
    return rows,record


def assess(approx,reference,jobs,c0,diagnostic=None,exact_diagnostic=None):
    errors={}
    errors['produced_fraction']=abs(approx['produced']-reference['produced'])/jobs
    errors['incomplete_fraction']=abs(approx['incomplete_jobs']-reference['incomplete_jobs'])/jobs
    for key in ('queue_at_D','queue_max'):
        errors[key+'_fraction']=max(abs(a-b) for a,b in zip(approx[key],reference[key]))/jobs
    errors['wip_integral_relative']=abs(approx['wip_integral']-reference['wip_integral'])/max(1,reference['wip_integral'])
    false_success=approx['mission_success'] and not reference['mission_success']
    false_failure=not approx['mission_success'] and reference['mission_success']
    passed=not false_success and all(v<=.01 for k,v in errors.items() if k!='wip_integral_relative') and errors['wip_integral_relative']<=.05
    diagnostic_class='UNKNOWN'
    if diagnostic is not None and exact_diagnostic is not None and diagnostic['cmax'] is not None and exact_diagnostic['cmax'] is not None:
        errors['cmax_fraction_C0']=abs(diagnostic['cmax']-exact_diagnostic['cmax'])/c0
        diagnostic_class='APPROX-DIAGNOSTIC-1' if passed and errors['cmax_fraction_C0']<=.01 else 'OUTSIDE'
    return dict(scenario_id=approx['scenario_id'],errors=errors,false_success=false_success,false_failure=false_failure,
                mission_class='APPROX-MISSION-1' if passed else 'OUTSIDE',diagnostic_class=diagnostic_class)


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
    p=argparse.ArgumentParser()
    p.add_argument('--n',type=int,required=True)
    p.add_argument('--family',choices=['F1','F2'],required=True)
    p.add_argument('--density',choices=['DENSE','SPARSE'],required=True)
    p.add_argument('--seed',type=int,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    root=args.output;root.mkdir(parents=True,exist_ok=True)
    data=make_dataset(args.n,args.family,args.density,args.seed)
    metadata=data['metadata'];jobs=len(data['jobs'])
    nominal=dict(id='M0',failures=[],work_overrides=[])
    sc=[nominal,*scenarios(data,10)]
    scenario_path=root/'scenarios.json';scenario_path.write_text(json.dumps(sc))
    write_binary(data,root/'G0.bin')
    representation=write_grouped(data,root/'G1.bin')
    representation['G0_input_bytes']=(root/'G0.bin').stat().st_size
    summary=dict(status='RUNNING',dataset_id=data['dataset_id'],metadata=metadata,representation=representation,
                 protocol='docs/AGGREGATION_SPEC_RU.md',K=11,measurements=[],accuracy=[])
    (root/'summary.json').write_text(json.dumps(summary,indent=2))
    del data;gc.collect()
    results={}
    for mode in ('MISSION','DIAGNOSTIC'):
        horizon=metadata['D_ticks']*(10 if mode=='DIAGNOSTIC' else 1)
        # Two references share output metrics only. G1 retains the G0 TSFG solver.
        for label,engine,representation in (('G0-des','des','G0'),('G0-dag','dag','G0'),
                                             ('G0-tsfg','tsfg','G0'),('G1-tsfg','tsfg','G1'),('G2-tsfg','tsfg-agg','G0')):
            rows,record=run(engine,root/f'{representation}.bin',scenario_path,root/f'{mode}-{label}.jsonl',horizon,mode)
            record['label']=label;summary['measurements'].append(record)
            results[(mode,label)]={r['scenario_id']:r for r in rows}
            reference=results[(mode,'G0-des')]
            if label!='G2-tsfg':
                for row in rows:
                    ref=reference[row['scenario_id']]
                    assert all(row[k]==ref[k] for k in METRICS),(mode,label,row['scenario_id'])
            (root/'summary.json').write_text(json.dumps(summary,indent=2))
    for key,row in results[('MISSION','G2-tsfg')].items():
        ref=results[('MISSION','G0-des')][key]
        summary['accuracy'].append(assess(row,ref,jobs,metadata['C0_ticks'],
            results[('DIAGNOSTIC','G2-tsfg')].get(key),results[('DIAGNOSTIC','G0-des')].get(key)))
    summary['status']='PASS_WITH_CENSORED_MEASUREMENTS' if any(r['status']=='TIMEOUT' for r in summary['measurements']) else 'PASS'
    summary['false_successes']=sum(r['false_success'] for r in summary['accuracy'])
    summary['outside_mission_class']=sum(r['mission_class']=='OUTSIDE' for r in summary['accuracy'])
    (root/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k not in ('measurements','accuracy')}),flush=True)


if __name__=='__main__':main()
