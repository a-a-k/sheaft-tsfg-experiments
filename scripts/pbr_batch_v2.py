"""Admission, frozen batch order and complete/partial first-stage reporting."""
import argparse
import csv
import hashlib
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
    repo=os.environ['GITHUB_REPOSITORY']
    run=api(f'repos/{repo}/actions/runs/{args.admission_run}')
    assert run['conclusion']=='success' and run['path']=='.github/workflows/extended_admission_v2.yml'
    artifact=next(a for a in artifacts(repo,args.admission_run) if a['name']=='pbr-rational-controls')
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'admission.zip';digest=artifact_download(repo,artifact,path)
        with zipfile.ZipFile(path) as bundle:
            summary=json.loads(bundle.read('pbr-mk01/pbr-admission.json'))
    assert summary['status']=='PASS' and summary['combined_trajectories_per_engine']==135 and summary['combined_deadline_checks_per_engine']==405
    source_hashes={}
    for name in ('engines/tsfg_op/operation_adapter.go','engines/tsfg_op/pbr_adapter.go','engines/des_ext/main.cpp',
                 'references/pbr_ref.py','validation/pbr_checks.py'):
        original=subprocess.check_output(['git','-c',f'safe.directory={Path.cwd()}','show',f'{run["head_sha"]}:{name}'])
        actual=Path(name).read_bytes()
        assert actual==original,'Changed admitted source: '+name
        source_hashes[name]=hashlib.sha256(actual).hexdigest()
    index=json.loads((args.root/'pbr-inputs-index.json').read_text())
    cases=[dict(case=r['id']) for r in index['cases'] if r['batch']==args.batch]
    assert len(cases)==6
    (args.root/'batch-manifest.json').write_text(json.dumps(dict(cases=cases,batch=args.batch,
        admission_run=args.admission_run,admission_artifact_sha256=digest,source_hashes=source_hashes,
        reservation_seconds=args.reservation),indent=2)+'\n')
    with open(os.environ['GITHUB_OUTPUT'],'a') as out:out.write('matrix='+json.dumps(dict(include=cases),separators=(',',':'))+'\n')


def report(args):
    rows=[json.loads(p.read_text()) for p in sorted(args.root.glob('**/screen.json'))]
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'pbr-screen.json').write_text(json.dumps(rows,indent=2)+'\n')
    fields=['id','family','n','seed','profile','execution_status','correctness_status','input_status','nominal_status',
        'K10_status','control_status','C0','D','resource_wait_integral','blocked_machine_integral','coupling_witnesses',
        'T_TSFG_K10_s','T_DES_K10_s','TSFG_K10_status','DES_K10_status']
    with (args.output/'pbr-screen.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader()
        for row in rows:
            flat={**row,**row.get('constraints',{})}
            for engine in ('tsfg','des'):
                k10=next((p for p in row['processes'] if p['engine']==engine and p['label']=='K10-standalone'),{})
                flat[f'T_{engine.upper()}_K10_s']=k10.get('T_total_s')
                flat[f'{engine.upper()}_K10_status']=k10.get('performance_status','NOT_RUN')
            writer.writerow({k:flat.get(k) for k in fields})
    summary=dict(execution_status='COMPLETE' if len(rows)==6 and all(r['execution_status']=='COMPLETE' for r in rows) else 'PARTIAL',
        expected=6,actual=len(rows),invalid=sum(r['correctness_status']=='INVALID' for r in rows),
        K10_complete=sum(r.get('K10_status')=='COMPLETE_VALID' for r in rows))
    (args.output/'execution-status.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['plan','report'])
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--output',type=Path)
    parser.add_argument('--admission-run',type=int);parser.add_argument('--batch',type=int)
    parser.add_argument('--reservation',type=int,default=5040)
    args=parser.parse_args();{'plan':plan,'report':report}[args.action](args)


if __name__=='__main__':main()
