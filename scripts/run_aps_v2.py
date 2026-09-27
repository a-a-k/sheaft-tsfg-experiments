"""Launch exactly one measured APS process; keep censored/error outcomes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time


def digest(path):
    with path.open('rb') as file: return hashlib.file_digest(file, 'sha256').hexdigest()


def memory_events():
    path = Path('/sys/fs/cgroup/memory.events')
    return dict(line.split() for line in path.read_text().splitlines()) if path.exists() else {}


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true': raise SystemExit('Actions only')
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, required=True)
    parser.add_argument('--repeat', type=int, required=True)
    args = parser.parse_args()
    root = args.output
    root.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((args.input.parent/'manifest.json').read_text())
    expected = manifest['diagnostic_10k'] if args.input.name == 'diagnostic-10k.jsonl' else manifest
    assert digest(args.input) == expected['file_sha256']
    command = [sys.executable, 'experiments/aps_schedule.py', '--input', str(args.input),
               '--output', str(root/'schedule.jsonl'), '--launch-time']
    record = dict(algorithm='SHEAFT-LIST-v1', task_sha256=expected['task_sha256'],
        parent_task_sha256=manifest['task_sha256'], input_sha256=expected['file_sha256'],
        source_sha=os.environ['GITHUB_SHA'], run_id=os.environ['GITHUB_RUN_ID'], repeat=args.repeat,
        operation_count=expected['operations'], aliases=manifest['aliases'],
        family=manifest['family'], density=manifest['density'], seed=manifest['seed'],
        python=sys.version, platform=platform.platform(), allowed_cpus=sorted(os.sched_getaffinity(0)),
        cpuinfo=Path('/proc/cpuinfo').read_text(), limit_seconds=args.limit,
        correctness_status='UNCHECKED', quality_status='QUALITY_UNKNOWN')
    record['measurement_code_sha256'] = {name: digest(Path(name)) for name in
        ('planning/list_v1.py', 'planning/aps_format.py', 'experiments/aps_schedule.py', 'scripts/run_aps_v2.py')}
    before = memory_events()
    begin = time.monotonic()
    with (root/'stdout.txt').open('w') as stdout, (root/'stderr.txt').open('w') as stderr:
        process = subprocess.Popen([*command, str(begin)], stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            process.wait(timeout=args.limit)
            status = 'MEASURED' if process.returncode == 0 else 'ERROR'
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            status = 'TIMEOUT'
    elapsed = time.monotonic()-begin
    after = memory_events()
    if status == 'ERROR' and int(after.get('oom_kill', 0)) > int(before.get('oom_kill', 0)): status = 'OOM'
    record.update(performance_status=status, execution_status='COMPLETE' if status == 'MEASURED' else 'PARTIAL',
                  process_elapsed_s=elapsed, returncode=process.returncode, memory_events_before=before, memory_events_after=after)
    if status == 'MEASURED':
        measured = json.loads((root/'schedule.measurement.json').read_text())
        assert measured['task_sha256'] == record['task_sha256']
        assert measured['T_total_s'] <= elapsed
        record.update(measurement=measured, output_sha256=digest(root/'schedule.jsonl'))
    else:
        record.update(T_total_s=None, elapsed_lower_bound_s=args.limit if status == 'TIMEOUT' else None)
    (root/'process.json').write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps({k: v for k, v in record.items() if k != 'cpuinfo'}), flush=True)


if __name__ == '__main__': main()
