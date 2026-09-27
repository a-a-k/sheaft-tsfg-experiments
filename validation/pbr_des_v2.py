"""Compare independent C++ DES with analytic cases and the rational oracle."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.pbr_cases_v2 import manual_cases
from references.pbr_ref import simulate

FIELDS = ['start', 'finish', 'remaining', 'state', 'job_finish', 'mission_success', 'completion_known',
          'cmax', 'completion_lower_bound', 'run_status', 'stopped', 'machine_release', 'transfer_at',
          'buffer_entry', 'buffer_counts', 'buffer_peaks', 'resource_unit', 'resource_owners',
          'resource_ownership', 'resource_wait_integral', 'blocked_machine_integral', 'coupling_witnesses']


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true': raise SystemExit('Actions only')
    parser=argparse.ArgumentParser()
    parser.add_argument('--tsfg', action='store_true')
    args=parser.parse_args()
    root = Path('artifacts/pbr-des')
    root.mkdir(parents=True, exist_ok=True)
    checks = 0
    for case in manual_cases():
        folder = root/case['name']
        folder.mkdir(exist_ok=True)
        (folder/'input.json').write_text(json.dumps(case['data']))
        (folder/'scenario.json').write_text(json.dumps([case['scenario']]))
        for mode, horizon in [('DIAGNOSTIC', case['horizon']), ('MISSION', 0), ('MISSION', 100), ('MISSION', case['horizon'])]:
            expected = simulate(case['data'], case['scenario'], horizon, mode)
            output = folder/f'{mode}-{horizon}.jsonl'
            subprocess.run(['artifacts/build/des-ext', str(folder/'input.json'), str(folder/'scenario.json'),
                            str(output), mode, str(horizon)], check=True, timeout=20)
            actual = json.loads(output.read_text())
            (folder/f'{mode}-{horizon}-reference.json').write_text(json.dumps(expected, indent=2))
            for field in FIELDS: assert actual[field] == expected[field], (case['name'], mode, horizon, field, actual[field], expected[field])
            if args.tsfg:
                tsfg_output=folder/f'{mode}-{horizon}-tsfg.jsonl'
                subprocess.run(['.private/runtime/tsfg', 'tsfg-ext', str(folder/'input.json'), str(folder/'scenario.json'),
                    str(tsfg_output), mode, str(horizon), '5'], check=True, timeout=30,
                    env={**os.environ, 'TSFG_OP_DRIVER':'true', 'GOMAXPROCS':'1'})
                tsfg=json.loads(tsfg_output.read_text())
                for field in FIELDS: assert tsfg[field] == expected[field], (case['name'], 'TSFG', mode, horizon, field, tsfg[field], expected[field])
            checks += 1
    (root/'summary.json').write_text(json.dumps(dict(status='PASS', checks=checks, engines=['DES-EXT', 'Fraction']+(['TSFG-EXT'] if args.tsfg else [])), indent=2)+'\n')
    print(json.dumps(dict(status='PASS', checks=checks)))


if __name__ == '__main__': main()
