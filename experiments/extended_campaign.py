"""E1X on explicitly named extensions of Mk01, after E0-extended."""
import copy
import itertools
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from references.extended_ref import simulate
from validation.checks import validate_dataset
from validation.extended_core import native


def full_scenarios(data):
    c0=data["C0"];m=len(data["queues"])
    result=[dict(id="M0",family="M0",failures=[],work_overrides=[])]
    for k in (1,2):
        for machines in itertools.combinations(range(m),k):
            for a,b in itertools.product((10,30,50,70,90),(5,10,20)):
                begin,length=c0*a//100,c0*b//100
                result.append(dict(id=f"M{k}-{machines}-{a}-{b}",family=f"M{k}",
                                   failures=[[machine,begin,begin+length] for machine in machines],work_overrides=[]))
    for o in data["operations"]:
        for pct in (125,150,200):
            result.append(dict(id=f"M3-{o['id']}-{pct}",family="M3",failures=[],work_overrides=[[o["id"],o["work"]*pct//100]]))
    assert len(result)==481
    return result


def freeze_baseline(source,folder):
    data=copy.deepcopy(source)
    empty=dict(id="nominal-probe",failures=[],work_overrides=[])
    probe=simulate(data,empty,source["C0"]*20)
    (folder/"original-baseline-probe.json").write_text(json.dumps(probe,indent=2))
    if not probe["completion_known"]:
        data["queues"]=[[] for q in data["queues"]]
        t=0
        for o in sorted(data["operations"],key=lambda o:(o["job"],o["id"])):
            o["planned_start"]=t;o["planned_end"]=t+o["work"]
            data["queues"][o["machine"]].append(o["id"])
            t+=o["work"]
        reason="Original extended baseline deadlocked/censored; serial feasible replacement"
    else:
        for o,s in zip(data["operations"],probe["start"]):
            assert isinstance(s,int)
            o["planned_start"]=s;o["planned_end"]=s+o["work"]
        reason="Freeze feasible nominal extended execution"
    data["C0"]=max(o["planned_end"] for o in data["operations"])
    check=simulate(data,empty,data["C0"]*10)
    assert check["completion_known"] and check["cmax"]==data["C0"]
    assert check["start"]==[o["planned_start"] for o in data["operations"]]
    validate_dataset(data)
    (folder/"baseline.json").write_text(json.dumps(data,indent=2))
    (folder/"baseline-change.json").write_text(json.dumps(dict(reason=reason,old_C0=source["C0"],new_C0=data["C0"]),indent=2))
    return data


def exact_series(data,scenarios,folder):
    horizon=data["C0"]*125//10
    rows=native(data,scenarios,horizon,5,folder)
    reference=[];false_success=false_failure=0;deadlock=0
    for sc,row in zip(scenarios,rows):
        ref=simulate(data,sc,horizon)
        reference.append(ref)
        for key in ("start","finish","remaining","state","machine_release","shared_owner","buffer_counts","run_status","cmax"):
            assert row[key]==ref[key],(data["dataset_id"],sc["id"],key,row[key],ref[key])
        deadlock+=row["run_status"]=="DEADLOCK"
        for deadline in (data["C0"],data["C0"]*110//100,data["C0"]*125//100):
            expected=ref["cmax"] is not None and ref["cmax"]<=deadline
            actual=row["cmax"] is not None and row["cmax"]<=deadline
            false_success+=actual and not expected;false_failure+=expected and not actual
    (folder/"fraction-ref.jsonl").write_text("".join(json.dumps(r)+"\n" for r in reference))
    return dict(scenarios=len(rows),deadline_checks=len(rows)*3,deadlock=deadlock,
                false_success=false_success,false_failure=false_failure,status="PASS")


def main():
    if os.environ.get("GITHUB_ACTIONS")!="true":raise SystemExit("Actions only")
    assert json.loads(Path("artifacts/e0-extended/summary.json").read_text())["status"]=="PASS"
    source=json.loads(Path("artifacts/mk01/input/dataset.json").read_text())
    root=Path("artifacts/e1x");root.mkdir(parents=True,exist_ok=True)
    summary=dict(status="RUNNING",buffers={},shared_resource={},fractional_speed={})
    for capacity in (1,2,4):
        folder=root/f"buffer-{capacity}";folder.mkdir(exist_ok=True)
        data=copy.deepcopy(source);data["buffer_capacity"]=capacity
        data["dataset_id"]+=f"-buffer-{capacity}"
        data=freeze_baseline(data,folder)
        scenarios=full_scenarios(data)
        # M1 gate before the complete M1–M3 campaign; no rank/effect cherry-picking.
        exact_series(data,[s for s in scenarios if s["family"] in ("M0","M1")],folder/"m1-gate")
        summary["buffers"][str(capacity)]=exact_series(data,scenarios,folder/"full")
    folder=root/"shared";folder.mkdir(exist_ok=True)
    data=copy.deepcopy(source)
    data["shared_operations"]=[min(o["id"] for o in data["operations"] if o["job"]==j["id"])
                               for j in data["jobs"] if j["id"]%2==0]
    data["dataset_id"]+="-shared-setup"
    data=freeze_baseline(data,folder)
    scenarios=[]
    for a,b in itertools.product((10,30,50,70,90),(5,10,20)):
        begin,length=data["C0"]*a//100,data["C0"]*b//100
        scenarios.append(dict(id=f"shared-{a}-{b}",failures=[],work_overrides=[],shared_failures=[[begin,begin+length]]))
    summary["shared_resource"]=exact_series(data,scenarios,folder/"series")
    folder=root/"speed";folder.mkdir(exist_ok=True)
    scenarios=[];c0=source["C0"]
    for machine,a,rate in itertools.product(range(6),(10,30,50,70,90),(50,75,90)):
        begin=c0*a//100
        scenarios.append(dict(id=f"speed-{machine}-{a}-{rate}",failures=[],work_overrides=[],
                              speed_intervals=[[machine,begin,begin+c0//5,rate]]))
    reference=[simulate(source,sc,c0*125//10) for sc in scenarios]
    (folder/"fraction-ref.jsonl").write_text("".join(json.dumps(r)+"\n" for r in reference))
    errors={};outcomes={}
    for delta in (5,1):
        rows=native(source,scenarios,c0*125//10,delta,folder)
        errors[delta]=[];false_success=false_failure=0
        for ref,row in zip(reference,rows):
            assert ref["completion_known"] and row["completion_known"]
            err=max(abs(a-b) for key in ("start","finish") for a,b in zip(row[key],ref[key]))
            assert all(a+1e-7>=b for a,b in zip(row["finish"],ref["finish"]))
            errors[delta].append(err)
            for d in (c0,c0*110//100,c0*125//100):
                false_success+=(row["cmax"]<=d<ref["cmax"])
                false_failure+=(ref["cmax"]<=d<row["cmax"])
        outcomes[delta]=dict(false_success=false_success,false_failure=false_failure)
    summary["fractional_speed"]=dict(scenarios=90,delta_ticks=[5,1],
        max_individual_time_error_ticks={str(k):max(v) for k,v in errors.items()},classification=outcomes,
        refined_not_worse=sum(b<=a+1e-7 for a,b in zip(errors[5],errors[1])),
        accuracy="Approximate grid; exact continuous event reference",status="MEASURED")
    summary["status"]="PASS"
    (root/"summary.json").write_text(json.dumps(summary,indent=2))
    report=["# E1X: расширения Mk01", "", "Исходное ядро S1 обслуживает работу; новый адаптер задаёт владение деталями и ресурсом.",
            "Непрерывный независимый эталон использует рациональные времена Fraction.", "", "```json",json.dumps(summary,ensure_ascii=False,indent=2),"```", "",
            "Для буферов сохранены старые и новые планы, причины изменения и исходные блокировки.",
            "Дробная скорость GRID имеет погрешность; её результаты не названы точными и не входят в H3."]
    (root/"REPORT_RU.md").write_text("\n".join(report)+"\n")
    print(json.dumps(summary))


if __name__=="__main__":main()
