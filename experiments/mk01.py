"""Freeze one feasible Mk01 schedule and the predeclared 481-scenario campaign."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import sys

from ortools.sat.python import cp_model

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validation.checks import validate_dataset


def parse(path):
    rows = [list(map(int,line.split())) for line in path.read_text().splitlines() if line.strip()]
    job_count,machines = rows[0]
    assert len(rows) == job_count+1
    jobs=[]
    for row in rows[1:]:
        count=row[0];cursor=1;operations=[]
        for _ in range(count):
            alternatives=row[cursor];cursor+=1
            options=[]
            for _ in range(alternatives):
                machine,work=row[cursor:cursor+2];cursor+=2
                assert 0<=machine<machines and work>0
                options.append((machine,work))
            assert len({m for m,_ in options})==len(options)
            operations.append(options)
        assert cursor==len(row)
        jobs.append(operations)
    assert (job_count,machines,sum(map(len,jobs)))==(10,6,55)
    return jobs,machines


def main():
    if os.environ.get("GITHUB_ACTIONS")!="true": raise SystemExit("Actions only")
    out=Path("artifacts/mk01/input");out.mkdir(parents=True,exist_ok=True)
    source=Path("fixtures/mk01/mk01.txt")
    jobs,machines=parse(source)
    model=cp_model.CpModel()
    bound=sum(max(p for _,p in op) for job in jobs for op in job)
    slots=[[] for _ in range(machines)]
    records=[];job_ends=[]
    for j,job in enumerate(jobs):
        previous=None
        for k,options in enumerate(job):
            i=len(records)
            start=model.new_int_var(0,bound,f"s{i}")
            end=model.new_int_var(0,bound,f"c{i}")
            selected=[]
            for m,p in options:
                choice=model.new_bool_var(f"x{i}_{m}")
                interval=model.new_optional_interval_var(start,p,end,choice,f"I{i}_{m}")
                slots[m].append(interval);selected.append(choice)
            model.add_exactly_one(selected)
            if previous is not None: model.add(start>=records[previous][3])
            records.append((j,k,start,end,options,selected,previous))
            previous=i
        job_ends.append(previous)
    for intervals in slots: model.add_no_overlap(intervals)
    cmax=model.new_int_var(0,bound,"C0")
    model.add_max_equality(cmax,[records[i][3] for i in job_ends])
    model.minimize(cmax)
    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=120
    solver.parameters.num_search_workers=1
    solver.parameters.random_seed=20260926
    status=solver.solve(model)
    if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE): raise RuntimeError("No feasible schedule")
    operations=[]
    for i,(j,k,start,end,options,selected,previous) in enumerate(records):
        chosen=[a for a,x in zip(options,selected) if solver.value(x)]
        assert len(chosen)==1
        m,p=chosen[0]
        operations.append(dict(id=i,job=j,job_operation=k,machine=m,work=p*100,
            planned_start=solver.value(start)*100,planned_end=solver.value(end)*100,release=0,
            predecessors=[] if previous is None else [previous],
            alternatives=[dict(machine=m,work=p*100) for m,p in options]))
    queues=[[o['id'] for o in sorted(operations,key=lambda o:(o['planned_start'],o['id']))
             if o['machine']==m] for m in range(machines)]
    C0=solver.value(cmax)*100
    data=dict(schema_version="1.1",dataset_id="Brandimarte-Mk01",tick_unit="0.01 original Mk01 time unit",
              operations=operations,queues=queues,
              jobs=[dict(id=j,release=0,final_operation=i) for j,i in enumerate(job_ends)],C0=C0)
    validate_dataset(data)
    scenarios=[dict(id="M0",family="M0",failures=[],work_overrides=[])]
    for count in (1,2):
        for group in itertools.combinations(range(machines),count):
            for a,b in itertools.product((10,30,50,70,90),(5,10,20)):
                assert C0*a%100==C0*b%100==0
                begin,duration=C0*a//100,C0*b//100
                identity=f"M{count}-{'-'.join(map(str,group))}-a{a}-b{b}"
                scenarios.append(dict(id=identity,family=f"M{count}",machines=list(group),a=a,b=b,
                                      failures=[[m,begin,begin+duration] for m in group],work_overrides=[]))
    for o in operations:
        for pct in (125,150,200):
            assert o['work']*pct%100==0
            scenarios.append(dict(id=f"M3-o{o['id']}-p{pct}",family="M3",operation=o['id'],percent=pct,
                                  failures=[],work_overrides=[[o['id'],o['work']*pct//100]]))
    assert len(scenarios)==481 and len({s['id'] for s in scenarios})==481
    assert all(x%5==0 for s in scenarios for f in s['failures'] for x in f[1:])
    assert all(p%5==0 for s in scenarios for _,p in s['work_overrides'])
    deadlines=[C0,C0*110//100,C0*125//100]
    metadata=dict(solver="OR-Tools CP-SAT",status=solver.status_name(status),seed=20260926,
                  num_workers=1,time_limit_s=120,wall_time_s=solver.wall_time,
                  objective_original_units=C0/100,best_bound_original_units=solver.best_objective_bound,
                  proven_optimal=status==cp_model.OPTIMAL,deadlines=deadlines,
                  diagnostic_horizon=10*max(deadlines),delta_ticks=5,scenario_count=len(scenarios),
                  source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    for name,value in (("dataset.json",data),("scenarios.json",scenarios),("manifest.json",metadata)):
        (out/name).write_text(json.dumps(value,indent=2)+"\n")
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob('*.json'))}
    (out/"sha256.json").write_text(json.dumps(hashes,indent=2)+"\n")
    print(json.dumps(metadata,indent=2))


if __name__=="__main__":main()
