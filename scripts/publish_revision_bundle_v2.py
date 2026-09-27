"""Immutable generic public bundle with a separate download verification job."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.publish_e4_v2 import gh,sha,REPO


def verify(root,archive_name):
    hashes=json.loads((root/'SHA256.json').read_text());assert set(hashes)=={archive_name}
    assert sha(root/archive_name)==hashes[archive_name]
    with zipfile.ZipFile(root/archive_name) as bundle:
        for name,digest in json.loads(bundle.read('SHA256.json')).items():
            with bundle.open(name) as file:assert hashlib.file_digest(file,'sha256').hexdigest()==digest
    return hashes


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('first-package'))
    p.add_argument('--kind',default='first-package');p.add_argument('--report',default='FIRST_PACKAGE_REPORT_RU.md')
    p.add_argument('--download-verify',action='store_true');args=p.parse_args()
    tag='revision-v2-'+args.kind+'-'+os.environ['GITHUB_SHA'][:12]
    root=Path('publication');root.mkdir(exist_ok=True);archive_name=args.kind+'-v2.zip'
    if args.download_verify:
        gh('release','download',tag,'--repo',REPO,'--dir',str(root))
        (root/'download-verification.json').write_text(json.dumps(dict(status='PASS',release=tag,files=verify(root,archive_name)),indent=2)+'\n')
        return
    with zipfile.ZipFile(root/archive_name,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as bundle:
        for path in sorted(args.root.rglob('*')):
            if path.is_file():bundle.write(path,str(path.relative_to(args.root)))
    (root/'SHA256.json').write_text(json.dumps({archive_name:sha(root/archive_name)},indent=2)+'\n')
    expected={**verify(root,archive_name),'SHA256.json':sha(root/'SHA256.json')}
    body=(args.root/'report'/args.report).read_text(encoding='utf-8')
    if args.kind=='final-package':
        status=json.loads((args.root/'report/execution-status.json').read_text())
        body=('Итог исполнения Sheaft v2.2. Научный статус: **'+status['execution_status']+'**.\n\n'
            'Полный отчёт находится в `report/FINAL_REPORT_RU.md` внутри `final-package-v2.zip`. '
            'Там же: первичные таблицы, 32 проверки Холма, допуски, бюджет и реестр источников. '
            'Каталог `raw/` сохраняет новые исходные Actions-архивы.\n\n'
            'Все 60 основных APS-процессов завершены и проверены. Таймауты PBR, номинальные блокировки '
            'и недопущенные области резервов сохранены отдельно; они не заменены пилотами. '
            'Прежняя кампания и её результаты сохранены.\n\n'
            'Внешний и внутренний SHA-256 проверяются отдельным job после публикации.')
    payload=root/'request.json';payload.write_text(json.dumps(dict(tag_name=tag,target_commitish=os.environ['GITHUB_SHA'],
        draft=True,prerelease=True,name='Sheaft v2.2: '+args.kind,
        body=body)))
    current=json.loads(gh('api',f'repos/{REPO}/releases','--method','POST','--input',str(payload)))
    gh('release','upload',tag,'--repo',REPO,*[str(root/name) for name in expected])
    for attempt in range(6):
        current=json.loads(gh('api',f'repos/{REPO}/releases/{current["id"]}?check={time.time_ns()}'))
        if len(current['assets'])==len(expected):break
        time.sleep(2)
    assert {a['name']:a.get('digest') for a in current['assets']}=={n:'sha256:'+h for n,h in expected.items()}
    gh('release','edit',tag,'--repo',REPO,'--draft=false','--latest=false')
    print('Published',tag)


if __name__=='__main__':main()
