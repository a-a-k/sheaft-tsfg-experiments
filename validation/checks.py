"""Physical checks and output projection, independent of engine transitions."""
from collections import deque


def calendars(data, scenario):
    result = [[] for _ in data["queues"]]
    for m, a, b in scenario["failures"]:
        assert 0 <= m < len(result) and 0 <= a < b
        result[m].append((a, b))
    for m, raw in enumerate(result):
        boundaries = sorted({t for pair in raw for t in pair})
        # Independent union by coverage of elementary intervals, used only in
        # the small validation oracle, not as an engine calendar implementation.
        result[m] = [(a, b) for a, b in zip(boundaries, boundaries[1:])
                     if any(x <= a and b <= y for x, y in raw)]
    return result


def work_vector(data, scenario):
    values = [o["work"] for o in data["operations"]]
    for i, work in scenario["work_overrides"]:
        assert 0 <= i < len(values) and work > 0
        values[i] = work
    return values


def service(a, b, down):
    return b - a - sum(max(0, min(b, y) - max(a, x)) for x, y in down)


def validate_dataset(data):
    ops, queues, jobs = data["operations"], data["queues"], data["jobs"]
    n = len(ops)
    assert n > 0 and [o["id"] for o in ops] == list(range(n))
    assert [j["id"] for j in jobs] == list(range(len(jobs)))
    flat = [i for q in queues for i in q]
    assert sorted(flat) == list(range(n)), "Queues must partition operations"
    pred = [set(o["predecessors"]) for o in ops]
    for o in ops:
        i = o["id"]
        assert o["work"] > 0 and o["release"] >= 0
        assert o["planned_start"] >= o["release"]
        assert o["planned_end"] == o["planned_start"] + o["work"]
        assert len(pred[i]) == len(o["predecessors"])
        assert {"machine": o["machine"], "work": o["work"]} in o["alternatives"]
        for p in pred[i]:
            assert 0 <= p < n and p != i and ops[p]["job"] == o["job"]
            assert ops[p]["planned_end"] <= o["planned_start"]
    for m, queue in enumerate(queues):
        for i in queue:
            assert ops[i]["machine"] == m
        for a, b in zip(queue, queue[1:]):
            assert ops[a]["planned_end"] <= ops[b]["planned_start"]
            pred[b].add(a)
    successors = [[] for _ in ops]
    indegree = [len(p) for p in pred]
    for i, predecessors in enumerate(pred):
        for p in predecessors:
            successors[p].append(i)
    ready = deque(i for i, degree in enumerate(indegree) if degree == 0)
    visited = 0
    while ready:
        i = ready.popleft()
        visited += 1
        for j in successors[i]:
            indegree[j] -= 1
            if not indegree[j]: ready.append(j)
    assert visited == n, "Cycle in fixed schedule"
    for job in jobs:
        assert ops[job["final_operation"]]["job"] == job["id"]
        for o in ops:
            if o["job"] == job["id"]: assert o["release"] == job["release"]


def validate_result(data, scenario, result):
    ops = data["operations"]
    n = len(ops)
    h = result["horizon"]
    down = calendars(data, scenario)
    work = work_vector(data, scenario)
    for key in ("start", "finish", "remaining", "state"):
        assert len(result[key]) == n, key
    s, c, rem = result["start"], result["finish"], result["remaining"]
    for i, op in enumerate(ops):
        if s[i] is None:
            assert c[i] is None and rem[i] == work[i] and result["state"][i] == "NOT_STARTED"
            continue
        assert isinstance(s[i], int) and max(op["planned_start"], op["release"]) <= s[i] <= h
        assert not any(a <= s[i] < b for a, b in down[op["machine"]]), "Start in failure"
        for p in op["predecessors"]:
            assert c[p] is not None and c[p] <= s[i], "Unfinished technological predecessor"
        end = h if c[i] is None else c[i]
        assert s[i] <= end <= h and rem[i] >= 0
        performed = service(s[i], end, down[op["machine"]])
        assert performed + rem[i] == work[i], "Work conservation"
        if c[i] is not None:
            assert isinstance(c[i], int) and c[i] > s[i] and rem[i] == 0
            assert result["state"][i] == "DONE"
        else:
            assert rem[i] > 0, "Finished work must commit at horizon"
            expected = "SUSPENDED" if any(a <= h < b for a, b in down[op["machine"]]) else "PROCESSING"
            assert result["state"][i] == expected
    for queue in data["queues"]:
        for a, b in zip(queue, queue[1:]):
            if s[b] is not None:
                assert c[a] is not None and c[a] <= s[b], "Queue bypass or machine overlap"
    complete = all(t is not None for t in c)
    assert result["mission_success"] == complete and result["completion_known"] == complete
    assert result["cmax"] == (max(c) if complete else None)
    assert result["completion_lower_bound"] == (None if complete else h)
    assert result["job_finish"] == [c[j["final_operation"]] for j in data["jobs"]]
    expected_stop = max(c) if result["mode"] == "DIAGNOSTIC" and complete else h
    assert result["stopped"] == expected_stop


SIGNATURE = ("start", "finish", "remaining", "state", "job_finish", "cmax",
             "completion_known", "completion_lower_bound", "mission_success", "stopped")


def compare(reference, candidate):
    for key in SIGNATURE:
        assert reference[key] == candidate[key], f"{candidate['engine']}: {key} mismatch"


def project(data, scenario, trajectory, deadline):
    down, work = calendars(data, scenario), work_vector(data, scenario)
    result = dict(trajectory, mode="MISSION", horizon=deadline, stopped=deadline)
    result["start"], result["finish"], result["remaining"], result["state"] = [], [], [], []
    for i, op in enumerate(data["operations"]):
        start, finish = trajectory["start"][i], trajectory["finish"][i]
        start = start if start is not None and start <= deadline else None
        finish = finish if finish is not None and finish <= deadline else None
        remaining = work[i] if start is None else work[i] - service(start, finish if finish is not None else deadline, down[op["machine"]])
        state = "NOT_STARTED" if start is None else "DONE" if finish is not None else (
            "SUSPENDED" if any(a <= deadline < b for a, b in down[op["machine"]]) else "PROCESSING")
        result["start"].append(start); result["finish"].append(finish)
        result["remaining"].append(remaining); result["state"].append(state)
    complete = all(c is not None for c in result["finish"])
    result.update(mission_success=complete, completion_known=complete,
                  cmax=max(result["finish"]) if complete else None,
                  completion_lower_bound=None if complete else deadline,
                  job_finish=[result["finish"][j["final_operation"]] for j in data["jobs"]])
    return result
