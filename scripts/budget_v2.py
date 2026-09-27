"""Reserve a complete workflow group against actual Actions job consumption."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.collect_evidence import api


def pages(path, key):
    result, page = [], 1
    while True:
        response = api(path + ('&' if '?' in path else '?') + f'per_page=100&page={page}')
        items = response[key]
        result.extend(items)
        if len(result) >= response['total_count'] or not items:
            return result
        page += 1


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true': raise SystemExit('Actions only')
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', required=True)
    parser.add_argument('--reserve-seconds', type=int, required=True)
    parser.add_argument('--output', type=Path, default=Path('artifacts/budget'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    config = json.loads(Path('provenance/budget-v2.json').read_text())
    repo = os.environ['GITHUB_REPOSITORY']
    current = int(os.environ['GITHUB_RUN_ID'])
    entries, consumed = [], {p: 0 for p in config['packages']}
    active = []
    for run in pages(f'repos/{repo}/actions/runs?branch={config["branch"]}', 'workflow_runs'):
        if run['id'] < config['campaign_start_run_id'] or run['id'] == current: continue
        workflow = Path(run['path']).name
        if workflow not in config['workflow_packages']:
            raise ValueError('Unbudgeted workflow: ' + workflow)
        package = config['workflow_packages'][workflow]
        for attempt in range(1, run['run_attempt']+1):
            jobs = pages(f'repos/{repo}/actions/runs/{run["id"]}/attempts/{attempt}/jobs', 'jobs')
            for job in jobs:
                if job['conclusion'] == 'skipped': continue
                if job['status'] != 'completed':
                    # Groups are dispatched sequentially within each package;
                    # refusing concurrent groups avoids double spending.
                    active.append(dict(run=run['id'], job=job['id'], package=package))
                    continue
                if not job.get('started_at') or not job.get('completed_at'): continue
                seconds = max(0, (datetime.fromisoformat(job['completed_at'].replace('Z', '+00:00')) -
                                  datetime.fromisoformat(job['started_at'].replace('Z', '+00:00'))).total_seconds())
                consumed[package] += seconds
                entries.append(dict(kind='ACTUAL', package=package, run_id=run['id'], attempt=attempt,
                    job_id=job['id'], job=job['name'], runner_seconds=seconds, conclusion=job['conclusion']))
    entries.append(dict(kind='RESERVATION', package=args.package, run_id=current,
                        runner_seconds=args.reserve_seconds, created_at=datetime.now(timezone.utc).isoformat()))
    (args.output / 'budget-ledger.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in entries))
    (args.output / 'budget-v2.json').write_text(json.dumps(dict(config, actual_seconds=consumed,
        reservation_seconds=args.reserve_seconds, reservation_package=args.package, active_other_jobs=active), indent=2))
    assert not any(j['package'] == args.package for j in active), 'Another group still reserves this package'
    assert consumed[args.package] + args.reserve_seconds <= config['packages'][args.package], 'Package budget gate'
    # Each package has a fixed allowance and their sum equals the campaign cap.
    assert sum(config['packages'].values()) == config['total_runner_seconds']
    print(json.dumps(dict(status='RESERVED', package=args.package, seconds=args.reserve_seconds,
                          actual_package_seconds=consumed[args.package])))


if __name__ == '__main__': main()
