"""Small continuous-time E1X oracle; Fraction is the authoritative clock."""
from collections import deque
from fractions import Fraction as Q


def number(value):
    if value is None:return None
    return int(value) if value.denominator==1 else float(value)


def simulate(data, sc, horizon, mode="DIAGNOSTIC"):
    if data.get('semantics') == 'PBR-EXACT-v2.2':
        from references.pbr_ref import simulate as pbr_simulate
        return pbr_simulate(data, sc, horizon, mode)
    ops=data["operations"];n=len(ops);m=len(data["queues"])
    queues=[deque(q) for q in data["queues"]]
    stores=[set() for _ in range(m)]
    occupancy=[None]*m
    start=[None]*n;finish=[None]*n;released=[None]*n
    remaining=[Q(o["work"]*100) for o in ops]
    for i,w in sc.get("work_overrides",[]):remaining[i]=Q(w*100)
    children=[[] for _ in ops]
    for o in ops:
        if len(o["predecessors"])>1:raise ValueError("Chain buffers only")
        for p in o["predecessors"]:children[p].append(o["id"])
    needs=set(data.get("shared_operations",[]));owner=None
    capacity=data.get("buffer_capacity",0)
    base=data.get("base_speed_percent",[100]*m)
    order=sorted(range(n),key=lambda i:(ops[i]["planned_start"],ops[i]["job"],i,ops[i]["machine"]))
    times={Q(horizon)}
    for o in ops:times.update((Q(o["planned_start"]),Q(o["release"])))
    for _,a,b in sc.get("failures",[]):times.update((Q(a),Q(b)))
    for _,a,b,_ in sc.get("speed_intervals",[]):times.update((Q(a),Q(b)))
    for a,b in sc.get("shared_failures",[]):times.update((Q(a),Q(b)))
    boundaries=iter(sorted(t for t in times if t>0));boundary=next(boundaries,None)
    t=Q(0);deadlock=False;peak=[0]*m;transfers=0

    def machine_up(machine):
        return not any(mm==machine and a<=t<b for mm,a,b in sc.get("failures",[]))

    def shared_up():
        return not any(a<=t<b for a,b in sc.get("shared_failures",[]))

    def rate(i):
        machine=ops[i]["machine"]
        if not machine_up(machine) or (i in needs and not shared_up()):return Q(0)
        value=base[machine]
        for mm,a,b,v in sc.get("speed_intervals",[]):
            if mm==machine and a<=t<b:value=v
        return Q(value)

    def release(i):
        if released[i] is not None:return
        machine=ops[i]["machine"]
        assert occupancy[machine]==i and finish[i] is not None
        assert queues[machine].popleft()==i
        occupancy[machine]=None;released[i]=t

    def can_begin(i,self_handoff=False):
        o=ops[i];machine=o["machine"]
        if max(o["release"],o["planned_start"])>t or not machine_up(machine):return False
        if i in needs and (owner is not None or not shared_up()):return False
        if any(finish[p] is None for p in o["predecessors"]):return False
        if occupancy[machine] is None:return bool(queues[machine]) and queues[machine][0]==i
        prev=occupancy[machine]
        return (self_handoff and o["predecessors"]==[prev] and finish[prev] is not None
                and len(queues[machine])>1 and queues[machine][1]==i)

    def begin(i):
        nonlocal owner
        machine=ops[i]["machine"]
        stores[machine].discard(i)
        start[i]=t;occupancy[machine]=i
        if i in needs:
            assert owner is None
            owner=i

    while True:
        # All service completions commit together, then ownership is released.
        completed=[i for i in occupancy if i is not None and remaining[i]==0 and finish[i] is None]
        for i in completed:finish[i]=t
        for i in completed:
            if i in needs:
                assert owner==i
                owner=None
            if not children[i] or capacity==0:release(i)
        changed=True
        while changed:
            changed=False
            for i in order:
                o=ops[i];machine=o["machine"]
                if start[i] is not None or o["release"]>t or any(finish[p] is None for p in o["predecessors"]):continue
                if i not in stores[machine]:
                    direct=can_begin(i,True)
                    if not direct and capacity and len(stores[machine])>=capacity:continue
                    for prev in o["predecessors"]:release(prev)
                    transfers+=1;changed=True
                    if direct:begin(i)
                    else:stores[machine].add(i)
                if i in stores[machine] and can_begin(i):begin(i);changed=True
            peak=[max(p,len(s)) for p,s in zip(peak,stores)]
            assert not capacity or all(len(s)<=capacity for s in stores)
        complete=all(c is not None for c in finish)
        running=[i for i in occupancy if i is not None and finish[i] is None]
        useful_future=any(o["planned_start"]>t or o["release"]>t for i,o in enumerate(ops) if start[i] is None)
        useful_future|=any(b>t for _,a,b in sc.get("failures",[]))
        useful_future|=any(b>t for a,b in sc.get("shared_failures",[]))
        if not complete and not running and not useful_future:deadlock=True;break
        if t==horizon or (mode=="DIAGNOSTIC" and complete):break
        if complete:t=Q(horizon);break
        while boundary is not None and boundary<=t:boundary=next(boundaries,None)
        finish_events=[t+remaining[i]/rate(i) for i in running if rate(i)>0]
        next_t=min([Q(horizon),*finish_events,*([boundary] if boundary is not None else [])])
        assert next_t>t
        for i in running:
            remaining[i]-=rate(i)*(next_t-t)
            assert remaining[i]>=0
        t=next_t
    states=[]
    for i in range(n):
        if finish[i] is not None:state="DONE" if released[i] is not None else "BLOCKED_AFTER_PROCESSING"
        elif start[i] is not None:state="PROCESSING" if rate(i)>0 else "SUSPENDED"
        else:state="NOT_STARTED"
        states.append(state)
    complete=all(c is not None for c in finish)
    return dict(scenario_id=sc["id"],engine="fraction-ref",mode=mode,horizon=horizon,
                stopped=number(t),start=list(map(number,start)),finish=list(map(number,finish)),
                remaining=[number(v/100) for v in remaining],remaining_work_units=list(map(number,remaining)),work_scale=100,
                state=states,job_finish=[number(finish[j["final_operation"]]) for j in data["jobs"]],
                mission_success=complete,completion_known=complete,cmax=number(max(finish)) if complete else None,
                completion_lower_bound=None if complete else horizon,run_status="DEADLOCK" if deadlock else "OK",
                machine_release=[-1 if c is None else number(c) for c in released],buffer_counts=list(map(len,stores)),
                shared_owner=-1 if owner is None else owner,buffer_peaks=peak,
                counters=dict(transfers=transfers))
