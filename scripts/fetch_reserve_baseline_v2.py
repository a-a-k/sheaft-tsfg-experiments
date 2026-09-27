"""Retrieve an admitted frozen PBR baseline, never regenerate its schedule."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.collect_evidence import api,artifacts,artifact_download


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    p=argparse.ArgumentParser();p.add_argument('--run',type=int,required=True);p.add_argument('--family',required=True)
    p.add_argument('--size',type=int,choices=[10000,100000],required=True);p.add_argument('--output',type=Path,default=Path('baseline'));args=p.parse_args()
    repo=os.environ['GITHUB_REPOSITORY'];run=api(f'repos/{repo}/actions/runs/{args.run}')
    assert run['status']=='completed'
    identity=f'{args.family}-DENSE-N{args.size}-M200-s101-PBR'
    name=('pbr-screen-' if args.size==10000 else 'pbr-nominal-')+identity
    item=next(a for a in artifacts(repo,args.run) if a['name']==name and not a['expired'])
    args.output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'baseline.zip';digest=artifact_download(repo,item,path)
        with zipfile.ZipFile(path) as bundle:
            summary=json.loads(bundle.read('screen.json' if args.size==10000 else 'nominal-admission.json'))
            if summary['input_status']!='NOMINALLY_ADMISSIBLE':
                summary.update(baseline_run=args.run,baseline_source_sha=run['head_sha'],baseline_artifact_id=item['id'],
                    baseline_archive_sha256=digest)
                (args.output/'baseline.json').write_text(json.dumps(summary,indent=2)+'\n')
                return
            # A K10 timeout does not erase a successfully cross-validated M0.
            assert all(p['correctness_status']=='VALID' for p in summary['processes'] if p['label'].startswith('M0-'))
            data=bundle.read('frozen-baseline.json' if args.size==10000 else 'input.json')
            (args.output/'input.json').write_bytes(data)
    summary.update(baseline_run=args.run,baseline_source_sha=run['head_sha'],baseline_artifact_id=item['id'],
        baseline_archive_sha256=digest,baseline_input_sha256=hashlib.sha256(data).hexdigest())
    (args.output/'baseline.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':main()
