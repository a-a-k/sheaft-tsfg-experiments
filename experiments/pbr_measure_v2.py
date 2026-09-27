"""Standalone complete-output PBR processes; no validation inside the timer."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import select
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.pbr_screen_v2 import sha,oom_kills


def run_one(data_path,scenarios_path,horizon,engine,root,limit,label):
    root.mkdir(parents=True,exist_ok=True);raw=root/'output.jsonl'
    command=['.private/runtime/tsfg','tsfg-ext'] if engine=='tsfg' else ['artifacts/build/des-ext']
    command += [str(data_path),str(scenarios_path),str(raw),'MISSION',str(horizon)]
    if engine=='tsfg':command.append('5')
    record=dict(engine=engine,label=label,horizon=horizon,limit_seconds=limit,
        source_sha=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],
        input_sha256=sha(data_path),scenarios_sha256=sha(scenarios_path),
        wait_method='Linux pidfd readiness',correctness_status='UNCHECKED')
    before=oom_kills();start=time.monotonic();timeout=False
    with (root/'stdout.txt').open('wb') as stdout,(root/'stderr.txt').open('wb') as stderr:
        process=subprocess.Popen(command,stdout=stdout,stderr=stderr,start_new_session=True,
            env={**os.environ,'TSFG_OP_DRIVER':'true','GOMAXPROCS':'1'})
        descriptor=os.pidfd_open(process.pid)
        ready,_,_=select.select([descriptor],[],[],max(0,limit-(time.monotonic()-start)))
        if not ready:timeout=True;os.killpg(process.pid,signal.SIGKILL)
        _,status,usage=os.wait4(process.pid,0);elapsed=time.monotonic()-start
        os.close(descriptor);process.returncode=os.waitstatus_to_exitcode(status)
    outcome='TIMEOUT' if timeout else 'MEASURED' if process.returncode==0 else 'OOM' if oom_kills()>before else 'ERROR'
    record.update(performance_status=outcome,T_total_s=elapsed if outcome=='MEASURED' else None,
        elapsed_s=elapsed,T_total_lower_bound_s=limit if timeout else None,exit_code=process.returncode,
        cpu_s=usage.ru_utime+usage.ru_stime)
    meta=Path(str(raw)+'.meta.json')
    if meta.exists():record['metadata']=json.loads(meta.read_text())
    if raw.exists():
        record.update(output_sha256=sha(raw),output_bytes=raw.stat().st_size)
        with raw.open('rb') as source,gzip.open(root/'output.jsonl.gz','wb',compresslevel=1) as target:
            shutil.copyfileobj(source,target,1024*1024)
        with gzip.open(root/'output.jsonl.gz','rb') as restored:
            assert hashlib.file_digest(restored,'sha256').hexdigest()==record['output_sha256']
    (root/'process.json').write_text(json.dumps(record,indent=2)+'\n')
    return record


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--count',type=int,choices=[10,100],required=True);p.add_argument('--round',type=int,default=0);args=p.parse_args()
    nominal=json.loads((args.input/'nominal-admission.json').read_text())
    assert nominal['input_status']=='NOMINALLY_ADMISSIBLE' and nominal['correctness_status']=='VALID'
    assert sha(args.input/'input.json')==nominal['input_sha256']
    root=args.output;root.mkdir(parents=True,exist_ok=True)
    environment=dict(source_sha=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],
        python=sys.version,platform=platform.platform(),allowed_cpus=sorted(os.sched_getaffinity(0)),
        cpuinfo=Path('/proc/cpuinfo').read_text(),
        cgroup={n:Path('/sys/fs/cgroup',n).read_text().strip() for n in ('cpu.max','memory.max','memory.swap.max')},
        engine_code={n:sha(Path(n)) for n in ('engines/des_ext/main.cpp','engines/tsfg_op/pbr_adapter.go','engines/tsfg_op/operation_adapter.go')})
    (root/'environment.json').write_text(json.dumps(environment,indent=2)+'\n')
    order=['des','tsfg'] if args.count==10 else ['des','tsfg','tsfg','des'] if args.round%2 else ['tsfg','des','des','tsfg']
    assert args.count==10 or args.round in (1,2,3)
    rows=[]
    for i,engine in enumerate(order):
        rows.append(run_one(args.input/'input.json',args.input/f'scenarios-{args.count}.json',nominal['D'],engine,root/str(i),300,str(i)))
    result=dict(id=nominal['id'],n=nominal['n'],family=nominal['family'],seed=nominal['seed'],round=args.round,
        count=args.count,order=order,processes=rows,task_sha256=nominal['task_sha256'],
        execution_status='COMPLETE' if all(r['performance_status']=='MEASURED' for r in rows) else 'PARTIAL')
    (root/'measurements.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
