"""Analytic PBR controls before either measured implementation is admitted."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.pbr_cases_v2 import manual_cases, r5
from references.pbr_ref import simulate


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true': raise SystemExit('Actions only')
    assert [r5(n, 2) for n in (0, 4, 5, 6, 14, 15, 16)] == [0, 0, 5, 5, 5, 10, 10]
    root = Path('artifacts/pbr-reference')
    root.mkdir(parents=True, exist_ok=True)
    passed = []
    for case in manual_cases():
        result = simulate(case['data'], case['scenario'], case['horizon'])
        (root/(case['name']+'.json')).write_text(json.dumps(dict(case=case, result=result), indent=2)+'\n')
        for key, expected in case['expected'].items(): assert result[key] == expected, (case['name'], key, result[key], expected)
        for deadline in (0, case['horizon']//5*5):
            mission = simulate(case['data'], case['scenario'], deadline, 'MISSION')
            assert all(v is None or v <= deadline for v in mission['finish'])
        passed.append(case['name'])
    (root/'summary.json').write_text(json.dumps(dict(status='PASS', cases=passed, reference='independent rational sweeps'), indent=2)+'\n')
    print(json.dumps(dict(status='PASS', cases=len(passed))))


if __name__ == '__main__': main()
