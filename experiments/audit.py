"""Correctness + CPU cost audit; instrumented times do not enter H3."""
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.scale_run import run_one


def profile_top(binary,profile,target):
    result=subprocess.run(["go","tool","pprof","-top","-nodecount=40",binary,str(profile)],capture_output=True,text=True,check=True)
    target.write_text(result.stdout)
    result=subprocess.run(["go","tool","pprof","-top","-cum","-nodecount=40",binary,str(profile)],capture_output=True,text=True,check=True)
    target.with_name(target.stem+"-cumulative.txt").write_text(result.stdout)


def main():
    if os.environ.get("GITHUB_ACTIONS")!="true":raise SystemExit("Actions only")
    root=Path("artifacts/audit");root.mkdir(parents=True,exist_ok=True)
    private=Path(".private/profiles");private.mkdir(parents=True,exist_ok=True)
    binary=".private/runtime/tsfg"
    original=[]
    for i in range(2):
        env={**os.environ,"TSFG_REPLAY_OZON":"true","GOMAXPROCS":"1",
             "TSFG_REPLAY_OUTPUT":str(root/f"ozon-replay-{i}.json")}
        if i==1:env["TSFG_CPU_PROFILE"]=str(private/"original.pprof")
        with (private/"original.log").open("w") as log:
            subprocess.run([binary],env=env,check=True,timeout=300,stdout=log,stderr=log)
        original.append(json.loads((root/f"ozon-replay-{i}.json").read_text()))
    profile_top(binary,private/"original.pprof",root/"ozon-cpu-top.txt")
    history=json.loads(Path(".private/upstream/contracts/convergence/outputs/convergence.json").read_text())
    regime=next(r for r in history["timestep"] if r["id"]=="healthy_100k")
    point=next(r for r in regime["points"] if r["dt_s"]==5)
    expected={m["metric"]:m["value"] for m in point["metrics"]}
    for replay in original:
        assert replay["workload_fingerprint"]==regime["workload_fingerprint"]
        for key,value in replay["metrics"].items():
            assert abs(value-expected[key])<=1e-7,(key,value,expected[key])
    (root/"ozon-reproduction-check.json").write_text(json.dumps(dict(status="PASS",
        workload_fingerprint=regime["workload_fingerprint"],historical_runtime_ms=point["runtime_ms"],
        metric_checks=2*len(original[0]["metrics"]),
        scope="Exact historical metric reproduction; historical runtime is not a paired benchmark"),indent=2))
    for family in ("F1","F2"):
        folder=root/family;folder.mkdir(exist_ok=True)
        subprocess.run([sys.executable,"experiments/scale_data.py","--n","10000","--family",family,
                        "--seed","902","--output",str(folder/"dataset")],check=True)
        order=("baseline","tsfg","grid","des","dag","dag","des","grid","tsfg","baseline")
        for index,engine in enumerate(order):
            actual="tsfg" if engine=="baseline" else engine
            binary_override=".private/runtime/tsfg-baseline" if engine=="baseline" else None
            run_one(folder/"dataset",actual,100,folder/"measurements"/f"{index:02d}-{engine}",
                    label=f"audit-uninstrumented-{engine}",binary_override=binary_override)
        subprocess.run([sys.executable,"validation/scale_results.py","--dataset",str(folder/"dataset"),
                        "--results",str(folder/"measurements")],check=True)
        os.environ["TSFG_CPU_PROFILE"]=str(private/f"{family}.pprof")
        run_one(folder/"dataset","tsfg",100,folder/"profiled"/"tsfg",label="audit-CPU-PROFILE-not-H3")
        del os.environ["TSFG_CPU_PROFILE"]
        profile_top(binary,private/f"{family}.pprof",folder/"tsfg-cpu-top.txt")
        totals={}
        with gzip.open(folder/"measurements"/"01-tsfg"/"result.jsonl.gz","rt") as f:
            for line in f:
                row=json.loads(line)
                for key,value in row["phase_seconds"].items():totals[key]=totals.get(key,0)+value
        (folder/"phase-seconds.json").write_text(json.dumps(totals,indent=2))
    summary=dict(status="PASS",cases=["original healthy_100k","F1-10000-seed902","F2-10000-seed902"],
                 K=100,output="SCHEDULE",controls=["original TSFG","auxiliary C++ grid","DES","DAG"],
                 note="Profiles are diagnostic. No speedup accepted from instrumented times.")
    (root/"summary.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary))


if __name__=="__main__":main()
