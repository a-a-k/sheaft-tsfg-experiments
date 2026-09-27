"""VmHWM calibration in fresh executable images; inherited rusage is ignored."""
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true': raise SystemExit('Actions only')
    root = Path('artifacts/aps-admission')
    root.mkdir(parents=True, exist_ok=True)
    resident_parent = bytearray(128*2**20)
    for offset in range(0, len(resident_parent), 4096): resident_parent[offset] = 1
    code = '''import json,sys
from pathlib import Path
x=bytearray(int(sys.argv[1])*2**20)
for offset in range(0,len(x),4096): x[offset]=1
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
print(json.dumps({'VmHWM_bytes':int(status['VmHWM'].split()[0])*1024,'allocated_bytes':len(x)}))
'''
    measurements = [json.loads(subprocess.check_output([sys.executable, '-c', code, str(m)])) for m in (0, 64)]
    small, large = [r['VmHWM_bytes'] for r in measurements]
    assert small < len(resident_parent)/2
    assert 60*2**20 < large-small < 72*2**20
    (root/'memory-counter.json').write_text(json.dumps(dict(status='PASS', measurements=measurements,
        parent_allocation_bytes=len(resident_parent), counter='/proc/self/status VmHWM after exec'), indent=2)+'\n')
    print('PASS: VmHWM reflects child allocation, not resident parent history')


if __name__ == '__main__': main()
