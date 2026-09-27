"""Freeze large PBR groups and retain both failed gates and process outcomes."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.collect_evidence import api,artifacts,artifact_download


def plan(args):
    root=args.root;root.mkdir(parents=True,exist_ok=True);repo=os.environ['GITHUB_REPOSITORY']
    run=api(f'repos/{repo}/actions/runs/{args.nominal_run}')
    assert run['status']=='completed' and run['path']=='.github/workflows/extended_benchmark_v2.yml'
    for name in ('engines/des_ext/main.cpp','engines/tsfg_op/operation_adapter.go','engines/tsfg_op/pbr_adapter.go'):
        original=subprocess.check_output(['git','-c',f'safe.directory={Path.cwd()}','show',f'{run["head_sha"]}:{name}'])
        assert original==Path(name).read_bytes(),'Engine changed after nominal admission: '+name
    items=[a for a in artifacts(repo,args.nominal_run) if a['name'].startswith('pbr-nominal-admission-') and not a['expired']]
    assert len(items)==6
    summaries=[];evidence=[]
    with tempfile.TemporaryDirectory() as temp:
        for item in sorted(items,key=lambda a:a['name']):
            path=Path(temp)/'nominal.zip';digest=artifact_download(repo,item,path)
            with zipfile.ZipFile(path) as bundle:summary=json.loads(bundle.read('nominal-admission.json'))
            summaries.append(summary);evidence.append(dict(id=item['id'],sha256=digest))
    cases=[];decisions=[];families=('F1','F2') if args.phase=='pilot' else [args.family]
    for family in families:
        selected=[s for s in summaries if s['family']==family]
        allowed=len(selected)==3 and {s['seed'] for s in selected}=={101,102,103} and all(
            s['input_status']=='NOMINALLY_ADMISSIBLE' and s['correctness_status']=='VALID' for s in selected)
        if args.phase=='measure' and selected[0]['n']==1000000:
            assert args.pilot_run
            pilot=api(f'repos/{repo}/actions/runs/{args.pilot_run}')
            assert pilot['status']=='completed' and pilot['path']=='.github/workflows/extended_benchmark_v2.yml'
            item=next(a for a in artifacts(repo,args.pilot_run) if a['name']=='pbr-large-batch-report')
            with tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/'report.zip';digest=artifact_download(repo,item,path)
                with zipfile.ZipFile(path) as bundle:rows=json.loads(bundle.read('pbr-points.json'))
            gates=[r for r in rows if r['family']==family]
            allowed &= len(gates)==3 and all(r.get('million_admitted') and r['count']==10 and r['n']==1000000 and
                any(s['id']==r['id'] and s['task_sha256']==r['task_sha256'] for s in selected) for r in gates)
            evidence.append(dict(pilot_run=args.pilot_run,artifact_id=item['id'],sha256=digest))
        decisions.append(dict(family=family,allowed=allowed,status='ADMITTED' if allowed else 'NOT_RUN_BUDGET_GATE',
            nominal_statuses={s['seed']:s['input_status'] for s in selected}))
        if allowed:cases.extend(dict(case=s['id']) for s in selected)
    count=10 if args.phase=='pilot' else 100
    reservation=360+len(cases)*(1260 if count==10 else 2580)
    (root/'measurement-manifest.json').write_text(json.dumps(dict(cases=cases,count=count,round=args.round,
        nominal_run=args.nominal_run,decisions=decisions,evidence=evidence,reservation_seconds=reservation),indent=2)+'\n')
    with open(os.environ['GITHUB_OUTPUT'],'a') as file:
        file.write('matrix='+json.dumps(dict(include=cases),separators=(',',':'))+'\n')
        file.write(f'count={len(cases)}\nreservation={reservation}\n')


def report(args):
    args.output.mkdir(parents=True,exist_ok=True)
    rows=[json.loads(p.read_text()) for p in sorted(args.root.glob('**/validated.json'))]
    (args.output/'pbr-points.json').write_text(json.dumps(rows,indent=2)+'\n')
    status=dict(execution_status='COMPLETE' if len(rows)==args.expected and all(r['execution_status']=='COMPLETE' for r in rows) else 'PARTIAL',
        expected=args.expected,actual=len(rows),measured=sum(p['performance_status']=='MEASURED' for r in rows for p in r['processes']),
        timeouts=sum(p['performance_status']=='TIMEOUT' for r in rows for p in r['processes']))
    (args.output/'execution-status.json').write_text(json.dumps(status,indent=2)+'\n');print(json.dumps(status))


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    p=argparse.ArgumentParser();p.add_argument('action',choices=['plan','report']);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path);p.add_argument('--nominal-run',type=int);p.add_argument('--pilot-run',type=int)
    p.add_argument('--phase',choices=['pilot','measure']);p.add_argument('--family',choices=['F1','F2']);p.add_argument('--round',type=int,default=0)
    p.add_argument('--expected',type=int);args=p.parse_args();{'plan':plan,'report':report}[args.action](args)


if __name__=='__main__':main()
