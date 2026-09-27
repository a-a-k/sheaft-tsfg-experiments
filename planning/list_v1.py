"""SHEAFT-LIST-v1: original earliest-start scheduler, unchanged transition logic."""
import heapq

VERSION = 'SHEAFT-LIST-v1'


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


