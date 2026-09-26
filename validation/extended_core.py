"""E0-extended controls and differential tests, separate from base acceptance."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from validation.core import instance
from references.extended_ref import simulate


def native(data,sc,horizon,delta,folder,mode="DIAGNOSTIC"):
    folder.mkdir(parents=True,exist_ok=True)
    (folder/"input.json").write_text(json.dumps(data))
    (folder/"scenarios.json").write_text(json.dumps(sc))
    target=folder/f"tsfg-ext-{delta}-{mode}-{horizon}.jsonl"
    subprocess.run([".private/runtime/tsfg","tsfg-ext",str(folder/"input.json"),str(folder/"scenarios.json"),
                    str(target),mode,str(horizon),str(delta)],check=True,timeout=300,
                   env={**os.environ,"TSFG_OP_DRIVER":"true","GOMAXPROCS":"1"})
    return [json.loads(line) for line in target.read_text().splitlines()]


def main():
    if os.environ.get("GITHUB_ACTIONS")!="true":raise SystemExit("Actions only")
    root=Path("artifacts/e0-extended");root.mkdir(parents=True,exist_ok=True)
    plain=dict(id="base",failures=[],work_overrides=[])
    cases=[]
    serial=instance([(0,100,0,[],0,0),(0,100,100,[0],0,0)])
    serial["buffer_capacity"]=1
    cases.append(("self_handoff",serial,plain,[100,200]))
    handoff=instance([(0,100,0,[],0,0),(1,100,100,[0],0,0)])
    handoff["buffer_capacity"]=1
    cases.append(("direct_handoff",handoff,plain,[100,200]))
    resource=instance([(0,200,0,[],0,0),(1,100,0,[],1,0)])
    resource["shared_operations"]=[0,1]
    cases.append(("shared_serialization",resource,plain,[200,300]))
    cases.append(("shared_failure_hold",resource,dict(plain,id="shared",shared_failures=[[50,150]]),[300,400]))
    cases.append(("machine_failure_holds_shared",resource,dict(plain,id="machine",failures=[[0,50,150]]),[300,400]))
    # One waiting part fills M1's buffer; the other holds M0 until M1 starts it.
    blocked=instance([(1,300,0,[],0,0),(0,100,0,[],1,0),(1,100,300,[1],1,0),
                      (0,100,100,[],2,0),(1,100,400,[3],2,0),(0,100,200,[],3,0)])
    blocked["buffer_capacity"]=1
    cases.append(("blocked_after_processing",blocked,plain,[300,100,400,200,500,400]))
    # Both machines retain parts destined for a full opposite buffer; heads wait.
    deadlock=instance([(0,100,0,[],0,0),(1,100,200,[0],0,0),
                       (1,100,0,[],1,0),(0,100,200,[2],1,0),
                       (0,100,300,[],2,0),(1,100,300,[],3,0)])
    deadlock["buffer_capacity"]=1
    cases.append(("finite_buffer_deadlock",deadlock,plain,None))
    checks=0;details=[]
    for label,data,sc,expected in cases:
        ref=simulate(data,sc,2000)
        if expected is not None:assert ref["finish"]==expected,(label,ref["finish"])
        else:assert ref["run_status"]=="DEADLOCK",(label,ref)
        row=native(data,[sc],2000,5,root/label)[0]
        for key in ("start","finish","remaining","state","machine_release","shared_owner","buffer_counts","run_status"):
            assert row[key]==ref[key],(label,key,row[key],ref[key])
        for horizon in (0,50,100,200,300,400,500):
            ref_h=simulate(data,sc,horizon,"MISSION")
            actual=native(data,[sc],horizon,5,root/label,"MISSION")[0]
            for key in ("start","finish","remaining","state","machine_release","shared_owner","buffer_counts","run_status"):
                assert actual[key]==ref_h[key],(label,horizon,key,actual[key],ref_h[key])
            checks+=1
        checks+=1;details.append(dict(case=label,status="PASS"))
    fractional=instance([(0,100,0,[],0,0),(1,100,100,[0],0,0)])
    for speed in (50,75,90,110):
        sc=dict(plain,id=f"speed-{speed}",speed_intervals=[[0,0,2000,speed]])
        ref=simulate(fractional,sc,2000)
        errors=[]
        for delta in (5,1):
            actual=native(fractional,[sc],2000,delta,root/f"speed-{speed}")[0]
            error=max(a-b for a,b in zip(actual["finish"],ref["finish"]))
            assert 0<=error<=len(fractional["operations"])*delta+1e-7
            errors.append(error);checks+=1
        assert errors[1]<=errors[0]+1e-7
        details.append(dict(case=f"speed-{speed}",finish_ref=ref["finish"],max_error_ticks=errors,status="PASS"))
    summary=dict(status="PASS",checks=checks,cases=details,oracle="Fraction continuous event clock",
                 exact_profiles=["finite buffers","shared resource"],approximate_profiles=["fractional speed GRID"])
    (root/"summary.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary))


if __name__=="__main__":main()
