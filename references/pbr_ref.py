"""Small rational PBR oracle. Deliberately uses complete ordered sweeps."""
from collections import deque
from fractions import Fraction as F


def simulate(data, sc, horizon, mode='DIAGNOSTIC'):
    ops = data['operations']
    assert not sc.get('speed_intervals') and all(v == 100 for v in data.get('base_speed_percent', []))
    n, m = len(ops), len(data['queues'])
    capacities = data.get('buffer_capacities', [data.get('buffer_capacity', 0) or 'unbounded']*m)
    pools = data.get('resource_pools', [dict(id=0, capacity=1)] if data.get('shared_operations') else [])
    needs = [o.get('resource_pool') for o in ops]
    for i in data.get('shared_operations', []): needs[i] = 0
    owners = [[None]*r['capacity'] for r in pools]
    failures = sc.get('resource_failures', []) + [[0, 0, a, b] for a, b in sc.get('shared_failures', [])]
    queues = [deque(q) for q in data['queues']]
    buffers = [set() for _ in range(m)]
    machine = [None]*m
    starts, finishes, releases, transfers, entries = ([None]*n for _ in range(5))
    assigned = [None]*n
    remaining = [F(o['work']) for o in ops]
    for i, work in sc.get('work_overrides', []): remaining[i] = F(work)
    children = [[] for _ in ops]
    for op in ops:
        for p in op['predecessors']: children[p].append(op['id'])
    assert all(len(o['predecessors']) <= 1 for o in ops) and all(len(c) <= 1 for c in children)
    order = sorted(range(n), key=lambda i: (ops[i]['planned_start'], ops[i]['job'], i, ops[i]['machine']))
    future = set()
    for _, a, b in sc.get('failures', []): future.update((F(a), F(b)))
    for _, _, a, b in failures: future.update((F(a), F(b)))
    t = F(0)
    peaks = [0]*m
    resource_wait, blocked_time = F(0), F(0)
    links = []
    link_index = {}
    ownership = []
    ownership_index = [None]*n
    deadlock = False

    def up_machine(k):
        return not any(mm == k and a <= t < b for mm, a, b in sc.get('failures', []))

    def up_unit(r, unit):
        return not any(rr == r and uu == unit and a <= t < b for rr, uu, a, b in failures)

    def free_unit(r):
        return next((u for u, owner in enumerate(owners[r]) if owner is None and up_unit(r, u)), None)

    def can_start(i, own=False, ignore_resource=False):
        op = ops[i]
        k = op['machine']
        if starts[i] is not None or max(op['release'], op['planned_start']) > t or not up_machine(k): return False
        if any(finishes[p] is None for p in op['predecessors']): return False
        if machine[k] is None:
            if not queues[k] or queues[k][0] != i: return False
        else:
            p = machine[k]
            if not (own and op['predecessors'] == [p] and finishes[p] is not None and
                    len(queues[k]) > 1 and queues[k][1] == i): return False
        return ignore_resource or needs[i] is None or free_unit(needs[i]) is not None

    def release(i):
        if releases[i] is not None: return
        k = ops[i]['machine']
        assert machine[k] == i and finishes[i] is not None and queues[k].popleft() == i
        machine[k] = None
        releases[i] = t

    def start(i):
        k = ops[i]['machine']
        assert machine[k] is None
        buffers[k].discard(i)
        starts[i] = t
        machine[k] = i
        if needs[i] is not None:
            r = needs[i]
            unit = free_unit(r)
            assert unit is not None
            assigned[i] = unit
            owners[r][unit] = i
            ownership_index[i] = len(ownership)
            ownership.append([r, unit, i, t, None])

    def processing(i):
        return up_machine(ops[i]['machine']) and (needs[i] is None or up_unit(needs[i], assigned[i]))

    while True:
        completed = [i for i in machine if i is not None and finishes[i] is None and remaining[i] == 0]
        for i in completed: finishes[i] = t
        for i in completed:
            if needs[i] is not None:
                assert owners[needs[i]][assigned[i]] == i
                owners[needs[i]][assigned[i]] = None
                ownership[ownership_index[i]][4] = t
            if not children[i] or capacities[ops[i]['machine']] == 'unbounded': release(i)
        changed = True
        while changed:
            changed = False
            for i in order:
                op = ops[i]
                k = op['machine']
                if starts[i] is not None or op['release'] > t or any(finishes[p] is None for p in op['predecessors']): continue
                if transfers[i] is None:
                    direct = can_start(i, own=True)
                    if not direct and capacities[k] != 'unbounded' and len(buffers[k]) >= capacities[k]: continue
                    for p in op['predecessors']: release(p)
                    transfers[i] = t
                    if direct: start(i)
                    else:
                        buffers[k].add(i)
                        entries[i] = t
                        peaks[k] = max(peaks[k], len(buffers[k]))
                    changed = True
                if i in buffers[k] and can_start(i):
                    start(i)
                    changed = True
            assert all(c == 'unbounded' or len(b) <= c for b, c in zip(buffers, capacities))
        complete = all(f is not None for f in finishes)
        running = [i for i in machine if i is not None and finishes[i] is None]
        # Future input events are an intentionally conservative deadlock guard.
        future_events = [v for v in future if v > t]
        for i, op in enumerate(ops):
            if starts[i] is None and all(finishes[p] is not None for p in op['predecessors']):
                future_events.extend(F(v) for v in (op['release'], op['planned_start']) if v > t)
        if t == horizon or (mode == 'DIAGNOSTIC' and complete): break
        if not complete and not running and not future_events:
            deadlock = True
            break
        if complete:
            t = F(horizon)
            break
        next_t = min([F(horizon), *future_events,
                      *[t+remaining[i] for i in running if processing(i)]])
        assert next_t > t
        waiting = [i for i in order if needs[i] is not None and can_start(i, own=True, ignore_resource=True)
                   and free_unit(needs[i]) is None]
        blocked = [i for i in machine if i is not None and finishes[i] is not None]
        resource_wait += len(waiting)*(next_t-t)
        blocked_time += len(blocked)*(next_t-t)
        for i in waiting:
            k = ops[i]['machine']
            for p in ops[i]['predecessors']:
                if p in blocked and transfers[i] is None and capacities[k] != 'unbounded' and len(buffers[k]) >= capacities[k]:
                    item = [t, next_t, p, i, k, needs[i]]
                    key = tuple(item[2:])
                    previous = link_index.get(key)
                    if previous is not None and links[previous][1] == t: links[previous][1] = next_t
                    else:
                        link_index[key] = len(links)
                        links.append(item)
        for i in running:
            if processing(i): remaining[i] -= next_t-t
        t = next_t

    def num(value):
        if value is None: return None
        value = F(value)
        return int(value) if value.denominator == 1 else float(value)

    states = []
    for i in range(n):
        if finishes[i] is not None: state = 'DONE' if releases[i] is not None else 'BLOCKED_AFTER_PROCESSING'
        elif starts[i] is not None: state = 'PROCESSING' if processing(i) else 'SUSPENDED'
        else: state = 'NOT_STARTED'
        states.append(state)
    complete = all(f is not None for f in finishes)
    if deadlock and mode == 'MISSION':
        blocked_time += sum(f is not None and released is None for f,released in zip(finishes,releases))*(horizon-t)
    job_results=[]
    for j,job in enumerate(data['jobs']):
        end=num(finishes[job['final_operation']])
        job_results.append(dict(job_id=j,finish=end,completion_lower_bound=None if end is not None else horizon,
            produced=end is not None,status='COMPLETE' if end is not None else 'DEADLOCK' if deadlock else 'CENSORED'))
    return dict(scenario_id=sc['id'], engine='fraction-pbr-ref', mode=mode, horizon=horizon, stopped=num(t),
        start=list(map(num, starts)), finish=list(map(num, finishes)), remaining=list(map(num, remaining)), state=states,
        job_finish=[num(finishes[j['final_operation']]) for j in data['jobs']],
        job_results=job_results,
        mission_success=complete, completion_known=complete, cmax=num(max(finishes)) if complete else None,
        completion_lower_bound=None if complete else horizon, run_status='DEADLOCK' if deadlock else 'OK' if complete else 'CENSORED',
        machine_release=[-1 if v is None else num(v) for v in releases],
        transfer_at=[-1 if v is None else num(v) for v in transfers],
        buffer_entry=[-1 if v is None else num(v) for v in entries], buffer_counts=list(map(len, buffers)), buffer_peaks=peaks,
        resource_unit=[-1 if v is None else v for v in assigned],
        resource_owners=[[-1 if v is None else v for v in row] for row in owners],
        resource_ownership=[[num(v) if v is not None else -1 for v in row] for row in ownership],
        resource_wait_integral=num(resource_wait), blocked_machine_integral=num(blocked_time),
        coupling_witnesses=[[num(v) for v in row] for row in sorted(links)],
        deadlock_proof=dict(no_running_operations=not running, no_future_changes=not future_events) if deadlock else None)
