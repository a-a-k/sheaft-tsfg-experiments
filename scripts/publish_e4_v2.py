"""Durable revision evidence publication and a separate download audit."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile

REPO = 'a-a-k/sheaft-tsfg-experiments'


def sha(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)


def verify(root):
    hashes = json.loads((root / 'SHA256.json').read_text())
    assert set(hashes) == {'e4-complete-v2.zip'}
    for name, expected in hashes.items():
        assert sha(root / name) == expected
    with zipfile.ZipFile(root / 'e4-complete-v2.zip') as bundle:
        for section in ('raw', 'analysis'):
            manifest = json.loads(bundle.read(section + '/SHA256.json'))
            for name, expected in manifest.items():
                assert name == Path(name).name
                assert hashlib.sha256(bundle.read(section + '/' + name)).hexdigest() == expected
        evidence = json.loads(bundle.read('raw/evidence-v2.json'))
        for entry in evidence['entries']:
            with zipfile.ZipFile(io.BytesIO(bundle.read('raw/' + entry['name'] + '.zip'))) as original:
                for name, expected in entry['files'].items():
                    assert hashlib.sha256(original.read(name)).hexdigest() == expected
        assert json.loads(bundle.read('analysis/summary.json'))['status'] == 'COMPLETE'
    return hashes


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Actions only')
    parser = argparse.ArgumentParser()
    parser.add_argument('--download-verify', action='store_true')
    args = parser.parse_args()
    tag = 'revision-v2-e4-' + os.environ['GITHUB_SHA'][:12]
    root = Path('publication')
    root.mkdir(exist_ok=True)
    if args.download_verify:
        gh('release', 'download', tag, '--repo', REPO, '--dir', str(root))
        hashes = verify(root)
        (root / 'download-verification.json').write_text(json.dumps(dict(status='PASS', release=tag, files=hashes,
            check='Downloaded release; outer archive, internal manifests, original raw files verified'), indent=2))
        print('PASS: downloaded durable archive matches every manifest')
        return
    with zipfile.ZipFile(root / 'e4-complete-v2.zip', 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
        for section in ('raw', 'analysis'):
            for path in sorted((Path('publication-input') / section).iterdir()):
                assert path.is_file()
                bundle.write(path, section + '/' + path.name)
    (root / 'SHA256.json').write_text(json.dumps({'e4-complete-v2.zip': sha(root / 'e4-complete-v2.zip')}, indent=2))
    hashes = verify(root)
    notes = Path('publication-notes.md')
    notes.write_text('Полные исходные E4 и дополнительный анализ выпуска по инструкции 2.2. '
        'Симуляторы не запускались. Прежняя H5 не пересматривается. '
        'В архиве исходные ZIP без изменения байтов, входы, сценарии, полные оценочные записи, '
        'хеши и общие bootstrap-индексы. Этот выпуск не означает завершения APS/PBR.\n', encoding='utf-8')
    # A failed infrastructure attempt can resume the same draft without replacing
    # an existing asset. Other source versions publish separate release tags.
    pages = json.loads(gh('api', f'repos/{REPO}/releases?per_page=100', '--paginate', '--slurp'))
    matches = [r for page in pages for r in page if r['tag_name'] == tag]
    if not matches:
        payload = root / 'release-request.json'
        payload.write_text(json.dumps(dict(tag_name=tag, target_commitish=os.environ['GITHUB_SHA'],
            draft=True, prerelease=True, name='E4: complete source archive and output reanalysis',
            body=notes.read_text(encoding='utf-8'))))
        # Retain the ID returned by POST: a newly created draft need not be
        # immediately visible in a cached paginated list response.
        current = json.loads(gh('api', f'repos/{REPO}/releases', '--method', 'POST', '--input', str(payload)))
    else:
        current = matches[0]
    expected = {**hashes, 'SHA256.json': sha(root / 'SHA256.json')}
    existing = {a['name']: a for a in current['assets']}
    assert existing.keys() <= expected.keys()
    assert all(a.get('digest') == 'sha256:' + expected[n] for n, a in existing.items())
    missing = [str(root / n) for n in expected if n not in existing]
    if missing:
        assert current['draft']
        gh('release', 'upload', tag, '--repo', REPO, *missing)
    for attempt in range(6):
        current = json.loads(gh('api', f'repos/{REPO}/releases/{current["id"]}?check={time.time_ns()}'))
        if len(current['assets']) == len(expected): break
        time.sleep(2)
    assert {a['name']: a.get('digest') for a in current['assets']} == {n: 'sha256:' + h for n, h in expected.items()}
    if current['draft']:
        gh('release', 'edit', tag, '--repo', REPO, '--draft=false', '--latest=false')
    print('Published', tag)


if __name__ == '__main__':
    main()
