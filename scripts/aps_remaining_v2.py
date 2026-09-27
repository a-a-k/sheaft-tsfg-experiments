"""Fixed remaining APS order, per-area gates and full timeout reservation."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.collect_evidence import api,artifacts,artifact_download
from scripts.aps_million_gate_v2 import read_report


def previous(run_id):
    repo=os.environ['GITHUB_REPOSITORY'];run=api(f'repos/{repo}/actions/runs/{run_id}')
    assert run['status']=='completed' and run['path'] in (
        '.github/workflows/aps_schedule_benchmark.yml','.github/workflows/aps_remaining_v2.yml')
    item=next(a for a in artifacts(repo,run_id) if a['name']=='aps-batch-report' and not a['expired'])
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'report.zip';digest=artifact_download(repo,item,path)
        with zipfile.ZipFile(path) as bundle:rows=json.loads(bundle.read('aps-processes.json'))
    jobs=api(f'repos/{repo}/actions/runs/{run_id}/jobs?per_page=100')['jobs']
    durations={}
    for kind in ('measure','validate'):
        durations[kind]=max((
            (datetime.fromisoformat(j['completed_at'].replace('Z','+00:00'))-
             datetime.fromisoformat(j['started_at'].replace('Z','+00:00'))).total_seconds()
            for j in jobs if j['name'].startswith(kind+' (') and j['conclusion']=='success'),default=0)
    return rows,dict(run_id=run_id,artifact_id=item['id'],sha256=digest,job_max_seconds=durations)


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    p=argparse.ArgumentParser();p.add_argument('--batch',type=int,required=True)
    p.add_argument('--previous-runs',required=True);p.add_argument('--root',type=Path,default=Path('batch'));args=p.parse_args()
    index=json.loads((args.root/'aps-inputs-index.json').read_text())
    tasks=sorted(index['unique_tasks'],key=lambda r:r['aliases'][0]);assert len(tasks)==10
    initial={t['task_sha256'] for t in tasks if any('-DENSE-' in a and a.endswith('-s101') for a in t['aliases'])}
    sparse=[dict(task=t['task_sha256'],repeat=1) for t in tasks if any('-SPARSE-' in a and a.endswith('-s101') for a in t['aliases'])]
    first_done=initial|{c['task'] for c in sparse}
    restfirst=[dict(task=t['task_sha256'],repeat=1) for t in tasks if t['task_sha256'] not in first_done]
    r2=[dict(task=t['task_sha256'],repeat=2) for t in tasks]
    r3=[dict(task=t['task_sha256'],repeat=3) for t in tasks]
    groups=[sparse,restfirst,r2[:6],r2[6:],r3[:6],r3[6:]]
    assert list(map(len,groups))==[2,6,6,4,6,4]
    old=[];evidence=[]
    ids=[int(v) for v in args.previous_runs.split(',')];assert len(set(ids))==len(ids)
    for run in ids:
        rows,source=previous(run);old.extend(rows);evidence.append(source)
    keys=[(r['task_sha256'],r['repeat']) for r in old if r['operation_count']==1000000]
    assert len(keys)==len(set(keys))
    required=[(c['task'],c['repeat']) for group in groups[:args.batch] for c in group]
    assert all(key in keys for key in required),'Previous fixed-order batches must have outcomes'
    candidates=groups[args.batch];assert all((c['task'],c['repeat']) not in keys for c in candidates),'No automatic retries'
    diagnostics,source=read_report(36308210267);evidence.append(source)
    small=[]
    for run in (36308617954,36308875750,36309164491):
        rows,source=read_report(run);small.extend(rows);evidence.append(source)
    hashes={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in
        ('planning/list_v1.py','planning/aps_format.py','experiments/aps_schedule.py','scripts/run_aps_v2.py')}
    assert all(r['measurement_code_sha256']==hashes for r in [*old,*small,*diagnostics])
    ledger=json.loads(Path('artifacts/budget/budget-v2.json').read_text())
    remaining=ledger['packages']['aps-rest']-ledger['actual_seconds']['aps-rest']
    # Preparation/download/validation overhead uses observed complete jobs, with
    # a conservative floor; every projected remaining job is doubled.
    overhead=max([300]+[s['job_max_seconds']['measure']+s['job_max_seconds']['validate'] for s in evidence if 'job_max_seconds' in s])
    decisions=[];selected=[]
    for case in candidates:
        task=next(t for t in tasks if t['task_sha256']==case['task']);alias=task['aliases'][0]
        family,density=alias.split('-')[:2];smallalias=alias.replace('N1000000','N100000')
        rows=[r for r in small if smallalias in r['aliases']];diag=next(r for r in diagnostics if smallalias in r['aliases'])
        valid=len(rows)==3 and {r['repeat'] for r in rows}=={1,2,3} and all(r['correctness_status']=='VALID' and r['performance_status']=='MEASURED' for r in [*rows,diag])
        max_time=max(r['measurement']['T_total_s'] for r in rows)
        rss10=diag['measurement']['VmHWM_bytes'];rss100=max(r['measurement']['VmHWM_bytes'] for r in rows)
        estimate=1.25*(rss10+11*max(0,rss100-rss10))
        firstalias=f'{family}-{density}-N1000000-M200-s101'
        first=next((r for r in old if firstalias in r['aliases'] and r['repeat']==1),None)
        first_valid=first is not None and first['correctness_status']=='VALID' and first['performance_status']=='MEASURED'
        branch_first=firstalias in task['aliases'] and case['repeat']==1
        branch_remaining=sum(1 for t in tasks for repeat in (1,2,3)
            if t['aliases'][0].startswith(f'{family}-{density}-') and (t['task_sha256'],repeat) not in keys)
        projected_measure=first['measurement']['T_total_s'] if first_valid else 20*max_time
        projected=2*(projected_measure+overhead)*branch_remaining+480
        catalog=(task['catalog_entries']==10 and task['catalog_alternatives']==200) if family=='F1' else task['catalog_alternatives']<=3*task['operations']
        allowed=valid and max_time<=90 and estimate<3*2**30 and catalog and (branch_first or first_valid) and projected<=remaining
        decisions.append(dict(**case,alias=alias,allowed=allowed,small_valid=valid,max_100k_s=max_time,
            estimated_RSS_1m_bytes=estimate,catalog_valid=catalog,first_in_area_valid=first_valid,
            remaining_area_processes=branch_remaining,projected_runner_seconds=projected,
            remaining_package_seconds=remaining,performance_status='ADMITTED' if allowed else 'NOT_RUN_BUDGET_GATE'))
        if allowed:selected.append(case)
    reservation=480+3480*len(selected)
    if reservation>remaining:
        for d in decisions:d.update(allowed=False,performance_status='NOT_RUN_BUDGET_GATE',reason='Full job timeout reservation exceeds remaining package budget')
        selected=[];reservation=480
    result=dict(batch=args.batch,fixed_order=groups,cases=selected,decisions=decisions,evidence=evidence,
        reservation_seconds=reservation,measurement_code_sha256=hashes)
    (args.root/'remaining-admission.json').write_text(json.dumps(result,indent=2)+'\n')
    with open(os.environ['GITHUB_OUTPUT'],'a') as file:
        file.write('matrix='+json.dumps(dict(include=selected),separators=(',',':'))+'\n')
        file.write(f'count={len(selected)}\nreservation={reservation}\n')
    print(json.dumps(dict(batch=args.batch,count=len(selected),decisions=decisions)))


if __name__=='__main__':main()
