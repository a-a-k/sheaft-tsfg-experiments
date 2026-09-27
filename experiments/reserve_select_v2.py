"""Freeze one intervention on a separate selection bank before opening holdout."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.reserve_inputs_v2 import scenario,scaled_scenario,accelerated,evaluate
from experiments.pbr_cases_v2 import r5
from experiments.pbr_inputs_v2 import task_hash


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    p=argparse.ArgumentParser();p.add_argument('--pilot',type=Path,required=True);p.add_argument('--output',type=Path,default=Path('selection'))
    p.add_argument('--ranking',type=Path);args=p.parse_args();root=args.output;root.mkdir(parents=True,exist_ok=True)
    pilot=json.loads((args.pilot/'pilot/reserve-pilot.json').read_text());assert pilot['execution_status']=='COMPLETE'
    data=json.loads((args.pilot/'baseline/input.json').read_text());task=task_hash(data);assert task==pilot['task_sha256']
    scaled=accelerated(data);c0=pilot['baseline']['C0'];deadline=11*r5(c0*110,100);jobs=len(data['jobs']);law=pilot['law']
    records=[];manifest=dict(task_sha256=task,law=law,family=pilot['family'],n=pilot['n'],D_fixed=deadline,
        execution_status='PARTIAL',holdout_generated=False,primary_engine='DES-EXT-v2.2',pilot_sha256=digest(args.pilot/'pilot/reserve-pilot.json'))
    try:
        nominal=[dict(id='reserve-M0',failures=[],resource_failures=[],work_overrides=[])]
        base,meta=evaluate(scaled,nominal,11*c0,'DIAGNOSTIC',root/'M0',['reserve-M0']);assert len(base)==1
        assert base[0]['cmax']==11*c0 and base[0]['produced_jobs']==jobs
        if args.ranking:
            ranking=json.loads(args.ranking.read_text());assert ranking['task_sha256']==task and ranking['D_fixed']==deadline
            ranking['reused_from_sha256']=digest(args.ranking)
        else:
            ranks=[]
            for machine in range(len(data['queues'])):
                probes=[dict(id=f'R-{machine}-{a}-{b}',failures=[[machine,11*r5(a*c0,100),11*(r5(a*c0,100)+max(5,r5(b*c0,100)))]],
                    resource_failures=[],work_overrides=[]) for a in (10,30,50,70,90) for b in (5,10,20)]
                result,meta=evaluate(scaled,probes,deadline,'MISSION',root/f'criticality-{machine:03d}')
                assert len(result)==15
                ranks.append(dict(machine=machine,R=sum((jobs-r['produced_jobs'])/jobs for r in result)/15,
                    U_processing=base[0]['processing_by_machine'][machine]/(11*c0),
                    U_blocked=base[0]['blocked_by_machine'][machine]/(11*c0)))
            critical=[r['machine'] for r in sorted(ranks,key=lambda r:(-r['R'],r['machine']))]
            load=[r['machine'] for r in sorted(ranks,key=lambda r:(-r['U_processing'],r['machine']))]
            random=sorted(range(len(data['queues'])),key=lambda m:(hashlib.sha256(f'v2.2|random-control|{task}|{m}'.encode()).digest(),m))[:3]
            ranking=dict(task_sha256=task,D_fixed=deadline,rows=ranks,critical_order=critical,load_order=load,random_controls=random)
        (root/'ranking.json').write_text(json.dumps(ranking,indent=2)+'\n')
        candidates=sorted(set(ranking['critical_order'][:3]+ranking['load_order'][:3]+ranking['random_controls']))
        # Reuse the first five completed pilot calibrations byte-for-byte.
        calibration=pilot['calibration_records'][:];calibration_bank=[];seeds=[]
        for index in range(100):
            row,audit=scenario(data,c0,law,'calibration',index);calibration_bank.append(scaled_scenario(row));seeds.append(audit)
        (root/'calibration-bank.json').write_text(json.dumps(calibration_bank,separators=(',',':')))
        for start in range(5,100,25):
            batch=calibration_bank[start:min(start+25,100)]
            result,meta=evaluate(scaled,batch,10*deadline,'DIAGNOSTIC',root/f'calibration-{start:03d}')
            assert len(result)==len(batch);calibration.extend(result)
        assert len(calibration)==100
        known=sorted(r['cmax'] for r in calibration if r['completion_known'])
        d_cal=r5(known[49]+known[50],2) if len(known)>=51 else None
        # Every censored value is beyond the same diagnostic horizon; proven
        # deadlock has infinite completion. Both middle order statistics are
        # known exactly when at least 51 finite completions were observed.
        if d_cal is not None:
            assert all(r['run_status']=='DEADLOCK' or r['completion_lower_bound']>=known[50] for r in calibration if not r['completion_known'])
        selection=[];bank=[]
        for index in range(100):
            row,audit=scenario(data,c0,law,'selection',index);bank.append(scaled_scenario(row));seeds.append(audit)
        (root/'selection-bank.json').write_text(json.dumps(bank,separators=(',',':')))
        for machine in [None,*candidates]:
            result=[];changed=accelerated(data,machine)
            for start in range(0,100,25):
                observed,meta=evaluate(changed,bank[start:start+25],deadline,'MISSION',root/f'selection-{machine}-{start:03d}')
                assert len(observed)==25;result.extend(observed)
            selection.append(dict(machine=machine,produced_jobs=[r['produced_jobs'] for r in result]))
        original=selection[0]['produced_jobs'];effects=[]
        for item in selection[1:]:
            effects.append(dict(machine=item['machine'],mean_gain=sum(a-b for a,b in zip(item['produced_jobs'],original))/(100*jobs)))
        selected=min(effects,key=lambda r:(-r['mean_gain'],r['machine']))['machine']
        configurations=sorted(set([selected,ranking['critical_order'][0],ranking['load_order'][0],*ranking['random_controls']]))
        candidate_bytes=json.dumps(candidates,separators=(',',':')).encode()
        manifest.update(execution_status='COMPLETE',C0=11*c0,D_cal=d_cal,
            calibration_status='RESOLVED' if d_cal is not None else 'CALIBRATION_UNRESOLVED',
            known_calibration_completions=len(known),selected=selected,candidates=candidates,
            candidates_sha256=hashlib.sha256(candidate_bytes).hexdigest(),selection_effects=effects,
            critical_control=ranking['critical_order'][0],load_control=ranking['load_order'][0],random_controls=ranking['random_controls'],
            configurations=[None,*configurations],ranking_sha256=digest(root/'ranking.json'),
            selection_bank_sha256=digest(root/'selection-bank.json'),calibration_bank_sha256=digest(root/'calibration-bank.json'),
            baseline_input_sha256=digest(args.pilot/'baseline/input.json'),
            statistics_spec_sha256=digest(Path('Sheaft_Execution_Instructions_v2_2_RU.md')),
            tick_unit='0.01/11 second',primary_metric='fraction of jobs completed by the specified deadline')
        (root/'namespace.json').write_text(json.dumps(seeds,indent=2)+'\n')
        (root/'selection-results.json').write_text(json.dumps(selection,separators=(',',':'))+'\n')
        (root/'input.json').write_bytes((args.pilot/'baseline/input.json').read_bytes())
    finally:
        (root/'selection.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print(json.dumps(manifest))


if __name__=='__main__':main()
