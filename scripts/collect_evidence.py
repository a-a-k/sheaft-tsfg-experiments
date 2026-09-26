"""Fetch pinned public Actions evidence with archive and path checks."""
import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile


def api(path):
    request=urllib.request.Request('https://api.github.com/'+path,
        headers={'Accept':'application/vnd.github+json','Authorization':'Bearer '+os.environ['GH_TOKEN'],
                 'X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.urlopen(request,timeout=90) as response:return json.load(response)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None


def artifact_download(repository,artifact,target):
    request=urllib.request.Request(f"https://api.github.com/repos/{repository}/actions/artifacts/{artifact['id']}/zip",
        headers={'Authorization':'Bearer '+os.environ['GH_TOKEN']})
    try:
        response=urllib.request.build_opener(NoRedirect).open(request,timeout=90)
    except urllib.error.HTTPError as error:
        if error.code not in (301,302,303,307,308):raise
        # Signed storage URL is fetched without forwarding the GitHub token.
        location=error.headers['Location']
        if not location.startswith('https://'):raise ValueError('Non-HTTPS artifact redirect')
        response=urllib.request.urlopen(location,timeout=180)
    with response,target.open('wb') as file:shutil.copyfileobj(response,file,1024*1024)
    with target.open('rb') as file:digest=hashlib.file_digest(file,'sha256').hexdigest()
    declared=artifact.get('digest')
    if declared:assert declared=='sha256:'+digest,'Artifact digest mismatch'
    return digest


def artifacts(repository,run_id):
    rows=[];page=1
    while True:
        response=api(f'repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100&page={page}')
        rows.extend(response['artifacts'])
        if len(rows)>=response['total_count']:return rows
        page+=1


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
    p=argparse.ArgumentParser()
    p.add_argument('--registry',type=Path,default=Path('provenance/campaign.json'))
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--check-only',action='store_true')
    p.add_argument('--inputs',action='store_true')
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    registry=json.loads(args.registry.read_text());repository=registry['repository'];runs={}
    for role,item in registry['runs'].items():
        actual=api(f"repos/{repository}/actions/runs/{item['id']}")
        runs[role]={k:actual[k] for k in ('id','head_sha','status','conclusion','html_url','run_attempt','created_at','updated_at')}
    ready=all(r['status']=='completed' and r['conclusion']=='success' for r in runs.values())
    (args.output/'runs.json').write_text(json.dumps(runs,indent=2))
    if args.check_only:
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('ready='+str(ready).lower()+'\n')
        print(json.dumps(dict(ready=ready,runs=runs)));return
    if not ready:raise SystemExit('Required campaigns are not all complete and successful')
    index=[]
    with tempfile.TemporaryDirectory() as temp:
        downloaded=Path(temp)/'artifact.zip'
        if args.inputs:
            items=artifacts(repository,registry['runs']['screen']['id'])
            items=[a for a in items if a['name'].startswith('scale-screen-')]
            assert len(items)==48
            with zipfile.ZipFile(args.output/'inputs.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as bundle:
                for artifact in sorted(items,key=lambda a:a['name']):
                    digest=artifact_download(repository,artifact,downloaded)
                    with zipfile.ZipFile(downloaded) as archive:
                        manifest=json.loads(archive.read('dataset/manifest.json'))
                        dataset=manifest['dataset_id']
                        assert '/' not in dataset and '\\' not in dataset and '..' not in dataset
                        for name in ('manifest.json','input.bin','operations.jsonl.gz','scenarios-1000.json','sample.json'):
                            with archive.open('dataset/'+name) as source,bundle.open(dataset+'/'+name,'w',force_zip64=True) as target:
                                hasher=hashlib.sha256()
                                while chunk:=source.read(1024*1024):hasher.update(chunk);target.write(chunk)
                            if name in manifest['files']:assert hasher.hexdigest()==manifest['files'][name]
                        index.append(dict(dataset_id=dataset,artifact_id=artifact['id'],artifact_sha256=digest,files=manifest['files']))
                    print('Preserved public input:',dataset,flush=True)
            (args.output/'inputs-index.json').write_text(json.dumps(index,indent=2));return
        for role,item in registry['runs'].items():
            available=artifacts(repository,item['id'])
            for selection in item['artifacts']:
                matches=[a for a in available if fnmatch.fnmatchcase(a['name'],selection['pattern'])]
                if not matches:raise ValueError('Missing evidence pattern '+selection['pattern'])
                for artifact in sorted(matches,key=lambda a:a['name']):
                    assert not artifact['expired']
                    destination=args.output/selection['directory']
                    if selection.get('subdirectories'):destination/=artifact['name']
                    destination.mkdir(parents=True,exist_ok=True)
                    digest=artifact_download(repository,artifact,downloaded)
                    with zipfile.ZipFile(downloaded) as archive:
                        for entry in archive.infolist():
                            path=PurePosixPath(entry.filename)
                            if path.is_absolute() or '..' in path.parts or '\\' in entry.filename:raise ValueError('Unsafe archive path')
                            # Reporting needs public JSON/CSV/text, never native binaries or private data.
                            if path.suffix not in ('.json','.csv','.md','.txt'):continue
                            if any(part.startswith('.private') for part in path.parts):raise ValueError('Unexpected private evidence')
                            target=destination.joinpath(*path.parts);target.parent.mkdir(parents=True,exist_ok=True)
                            with archive.open(entry) as source,target.open('wb') as file:shutil.copyfileobj(source,file)
                    index.append(dict(role=role,name=artifact['name'],id=artifact['id'],sha256=digest,run_id=item['id']))
                    print('Verified evidence:',artifact['name'],flush=True)
    (args.output/'artifact-index.json').write_text(json.dumps(index,indent=2))


if __name__=='__main__':main()
