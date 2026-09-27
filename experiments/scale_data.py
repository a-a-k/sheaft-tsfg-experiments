"""Normative E2 generator. Execution and tests are restricted to Actions."""
import argparse
import gzip
import hashlib
import heapq
import json
import io
import math
import os
from pathlib import Path
import struct
import resource
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validation.checks import validate_dataset

VERSION = "e2-earliest-start-2"


def rng(dataset_id, purpose, scenario_id="none"):
    raw = f"20260926|1.1|{dataset_id}|{scenario_id}|{purpose}".encode()
    seed = int.from_bytes(hashlib.sha256(raw).digest()[:8], "little")
    return np.random.Generator(np.random.PCG64(seed))


from planning.list_v1 import schedule


def naive_schedule(ops, machines):
    """Small independent exhaustive oracle, deliberately no frontier heaps."""
    assigned, tail, queues = set(), [0]*machines, [[] for _ in range(machines)]
    while len(assigned) < len(ops):
        candidates = []
        for o in ops:
            if o["id"] in assigned or any(p not in assigned for p in o["predecessors"]):
                continue
            for a in o["alternatives"]:
                start = max([o["release"], tail[a["machine"]],
                             *(ops[p]["planned_end"] for p in o["predecessors"])])
                candidates.append((start, start+a["work"], o["job"], o["id"], a["machine"]))
        start, end, _, i, m = min(candidates)
        ops[i].update(machine=m, work=end-start, planned_start=start, planned_end=end)
        assigned.add(i)
        queues[m].append(i)
        tail[m] = end
    return queues


def composition(n, family, seed, machines=200, alternatives_count=None):
    assert n % 10 == 0 and machines % 10 == 0
    width = machines // 10
    identity = f"{family}-N{n}-M{machines}-s{seed}"
    routes, durations = rng(identity, "routes"), rng(identity, "durations")
    catalog = [[dict(machine=g*width+k, work=(20+4*g)*100) for k in range(width)] for g in range(10)]
    ops = []
    for j in range(n//10):
        groups = range(10) if family == "F1" else routes.permutation(10)
        for k, group in enumerate(groups):
            group = int(group)
            i = 10*j+k
            if family == "F1":
                alternatives = catalog[group]
            else:
                count = min(alternatives_count or (3 if machines == 200 else 2), width)
                chosen = routes.choice(width, count, replace=False)
                base = int(durations.integers(20, 61))
                alternatives = [dict(machine=group*width+int(m), work=((base*coef+4)//5)*100)
                                for m, coef in zip(chosen, (4,5,6))]
            pred = [] if k == 0 else [i-1]
            if family == "F3":
                if k == 3: pred = []
                if k == 6: pred = [i-1, i-4]
            ops.append(dict(id=i, job=j, release=0, predecessors=pred, alternatives=alternatives))
    return ops


def make_dataset(n, family, density, seed, machines=200, alternatives_count=None):
    identity = f"{family}-{density}-N{n}-M{machines}-s{seed}"
    if alternatives_count is not None:identity+=f"-A{alternatives_count}"
    ops = composition(n, family, seed, machines, alternatives_count)
    queues = schedule(ops, machines)
    c_dense = max(o["planned_end"] for o in ops)
    releases = [0]*(n//10)
    metadata = dict(generator_version=VERSION, family=family, density=density, seed=seed,
                    n=n, machines=machines, C_dense_ticks=c_dense)
    if alternatives_count is not None:metadata['alternatives_per_operation']=alternatives_count
    if density == "SPARSE":
        releases = [int(r)*100 for r in rng(identity, "arrivals").integers(0, 3*(c_dense//100)+1, n//10)]
    elif density == "BURST":
        import copy
        offset, release, groups = 0, 0, []
        for b in range(4):
            count = n//10//4 + (b < n//10%4)
            subset = copy.deepcopy(ops[10*offset:10*(offset+count)])
            for o in subset:
                o["id"] -= 10*offset
                o["predecessors"] = [p-10*offset for p in o["predecessors"]]
            schedule(subset, machines)
            duration = max(o["planned_end"] for o in subset)
            releases[offset:offset+count] = [release]*count
            groups.append(dict(first_job=offset, jobs=count, release=release, duration=duration))
            release += duration + max(100, c_dense)
            offset += count
        metadata["burst_groups"] = groups
        metadata["minimum_gap_ticks"] = max(100, c_dense)
    elif density != "DENSE":
        raise ValueError(density)
    if density != "DENSE":
        for o in ops:
            o["release"] = releases[o["job"]]
        queues = schedule(ops, machines)
    jobs = [dict(id=j, release=r, final_operation=10*j+9) for j, r in enumerate(releases)]
    data = dict(schema_version="1.1", dataset_id=identity, tick_unit="0.01 second",
                operations=ops, queues=queues, jobs=jobs, metadata=metadata)
    validate_dataset(data)
    if density == "BURST":
        for prev, nxt in zip(metadata["burst_groups"], metadata["burst_groups"][1:]):
            last = max(ops[10*j+9]["planned_end"] for j in range(prev["first_job"], prev["first_job"]+prev["jobs"]))
            assert nxt["release"]-last >= metadata["minimum_gap_ticks"]
    metadata["C0_ticks"] = max(o["planned_end"] for o in ops)
    metadata["D_ticks"] = metadata["C0_ticks"]*11//10
    return data


def scenarios(data, count=1000, purpose="scale_scenarios"):
    result = []
    c0 = data["metadata"]["C0_ticks"]/100
    width = len(data["queues"])//10
    for i in range(count):
        source = rng(data["dataset_id"], purpose+":failures", str(i))
        recovery = rng(data["dataset_id"], purpose+":recovery", str(i))
        work_source = rng(data["dataset_id"], purpose+":work", str(i))
        start_s = float(source.uniform(.1*c0, .9*c0))
        duration = float(recovery.choice([.01,.05,.1]))*c0
        start = math.floor(start_s+.5)*100
        end = max(start+100, math.floor(start_s+duration+.5)*100)
        affected, overrides = [], []
        if i%4 == 0:
            affected = [int(source.integers(len(data["queues"])))]
        elif i%4 == 1:
            affected = [int(m) for m in source.choice(len(data["queues"]), 2, replace=False)]
        elif i%4 == 2:
            op = int(work_source.integers(len(data["operations"])))
            coef = int(work_source.choice([125,150,200]))
            overrides = [[op, math.ceil(data["operations"][op]["work"]*coef/10000)*100]]
        else:
            g = int(source.integers(10))
            affected = [g*width+int(m) for m in source.choice(width, min(5,width), replace=False)]
        result.append(dict(id=f"S{i:04d}", failures=[[m,start,end] for m in affected], work_overrides=overrides))
    return result


def write_binary(data, path):
    with Path(path).open("wb") as f:
        f.write(b"TSFGBIN1")
        f.write(struct.pack("<III", len(data["operations"]),len(data["jobs"]),len(data["queues"])))
        for o in data["operations"]:
            f.write(struct.pack("<IIqqqI",o["job"],o["machine"],o["work"],o["planned_start"],o["release"],len(o["predecessors"])))
            f.write(struct.pack(f"<{len(o['predecessors'])}I",*o["predecessors"]))
        for q in data["queues"]:
            f.write(struct.pack("<I",len(q)))
            f.write(struct.pack(f"<{len(q)}I",*q))
        f.write(struct.pack(f"<{len(data['jobs'])}I",*(j["final_operation"] for j in data["jobs"])))


def read_binary(path):
    with Path(path).open("rb") as f:
        magic=f.read(8)
        assert magic in (b"TSFGBIN1",b"TSFGGRP1")
        n,jobs,machines = struct.unpack("<III",f.read(12))
        types=[]
        if magic==b"TSFGGRP1":
            count,=struct.unpack("<I",f.read(4))
            assert 0<count<=n
            types=struct.unpack(f"<{count}q",f.read(8*count))
            assert min(types)>0
        ops=[]
        for i in range(n):
            if types:
                j,m,type_id,s,r,k=struct.unpack("<IIIqqI",f.read(32))
                p=types[type_id]
            else:
                j,m,p,s,r,k = struct.unpack("<IIqqqI",f.read(36))
            pred = list(struct.unpack(f"<{k}I",f.read(k*4)))
            ops.append(dict(id=i,job=j,machine=m,work=p,planned_start=s,planned_end=s+p,release=r,predecessors=pred))
        queues=[]
        for _ in range(machines):
            k,=struct.unpack("<I",f.read(4))
            queues.append(list(struct.unpack(f"<{k}I",f.read(k*4))))
        finals=struct.unpack(f"<{jobs}I",f.read(jobs*4))
        assert not f.read(1)
    return dict(operations=ops,queues=queues,jobs=[dict(id=j,final_operation=i,release=ops[i]["release"]) for j,i in enumerate(finals)])


def sha256(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("Actions only")
    p=argparse.ArgumentParser()
    p.add_argument("--n",type=int,required=True)
    p.add_argument("--family",choices=["F1","F2","F3"],required=True)
    p.add_argument("--density",choices=["DENSE","SPARSE","BURST"],default="DENSE")
    p.add_argument("--seed",type=int,required=True)
    p.add_argument("--machines",type=int,default=200)
    p.add_argument("--alternatives",type=int,choices=[0,2,3],default=0)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    begin=time.monotonic()
    data=make_dataset(args.n,args.family,args.density,args.seed,args.machines,args.alternatives or None)
    args.output.mkdir(parents=True,exist_ok=True)
    write_binary(data,args.output/"input.bin")
    # Full alternative sets and schedule provenance; never read by timed engines.
    with (args.output/"operations.jsonl.gz").open("wb") as raw, gzip.GzipFile(filename="",fileobj=raw,mode="wb",compresslevel=1,mtime=0) as compressed, io.TextIOWrapper(compressed,encoding="utf-8") as f:
        for o in data["operations"]:
            f.write(json.dumps(o,separators=(",",":"))+"\n")
    (args.output/"scenarios-1000.json").write_text(json.dumps(scenarios(data),separators=(",",":")))
    (args.output/"sample.json").write_text(json.dumps(data["operations"][:10],indent=2))
    manifest=dict(dataset_id=data["dataset_id"],metadata=data["metadata"],schema="TSFGBIN1",
                  generation_wall_s=time.monotonic()-begin,generator_rss_peak_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                  validation="PASS",seed_spec="PCG64/SHA256/8-byte-LE",
                  files={name:sha256(args.output/name) for name in ("input.bin","operations.jsonl.gz","scenarios-1000.json")})
    (args.output/"manifest.json").write_text(json.dumps(manifest,indent=2))
    print(json.dumps(manifest),flush=True)


if __name__ == "__main__":
    main()
