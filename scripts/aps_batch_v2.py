"""Freeze a small measurement batch and collect its independent validation."""
import argparse
import csv
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.collect_evidence import api
from scripts.preserve_e4_v2 import digest


def plan(args):
    repo = os.environ['GITHUB_REPOSITORY']
    for run_id in (args.inputs_run, args.admission_run):
        run = api(f'repos/{repo}/actions/runs/{run_id}')
        assert run['conclusion'] == 'success' and run['path'] == '.github/workflows/aps_schedule_benchmark.yml'
    index = json.loads((args.root/'aps-inputs-index.json').read_text())
    if args.phase == 'hundred':
        diagnostics = json.loads((args.root/'diagnostic'/'aps-processes.json').read_text())
        valid = {r['parent_task_sha256'] for r in diagnostics if r['correctness_status'] == 'VALID'
                 and r['performance_status'] == 'MEASURED' and r['operation_count'] == 10000}
        assert all(t['task_sha256'] in valid for t in index['unique_tasks']), 'Diagnostic branch admission failed'
    cases = [dict(task=t['task_sha256'], label=t['aliases'][0], repeat=args.repeat) for t in index['unique_tasks']]
    assert 0 < len(cases) <= 12
    assert args.repeat == 0 if args.phase == 'diagnostic' else args.repeat in (1, 2, 3)
    reservation = 360 + len(cases)*(480 if args.phase == 'diagnostic' else 660)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as file:
        file.write('matrix='+json.dumps(dict(include=cases), separators=(',', ':'))+'\n')
        file.write('reservation='+str(reservation)+'\n')
    (args.root/'batch-manifest.json').write_text(json.dumps(dict(phase=args.phase, repeat=args.repeat,
        cases=cases, inputs_run=args.inputs_run, admission_run=args.admission_run,
        reserved_runner_seconds=reservation), indent=2)+'\n')


def validate_one(args):
    from validation.aps_schedule import validate_file
    row = json.loads((args.root/'process.json').read_text())
    assert row['task_sha256']
    if row['performance_status'] != 'MEASURED':
        quality = dict(correctness_status='UNCHECKED', quality_status='QUALITY_UNKNOWN',
                       reason=row['performance_status'])
    else:
        assert digest(args.root/'schedule.jsonl') == row['output_sha256']
        try:
            quality = validate_file(args.task, args.root/'schedule.jsonl', args.root/'validation')
        except Exception as error:
            quality = dict(correctness_status='INVALID', quality_status='QUALITY_UNKNOWN',
                           error=f'{type(error).__name__}: {error}')
    row.update(quality=quality, correctness_status=quality['correctness_status'], quality_status=quality['quality_status'])
    (args.root/'validated.json').write_text(json.dumps(row, indent=2)+'\n')
    print(json.dumps({k: v for k, v in row.items() if k not in ('cpuinfo', 'quality')}))
    if quality['correctness_status'] == 'INVALID': raise SystemExit('INVALID_SCHEDULE')


def report(args):
    rows = [json.loads(p.read_text()) for p in sorted(args.root.glob('**/validated.json'))]
    assert rows, 'No validated process evidence'
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'aps-processes.json').write_text(json.dumps(rows, indent=2)+'\n')
    fields = ['task_sha256', 'family', 'density', 'operation_count', 'repeat', 'source_sha',
              'performance_status', 'correctness_status', 'quality_status', 'T_total_s',
              'T_read_s', 'T_schedule_s', 'T_output_s', 'VmHWM_bytes', 'Cmax_ticks', 'LB_ticks', 'gap_bound']
    with (args.output/'aps-processes.csv').open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            flat = {**row, **row.get('measurement', {}), **row.get('quality', {})}
            writer.writerow({k: flat.get(k) for k in fields})
    quality_fields = ['task_sha256', 'quality_status', 'Cmax_ticks', 'LB_ticks', 'gap_bound']
    with (args.output/'aps-quality.csv').open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=quality_fields)
        writer.writeheader()
        for row in rows: writer.writerow({k: {**row, **row.get('quality', {})}.get(k) for k in quality_fields})
    status = dict(execution_status='COMPLETE' if len(rows) == args.expected else 'PARTIAL',
                  expected=args.expected, actual=len(rows), invalid=sum(r['correctness_status']=='INVALID' for r in rows))
    (args.output/'execution-status.json').write_text(json.dumps(status, indent=2)+'\n')
    print(json.dumps(status))


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true': raise SystemExit('Actions only')
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['plan', 'validate', 'report'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--task', type=Path)
    parser.add_argument('--phase', choices=['diagnostic', 'hundred'])
    parser.add_argument('--repeat', type=int, default=0)
    parser.add_argument('--inputs-run', type=int)
    parser.add_argument('--admission-run', type=int)
    parser.add_argument('--expected', type=int, default=10)
    args = parser.parse_args()
    {'plan': plan, 'validate': validate_one, 'report': report}[args.action](args)


if __name__ == '__main__': main()
