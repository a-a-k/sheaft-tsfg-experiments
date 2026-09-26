"""Standalone bounded process measurements, with full SCHEDULE output retained."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import signal
import select
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.scale_data import sha256
from validation.checks import SIGNATURE


def run_one(dataset, engine, count, output, limit=300, label="screen", mode="MISSION", binary_override=None):
    manifest=json.loads((dataset/"manifest.json").read_text())
    scenarios=json.loads((dataset/"scenarios-1000.json").read_text())[:count]
    output.mkdir(parents=True,exist_ok=True)
    scenario_path=output/"scenarios.json"
    scenario_path.write_text(json.dumps(scenarios,separators=(",",":")))
    raw=output/"result.jsonl"
    binary=".private/runtime/tsfg" if engine=="tsfg" else "artifacts/build/simulator"
    if binary_override is not None:binary=binary_override
    horizon=manifest["metadata"]["D_ticks"]*(10 if mode=="DIAGNOSTIC" else 1)
    command=[binary,engine,str(dataset/"input.bin"),str(scenario_path),str(raw),mode,str(horizon),"100"]
    record=dict(dataset_id=manifest["dataset_id"],engine=engine,K=count,label=label,
                process_time_limit_s=limit,mode=mode,output_profile="SCHEDULE",delta_ticks=100,
                input_sha256=manifest["files"]["input.bin"],scenarios_sha256=sha256(scenario_path),
                binary_sha256=sha256(binary),
                commit=os.environ["GITHUB_SHA"],run_id=os.environ["GITHUB_RUN_ID"],
                status="RUNNING",completion_validated=False)
    result_path=output/"measurement.json"
    result_path.write_text(json.dumps(record,indent=2))
    private_log=Path(".private")/"last-run.stderr"
    start=time.monotonic()
    timed_out=False
    with private_log.open("wb") as log:
        process=subprocess.Popen(command,stdout=log,stderr=log,start_new_session=True,
                                 env={**os.environ,"TSFG_OP_DRIVER":"true","GOMAXPROCS":"1"})
        # Kernel notification avoids rounding short processes to a polling period.
        descriptor=os.pidfd_open(process.pid)
        ready,_,_=select.select([descriptor],[],[],max(0,limit-(time.monotonic()-start)))
        if not ready:
            timed_out=True
            os.killpg(process.pid,signal.SIGKILL)
        _,status,usage=os.wait4(process.pid,0)
        os.close(descriptor)
        process.returncode=os.waitstatus_to_exitcode(status)
    elapsed=time.monotonic()-start
    record.update(process_wall_observed_s=elapsed,wait_method="Linux pidfd readiness",exit_code=process.returncode,
                  rss_peak_bytes=usage.ru_maxrss*1024,cpu_s=usage.ru_utime+usage.ru_stime)
    if timed_out:
        record.update(status="TIMEOUT",T_total_s=None,T_total_lower_bound_s=limit)
    elif process.returncode:
        record.update(status="KILLED" if process.returncode<0 else "ERROR",T_total_s=None)
    else:
        record.update(status="OK",T_total_s=elapsed)
    for suffix,key in ((".meta.json","engine_meta"),(".progress.json","last_progress")):
        p=Path(str(raw)+suffix)
        if p.exists():record[key]=json.loads(p.read_text())
    signatures=[]
    if raw.exists():
        with raw.open("rb") as source,gzip.open(output/"result.jsonl.gz","wb",compresslevel=1) as target:
            for line in source:
                if not line.endswith(b"\n"):
                    record["partial_last_row_bytes"]=len(line)
                    break
                row=json.loads(line)
                target.write(line)
                digest=hashlib.sha256(json.dumps({k:row[k] for k in SIGNATURE},sort_keys=True,separators=(",",":")).encode()).hexdigest()
                signatures.append(dict(scenario_id=row["scenario_id"],sha256=digest,
                                       cmax=row["cmax"],mission_success=row["mission_success"],counters=row["counters"]))
        raw.unlink()  # Exact full JSONL retained losslessly in gzip, outside timer.
    record["scenarios_completed"]=len(signatures)
    record["signatures"]=signatures
    if record["status"]=="OK" and len(signatures)!=count:record["status"]="INCOMPLETE_OUTPUT"
    result_path.write_text(json.dumps(record,indent=2))
    print(json.dumps({k:v for k,v in record.items() if k not in ("signatures",)}),flush=True)
    return record


def main():
    if os.environ.get("GITHUB_ACTIONS")!="true":raise SystemExit("Actions only")
    p=argparse.ArgumentParser()
    p.add_argument("--dataset",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--k",type=int,default=10)
    p.add_argument("--limit",type=int,default=300)
    p.add_argument("--paired",action="store_true")
    p.add_argument("--round",type=int,default=0)
    args=p.parse_args()
    engines=("tsfg","des","dag")
    if args.paired:
        shift=args.round%3
        engines=engines[shift:]+engines[:shift]
        engines=engines+engines[::-1]
    records=[]
    for i,engine in enumerate(engines):
        records.append(run_one(args.dataset,engine,args.k,args.output/f"{i}-{engine}",args.limit,
                               label=f"round-{args.round}" if args.paired else "screen"))
    summary=dict(status="MEASURED_NOT_YET_VALIDATED",records=[str(p.relative_to(args.output)) for p in args.output.glob("*/measurement.json")])
    (args.output/"summary.json").write_text(json.dumps(summary,indent=2))


if __name__=="__main__":main()
