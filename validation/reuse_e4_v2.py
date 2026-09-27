"""Analytic checks for row pairing, null handling and transformed time units."""
import copy
import os
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.reuse_e4_v2 import analyze, paired_summary, validate


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Actions only')
    values = np.array([[0, 1, -1], [0, 3, -3]])
    stats = paired_summary(values, np.random.default_rng(1))
    assert [s['mean'] for s in stats] == [0, 2, -2]
    assert stats[0]['ci95'] == [0, 0]
    assert stats[1]['ci95'] == [1, 3] and stats[2]['ci95'] == [-3, -1]
    frozen = dict(T=[0, 1, 2], B=[3, 4, 5], common_D_ticks=1000, dataset_sha256='0'*64)
    scenarios = [dict(id=str(i)) for i in range(1000)]
    evidence = dict(status='PASS', engines=['dag', 'des'], targets=[-1, 0, 1, 2, 3, 4, 5],
        time_scale=11, D_scaled_ticks=11000, records=[dict(scenario_id=str(i), exact_engine_agreement=True,
        produced_jobs=[10]*7, outcomes=[True]*7, cmax_scaled_ticks=[11000]+[9900]*6) for i in range(1000)])
    result = analyze(evidence, scenarios, frozen, 10, 'analytic', 'known')
    assert all(c['cmax_reduction_seconds']['mean'] == 1 for c in result['configurations'])
    incomplete = copy.deepcopy(evidence)
    for row in incomplete['records']:
        row.update(produced_jobs=[5, 6, 5, 5, 5, 5, 5], outcomes=[False]*7, cmax_scaled_ticks=[None]*7)
    result = analyze(incomplete, scenarios, frozen, 10, 'analytic', 'unknown')
    assert result['configurations'][0]['produced_jobs_effect']['mean'] == 1
    assert all(c['cmax_reduction_seconds'] is None for c in result['configurations'])
    for mutation in ('substituted_horizon', 'mispaired_scenario', 'invalid_count'):
        bad = copy.deepcopy(incomplete)
        if mutation == 'substituted_horizon': bad['records'][0]['cmax_scaled_ticks'][0] = 11000
        if mutation == 'mispaired_scenario': bad['records'][0]['scenario_id'] = 'wrong'
        if mutation == 'invalid_count': bad['records'][0]['produced_jobs'][0] = 11
        try:
            validate(bad, scenarios, frozen, 10)
        except AssertionError:
            pass
        else:
            raise AssertionError('Accepted invalid saved record: '+mutation)
    print('PASS: analytic effects, paired rows, nulls, units and invalid records')


if __name__ == '__main__':
    main()
