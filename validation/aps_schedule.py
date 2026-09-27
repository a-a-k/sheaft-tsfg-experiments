"""Independent APS schedule constraints, lower bounds and DAG replay."""
import argparse
from collections import deque
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from planning.aps_format import read_task, write_task, canonical_operation, compact_json, semantic_prefix
from planning.list_v1 import schedule
from experiments.scale_data import naive_schedule, composition, write_binary
from experiments.mk01 import parse as parse_mk01
from validation.checks import validate_dataset


def jobs_from(ops):
    jobs = {}
    successor_ids = {p for op in ops for p in op['predecessors']}
    for op in ops:
        if op['job'] not in jobs:
            jobs[op['job']] = dict(id=op['job'], release=op['release'], finals=[])
        assert jobs[op['job']]['release'] == op['release']
        if op['id'] not in successor_ids: jobs[op['job']]['finals'].append(op['id'])
    assert sorted(jobs) == list(range(len(jobs)))
    result = []
    for j in range(len(jobs)):
        job = jobs[j]
        assert len(job['finals']) == 1, 'Current APS/DAG interchange requires one terminal per job'
        result.append(dict(id=j, release=job['release'], final_operation=job['finals'][0]))
    return result


def semantic_hash(data):
    hasher = hashlib.sha256(semantic_prefix(data['tick_unit'], data['machines']))
    for i, op in enumerate(data['operations']):
        if i: hasher.update(b',')
        hasher.update(compact_json(canonical_operation(op)).encode())
    hasher.update(b']}')
    return hasher.hexdigest()


def constraints(ops, queues):
    validate_dataset(dict(operations=ops, queues=queues, jobs=jobs_from(ops)))


def lower_bound(ops, machines):
    minimum = [min(a['work'] for a in o['alternatives']) for o in ops]
    degrees = [len(o['predecessors']) for o in ops]
    successors = [[] for _ in ops]
    for op in ops:
        for p in op['predecessors']: successors[p].append(op['id'])
    ready = deque(i for i, count in enumerate(degrees) if count == 0)
    earliest_finish = [0]*len(ops)
    visited = 0
    while ready:
        i = ready.popleft()
        earliest_finish[i] = max([ops[i]['release'], *(earliest_finish[p] for p in ops[i]['predecessors'])]) + minimum[i]
        visited += 1
        for child in successors[i]:
            degrees[child] -= 1
            if degrees[child] == 0: ready.append(child)
    assert visited == len(ops), 'Cyclic precedence input'
    groups = ([list(range(g*20, (g+1)*20)) for g in range(10)] if machines == 200
              else [[m] for m in range(machines)])
    grouped = []
    for group in groups:
        allowed = set(group)
        included = [o['id'] for o in ops if all(a['machine'] in allowed for a in o['alternatives'])]
        work = sum(minimum[i] for i in included)
        grouped.append(dict(machines=group, operations=len(included), minimum_work=work,
            bound_ticks=(work+len(group)-1)//len(group),
            operation_ids_sha256=hashlib.sha256(compact_json(included).encode()).hexdigest(),
            membership_proof='Every alternative of every included operation was checked against this fixed group; '
                             'membership is reproducible from the published task, independent of selected assignments'))
    path = max(earliest_finish)
    work = (sum(minimum)+machines-1)//machines
    return dict(LB_ticks=max(path, work, *(g['bound_ticks'] for g in grouped)),
                critical_path_with_releases_ticks=path, total_work_bound_ticks=work, groups=grouped)


def dag_replay(ops, queues, root):
    root.mkdir(parents=True, exist_ok=True)
    data = dict(operations=ops, queues=queues, jobs=jobs_from(ops))
    write_binary(data, root/'plan.bin')
    (root/'scenario.json').write_text('[{"id":"APS-M0","failures":[],"work_overrides":[]}]')
    cmax = max(op['planned_end'] for op in ops)
    subprocess.run(['artifacts/build/simulator', 'dag', str(root/'plan.bin'), str(root/'scenario.json'),
                    str(root/'dag.jsonl'), 'DIAGNOSTIC', str(cmax), '1'], check=True, timeout=180)
    result = json.loads((root/'dag.jsonl').read_text())
    assert result['start'] == [o['planned_start'] for o in ops]
    assert result['finish'] == [o['planned_end'] for o in ops]
    assert result['cmax'] == cmax and result['mission_success']
    return dict(status='PASS', engine='DAG-REF', operations=len(ops), Cmax_ticks=cmax)


def validate_file(task_path, schedule_path, root):
    begin = time.monotonic()
    data = read_task(task_path)
    assert semantic_hash(data) == data['task_sha256']
    ops = data['operations']
    queues = []
    next_id = 0
    with schedule_path.open() as file:
        header = json.loads(next(file))
        assert header == dict(schema='APS-SCHEDULE-v1', algorithm='SHEAFT-LIST-v1',
                              task_sha256=data['task_sha256'], operations=len(ops), machines=data['machines'])
        for line in file:
            row = json.loads(line)
            if row[0] == 'O':
                assert not queues and len(row) == 5 and row[1] == next_id
                _, i, m, start, end = row
                assert all(type(v) is int for v in row[1:])
                assert 0 <= m < data['machines'] and end > start >= 0
                ops[i].update(machine=m, work=end-start, planned_start=start, planned_end=end)
                next_id += 1
            elif row[0] == 'Q':
                assert len(row) == 3 and row[1] == len(queues)
                queues.append(row[2])
            else: raise ValueError('Unknown schedule record')
    assert next_id == len(ops) and len(queues) == data['machines']
    constraints(ops, queues)
    bound = lower_bound(ops, data['machines'])
    cmax = max(o['planned_end'] for o in ops)
    assert cmax >= bound['LB_ticks']
    result = dict(correctness_status='VALID', task_sha256=data['task_sha256'], Cmax_ticks=cmax, **bound,
        gap_bound=(cmax-bound['LB_ticks'])/bound['LB_ticks'],
        quality_status='OPTIMAL_CERTIFIED' if cmax == bound['LB_ticks'] else 'GAP_BOUNDED',
        dag=dag_replay(ops, queues, root/'replay'))
    result['validation_seconds'] = time.monotonic()-begin
    (root/'quality.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def admission(root):
    root.mkdir(parents=True, exist_ok=True)
    # Late, high-priority job must not reserve an idle machine before an earlier release.
    cases = [[dict(id=0, job=0, release=100, predecessors=[], alternatives=[dict(machine=0, work=5)]),
              dict(id=1, job=1, release=0, predecessors=[], alternatives=[dict(machine=0, work=10)])]]
    for family in ('F1', 'F2'):
        for seed in (101, 102, 103): cases.append(composition(100, family, seed, machines=20))
    jobs, machines = parse_mk01(Path('fixtures/mk01/mk01.txt'))
    mk01 = []
    for j, route in enumerate(jobs):
        for k, alternatives in enumerate(route):
            i = len(mk01)
            mk01.append(dict(id=i, job=j, release=0, predecessors=[i-1] if k else [],
                alternatives=[dict(machine=m, work=p*100) for m, p in alternatives]))
    cases.append(mk01)
    results = []
    for index, ops in enumerate(cases):
        count = 1 if index == 0 else machines if index == len(cases)-1 else 20
        original = copy.deepcopy(ops)
        expected = copy.deepcopy(ops)
        queues = schedule(ops, count)
        naive_queues = naive_schedule(expected, count)
        assert ops == expected and queues == naive_queues
        constraints(ops, queues)
        dag = dag_replay(ops, queues, root/str(index))
        if index == 0: assert queues == [[1, 0]] and ops[1]['planned_start'] == 0
        bad = copy.deepcopy(ops)
        bad[0]['planned_end'] += 1
        try: constraints(bad, queues)
        except AssertionError: pass
        else: raise AssertionError('Validator accepted inconsistent duration')
        compact = root/f'task-{index}.jsonl'
        written = write_task(original, count, '0.01 Mk01 unit' if index == len(cases)-1 else '0.01 second', compact)
        loaded = read_task(compact)
        assert semantic_hash(loaded) == written['task_sha256']
        assert not any({'machine', 'work', 'planned_start', 'planned_end'} & o.keys() for o in loaded['operations'])
        repeated = schedule(loaded['operations'], count)
        assert repeated == queues
        bound = lower_bound(ops, count)
        record = dict(case=index, status='PASS', dag=dag, **bound)
        if index == len(cases)-1:
            record.update(name='Mk01', optimum_ticks=4000, heuristic_Cmax_ticks=dag['Cmax_ticks'],
                          exact_gap=(dag['Cmax_ticks']-4000)/4000,
                          optimum_source='Previously saved CP-SAT proof; no optimization rerun')
        results.append(record)
    # The shared catalog remains shared after loading.
    shared = composition(100, 'F1', 101)
    write_task(shared, 200, '0.01 second', root/'shared.jsonl')
    loaded = read_task(root/'shared.jsonl')
    assert loaded['catalog_entries'] == 10 and loaded['catalog_alternatives'] == 200
    assert loaded['operations'][0]['alternatives'] is loaded['operations'][10]['alternatives']
    (root/'admission.json').write_text(json.dumps(dict(status='PASS', cases=results), indent=2)+'\n')
    print('PASS: full naive schedules, independent constraints, Mk01, DAG and shared catalog')


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true': raise SystemExit('Actions only')
    parser = argparse.ArgumentParser()
    parser.add_argument('--admission', action='store_true')
    parser.add_argument('--task', type=Path)
    parser.add_argument('--schedule', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.admission: admission(args.output)
    else: print(json.dumps(validate_file(args.task, args.schedule, args.output)))


if __name__ == '__main__': main()
