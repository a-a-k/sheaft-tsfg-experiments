"""One first-stage input: independent M0, frozen-base replay and standalone K10."""
import argparse
import copy
import hashlib
import json
import os
import platform
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.pbr_cases_v2 import r5
from experiments.pbr_inputs_v2 import screen_scenarios,task_hash
from validation.pbr_checks import validate
from validation.pbr_des_v2 import FIELDS


def sha(path):
    with path.open('rb') as file:return hashlib.file_digest(file,'sha256').hexdigest()


def oom_kills():
    path=Path('/sys/fs/cgroup/memory.events')
    if not path.exists():return 0
    return int(dict(line.split() for line in path.read_text().splitlines()).get('oom_kill',0))


def execute(data,scenarios,horizon,mode,engine,root,records,label):
    root.mkdir(parents=True,exist_ok=True)
    input_file=root/'input.json';scenario_file=root/'scenarios.json';output=root/'output.jsonl'
    input_file.write_text(json.dumps(data,separators=(',',':')));scenario_file.write_text(json.dumps(scenarios,separators=(',',':')))
    command=(['.private/runtime/tsfg','tsfg-ext'] if engine=='tsfg' else ['artifacts/build/des-ext'])
    command += [str(input_file),str(scenario_file),str(output),mode,str(horizon)]
    if engine=='tsfg':command.append('5')
    observed=0;before_oom=oom_kills();start=time.monotonic();status='MEASURED'
    with (root/'stdout.txt').open('w') as stdout,(root/'stderr.txt').open('w') as stderr:
        process=subprocess.Popen(command,stdout=stdout,stderr=stderr,start_new_session=True,
            env={**os.environ,'TSFG_OP_DRIVER':'true','GOMAXPROCS':'1'})
        while process.poll() is None:
            try:
                for line in Path(f'/proc/{process.pid}/status').read_text().splitlines():
                    if line.startswith('VmHWM:'):observed=max(observed,int(line.split()[1])*1024)
            except FileNotFoundError:pass
            if time.monotonic()-start>=60:
                os.killpg(process.pid,signal.SIGKILL);status='TIMEOUT';break
            time.sleep(.02)
        process.wait()
    elapsed=time.monotonic()-start
    if status=='MEASURED' and process.returncode!=0:status='ERROR'
    if status=='ERROR' and oom_kills()>before_oom:status='OOM'
    record=dict(label=label,engine=engine,mode=mode,horizon=horizon,scenarios=len(scenarios),
        performance_status=status,T_total_s=elapsed if status=='MEASURED' else None,
        elapsed_s=elapsed,elapsed_lower_bound_s=60 if status=='TIMEOUT' else None,
        observed_peak_bytes=observed,observed_peak_status='OBSERVED_LOWER_BOUND',input_sha256=sha(input_file),scenarios_sha256=sha(scenario_file),
        source_sha=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],returncode=process.returncode)
    rows=None
    if status=='MEASURED':
        rows=[json.loads(line) for line in output.read_text().splitlines()]
        assert len(rows)==len(scenarios)
        record.update(output_sha256=sha(output),output_bytes=output.stat().st_size,
            metadata=json.loads(Path(str(output)+'.meta.json').read_text()))
        for sc,row in zip(scenarios,rows):
            assert row['scenario_id']==sc['id'];validate(data,sc,row)
        record['correctness_status']='PHYSICAL_INVARIANTS_VALID'
    else:record['correctness_status']='UNCHECKED'
    records.append(record)
    (root/'process.json').write_text(json.dumps(record,indent=2)+'\n')
    return rows


def pair(data,scenarios,horizon,mode,root,records,label):
    rows={engine:execute(data,scenarios,horizon,mode,engine,root/engine,records,label) for engine in ('des','tsfg')}
    if any(value is None for value in rows.values()):return None
    for sc,a,b in zip(scenarios,rows['des'],rows['tsfg']):
        for field in FIELDS:assert a[field]==b[field],(label,sc['id'],field)
    for record in records[-2:]:record['correctness_status']='VALID'
    return rows['des']


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.output;root.mkdir(parents=True,exist_ok=True)
    environment=dict(source_sha=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],
        python=sys.version,platform=platform.platform(),allowed_cpus=sorted(os.sched_getaffinity(0)),
        cpuinfo=Path('/proc/cpuinfo').read_text(),
        cgroup={name:Path('/sys/fs/cgroup',name).read_text().strip() for name in ('cpu.max','memory.max','memory.swap.max')},
        versions={name:subprocess.check_output(command,text=True) for name,command in
                  [('go',['go','version']),('g++',['g++','--version'])]},
        public_code_sha256={name:sha(Path(name)) for name in ('engines/des_ext/main.cpp',
            'engines/tsfg_op/operation_adapter.go','engines/tsfg_op/pbr_adapter.go',
            'experiments/pbr_screen_v2.py','validation/pbr_checks.py')})
    (root/'environment.json').write_text(json.dumps(environment,indent=2)+'\n')
    manifest=json.loads((args.input/'manifest.json').read_text());assert sha(args.input/'original.json')==manifest['input_sha256']
    data=json.loads((args.input/'original.json').read_text());empty=[dict(id='M0',failures=[],work_overrides=[],resource_failures=[])]
    records=[];summary=dict(id=manifest['id'],family=manifest['family'],seed=manifest['seed'],n=manifest['n'],profile=manifest['profile'],
        execution_status='PARTIAL',correctness_status='UNCHECKED',source=manifest,processes=records)
    try:
        original=pair(data,empty,10*r5(manifest['C0_parent']*110,100),'DIAGNOSTIC',root/'nominal-original',records,'M0-original')
        if original is None:
            summary.update(input_status='COMPUTATION_INCOMPLETE',K10_status='NOT_RUN_NO_VALIDATED_BASELINE');return
        summary['nominal_status']=original[0]['run_status']
        if not original[0]['completion_known']:
            summary.update(input_status='NO_ADMISSIBLE_INPUT',correctness_status='VALID',execution_status='COMPLETE',
                           K10_status='NOT_RUN_NO_ADMISSIBLE_BASELINE',nominal_reason=original[0]['run_status']);return
        c0=original[0]['cmax']
        for op,begin in zip(data['operations'],original[0]['start']):op['planned_start']=begin;op['planned_end']=begin+op['work']
        replay=pair(data,empty,c0,'DIAGNOSTIC',root/'nominal-frozen',records,'M0-frozen')
        if replay is None:summary.update(input_status='COMPUTATION_INCOMPLETE',K10_status='NOT_RUN_NO_VALIDATED_BASELINE');return
        assert replay[0]['start']==original[0]['start'] and replay[0]['finish']==original[0]['finish']
        scenarios,bank=screen_scenarios(data,c0,manifest['profile'])
        (root/'scenario-bank.json').write_text(json.dumps(bank,indent=2)+'\n')
        (root/'frozen-baseline.json').write_text(json.dumps(data,separators=(',',':')))
        summary.update(C0=c0,D=r5(c0*110,100),task_sha256=task_hash(data),input_status='NOMINALLY_ADMISSIBLE')
        results=pair(data,scenarios,summary['D'],'MISSION',root/'K10',records,'K10-standalone')
        controls=[replay[0],*(results or [])]
        summary['constraints']=dict(resource_wait_integral=sum(r['resource_wait_integral'] for r in controls),
            blocked_machine_integral=sum(r['blocked_machine_integral'] for r in controls),
            coupling_witnesses=sum(len(r['coupling_witnesses']) for r in controls))
        metrics=summary['constraints']
        summary['control_status']='STRONG_CONTROL' if all(v>0 for v in metrics.values()) else 'WEAK_CONTROL'
        summary['K10_status']='COMPLETE_VALID' if results is not None else 'COMPUTATION_INCOMPLETE'
        summary['sensitivity']={}
        if manifest['profile']!='PR':
            for capacity in (1,4):
                changed=copy.deepcopy(data);changed['buffer_capacities']=[capacity]*len(data['queues'])
                probe=pair(changed,empty,10*summary['D'],'DIAGNOSTIC',root/f'capacity-{capacity}',records,f'M0-capacity-{capacity}')
                summary['sensitivity'][str(capacity)]=dict(status=probe[0]['run_status'] if probe else 'COMPUTATION_INCOMPLETE',
                    Cmax=probe[0]['cmax'] if probe else None)
        summary['correctness_status']='VALID' if all(r['correctness_status']=='VALID' for r in records) else 'UNCHECKED'
        summary['execution_status']='COMPLETE' if all(r['performance_status']=='MEASURED' for r in records) else 'PARTIAL'
    except Exception as error:
        summary.update(correctness_status='INVALID',error=f'{type(error).__name__}: {error}');raise
    finally:
        (root/'screen.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps({k:v for k,v in summary.items() if k not in ('source','processes')}),flush=True)


if __name__=='__main__':main()
