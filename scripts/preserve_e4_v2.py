"""Preserve pinned, complete E4 archives. No engine is built or executed."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.collect_evidence import api, artifact_download, artifacts


def digest(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Actions only')
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output
    root.mkdir(parents=True, exist_ok=True)
    registry = json.loads(Path('provenance/e4-reuse-v2.json').read_text())
    repo, run_id = registry['repository'], registry['run_id']
    run = api(f'repos/{repo}/actions/runs/{run_id}')
    assert run['head_sha'] == registry['commit']
    assert run['conclusion'] == 'success' and run['status'] == 'completed'
    available = {row['id']: row for row in artifacts(repo, run_id)}
    evidence = dict(schema='evidence-v2', source_run={key: run[key] for key in
                    ('id', 'head_sha', 'html_url', 'run_attempt', 'conclusion')}, entries=[])
    for item in registry['artifacts']:
        actual = available[item['id']]
        assert actual['name'] == item['name'] and not actual['expired']
        archive_path = root / (item['name'] + '.zip')
        assert artifact_download(repo, actual, archive_path) == item['sha256']
        family = item['family']
        prefix = f'e4/{family}/'
        files = {}
        with zipfile.ZipFile(archive_path) as archive:
            seen = set()
            for info in archive.infolist():
                name = info.filename
                path = PurePosixPath(name)
                assert not path.is_absolute() and '..' not in path.parts and '\\' not in name
                assert name not in seen, 'Duplicate archive member'
                seen.add(name)
                if info.is_dir():
                    continue
                # These old evaluate jobs contain only public C++ build products
                # and E4 files. Fail closed before republishing unexpected members.
                assert (name in ('build/reserve', 'build/simulator', 'build/environment.json') or
                        (name.startswith(prefix) and path.suffix in ('.json', '.md', '.bin'))), name
                if not name.startswith(prefix):
                    continue
                target = root / 'extracted' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)
                files[name] = digest(target)
        source_dir = root / 'extracted' / 'e4' / family
        frozen = json.loads((source_dir / 'frozen-interventions.json').read_text())
        metadata = json.loads((source_dir / 'dataset-metadata.json').read_text())
        assert digest(source_dir / 'input.bin') == frozen['dataset_sha256'] == metadata['input_sha256']
        assert digest(source_dir / 'ranking.json') == frozen['ranking_sha256']
        old_summary = json.loads((source_dir / 'summary.json').read_text())
        for law in ('independent', 'common-cause'):
            entry = old_summary['series'][law]
            assert digest(source_dir / f'evaluation-{law}.json') == entry['evidence_sha256']
            assert digest(source_dir / f'scenarios-{law}.json') == entry['scenarios_sha256']
        evidence['entries'].append(dict(**item, status='REUSED_UNCHANGED',
            reason='Complete pinned archive retained byte for byte; saved output only',
            input_sha256=metadata['input_sha256'], files=files, mode=registry['mode'],
            semantics=registry['semantics'], engines=['DAG-REF', 'DES-REF'],
            engine_commit=registry['commit'], output=['outcomes', 'produced_jobs', 'cmax_scaled_ticks']))
    (root / 'evidence-v2.json').write_text(json.dumps(evidence, indent=2) + '\n')
    checksums = {p.name: digest(p) for p in root.iterdir() if p.is_file()}
    (root / 'SHA256.json').write_text(json.dumps(checksums, indent=2) + '\n')
    print('Verified complete E4 archives:', ', '.join(row['family'] for row in evidence['entries']))


if __name__ == '__main__':
    main()
