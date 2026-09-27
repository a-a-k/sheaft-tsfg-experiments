"""Region-level forecast plus full dynamic job timeout reservation."""
import argparse
import json
import math
import os
from pathlib import Path


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    p=argparse.ArgumentParser();p.add_argument('--pilot',type=Path,required=True);args=p.parse_args()
    pilot=json.loads((args.pilot/'pilot/reserve-pilot.json').read_text())
    ledger=json.loads(Path('artifacts/budget/budget-v2.json').read_text())
    available=ledger['packages']['reserves']-ledger['actual_seconds']['reserves']
    allowed=False;selection_minutes=0;holdout_minutes=0;estimate=None
    reason=pilot.get('reason','NOT_RUN_BUDGET_GATE')
    if pilot['execution_status']=='COMPLETE':
        maximum=max(pilot['scenario_costs_with_validation_s'])
        # Selection includes its separate base (up to 9 candidates + base).
        selection_minutes=math.ceil((2*maximum*(3000+100+1000)+300)/60)
        holdout_minutes=math.ceil((2*maximum*(7000+35)+300)/60)
        estimate=2*maximum*(3000+100+1000+7000+35)+600
        allowed=(selection_minutes<=360 and holdout_minutes<=360 and
                 60*(selection_minutes+holdout_minutes+6)<=available)
        reason='ADMITTED' if allowed else 'NOT_RUN_BUDGET_GATE'
    reservation=60*(selection_minutes+holdout_minutes+6) if allowed else 180
    result=dict(family=pilot['family'],n=pilot['n'],law=pilot['law'],allowed=allowed,reason=reason,
        available_runner_seconds=available,estimated_region_runner_seconds=estimate,
        reserved_runner_seconds=reservation,selection_timeout_minutes=selection_minutes,holdout_timeout_minutes=holdout_minutes)
    Path('gate').mkdir(exist_ok=True);Path('gate/reserve-admission.json').write_text(json.dumps(result,indent=2)+'\n')
    with open(os.environ['GITHUB_OUTPUT'],'a') as file:
        file.write(f'allowed={str(allowed).lower()}\nreservation={reservation}\nselection_minutes={selection_minutes}\nholdout_minutes={holdout_minutes}\n')
    print(json.dumps(result))


if __name__=='__main__':main()
