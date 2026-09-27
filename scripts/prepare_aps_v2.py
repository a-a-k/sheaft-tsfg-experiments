"""Convert pinned historical routes to published plan-free APS inputs."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from planning.aps_format import write_task
from scripts.collect_evidence import api, artifact_download
from scripts.preserve_e4_v2 import digest


def source_ops(path, limit=None):
    with gzip.open(path, 'rt', encoding='utf-8') as file:
        for i, line in enumerate(file):
            if limit is not None and i >= limit: break
            yield json.loads(line)


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true': raise SystemExit('Actions only')
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--size', type=int, default=100000, choices=[100000, 1000000])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    old_index = json.loads(Path('docs/results/full-study/inputs-index.json').read_text())
    # Full first-phase input order is frozen before observing any APS timing.
    wanted = [r for r in old_index if any(r['dataset_id'].startswith(f'{f}-{d}-N{args.size}-')
               for f in ('F1', 'F2') for d in ('DENSE', 'SPARSE'))]
    assert len(wanted) == 12
    mapping, unique = [], {}
    repo = 'a-a-k/sheaft-tsfg-experiments'
    with tempfile.TemporaryDirectory() as temporary:
        temp = Path(temporary)
        for parent in sorted(wanted, key=lambda r: r['dataset_id']):
            begin = time.monotonic()
            artifact = api(f'repos/{repo}/actions/artifacts/{parent["artifact_id"]}')
            assert not artifact['expired']
            assert artifact_download(repo, artifact, temp/'source.zip') == parent['artifact_sha256']
            with zipfile.ZipFile(temp/'source.zip') as archive:
                with archive.open('dataset/operations.jsonl.gz') as source, (temp/'operations.gz').open('wb') as target:
                    shutil.copyfileobj(source, target)
                manifest = json.loads(archive.read('dataset/manifest.json'))
            assert digest(temp/'operations.gz') == parent['files']['operations.jsonl.gz']
            assert manifest['dataset_id'] == parent['dataset_id']
            result = write_task(source_ops(temp/'operations.gz'), manifest['metadata']['machines'],
                                '0.01 second', temp/'task.jsonl')
            task = result['task_sha256']
            folder = args.output/task
            if task not in unique:
                folder.mkdir()
                shutil.copyfile(temp/'task.jsonl', folder/'task.jsonl')
                entry = dict(**result, file_sha256=digest(folder/'task.jsonl'), file_bytes=(folder/'task.jsonl').stat().st_size,
                    aliases=[], parent_operations_sha256=parent['files']['operations.jsonl.gz'],
                    family=manifest['metadata']['family'], density=manifest['metadata']['density'],
                    seed=manifest['metadata']['seed'], machines=manifest['metadata']['machines'])
                if args.size == 100000:
                    diagnostic = write_task(source_ops(temp/'operations.gz', 10000), manifest['metadata']['machines'],
                                            '0.01 second', folder/'diagnostic-10k.jsonl')
                    entry['diagnostic_10k'] = dict(**diagnostic, file_sha256=digest(folder/'diagnostic-10k.jsonl'),
                        selection='First 1000 complete ten-operation jobs; original releases unchanged')
                unique[task] = entry
            else:
                assert digest(temp/'task.jsonl') == unique[task]['file_sha256']
            unique[task]['aliases'].append(parent['dataset_id'])
            mapping.append(dict(dataset_id=parent['dataset_id'], parent_artifact=parent['artifact_id'],
                parent_archive_sha256=parent['artifact_sha256'], parent_operations_sha256=parent['files']['operations.jsonl.gz'],
                task_sha256=task, preparation_seconds=time.monotonic()-begin))
            print('Prepared', parent['dataset_id'], task, flush=True)
    report = dict(version='2.2', profile='APS-BASIC', size=args.size, source_records=mapping,
                  unique_tasks=list(unique.values()), repeated_measurements=3,
                  first_million_measurements=['F1-DENSE-N1000000-M200-s101', 'F2-DENSE-N1000000-M200-s101'])
    (args.output/'aps-inputs-index.json').write_text(json.dumps(report, indent=2)+'\n')
    for row in unique.values():
        (args.output/row['task_sha256']/'manifest.json').write_text(json.dumps(row, indent=2)+'\n')


if __name__ == '__main__': main()
