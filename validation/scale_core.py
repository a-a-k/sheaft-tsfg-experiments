"""Generator and binary adapter admission gate, run on Actions."""
import argparse
import copy
import json
import os
from pathlib import Path
import random
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.scale_data import make_dataset, naive_schedule, read_binary, schedule, write_binary
from validation.checks import compare, validate_dataset, validate_result


def main():
    if os.environ.get("GITHUB_ACTIONS")!="true":
        raise SystemExit("Actions only")
    parser=argparse.ArgumentParser()
    parser.add_argument('--engines', nargs='+', choices=['dag','des','tsfg'], default=['dag','des','tsfg'])
    args=parser.parse_args()
    root=Path("artifacts/scale-core")
    root.mkdir(parents=True,exist_ok=True)
    checks=0
    source=random.Random(901)
    for seed in range(80):
        ops=[]
        for i in range(24):
            ops.append(dict(id=i,job=i//4,release=(i//4%3)*100,
                            predecessors=[] if i%4==0 else [i-1],
                            alternatives=[dict(machine=m,work=source.randint(1,10)*100)
                                          for m in source.sample(range(5),source.randint(1,5))]))
        a,b=copy.deepcopy(ops),copy.deepcopy(ops)
        assert schedule(a,5)==naive_schedule(b,5),seed
        assert a==b,seed
        checks+=1
    late=[dict(id=0,job=0,release=10000,predecessors=[],alternatives=[dict(machine=0,work=1000)]),
          dict(id=1,job=1,release=0,predecessors=[],alternatives=[dict(machine=0,work=1000)])]
    assert schedule(late,1)==[[1,0]]
    assert [o["planned_start"] for o in late]==[10000,0]
    # The second operation must prefer start=0,end=1000 over start=100,end=200.
    earliest=[dict(id=0,job=0,release=0,predecessors=[],alternatives=[dict(machine=0,work=100)]),
              dict(id=1,job=1,release=0,predecessors=[],alternatives=[dict(machine=0,work=100),dict(machine=1,work=1000)])]
    schedule(earliest,2)
    assert earliest[1]["machine"]==1 and earliest[1]["planned_start"]==0
    checks+=2
    for family in ("F1","F2","F3"):
        for density in ("DENSE","SPARSE","BURST"):
            data=make_dataset(100,family,density,901)
            validate_dataset(data)
            folder=root/f"{family}-{density}"
            folder.mkdir(exist_ok=True)
            write_binary(data,folder/"input.bin")
            decoded=read_binary(folder/"input.bin")
            for actual,expected in zip(decoded["operations"],data["operations"]):
                for key,value in actual.items():
                    assert value==expected[key]
            assert decoded["queues"]==data["queues"] and decoded["jobs"]==data["jobs"]
            sc=[dict(id="base",failures=[],work_overrides=[]),
                dict(id="failure",failures=[[0,100,20000]],work_overrides=[[10,data["operations"][10]["work"]*2]])]
            (folder/"scenarios.json").write_text(json.dumps(sc))
            (folder/"input.json").write_text(json.dumps(data))
            reference=None
            horizon=data["metadata"]["D_ticks"]
            for engine in args.engines:
                for extension in ("bin","json"):
                    target=folder/f"{engine}-{extension}.jsonl"
                    binary=".private/runtime/tsfg" if engine=="tsfg" else "artifacts/build/simulator"
                    subprocess.run([binary,engine,str(folder/f"input.{extension}"),str(folder/"scenarios.json"),
                                    str(target),"MISSION",str(horizon),"100"],check=True,timeout=120,
                                   env={**os.environ,"TSFG_OP_DRIVER":"true","GOMAXPROCS":"1"})
                    rows=[json.loads(line) for line in target.read_text().splitlines()]
                    if reference is None: reference=rows
                    for scenario,expected,actual in zip(sc,reference,rows):
                        validate_result(data,scenario,actual)
                        compare(expected,actual)
                        checks+=1
    from experiments.input_diagnostics import describe
    for density in ('DENSE','SPARSE','BURST'):
        sample=make_dataset(100,'F1',density,902)
        diagnostic=describe(sample)
        assert diagnostic['lower_bound_ticks']<=diagnostic['C0_ticks']
        assert 0<=diagnostic['global_idle_fraction']<1
        if density=='BURST':assert diagnostic['longest_global_idle_ticks']>=sample['metadata']['minimum_gap_ticks']
        checks+=3
    for machines in (20,200,2000):
        growth=make_dataset(100,'F2','DENSE',902,machines,2)
        assert growth['dataset_id'].endswith('-A2')
        assert all(len(o['alternatives'])==2 for o in growth['operations'])
        original=copy.deepcopy(growth['operations'])
        assert naive_schedule(original,machines)==growth['queues']
        assert original==growth['operations']
        checks+=3
    summary=dict(status="PASS",checks=checks,generator_exhaustive_cases=80,
                 controls=["late priority arrival","earliest start before earliest finish"],
                 binary_json_equivalence=args.engines,families=["F1","F2","F3"],
                 densities=["DENSE","SPARSE","BURST"])
    (root/"summary.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary))


if __name__=="__main__":main()
