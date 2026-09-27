"""Meaningful boundary checks for final censored-time and lateness arithmetic."""
import math
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.revision_statistics_v2 import speedup_bounds,tardiness


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    rows=[dict(engine=engine,performance_status='MEASURED',T_total_s=value)
          for engine,value in [('des',2),('des',8),('tsfg',1),('tsfg',4)]]
    assert speedup_bounds(rows)['lower']==2==speedup_bounds(rows)['upper']
    rows[2]=dict(engine='tsfg',performance_status='TIMEOUT',T_total_lower_bound_s=300,T_total_s=None)
    bound=speedup_bounds(rows)
    assert bound['lower']==0 and math.isclose(bound['upper'],math.sqrt(16/1200))
    rows[0]=dict(engine='des',performance_status='TIMEOUT',T_total_lower_bound_s=300,T_total_s=None)
    assert speedup_bounds(rows)['upper'] is None
    known=[dict(completion_known=True,cmax=c,run_status='COMPLETE') for c in [1100,2200,3300]]
    result=tardiness(known,1100)
    assert result['observations']==3 and result['mean']==1 and result['p50']==1 and math.isclose(result['p95'],1.9)
    result=tardiness(known+[dict(completion_known=False,cmax=None,run_status='HORIZON',completion_lower_bound=4400)],1100)
    assert result['mean'] is None and result['p50'] is None and result['p95'] is None
    assert result['unknown']==1 and result['unknown_tardiness_lower_bounds_s']==[3.]
    print('PASS: paired-time bounds and unobserved full completion are kept separate')


if __name__=='__main__':main()
