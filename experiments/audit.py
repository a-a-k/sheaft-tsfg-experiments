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
    for family in ("F1","F2"):
        folder=root/family;folder.mkdir(exist_ok=True)
        subprocess.run([sys.executable,"experiments/scale_data.py","--n","10000","--family",family,
                        "--seed","902","--output",str(folder/"dataset")],check=True)
        for engine in ("tsfg","grid","des","dag"):
            run_one(folder/"dataset",engine,100,folder/"measurements"/engine,label="audit-uninstrumented")
        subprocess.run([sys.executable,"validation/scale_results.py","--dataset",str(folder/"dataset"),
                        "--results",str(folder/"measurements")],check=True)
        os.environ["TSFG_CPU_PROFILE"]=str(private/f"{family}.pprof")
        run_one(folder/"dataset","tsfg",100,folder/"profiled"/"tsfg",label="audit-CPU-PROFILE-not-H3")
        del os.environ["TSFG_CPU_PROFILE"]
        profile_top(binary,private/f"{family}.pprof",folder/"tsfg-cpu-top.txt")
        totals={}
        with gzip.open(folder/"measurements"/"tsfg"/"result.jsonl.gz","rt") as f:
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
