"""Normative E2 generator. Execution and tests are restricted to Actions."""
import argparse
import gzip
import hashlib
import heapq
import json
import math
import os
from pathlib import Path
import struct
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validation.checks import validate_dataset

VERSION = "e2-earliest-start-1"


def rng(dataset_id, purpose, scenario_id="none"):
    raw = f"20260926|1.1|{dataset_id}|{scenario_id}|{purpose}".encode()
    seed = int.from_bytes(hashlib.sha256(raw).digest()[:8], "little")
    return np.random.Generator(np.random.PCG64(seed))


def schedule(ops, machines):
    """Indexed ready frontiers, exactly the global normative five-key minimum.

    Future machine entries: (release after planned predecessors, work, job, id).
    Active entries: (work, job, id). Tail only increases. Assigned duplicates
    are removed lazily; changed machine minima invalidate global heap entries.
    """
    queues = [[] for _ in range(machines)]
    tail = [0] * machines
    active, future = ([[] for _ in range(machines)] for _ in range(2))
    done = bytearray(len(ops))
    pending = [len(o["predecessors"]) for o in ops]
    successors = [[] for _ in ops]
    for o in ops:
        for p in o["predecessors"]:
            successors[p].append(o["id"])
    global_heap, current, versions = [], [None] * machines, [0] * machines

    def refresh(m):
        f, a = future[m], active[m]
        while f and (done[f[0][3]] or f[0][0] <= tail[m]):
            ready, work, job, i = heapq.heappop(f)
            if not done[i]:
                heapq.heappush(a, (work, job, i))
        while a and done[a[0][2]]:
            heapq.heappop(a)
        if a:
            p, j, i = a[0]
            key = (tail[m], tail[m] + p, j, i, m)
        elif f:
            r, p, j, i = f[0]
            key = (r, r + p, j, i, m)
        else:
            key = None
        if key != current[m]:
            versions[m] += 1
            current[m] = key
            if key is not None:
                heapq.heappush(global_heap, (*key, versions[m]))

    def admit(i, touched):
        o = ops[i]
        r = max([o["release"], *(ops[p]["planned_end"] for p in o["predecessors"])])
        for alt in o["alternatives"]:
            m, p = alt["machine"], alt["work"]
            if r <= tail[m]:
                heapq.heappush(active[m], (p, o["job"], i))
            else:
                heapq.heappush(future[m], (r, p, o["job"], i))
            touched.add(m)

    touched = set()
    for i, degree in enumerate(pending):
        if not degree:
            admit(i, touched)
    for m in touched:
        refresh(m)
    assigned = 0
    while global_heap:
        start, end, job, i, m, version = heapq.heappop(global_heap)
        if version != versions[m] or done[i]:
            continue
        o = ops[i]
        o.update(machine=m, work=end-start, planned_start=start, planned_end=end)
        done[i] = 1
        assigned += 1
        queues[m].append(i)
        tail[m] = end
        touched = {a["machine"] for a in o["alternatives"]}
        for child in successors[i]:
            pending[child] -= 1
            if pending[child] == 0:
                admit(child, touched)
        for machine in touched:
            refresh(machine)
    if assigned != len(ops):
        raise ValueError("Cyclic or incomplete generator input")
    return queues


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


def composition(n, family, seed, machines=200):
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
                count = min(3 if machines == 200 else 2, width)
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


def make_dataset(n, family, density, seed, machines=200):
    identity = f"{family}-{density}-N{n}-M{machines}-s{seed}"
    ops = composition(n, family, seed, machines)
    queues = schedule(ops, machines)
    c_dense = max(o["planned_end"] for o in ops)
    releases = [0]*(n//10)
    metadata = dict(generator_version=VERSION, family=family, density=density, seed=seed,
                    n=n, machines=machines, C_dense_ticks=c_dense)
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
    metadata["D_ticks"] = ((metadata["C0_ticks"]*11+999)//1000)*100
    return data


def scenarios(data, count=1000, purpose="scale_scenarios"):
    result = []
    c0 = data["metadata"]["C0_ticks"]/100
    width = len(data["queues"])//10
    for i in range(count):
        source = rng(data["dataset_id"], purpose, str(i))
        start_s = float(source.uniform(.1*c0, .9*c0))
        duration = float(source.choice([.01,.05,.1]))*c0
        start = math.floor(start_s+.5)*100
        end = max(start+100, math.floor(start_s+duration+.5)*100)
        affected, overrides = [], []
        if i%4 == 0:
            affected = [int(source.integers(len(data["queues"])))]
        elif i%4 == 1:
            affected = [int(m) for m in source.choice(len(data["queues"]), 2, replace=False)]
        elif i%4 == 2:
            op = int(source.integers(len(data["operations"])))
            coef = int(source.choice([125,150,200]))
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
        assert f.read(8) == b"TSFGBIN1"
        n,jobs,machines = struct.unpack("<III",f.read(12))
        ops=[]
        for i in range(n):
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
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    begin=time.monotonic()
    data=make_dataset(args.n,args.family,args.density,args.seed,args.machines)
    args.output.mkdir(parents=True,exist_ok=True)
    write_binary(data,args.output/"input.bin")
    # Full alternative sets and schedule provenance; never read by timed engines.
    with gzip.open(args.output/"operations.jsonl.gz","wt",encoding="utf-8",compresslevel=1) as f:
        for o in data["operations"]:
            f.write(json.dumps(o,separators=(",",":"))+"\n")
    (args.output/"scenarios-1000.json").write_text(json.dumps(scenarios(data),separators=(",",":")))
    (args.output/"sample.json").write_text(json.dumps(data["operations"][:10],indent=2))
    manifest=dict(dataset_id=data["dataset_id"],metadata=data["metadata"],schema="TSFGBIN1",
                  generation_wall_s=time.monotonic()-begin,validation="PASS",seed_spec="PCG64/SHA256/8-byte-LE",
                  files={name:sha256(args.output/name) for name in ("input.bin","operations.jsonl.gz","scenarios-1000.json")})
    (args.output/"manifest.json").write_text(json.dumps(manifest,indent=2))
    print(json.dumps(manifest),flush=True)


if __name__ == "__main__":
    main()
