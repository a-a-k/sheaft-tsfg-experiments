"""Six fixed diagnostic fluid cases, independent Fraction oracle and S1."""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from references.fluid_ref_v2 import solve


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    root=Path('artifacts/pf');root.mkdir(parents=True,exist_ok=True)
    rows=[]
    for kind in ('serial','merge'):
        for regime in ('healthy','capacity','deadline'):
            limited=regime=='capacity'
            case=dict(id=kind+'-'+regime,volumes=[100] if kind=='serial' else [40,60],
                rates=[10] if kind=='serial' else [6,9],capacity=None if kind=='serial' else 5,
                sink_rate=4 if limited else 8 if kind=='serial' else 10,
                sink_down=[[3,5]] if limited else [],
                deadline=40 if limited else (12.5 if kind=='serial' else 10) if regime=='deadline' else 20)
            folder=root/case['id'];folder.mkdir(exist_ok=True)
            input_file=folder/'input.json';input_file.write_text(json.dumps(case,indent=2)+'\n')
            diagnostic=solve(case,100)
            assert diagnostic['cmax']==(27 if limited else 12.5 if kind=='serial' else 10)
            result=[]
            for label,horizon in [('diagnostic',100),('D-minus',case['deadline']-.05),('D',case['deadline']),('D-plus',case['deadline']+.05)]:
                ref=solve(case,horizon)
                out=folder/(label+'-s1.json')
                subprocess.run(['.private/runtime/tsfg-pf',str(input_file),str(horizon),str(out)],
                    env={**os.environ,'TSFG_PF_DRIVER':'true','TSFG_OP_DRIVER':'false','GOMAXPROCS':'1'},check=True,timeout=60)
                s1=json.loads(out.read_text())
                (folder/(label+'-reference.json')).write_text(json.dumps(ref,indent=2)+'\n')
                errors=dict(produced_abs=abs(s1['produced']-ref['produced']),
                    wip_integral_relative=abs(s1['wip_integral']-ref['wip_integral'])/max(1e-15,ref['wip_integral']),
                    cmax_abs=abs(s1['cmax']-ref['cmax']) if s1['cmax'] is not None and ref['cmax'] is not None else None,
                    queue_at_D_abs=[abs(a-b) for a,b in zip(s1['queue_at_D'],ref['queue_at_D'])],
                    queue_max_abs=[abs(a-b) for a,b in zip(s1['queue_max'],ref['queue_max'])])
                tolerances=[max(1,.05*v) for v in ref['queue_max']]
                if case['capacity'] is not None:tolerances[-1]=.05*case['capacity']
                balance=abs(s1['produced']+sum(s1['queue_at_D'])-sum(case['volumes']))
                physical=balance<=1e-7 and s1['material_balance_max_abs']<=1e-7 and min(s1['queue_at_D'])>=-1e-8
                if case['capacity'] is not None:physical &= s1['queue_max'][-1]<=case['capacity']+1e-8
                false_success=s1['mission_success'] and not ref['mission_success']
                accurate=(errors['produced_abs']<=1 and errors['wip_integral_relative']<=.05 and
                    (errors['cmax_abs'] is None or errors['cmax_abs']<=.01*diagnostic['cmax']) and
                    all(e<=tol+1e-8 for metric in ('queue_at_D_abs','queue_max_abs') for e,tol in zip(errors[metric],tolerances)) and
                    not false_success)
                result.append(dict(label=label,horizon=horizon,errors=errors,queue_tolerances=tolerances,
                    physical_valid=physical,accuracy_pass=accurate,false_success=false_success,
                    false_failure=ref['mission_success'] and not s1['mission_success']))
            status='ADMITTED' if all(r['physical_valid'] and r['accuracy_pass'] for r in result) else 'NOT_ADMITTED'
            rows.append(dict(id=case['id'],status=status,observations=result))
    summary=dict(execution_status='COMPLETE',cases=rows,expected_cases=6,
        correctness_status='VALID' if all(r['physical_valid'] for c in rows for r in c['observations']) else 'INVALID',
        approximation_status='ADMITTED' if all(c['status']=='ADMITTED' for c in rows) else 'RESTRICTED',
        false_successes=sum(r['false_success'] for c in rows for r in c['observations']),
        random_scenarios=0,false_success_probability_bound='NOT_ESTIMABLE',
        speed_hypothesis='NOT_APPLICABLE',individual_operation_times='UNSUPPORTED',
        scope='Six deterministic continuous homogeneous fluid cases; no discrete manufacturing equivalence claim')
    (root/'flow-admission.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='cases'}))
    assert summary['correctness_status']=='VALID'


if __name__=='__main__':main()
