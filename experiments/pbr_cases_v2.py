"""Protocol v2.2 manual fixtures. All construction/execution is Actions-only."""
import copy


def r5(numerator, denominator=1):
    assert numerator >= 0 and denominator > 0
    return 5*((2*numerator+5*denominator)//(10*denominator))


def dataset(name, rows, queues, capacities, pools):
    """Rows: job,machine,work,pred,planned,pool, expressed in input ticks."""
    ops = []
    for i, (job, machine, work, pred, planned, pool) in enumerate(rows):
        ops.append(dict(id=i, job=job, machine=machine, work=work, predecessors=pred,
            release=0, planned_start=planned, planned_end=planned+work,
            resource_pool=pool, alternatives=[dict(machine=machine, work=work)]))
    final = {}
    for op in ops: final[op['job']] = op['id']
    return dict(dataset_id=name, semantics='PBR-EXACT-v2.2', extended_profile=True,
        operations=ops, queues=queues, buffer_capacities=capacities,
        resource_pools=[dict(id=i, capacity=c) for i, c in enumerate(pools)],
        jobs=[dict(id=j, release=0, final_operation=final[j]) for j in range(len(final))])


def manual_cases():
    base = dict(id='M0', failures=[], work_overrides=[], resource_failures=[])
    interaction = dataset('buffer-resource-link', [
        (0, 0, 200, [], 0, None), (0, 1, 200, [0], 200, 0),
        (1, 2, 800, [], 0, 0), (2, 3, 100, [], 0, None), (2, 1, 100, [3], 300, 0)],
        [[0], [1, 4], [2], [3]], [1]*4, [1])
    cases = [dict(name='buffer-resource-link', data=interaction, scenario=base, horizon=1500,
        expected=dict(start=[0, 800, 0, 0, 1000], finish=[200, 1000, 800, 100, 1100], cmax=1100,
                      machine_release=[800, 1000, 800, 100, 1100], resource_wait_integral=600,
                      blocked_machine_integral=600, coupling_witnesses=[[200, 800, 0, 1, 1, 0]]))]
    larger = copy.deepcopy(interaction)
    larger['buffer_capacities'][1] = 2
    cases.append(dict(name='buffer-control-2', data=larger, scenario=base, horizon=1500,
        expected=dict(cmax=1100, machine_release=[200, 1000, 800, 100, 1100], blocked_machine_integral=0)))
    independent = copy.deepcopy(interaction)
    for op in independent['operations']: op['resource_pool'] = None
    cases.append(dict(name='resource-control-none', data=independent, scenario=base, horizon=1500,
        expected=dict(cmax=800, start=[0, 200, 0, 0, 400], finish=[200, 400, 800, 100, 500])))
    ordered = dataset('ordered-sweeps', [
        (0, 0, 200, [], 0, None), (0, 1, 100, [0], 200, None),
        (1, 0, 100, [], 100, 0), (2, 2, 100, [], 200, 0)], [[0, 2], [1], [3]], [1]*3, [1])
    cases.append(dict(name='ordered-sweeps', data=ordered, scenario=base, horizon=600,
        expected=dict(start=[0, 200, 300, 200], finish=[200, 300, 400, 300], cmax=400)))
    multi = dataset('capacity-two-and-independent-pool', [
        (0, 0, 200, [], 0, 0), (1, 1, 200, [], 0, 0),
        (2, 2, 200, [], 0, 0), (3, 3, 200, [], 0, 1)], [[0], [1], [2], [3]], [1]*4, [2, 1])
    cases.append(dict(name='capacity-two', data=multi, scenario=base, horizon=800,
        expected=dict(start=[0, 0, 200, 0], finish=[200, 200, 400, 200], resource_unit=[0, 1, 0, 0], cmax=400)))
    cases.append(dict(name='capacity-two-failed-unit', data=multi,
        scenario=dict(base, id='failed-unit', resource_failures=[[0, 0, 100, 300]]), horizon=800,
        expected=dict(start=[0, 0, 200, 0], finish=[400, 200, 400, 200], resource_unit=[0, 1, 1, 0], cmax=400)))
    chain = dataset('two-machine-failures', [(0, 0, 1000, [], 0, None), (0, 1, 1000, [0], 1000, None)],
                    [[0], [1]], [1, 1], [])
    for name, fails, end in [('A', [[0, 0, 200]], 2200), ('B', [[1, 1200, 1400]], 2200),
                             ('AB', [[0, 0, 200], [1, 1200, 1400]], 2400)]:
        cases.append(dict(name='two-failures-'+name, data=chain, scenario=dict(base, id=name, failures=fails),
                          horizon=3000, expected=dict(cmax=end)))
    deadlocked = dataset('zero-buffer-cycle', [(0, 0, 100, [], 0, None), (0, 1, 100, [0], 100, None),
        (1, 1, 100, [], 0, None), (1, 0, 100, [2], 100, None)], [[0, 3], [2, 1]], [0, 0], [])
    cases.append(dict(name='proven-deadlock', data=deadlocked, scenario=base, horizon=1000,
        expected=dict(run_status='DEADLOCK', stopped=100, cmax=None, finish=[100, None, 100, None])))
    later = dataset('release-at-horizon', [(0, 0, 100, [], 1000, None)], [[0]], [1], [])
    later['operations'][0]['release'] = 1000
    later['jobs'][0]['release'] = 1000
    cases.append(dict(name='release-at-horizon', data=later, scenario=base, horizon=1000,
        expected=dict(run_status='CENSORED', start=[1000], finish=[None], cmax=None)))
    return copy.deepcopy(cases)
