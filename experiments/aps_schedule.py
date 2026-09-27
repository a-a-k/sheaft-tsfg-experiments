"""One isolated SHEAFT-LIST-v1 measurement process; input contains no old plan."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from planning.aps_format import compact_json, read_task
from planning.list_v1 import schedule, VERSION


def memory():
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    return dict(VmHWM_bytes=int(status['VmHWM'].split()[0])*1024, VmRSS_bytes=int(status['VmRSS'].split()[0])*1024,
                source='/proc/self/status after exec; no child calculators')


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true': raise SystemExit('Actions only')
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--launch-time', type=float, required=True)
    args = parser.parse_args()
    begin = time.monotonic()
    data = read_task(args.input)
    imported = time.monotonic()
    queues = schedule(data['operations'], data['machines'])
    scheduled = time.monotonic()
    with args.output.open('w', encoding='utf-8', newline='\n') as file:
        file.write(compact_json(dict(schema='APS-SCHEDULE-v1', algorithm=VERSION,
            task_sha256=data['task_sha256'], operations=len(data['operations']), machines=data['machines']))+'\n')
        for op in data['operations']:
            file.write(compact_json(['O', op['id'], op['machine'], op['planned_start'], op['planned_end']])+'\n')
        for m, queue in enumerate(queues): file.write(compact_json(['Q', m, queue])+'\n')
    closed = time.monotonic()
    measurement = dict(status='COMPLETE_UNCHECKED', algorithm=VERSION, task_sha256=data['task_sha256'],
        T_read_s=imported-begin, T_schedule_s=scheduled-imported, T_output_s=closed-scheduled,
        T_startup_s=begin-args.launch_time, T_total_s=closed-args.launch_time,
        output_bytes=args.output.stat().st_size, **memory(),
        catalog_entries=data['catalog_entries'], expanded_alternatives=data['expanded_alternatives'],
        catalog_alternatives=data['catalog_alternatives'])
    args.output.with_suffix('.measurement.json').write_text(json.dumps(measurement, indent=2)+'\n')
    print(json.dumps(measurement), flush=True)


if __name__ == '__main__': main()
