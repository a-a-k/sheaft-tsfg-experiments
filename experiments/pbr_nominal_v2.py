"""Large-input nominal admission without replacing any queue or assignment."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.pbr_screen_v2 import pair,sha
from experiments.pbr_cases_v2 import r5
from experiments.pbr_inputs_v2 import screen_scenarios,task_hash


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    root=args.output;root.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((args.input/'manifest.json').read_text());assert sha(args.input/'original.json')==manifest['input_sha256']
    data=json.loads((args.input/'original.json').read_text());records=[]
    summary=dict(id=manifest['id'],family=manifest['family'],n=manifest['n'],seed=manifest['seed'],source=manifest,
        processes=records,execution_status='PARTIAL',correctness_status='UNCHECKED',input_status='NOT_ADMITTED')
    empty=[dict(id='M0',failures=[],resource_failures=[],work_overrides=[])]
    try:
        original=pair(data,empty,10*r5(manifest['C0_parent']*110,100),'DIAGNOSTIC',root/'M0-original',records,'M0-original',300)
        if original is None:summary['input_status']='COMPUTATION_INCOMPLETE';return
        if not original[0]['completion_known']:
            summary.update(input_status='NO_ADMISSIBLE_INPUT',execution_status='COMPLETE',correctness_status='VALID',nominal_status=original[0]['run_status']);return
        c0=original[0]['cmax']
        for op,start in zip(data['operations'],original[0]['start']):op['planned_start']=start;op['planned_end']=start+op['work']
        frozen=pair(data,empty,c0,'DIAGNOSTIC',root/'M0-frozen',records,'M0-frozen',300)
        if frozen is None:summary['input_status']='COMPUTATION_INCOMPLETE';return
        assert original[0]['start']==frozen[0]['start'] and original[0]['finish']==frozen[0]['finish']
        (root/'input.json').write_text(json.dumps(data,separators=(',',':')))
        banks={}
        for count in (10,100):
            scenarios,bank=screen_scenarios(data,c0,'PBR',count,'pbr_large','LARGE')
            (root/f'scenarios-{count}.json').write_text(json.dumps(scenarios,separators=(',',':')))
            banks[str(count)]=bank
        witnesses=[next(s['id'] for s in json.loads((root/'scenarios-100.json').read_text()) if s['kind']==kind)
            for kind in ('machine','work','resource','separated','common')]
        summary.update(input_status='NOMINALLY_ADMISSIBLE',execution_status='COMPLETE',correctness_status='VALID',
            C0=c0,D=r5(c0*110,100),task_sha256=task_hash(data),input_sha256=sha(root/'input.json'),banks=banks,
            retained_scenario_ids=witnesses,nominal_constraints={k:frozen[0][k] for k in
                ('resource_wait_integral','blocked_machine_integral','coupling_witnesses')})
    except Exception as error:
        summary.update(correctness_status='INVALID',error=f'{type(error).__name__}: {error}');raise
    finally:
        (root/'nominal-admission.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps({k:v for k,v in summary.items() if k not in ('source','processes','banks','nominal_constraints')}))


if __name__=='__main__':main()
