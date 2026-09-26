"""Publish only a complete, checksum-verified research artifact from Actions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


REPOSITORY='a-a-k/sheaft-tsfg-experiments'
TAG='v0.2.0-full-study'
EXPECTED=dict(screen_processes=144,main_processes=432,e3_datasets=48,e4_families=2,extra_processes=171)


def verify(root):
    summary=json.loads((root/'summary.json').read_text())
    assert summary['status']=='COMPLETED_WITH_DISCLOSED_LIMITATIONS','Preliminary or incomplete report cannot be published as final'
    assert summary['expected']==summary['actual']==EXPECTED
    assert summary['environment_records']==72
    assert len(summary['witnesses'])==4 and all(w['status']=='PASS' for w in summary['witnesses'])
    assert len(summary['H3'])==16 and len(summary['H4'])==48 and len(summary['H5'])==2
    assert all(r['status']=='completed' and r['conclusion']=='success' for r in summary['runs'].values())
    assert summary['runs']['main']['head_sha']=='afb7081898506524e3591af4e727461fc46efa2d'
    hashes=json.loads((root/'SHA256.json').read_text())
    required={'REPORT_RU.md','REPORT_RU.pdf','summary.json','main-processes.csv','H3-measurements.csv',
              'screen-processes.csv','supplementary-processes.csv','supplementary-summary.csv','aggregation.csv',
              'strict-deadlines-post-hoc.csv','H3.png','aggregation.png','reserves.png',
              'inputs.zip','inputs-index.json','input-diagnostics.json','evidence.zip','runs.json'}
    assert required<=hashes.keys(),required-hashes.keys()
    assert {p.name for p in root.iterdir() if p.is_file()}==hashes.keys()|{'SHA256.json'}
    for name,digest in hashes.items():
        assert name==Path(name).name and re.fullmatch('[0-9a-f]{64}',digest)
        path=root/name
        assert path.is_file() and 0<path.stat().st_size<2**31,'Missing or oversized release asset'
        with path.open('rb') as source:assert hashlib.file_digest(source,'sha256').hexdigest()==digest,name
    assert (root/'REPORT_RU.pdf').read_bytes().startswith(b'%PDF-')
    hashes['SHA256.json']=hashlib.sha256((root/'SHA256.json').read_bytes()).hexdigest()
    return summary,hashes


def gh(*args,check=True):
    return subprocess.run(['gh',*args],check=check,text=True,capture_output=True)


def release():
    result=gh('api',f'repos/{REPOSITORY}/releases/tags/{TAG}',check=False)
    if result.returncode:
        assert '404' in result.stderr,'Release lookup failed; refusing to infer absence'
        return None
    return json.loads(result.stdout)


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args();summary,hashes=verify(args.directory)
    if args.verify_only:
        print('Publication evidence verified');return
    source=os.environ['REPORT_SOURCE_SHA']
    assert re.fullmatch('[0-9a-f]{40}',source)
    current=release()
    if current is None:
        decisions={status:sum(d['status']==status for d in summary['H3'])
                   for status in ('SUPPORTED','NOT_SUPPORTED','INSUFFICIENT_COMPLETED')}
        notes=args.directory.parent/'release-notes.md'
        notes.write_text(
            '# TSFG: завершённая исследовательская кампания\n\n'
            'Точное пооперационное исполнение проверено независимыми DES/DAG. '
            'Результаты относятся к опубликованным моделям и данным.\n\n'
            f"H3, 16 решений по области/размеру/эталону: {decisions}. "
            'Нехватка полных пар сохранена как INSUFFICIENT_COMPLETED; таймауты не заменены временем завершения.\n\n'
            'REPORT_RU.pdf / REPORT_RU.md содержат результаты, ограничения агрегации, '
            'оценку резервов и отклонения от плана. inputs.zip сохраняет 48 наборов, '
            'evidence.zip — проверенные свидетельства и полные контрольные состояния на [0,D]. '
            'SHA256.json идентифицирует файлы. Частный S1 и его бинарник не включены.\n\n'
            f"[Сборка отчёта](https://github.com/{REPOSITORY}/actions/runs/{os.environ['REPORT_RUN_ID']})\n",
            encoding='utf-8')
        gh('release','create',TAG,'--repo',REPOSITORY,'--target',source,'--draft',
           '--title','TSFG: full manufacturing execution study','--notes-file',str(notes))
        current=release()
    assert current['target_commitish']==source,'Existing release belongs to a different report source'
    existing={asset['name']:asset for asset in current['assets']}
    assert existing.keys()<=hashes.keys(),'Unexpected existing release assets'
    for name,asset in existing.items():
        assert asset.get('digest')=='sha256:'+hashes[name],'Existing asset differs; refusing replacement'
    missing=[str(args.directory/name) for name in hashes if name not in existing]
    if missing:
        assert current['draft'],'Published incomplete release cannot be silently changed'
        gh('release','upload',TAG,'--repo',REPOSITORY,*missing)
    current=release();uploaded={a['name']:a for a in current['assets']}
    assert uploaded.keys()==hashes.keys()
    assert all(uploaded[name].get('digest')=='sha256:'+digest for name,digest in hashes.items())
    if current['draft']:gh('release','edit',TAG,'--repo',REPOSITORY,'--draft=false','--latest')
    current=release();assert not current['draft']
    print('Published verified research archive:',current['html_url'])


if __name__=='__main__':main()
