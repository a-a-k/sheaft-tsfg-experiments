"""Correctness campaign and descriptive report. Not an H3 timing experiment."""
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from validation.core import NATIVE_ENGINES, run_native
from validation.checks import calendars, compare, project, service, validate_dataset, validate_result
from references.simpy_ref import simulate
from validation.schema import validate as validate_schema


def write_csv(path, rows):
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def metrics(data,sc,row,h):
    ready=[max(o['release'],max((row['finish'][p] for p in o['predecessors']),default=0))
           for o in data['operations']]
    down=calendars(data,sc)
    snapshot=project(data,sc,row,h)
    integral=[0]*len(data['queues']);at_h=[0]*len(integral);peaks=[0]*len(integral)
    events={0,h}
    events.update(t for t in ready+row['start'] if 0<=t<=h)
    for o in data['operations']:
        i=o['id'];m=o['machine'];s=row['start'][i]
        integral[m]+=max(0,min(h,s)-ready[i])
        at_h[m]+=ready[i]<=h<s
    for t in sorted(events):
        values=[0]*len(integral)
        for o in data['operations']:
            i=o['id'];values[o['machine']]+=ready[i]<=t<row['start'][i]
        peaks=[max(a,b) for a,b in zip(peaks,values)]
    busy=[0]*len(integral)
    for o in data['operations']:
        i=o['id'];s=row['start'][i];c=row['finish'][i];m=o['machine']
        if s<h: busy[m]+=service(s,min(h,c),down[m])
    unavailable=[sum(max(0,min(h,b)-a) for a,b in items if a<h) for items in down]
    idle=[h-a-b for a,b in zip(busy,unavailable)]
    assert all(v>=0 for v in idle)
    wip_integral=sum(max(0,min(h,row['job_finish'][j['id']])-j['release']) for j in data['jobs'])
    wip=sum(j['release']<=h<row['job_finish'][j['id']] for j in data['jobs'])
    return dict(produced_jobs=sum(c is not None for c in snapshot['job_finish']),
                incomplete_operations=sum(c is None for c in snapshot['finish']),
                queue_at_D=at_h,queue_integral_ticks=integral,queue_max=peaks,
                wip_at_D=wip,wip_integral_ticks=wip_integral,
                machine_busy_ticks=busy,machine_down_ticks=unavailable,machine_idle_ticks=idle)


def causes(data,sc,row,base):
    previous={b:a for q in data['queues'] for a,b in zip(q,q[1:])}
    down=calendars(data,sc)
    result=[]
    for o in data['operations']:
        i=o['id'];s=row['start'][i];c=row['finish'][i]
        if c<=base['finish'][i]: continue
        reasons=[]
        technological=max([o['release']]+[row['finish'][p] for p in o['predecessors']])
        prev=previous.get(i)
        queue_ready=row['finish'][prev] if prev is not None else 0
        ready=max(o['planned_start'],technological,queue_ready)
        if s>ready: reasons.append(dict(kind='machine_unavailable_before_start',ticks=s-ready))
        for p in o['predecessors']:
            if row['finish'][p]>o['planned_start'] and row['finish'][p]==technological:
                reasons.append(dict(kind='technological_predecessor',operation=p))
        if prev is not None and queue_ready>max(o['planned_start'],technological):
            reasons.append(dict(kind='machine_queue_predecessor',operation=prev))
        if o['planned_start']>=max(technological,queue_ready): reasons.append(dict(kind='planned_start_floor'))
        interruption=c-s-service(s,c,down[o['machine']])
        if interruption: reasons.append(dict(kind='failure_during_processing',ticks=interruption,machine=o['machine']))
        result.append(dict(operation=i,job=o['job'],machine=o['machine'],start=s,finish=c,
                           finish_delay=c-base['finish'][i],reasons=reasons))
    return dict(scenario=sc['id'],cmax=row['cmax'],baseline_cmax=base['cmax'],delayed_operations=result)


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true': raise SystemExit('Actions only')
    root=Path('artifacts/mk01');inp=root/'input';traces=root/'traces';traces.mkdir(exist_ok=True)
    data=json.loads((inp/'dataset.json').read_text())
    scenarios=json.loads((inp/'scenarios.json').read_text())
    manifest=json.loads((inp/'manifest.json').read_text())
    hashes=json.loads((inp/'sha256.json').read_text())
    assert all(hashlib.sha256((inp/name).read_bytes()).hexdigest()==digest for name,digest in hashes.items())
    assert json.loads(Path('artifacts/e0/summary.json').read_text())['status']=='PASS'
    validate_dataset(data)
    h=manifest['diagnostic_horizon'];deadlines=manifest['deadlines'];C0=data['C0']
    summary=dict(status='RUNNING',trajectories_per_engine=481,deadline_checks_per_engine=1443,
                 operations=55,engines={},H3='NOT_EVALUATED',source_reuse='S1 unchanged Go kernel + operation adapter')
    try:
        results={}
        for engine in NATIVE_ENGINES:
            results[engine]=run_native(engine,data,scenarios,h,'DIAGNOSTIC',traces,'mk01')
        results['simpy']=[simulate(data,s,h,'DIAGNOSTIC') for s in scenarios]
        (traces/'mk01-simpy.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in results['simpy']))
        reference=results['dag'];flat=[];outcomes=[];snapshots=[]
        for engine,rows in results.items():
            assert len(rows)==481
            false_success=false_failure=mismatches=0
            for sc,ref,row in zip(scenarios,reference,rows):
                assert row['scenario_id']==sc['id'] and row['completion_known']
                validate_schema('result',row)
                validate_result(data,sc,row)
                mismatches+=sum(a!=b for key in ('start','finish') for a,b in zip(row[key],ref[key]))
                compare(ref,row)
                flat.append(dict(engine=engine,scenario=sc['id'],family=sc['family'],cmax_ticks=row['cmax'],
                                 delay_ticks=row['cmax']-C0))
                for d in deadlines:
                    projected=project(data,sc,row,d)
                    validate_result(data,sc,projected)
                    expected=ref['cmax']<=d;actual=projected['mission_success']
                    false_success+=actual and not expected;false_failure+=expected and not actual
                    outcomes.append(dict(engine=engine,scenario=sc['id'],D_ticks=d,success=actual,
                                         expected_success=expected))
                    full=metrics(data,sc,row,d)
                    snapshots.append(dict(engine=engine,scenario=sc['id'],D=d,**full))
            summary['engines'][engine]=dict(status='PASS',operation_time_mismatches=mismatches,
                false_success=false_success,false_failure=false_failure,complete_trajectories=len(rows),
                classifications=len(rows)*len(deadlines),operation_time_comparisons=len(rows)*55*2)
            assert false_success==false_failure==mismatches==0
        for engine,rows in results.items():
            assert rows[0]['start']==[o['planned_start'] for o in data['operations']],engine
            assert rows[0]['finish']==[o['planned_end'] for o in data['operations']],engine
        write_csv(root/'trajectories.csv',flat)
        write_csv(root/'mission_outcomes.csv',outcomes)
        (root/'mission_metrics.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in snapshots))
        lookup={s['id']:r for s,r in zip(scenarios,reference)}
        ranking=[]
        for m in range(6):
            selected=[lookup[s['id']]['cmax'] for s in scenarios if s['family']=='M1' and s['machines']==[m]]
            assert len(selected)==15
            ranking.append(dict(machine=m,delay_sum_ticks=sum(c-C0 for c in selected),
                                R=sum(c-C0 for c in selected)/(15*C0),F=sum(c>deadlines[1] for c in selected)))
        ranking.sort(key=lambda r:(-r['delay_sum_ticks'],-r['F'],r['machine']))
        top=[r['machine'] for r in ranking[:3]]
        controls=[r['machine'] for r in sorted(ranking[3:],key=lambda r:(r['delay_sum_ticks'],r['F'],r['machine']))]
        summary['critical_resources']=top;summary['control_resources']=controls
        write_csv(root/'resource_ranking.csv',ranking)
        pairs=[]
        for sc in scenarios:
            if sc['family']!='M2':continue
            a,b=sc['machines'];suffix=f"-a{sc['a']}-b{sc['b']}"
            ca=lookup[f'M1-{a}'+suffix]['cmax'];cb=lookup[f'M1-{b}'+suffix]['cmax'];cab=lookup[sc['id']]['cmax']
            for d in deadlines:
                pairs.append(dict(scenario=sc['id'],machine_a=a,machine_b=b,D=d,C_a=ca,C_b=cb,C_pair=cab,
                                  interaction_ticks=cab-ca-cb+C0,emergent_miss=ca<=d and cb<=d and cab>d))
        write_csv(root/'pair_interactions.csv',pairs)
        summary['emergent_pair_misses']=sum(p['emergent_miss'] for p in pairs)
        worst=max((s for s in scenarios if s['family']=='M1'),key=lambda s:(lookup[s['id']]['cmax'],s['id']))
        cascade=causes(data,worst,lookup[worst['id']],reference[0])
        (root/'cascade.json').write_text(json.dumps(cascade,indent=2)+'\n')
        fig,axes=plt.subplots(1,2,figsize=(12,4))
        axes[0].plot(range(481),[r['cmax']/100 for r in reference],'.',markersize=3)
        for d in deadlines:axes[0].axhline(d/100,linestyle='--',linewidth=.8,label=f'D={d/100:g}')
        axes[0].set(xlabel='Scenario index (M0, M1, M2, M3)',ylabel='Completion, original time units')
        axes[0].legend()
        axes[1].bar([str(r['machine']) for r in ranking],[r['R'] for r in ranking])
        axes[1].set(xlabel='Machine ID (ranked)',ylabel='Mean normalized delay in 15 single failures')
        fig.tight_layout();fig.savefig(root/'completion_and_resources.png',dpi=170);plt.close(fig)
        fig,ax=plt.subplots(figsize=(11,5))
        row=lookup[worst['id']]
        for o in data['operations']:
            i=o['id'];m=o['machine']
            ax.broken_barh([(row['start'][i]/100,(row['finish'][i]-row['start'][i])/100)],(m-.35,.7),
                          facecolors=plt.colormaps['tab10'](o['job']))
        for m,a,b in worst['failures']:
            ax.broken_barh([(a/100,(b-a)/100)],(m-.45,.9),facecolors='none',edgecolors='black',hatch='////')
        ax.set(xlabel='Time (operation spans include interruptions)',ylabel='Machine',yticks=range(6),title=worst['id'])
        fig.tight_layout();fig.savefig(root/'cascade.png',dpi=170);plt.close(fig)
        summary['status']='PASS'
        summary['run_url']=f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        table='\n'.join(f"| {e} | {v['complete_trajectories']} | {v['classifications']} | {v['operation_time_mismatches']} | {v['false_success']} / {v['false_failure']} |" for e,v in summary['engines'].items())
        report=f'''# Mk01: проверка исполнения фиксированного плана

Результат: **PASS**. [GitHub Actions]({summary['run_url']}). Commit `{os.environ['GITHUB_SHA']}`.

Основной TSFG использует неизменённое Go-ядро S1, commit
`8510baf28673758f1e437d2dbc5a51ead9843a3b`, с новым адаптером фиксированных операций.
Самостоятельный C++ `grid` — вспомогательный контроль. Исходник S1 и его бинарник
не опубликованы; для воспроизведения участника `tsfg` нужен доступ к закрытому репозиторию.

CP-SAT: **{manifest['status']}**, C0={C0/100:g}, нижняя граница
{manifest['best_bound_original_units']:g}; один поток, seed 20260926, лимит 120 с.
Одно расписание зафиксировано до всех сценариев. Δ=0,05; время хранится в целых ticks по 0,01.
Предел DIAGNOSTIC={h/100:g}. Неизвестных полных сроков нет.

| Участник | Полные траектории | Проверки трёх сроков | Расхождения времён | Ложный успех / срыв |
|---|---:|---:|---:|---:|
{table}

Для каждого участника проверены 52 910 значений начала/окончания операций, баланс работы,
очерёдность станков, технологические зависимости, поступления и интервалы недоступности.
MISSION-проверки границ и цензурирование отдельно покрыты E0. В Mk01 исходы и FULL-метрики
получены проекцией одной полной траектории на каждый из трёх сроков; это не замер MISSION.
FULL-постпроцессор общий; его стоимость не используется для утверждений об ускорении.

![Сроки и ранжирование](completion_and_resources.png)

Критические станки: {top}; контрольные: {controls}. Ранжирование использует только
15 одинаковых одиночных отказов на станок, R, затем F при D=1,10C0, затем ID.
Оценка резервов и H5 в этот результат не входят.
Случаев, когда оба одиночных воздействия проходят срок, а пара его нарушает:
{summary['emergent_pair_misses']} (с учётом трёх сроков). Все 225 пар и взаимодействия
I=C(A,B)−C(A)−C(B)+C0 сохранены в `pair_interactions.csv`.

Разбор каскада: `{worst['id']}`, C={cascade['cmax']/100:g} против C0={C0/100:g}.
Непосредственные зависимости задержанных операций сохранены в `cascade.json`.
Это вмешательства в данную модель, не доказательство причинности для реального производства.

![Каскад](cascade.png)

Артефакты: `input/` содержит зафиксированные входы и SHA-256; `traces/` — полные времена
всех операций; `trajectories.csv`, `mission_outcomes.csv`, `mission_metrics.jsonl` — результаты;
`../build/` — окружение и происхождение сборок, `../e0/summary.json` — допуск E0.

**H3 не оценивалась.** Корректность на Mk01 не доказывает преимущества TSFG по времени или
памяти. E2–E4 и крупные серии требуют отдельного запуска по протоколу.
'''
        (root/'REPORT_RU.md').write_text(report,encoding='utf-8')
    except Exception as exc:
        summary['status']='FAIL';summary['error']=str(exc);raise
    finally:
        (root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
