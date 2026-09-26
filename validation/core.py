"""Hand-calculated E0 cases and differential properties. Actions only."""
import copy
import json
import os
from pathlib import Path
import random
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from references.simpy_ref import simulate
from validation.checks import compare, project, validate_dataset, validate_result

NATIVE_ENGINES = ("tsfg", "grid", "des", "dag")


def instance(rows):
    # rows: machine, work, planned start, predecessors, job, release
    operations = []
    for i, (m, p, s, pred, job, release) in enumerate(rows):
        operations.append(dict(id=i, machine=m, work=p, planned_start=s, planned_end=s+p,
                               predecessors=pred, job=job, release=release,
                               alternatives=[dict(machine=m, work=p)]))
    machines = 1 + max(o["machine"] for o in operations)
    queues = [[o["id"] for o in sorted(operations, key=lambda o: (o["planned_start"], o["id"]))
               if o["machine"] == m] for m in range(machines)]
    jobs = [dict(id=j, release=next(o["release"] for o in operations if o["job"]==j),
                 final_operation=max(o["id"] for o in operations if o["job"]==j))
            for j in range(1+max(o["job"] for o in operations))]
    return dict(schema_version="1.1", dataset_id="e0", tick_unit="0.01 test unit",
                operations=operations, queues=queues, jobs=jobs)


def run_native(engine, data, scenarios, horizon, mode, folder, label):
    dataset = folder / "input.json"
    scenario_file = folder / "scenarios.json"
    dataset.write_text(json.dumps(data))
    scenario_file.write_text(json.dumps(scenarios))
    target = folder / f"{label}-{engine}-{mode}-{horizon}.jsonl"
    binary = ".private/runtime/tsfg" if engine == "tsfg" else "artifacts/build/simulator"
    subprocess.run([binary, engine, str(dataset), str(scenario_file),
                    str(target), mode, str(horizon), "5"], check=True, timeout=120,
                   env={**os.environ, "TSFG_OP_DRIVER": "true", "GOMAXPROCS": "1"})
    return [json.loads(line) for line in target.read_text().splitlines()]


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("E0 runs only in GitHub Actions")
    root = Path("artifacts/e0")
    root.mkdir(parents=True, exist_ok=True)
    base = [(0,300,0,[],0,0), (0,200,300,[0],0,0)]
    cases = [
        ("serial", base, [], [0,300], [300,500]),
        ("resume", base, [[0,100,300]], [0,500], [500,700]),
        ("failure_at_completion", base, [[0,300,500]], [0,500], [300,700]),
        ("initial_failure", base, [[0,0,200]], [200,500], [500,700]),
        ("overlapping_failures", base, [[0,100,300],[0,200,400]], [0,600], [600,800]),
        ("touching_failures", base, [[0,100,200],[0,200,300]], [0,500], [500,700]),
        ("same_machine_two_jobs", [(0,300,0,[],0,0),(0,200,300,[],1,0)], [], [0,300], [300,500]),
        ("parallel", [(0,300,0,[],0,0),(1,200,0,[],1,0)], [], [0,0], [300,200]),
        ("head_of_line", [(1,300,0,[],0,0),(0,100,300,[0],0,0),(0,100,400,[],1,0)],
            [[1,100,500]], [0,700,800], [700,800,900]),
        ("simultaneous_assembly", [(0,300,0,[],0,0),(1,300,0,[],0,0),(2,200,300,[0,1],0,0)],
            [], [0,0,300], [300,300,500]),
        ("material_release", [(0,100,200,[],0,200)], [], [200], [300]),
        ("planned_floor", [(0,100,200,[],0,0)], [], [200], [300]),
        ("repair_at_start", [(0,100,200,[],0,0)], [[0,0,200]], [200], [300]),
        ("failure_prevents_start", [(0,100,200,[],0,0)], [[0,200,300]], [300], [400]),
    ]
    summary = {"suite":"E0-core", "status":"RUNNING", "hand_cases":[], "property_cases":[],
               "engines":[*NATIVE_ENGINES,"simpy"], "invariant_checks":0, "comparisons":0}
    try:
        for label, rows, failures, expected_s, expected_c in cases:
            folder = root / label
            folder.mkdir(exist_ok=True)
            data=instance(rows)
            validate_dataset(data)
            sc=dict(id=label, failures=failures, work_overrides=[])
            oracle=simulate(data,sc,2000,"DIAGNOSTIC")
            assert oracle["start"]==expected_s and oracle["finish"]==expected_c, label
            trajectories={"simpy":oracle}
            for engine in NATIVE_ENGINES:
                row=run_native(engine,data,[sc],2000,"DIAGNOSTIC",folder,"trajectory")[0]
                assert row["start"]==expected_s and row["finish"]==expected_c, label
                trajectories[engine]=row
            for row in trajectories.values():
                validate_result(data,sc,row); summary["invariant_checks"]+=1
                compare(oracle,row); summary["comparisons"]+=1
            # Includes fractional last steps, starts at D, repairs at D,
            # completion at D, suspension and early completion padding.
            for h in (0,100,200,299,300,499,500,501,700,1200):
                projected=project(data,sc,oracle,h)
                candidates={"simpy":simulate(data,sc,h,"MISSION")}
                for engine in NATIVE_ENGINES:
                    candidates[engine]=run_native(engine,data,[sc],h,"MISSION",folder,"boundary")[0]
                for row in candidates.values():
                    validate_result(data,sc,row); summary["invariant_checks"]+=1
                    compare(projected,row); summary["comparisons"]+=1
            for engine in NATIVE_ENGINES:
                censored=run_native(engine,data,[sc],99,"DIAGNOSTIC",folder,"censored")[0]
                ref=simulate(data,sc,99,"DIAGNOSTIC")
                validate_result(data,sc,censored); compare(ref,censored)
                summary["invariant_checks"]+=1; summary["comparisons"]+=1
            summary["hand_cases"].append(dict(id=label,status="PASS"))

        rng=random.Random(20260926)
        for seed in range(24):
            rows=[]; machines=[0]*3; jobs=[0]*3; previous=[None]*3
            for i in range(18):
                job=i%3; m=rng.randrange(3); work=5*rng.randint(1,20)
                planned=max(machines[m],jobs[job])
                rows.append((m,work,planned,[] if previous[job] is None else [previous[job]],job,0))
                machines[m]=jobs[job]=planned+work; previous[job]=i
            data=instance(rows); validate_dataset(data)
            a=5*rng.randrange(1,20); b=a+5*rng.randrange(1,20); m=rng.randrange(3)
            scenarios=[dict(id="base",failures=[[m,a,b]],work_overrides=[]),
                       dict(id="more_work",failures=[[m,a,b]],work_overrides=[[seed%18,rows[seed%18][1]+50]]),
                       dict(id="longer_failure",failures=[[m,a,b+50]],work_overrides=[])]
            folder=root/f"property-{seed}"; folder.mkdir(exist_ok=True)
            references=[simulate(data,s,10000,"DIAGNOSTIC") for s in scenarios]
            for engine in NATIVE_ENGINES:
                results=run_native(engine,data,scenarios,10000,"DIAGNOSTIC",folder,"property")
                for sc,ref,row in zip(scenarios,references,results):
                    validate_result(data,sc,row); compare(ref,row)
                    summary["invariant_checks"]+=1; summary["comparisons"]+=1
                for changed in results[1:]:
                    assert all(x>=y for x,y in zip(changed["finish"],results[0]["finish"]))
            summary["property_cases"].append(dict(id=seed,status="PASS"))

        # Ensure validation is capable of rejecting a corrupted trajectory.
        corrupt=copy.deepcopy(oracle); corrupt["remaining"][0]=1
        try:
            validate_result(instance(cases[-1][1]), dict(id="bad",failures=cases[-1][2],work_overrides=[]),corrupt)
        except AssertionError:
            summary["validator_negative_control"]="PASS"
        else:
            raise AssertionError("Validator accepted corrupt completed work")
        summary["status"]="PASS"
    except Exception as exc:
        summary["status"]="FAIL"; summary["error"]=str(exc)
        raise
    finally:
        (root/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary,indent=2))


if __name__=="__main__": main()
