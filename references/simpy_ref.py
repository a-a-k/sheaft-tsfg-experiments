"""Independent small oracle: one SimPy process per fixed machine queue."""
import simpy


def simulate(data, scenario, horizon, mode):
    ops = data["operations"]
    n = len(ops)
    durations = [o["work"] for o in ops]
    for i, value in scenario["work_overrides"]:
        durations[i] = value
    # Own union implementation; not imported from the C++ input layer.
    intervals = [[] for _ in data["queues"]]
    for m, a, b in scenario["failures"]:
        intervals[m].append((a, b))
    for m, raw in enumerate(intervals):
        union = []
        for a, b in sorted(raw):
            if union and a <= union[-1][1]:
                union[-1] = (union[-1][0], max(b, union[-1][1]))
            else:
                union.append((a, b))
        intervals[m] = union

    env = simpy.Environment()
    done = [env.event() for _ in ops]
    starts, ends = [None] * n, [None] * n
    remaining = durations.copy()
    working_since = [None] * n
    completed = 0

    def machine_worker(m, queue):
        nonlocal completed
        for i in queue:
            op = ops[i]
            if op["predecessors"]:
                yield env.all_of([done[p] for p in op["predecessors"]])
            target = max(op["release"], op["planned_start"])
            if env.now < target:
                yield env.timeout(target - env.now)
            while remaining[i]:
                unavailable = next(((a, b) for a, b in intervals[m] if a <= env.now < b), None)
                if unavailable:
                    yield env.timeout(unavailable[1] - env.now)
                    continue
                if starts[i] is None:
                    starts[i] = env.now
                next_stop = next((a for a, _ in intervals[m] if a > env.now), float("inf"))
                amount = min(remaining[i], next_stop - env.now)
                working_since[i] = env.now
                yield env.timeout(amount)
                remaining[i] -= amount
                working_since[i] = None
            ends[i] = env.now
            completed += 1
            done[i].succeed()

    for m, queue in enumerate(data["queues"]):
        env.process(machine_worker(m, queue))
    stepped = 0
    # env.run(until=H) excludes normal-priority events exactly at H. Step the
    # inclusive boundary explicitly, including all same-time callbacks/starts.
    while env.peek() <= horizon and completed < n:
        env.step()
        stepped += 1
    stop = env.now if mode == "DIAGNOSTIC" and completed == n else horizon
    for i, since in enumerate(working_since):
        if since is not None:
            remaining[i] -= stop - since
    state = []
    for i, op in enumerate(ops):
        if ends[i] is not None:
            state.append("DONE")
        elif starts[i] is None:
            state.append("NOT_STARTED")
        elif any(a <= stop < b for a, b in intervals[op["machine"]]):
            state.append("SUSPENDED")
        else:
            state.append("PROCESSING")
    complete = completed == n
    return {
        "scenario_id": scenario["id"], "engine": "simpy", "mode": mode,
        "horizon": horizon, "stopped": stop, "start": starts, "finish": ends,
        "remaining": remaining, "state": state,
        "job_finish": [ends[j["final_operation"]] for j in data["jobs"]],
        "mission_success": complete, "completion_known": complete,
        "cmax": max(ends) if complete else None,
        "completion_lower_bound": None if complete else horizon,
        "run_status": "OK", "counters": {"simpy_steps": stepped},
    }
