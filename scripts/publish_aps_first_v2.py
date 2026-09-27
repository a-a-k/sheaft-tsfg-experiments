"""Publish generated public APS evidence and verify a fresh release download."""
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


def verify(root):
    expected=json.loads((root/'SHA256.json').read_text())
    assert set(expected)=={'aps-first-v2.zip'}
    assert sha(root/'aps-first-v2.zip')==expected['aps-first-v2.zip']
    with zipfile.ZipFile(root/'aps-first-v2.zip') as archive:
        for name,digest in json.loads(archive.read('SHA256.json')).items():
            with archive.open(name) as file:assert hashlib.file_digest(file,'sha256').hexdigest()==digest
        status=json.loads(archive.read('report/execution-status.json'))
        assert status['first_APS_package']=='COMPLETE' and status['execution_status']=='PARTIAL'
    return expected


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    parser=argparse.ArgumentParser();parser.add_argument('--download-verify',action='store_true');args=parser.parse_args()
    root=Path('publication');root.mkdir(exist_ok=True);tag='revision-v2-aps-first-'+os.environ['GITHUB_SHA'][:12]
    if args.download_verify:
        gh('release','download',tag,'--repo',REPO,'--dir',str(root))
        (root/'download-verification.json').write_text(json.dumps(dict(status='PASS',release=tag,files=verify(root)),indent=2)+'\n')
        return
    with zipfile.ZipFile(root/'aps-first-v2.zip','w',zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
        for path in sorted(Path('publication-input').rglob('*')):
            if path.is_file():archive.write(path,str(path.relative_to('publication-input')))
    (root/'SHA256.json').write_text(json.dumps({'aps-first-v2.zip':sha(root/'aps-first-v2.zip')},indent=2)+'\n')
    expected={**verify(root),'SHA256.json':sha(root/'SHA256.json')}
    body=(Path('publication-input/report/APS_FIRST_REPORT_RU.md').read_text(encoding='utf-8')+
          '\nРыночные ограничения сравнения: см. APS_MARKET_COMPARISON_RU.md внутри архива.\n')
    request=root/'request.json';request.write_text(json.dumps(dict(tag_name=tag,target_commitish=os.environ['GITHUB_SHA'],
        draft=True,prerelease=True,name='APS first package: validated million-operation plans',body=body)))
    current=json.loads(gh('api',f'repos/{REPO}/releases','--method','POST','--input',str(request)))
    gh('release','upload',tag,'--repo',REPO,*[str(root/name) for name in expected])
    for attempt in range(6):
        current=json.loads(gh('api',f'repos/{REPO}/releases/{current["id"]}?check={time.time_ns()}'))
        if len(current['assets'])==len(expected):break
        time.sleep(2)
    assert {a['name']:a.get('digest') for a in current['assets']}=={n:'sha256:'+h for n,h in expected.items()}
    gh('release','edit',tag,'--repo',REPO,'--draft=false','--latest=false')
    print('Published',tag)


if __name__=='__main__':main()
