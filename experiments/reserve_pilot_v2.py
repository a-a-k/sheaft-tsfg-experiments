"""Five predeclared calibration scenarios for the complete holdout budget gate."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.reserve_inputs_v2 import scenario,scaled_scenario,accelerated,evaluate
from experiments.pbr_cases_v2 import r5
from experiments.pbr_inputs_v2 import task_hash


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    p=argparse.ArgumentParser();p.add_argument('--law',choices=['independent','common-cause'],required=True)
    p.add_argument('--input',type=Path,default=Path('baseline'));p.add_argument('--output',type=Path,default=Path('pilot'));args=p.parse_args()
    root=args.output;root.mkdir(parents=True,exist_ok=True)
    baseline=json.loads((args.input/'baseline.json').read_text())
    if baseline['input_status']!='NOMINALLY_ADMISSIBLE':
        result=dict(family=baseline['family'],n=baseline['n'],law=args.law,execution_status='NOT_RUN',
            reason=baseline['input_status'],baseline=baseline,estimated_region_runner_seconds=None,
            holdout_generated=False,selection_opened=False)
        (root/'reserve-pilot.json').write_text(json.dumps(result,indent=2)+'\n');return
    data=json.loads((args.input/'input.json').read_text())
    c0=baseline['C0'];deadline=r5(c0*110,100);scaled=accelerated(data);records=[];seeds=[];costs=[]
    for index in range(5):
        start=time.monotonic();row,audit=scenario(data,c0,args.law,'calibration',index)
        out,process=evaluate(scaled,[scaled_scenario(row)],110*deadline,'DIAGNOSTIC',root/str(index),[row['id']])
        elapsed=time.monotonic()-start;costs.append(elapsed);records.extend(out);seeds.append(audit)
        if process['performance_status']!='MEASURED':break
    # Bounds use every possible unique configuration before looking at effects.
    counts=dict(criticality=200*15,calibration=100,selection=10*100,evaluation=7*1000,diagnostic=7*5)
    valid=len(records)==5
    estimate=2*max(costs)*sum(counts.values())+600 if valid else None
    result=dict(family=baseline['family'],n=baseline['n'],law=args.law,task_sha256=task_hash(data),
        execution_status='COMPLETE' if valid else 'PARTIAL',primary_engine='independent DES-EXT-v2.2',
        validation='Physical invariants per trajectory; model cross-validated with original S1 at admission and frozen M0',
        pilot_scenarios=5,calibration_records=records,namespace=seeds,scenario_costs_with_validation_s=costs,
        upper_run_counts=counts,estimated_region_runner_seconds=estimate,
        budget_formula='2 * max(full cost of five calibration scenarios) * sum(all upper configuration counts) + 600',
        baseline=baseline,holdout_generated=False,selection_opened=False)
    (root/'reserve-pilot.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('baseline','calibration_records','namespace')}))


if __name__=='__main__':main()
