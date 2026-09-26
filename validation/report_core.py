"""Direction and eligibility controls for descriptive censored-time bounds."""
import math
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.final_report import timeout_bounds


def row(engine,status,time,valid=True,sha='same'):
    return dict(dataset_id='F1-DENSE-N100000-M200-s101',label='round-0',engine=engine,
        status=status,T_total_s=time if status=='OK' else None,
        T_total_lower_bound_s=time if status=='TIMEOUT' else None,
        completion_validated=valid and status=='OK',input_sha256=sha,scenarios_sha256='same')


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
    slow=[row('tsfg','TIMEOUT',100),row('tsfg','TIMEOUT',400)]
    fast=[row('des','OK',3),row('des','OK',12)]
    bound=timeout_bounds(slow+fast)[0]
    assert bound['direction']=='UPPER' and math.isclose(bound['S_total_bound'],.03)
    assert not bound['eligible_for_H3']
    reversed_rows=[dict(r,engine='des' if r['engine']=='tsfg' else 'tsfg') for r in slow+fast]
    bound=timeout_bounds(reversed_rows)[0]
    assert bound['direction']=='LOWER' and math.isclose(bound['S_total_bound'],1/.03)
    assert not timeout_bounds(slow+[row('des','TIMEOUT',100),row('des','OK',12)])
    assert not timeout_bounds(slow+[row('des','OK',3,valid=False),fast[1]])
    assert not timeout_bounds(slow+[row('des','OK',3,sha='different'),fast[1]])
    assert not timeout_bounds(slow+fast[:1])
    print('PASS: censored process bounds, ineligible pairs and unknown two-sided censoring')


if __name__=='__main__':main()
