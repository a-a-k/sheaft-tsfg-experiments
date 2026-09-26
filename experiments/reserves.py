"""Frozen ranking, independent holdout scenarios and paired H5 intervals."""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.scale_data import make_dataset, rng, sha256, write_binary
from validation.checks import compare, validate_result


def holdout(data,count=1000,common=False):
    deadline=data["metadata"]["D_ticks"]/100
    horizon=10*deadline
    result=[]
    purpose="h5_common_evaluation" if common else "h5_evaluation"
    for i in range(count):
        failures=[]
        for m in range(len(data["queues"])):
            source=rng(data["dataset_id"],purpose+f":failures:{m}",str(i))
            recovery=rng(data["dataset_id"],purpose+f":recovery:{m}",str(i))
            t=0.
            while True:
                t+=float(source.exponential(10*deadline))
                if t>=horizon:break
                end=t+float(recovery.uniform(.01*deadline,.03*deadline))
                a=math.floor(t+.5)*100;b=max(a+100,math.floor(end+.5)*100)
                failures.append([m,a,b]);t=end
        if common:
            source=rng(data["dataset_id"],purpose+":common",str(i));t=0.
            while True:
                t+=float(source.exponential(2*deadline))
                if t>=horizon:break
                a=math.floor(t+.5)*100;b=max(a+100,math.floor(t+.02*deadline+.5)*100)
                failures.extend([m,a,b] for m in range(5))
        result.append(dict(id=f"{purpose}-{i:04d}",failures=sorted(failures),work_overrides=[]))
    return result


def wilson(success,n):
    z=1.959963984540054;p=success/n;den=1+z*z/n
    middle=(p+z*z/(2*n))/den
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [max(0,middle-half),min(1,middle+half)]


def statistics(data,evidence,purpose):
    assert evidence["status"]=="PASS" and len(evidence["records"])==1000
    outcomes=np.array([r["outcomes"] for r in evidence["records"]],dtype=np.int8)
    assert outcomes.shape==(1000,7)
    e_top=outcomes[:,1:4].mean(axis=1)-outcomes[:,0]
    e_bottom=outcomes[:,4:7].mean(axis=1)-outcomes[:,0]
    difference=e_top-e_bottom
    source=rng(data["dataset_id"],"h5_bootstrap",purpose)
    boots_top=[];boots_difference=[]
    for _ in range(10):
        indices=source.integers(0,1000,size=(1000,1000))
        boots_top.extend(e_top[indices].mean(axis=1))
        boots_difference.extend(difference[indices].mean(axis=1))
    top_ci=np.quantile(boots_top,[.025,.975],method="linear").tolist()
    diff_ci=np.quantile(boots_difference,[.025,.975],method="linear").tolist()
    rates=[]
    for k,m in enumerate(evidence["targets"]):
        successes=int(outcomes[:,k].sum())
        rates.append(dict(machine=m,successes=successes,total=1000,probability=successes/1000,
                          wilson95=wilson(successes,1000),rescued=int(((outcomes[:,k]==1)&(outcomes[:,0]==0)).sum()),
                          new_failures=int(((outcomes[:,k]==0)&(outcomes[:,0]==1)).sum())))
    return dict(status="SUPPORTED" if min(top_ci)>0 and min(diff_ci)>0 else "NOT_SUPPORTED",
                mean_e_T=float(e_top.mean()),mean_d=float(difference.mean()),e_T_ci95=top_ci,d_ci95=diff_ci,
                bootstrap_replicates=10000,scenarios=1000,configurations=rates,
                scope="Independent exact DAG/DES effect assessment; does not establish TSFG speedup")


def transform_gate(data,scenarios,ranking,root):
    transformed=copy.deepcopy(data)
    for o in transformed["operations"]:
        for key in ("work","planned_start","planned_end","release"):o[key]*=11
        o["alternatives"]=[dict(machine=a["machine"],work=a["work"]*11) for a in o["alternatives"]]
    for j in transformed["jobs"]:j["release"]*=11
    write_binary(transformed,root/"transformed.bin")
    horizon=data["metadata"]["D_ticks"]*11
    comparisons=0
    for target in [-1,*ranking["T"],*ranking["B"]]:
        changed=copy.deepcopy(scenarios)
        for sc in changed:
            for f in sc["failures"]:f[1]*=11;f[2]*=11
            if target>=0:
                sc["work_overrides"]=[[i,data["operations"][i]["work"]*10] for i in data["queues"][target]]
        scenario_path=root/f"gate-{target}.json";scenario_path.write_text(json.dumps(changed))
        reference=None
        for engine in ("dag","des","tsfg"):
            binary=".private/runtime/tsfg" if engine=="tsfg" else "artifacts/build/simulator"
            output=root/f"gate-{target}-{engine}.jsonl"
            subprocess.run([binary,engine,str(root/"transformed.bin"),str(scenario_path),str(output),"MISSION",str(horizon),"100"],
                           check=True,timeout=300,env={**os.environ,"TSFG_OP_DRIVER":"true","GOMAXPROCS":"1"})
            rows=[json.loads(line) for line in output.read_text().splitlines()]
            if reference is None:reference=rows
            for sc,row,ref in zip(changed,rows,reference):
                validate_result(transformed,sc,row);compare(ref,row);comparisons+=1
    return comparisons


def main():
    if os.environ.get("GITHUB_ACTIONS")!="true":raise SystemExit("Actions only")
    p=argparse.ArgumentParser()
    p.add_argument("--family",choices=["F1","F2"],required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--gate",action="store_true")
    args=p.parse_args();root=args.output;root.mkdir(parents=True,exist_ok=True)
    n,seed=(1000,902) if args.gate else (100000,101)
    data=make_dataset(n,args.family,"DENSE",seed)
    write_binary(data,root/"input.bin")
    (root/"dataset-metadata.json").write_text(json.dumps(dict(dataset_id=data["dataset_id"],metadata=data["metadata"],input_sha256=sha256(root/"input.bin")),indent=2))
    subprocess.run(["artifacts/build/reserve","rank",str(root/"input.bin"),str(root/"ranking.json")],check=True,timeout=1800)
    ranking=json.loads((root/"ranking.json").read_text())
    # Written before any evaluation scenarios are exposed to intervention selection.
    frozen=dict(T=ranking["T"],B=ranking["B"],ranking_sha256=sha256(root/"ranking.json"),speed_increase_percent=10,
                common_C0_ticks=ranking["C0_ticks"],common_D_ticks=ranking["D_ticks"],dataset_sha256=sha256(root/"input.bin"))
    (root/"frozen-interventions.json").write_text(json.dumps(frozen,indent=2))
    if args.gate:
        scenarios=holdout(data,5)
        # Ensure interruption during service is exercised, even in a small random sample.
        scenarios[0]["failures"].append([ranking["T"][0],100,10000])
        comparisons=transform_gate(data,scenarios,ranking,root)
        (root/"summary.json").write_text(json.dumps(dict(status="PASS",comparisons=comparisons,
            purpose="Exact constant-speed time transformation admission",engines=["tsfg","des","dag"]),indent=2))
        return
    summary=dict(family=args.family,n=n,seed=seed,T=ranking["T"],B=ranking["B"],series={})
    for common in (False,True):
        label="common-cause" if common else "independent"
        scenarios=holdout(data,common=common)
        scenario_path=root/f"scenarios-{label}.json";scenario_path.write_text(json.dumps(scenarios,separators=(",",":")))
        evidence_path=root/f"evaluation-{label}.json"
        subprocess.run(["artifacts/build/reserve","evaluate",str(root/"input.bin"),str(scenario_path),str(root/"ranking.json"),str(evidence_path)],
                       check=True,timeout=2700)
        evidence=json.loads(evidence_path.read_text())
        summary["series"][label]=statistics(data,evidence,label)
        summary["series"][label].update(scenarios_sha256=sha256(scenario_path),evidence_sha256=sha256(evidence_path))
        (root/"summary.json").write_text(json.dumps(summary,indent=2))
    report=["# E4/H5: "+args.family,"","T и B зафиксированы до 1000 независимых оценочных сценариев.",
            "Исходы проверены двумя независимыми точными движками и физическими инвариантами.",
            "Основной H5 относится только к independent; common-cause — отдельный дополнительный опыт.","", "```json",json.dumps(summary,ensure_ascii=False,indent=2),"```", "",
            "Эта серия оценивает полезность ранжирования в заданном профиле отказов. Она не подтверждает ускорения TSFG и не оценивает неизвестную статистику предприятия."]
    (root/"REPORT_RU.md").write_text("\n".join(report)+"\n")
    print(json.dumps(summary),flush=True)


if __name__=="__main__":main()
