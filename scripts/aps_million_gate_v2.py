"""Million gate using all three validated 100k repeats and measured 10k RSS."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.collect_evidence import api, artifact_download, artifacts


def read_report(run_id):
    repo=os.environ['GITHUB_REPOSITORY']
    run=api(f'repos/{repo}/actions/runs/{run_id}')
    assert run['conclusion']=='success' and run['path']=='.github/workflows/aps_schedule_benchmark.yml'
    found=[a for a in artifacts(repo,run_id) if a['name']=='aps-batch-report' and not a['expired']]
    assert len(found)==1
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'report.zip'
        digest=artifact_download(repo,found[0],path)
        with zipfile.ZipFile(path) as bundle: rows=json.loads(bundle.read('aps-processes.json'))
    return rows,dict(run_id=run_id,artifact_id=found[0]['id'],artifact_sha256=digest)


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--hundred-runs',required=True)
    parser.add_argument('--diagnostic-run',type=int,required=True)
    args=parser.parse_args()
    index=json.loads((args.root/'aps-inputs-index.json').read_text())
    run_ids=[int(v) for v in args.hundred_runs.split(',')]
    assert len(run_ids)==len(set(run_ids))==3
    observations=[];provenance=[]
    for run in run_ids:
        rows,source=read_report(run);observations.extend(rows);provenance.append(source)
    diagnostics,source=read_report(args.diagnostic_run);provenance.append(source)
    current_code={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in
        ('planning/list_v1.py','planning/aps_format.py','experiments/aps_schedule.py','scripts/run_aps_v2.py')}
    cases=[];decisions=[]
    for family in ('F1','F2'):
        alias=f'{family}-DENSE-N100000-M200-s101'
        small=[r for r in observations if alias in r['aliases']]
        diag=[r for r in diagnostics if alias in r['aliases']]
        large=next(t for t in index['unique_tasks'] if f'{family}-DENSE-N1000000-M200-s101' in t['aliases'])
        valid=(len(small)==3 and {r['repeat'] for r in small}=={1,2,3} and len(diag)==1 and
            all(r['correctness_status']=='VALID' and r['performance_status']=='MEASURED' and
                r['measurement_code_sha256']==current_code for r in [*small,*diag]))
        max_time=max((r.get('measurement',{}).get('T_total_s',float('inf')) for r in small),default=float('inf'))
        rss10=diag[0]['measurement']['VmHWM_bytes'] if len(diag)==1 else None
        rss100=max((r.get('measurement',{}).get('VmHWM_bytes',0) for r in small),default=0)
        estimate=1.25*(rss10+11*max(0,rss100-rss10)) if rss10 is not None else None
        shared_ok=large['catalog_entries']==10 and large['catalog_alternatives']==200 if family=='F1' else large['catalog_alternatives']<=3*large['operations']
        allowed=valid and max_time<=90 and estimate is not None and estimate<3*2**30 and shared_ok
        decision=dict(family=family,input_alias=large['aliases'][0],task_sha256=large['task_sha256'],
            allowed=allowed,performance_status='ADMITTED' if allowed else 'NOT_RUN_BUDGET_GATE',
            all_three_repeats_valid=valid,max_T_100k_s=max_time,RSS_10k=rss10,RSS_100k=rss100,
            estimated_RSS_1m_bytes=estimate,memory_formula='1.25*(RSS_10k+11*max(0,RSS_100k-RSS_10k))',
            catalog_entries=large['catalog_entries'],catalog_alternatives=large['catalog_alternatives'],
            expanded_alternatives=large['expanded_alternatives'],shared_catalog_check=shared_ok,
            structure_review='One dictionary per operation; one shared immutable object per catalog record. '
                             'Frontier candidates are Python tuples; stale assigned entries are removed lazily. '
                             'Observed per-process peaks include all candidate heaps; 4 GiB cgroup remains enforced.',
            time_projection_seconds=20*max_time,repeat=1,limit_seconds=2700)
        decisions.append(decision)
        if allowed:cases.append(dict(task=large['task_sha256'],label=large['aliases'][0],repeat=1))
    reservation=360+len(cases)*3480 # Each measured job 50 min + validation job 8 min, plus batch/report.
    result=dict(protocol='2.2',decisions=decisions,provenance=provenance,measurement_code_sha256=current_code,
                reserved_runner_seconds=reservation,first_million_repeats=True)
    (args.root/'million-admission.json').write_text(json.dumps(result,indent=2)+'\n')
    with open(os.environ['GITHUB_OUTPUT'],'a') as out:
        out.write('matrix='+json.dumps(dict(include=cases),separators=(',',':'))+'\n')
        out.write('reservation='+str(reservation)+'\n')
        out.write('count='+str(len(cases))+'\n')
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
