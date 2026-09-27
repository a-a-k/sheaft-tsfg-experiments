"""Collect durable evidence for v2.2 without reopening any experimental bank."""
import csv
import fnmatch
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import sys
import zipfile

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.collect_evidence import api,artifacts,artifact_download
from scripts.revision_statistics_v2 import speedup_bounds,tardiness
from experiments.reserve_holdout_v2 import effect,holm32


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def read_json(path,name):
    with zipfile.ZipFile(path) as archive:return json.loads(archive.read(name))


class Collector:
    def __init__(self,root,repo):
        self.root=root;self.repo=repo;self.runs={};self.available={};self.files={};self.evidence=[]
        (root/'raw').mkdir(parents=True,exist_ok=True)

    def listing(self,run_id):
        if run_id not in self.runs:
            run=api(f'repos/{self.repo}/actions/runs/{run_id}')
            assert run['status']=='completed',f'Active source run {run_id}'
            self.runs[run_id]={key:run[key] for key in ('id','head_sha','path','conclusion','run_attempt','html_url')}
            self.available[run_id]=artifacts(self.repo,run_id)
        return self.available[run_id]

    def get(self,run_id,name):
        key=(run_id,name)
        if key in self.files:return self.files[key]
        item=next(a for a in self.listing(run_id) if a['name']==name)
        assert not item['expired']
        path=self.root/'raw'/f'{run_id}-{name}.zip'
        digest=artifact_download(self.repo,item,path)
        self.files[key]=path
        self.evidence.append(dict(run_id=run_id,name=name,artifact_id=item['id'],sha256=digest,
            size_bytes=path.stat().st_size,source_sha=self.runs[run_id]['head_sha'],path=path.relative_to(self.root).as_posix()))
        print('Preserved',run_id,name,flush=True)
        return path

    def matching(self,run_id,pattern):
        names=sorted(a['name'] for a in self.listing(run_id) if fnmatch.fnmatchcase(a['name'],pattern))
        assert names,(run_id,pattern)
        return [(name,self.get(run_id,name)) for name in names]


def pbr_evidence(collector,registry,out):
    nominal=[];points=[];gates=[]
    for size,run in registry['pbr_nominal_runs'].items():
        records=collector.matching(run,'pbr-nominal-*')
        summaries=[read_json(path,'nominal-admission.json') for name,path in records if name.startswith('pbr-nominal-admission-')]
        assert len(summaries)==6 and all(r['n']==int(size) for r in summaries)
        nominal.extend(summaries)
    all_groups=sorted(set(registry['pbr_main_runs']+registry['pbr_gate_runs']+
        [r for r in registry['pbr_pilot_runs'].values() if r]))
    for run in all_groups:
        names={a['name'] for a in collector.listing(run)}
        batch=read_json(collector.get(run,'pbr-large-measurement-gate'),'batch/measurement-manifest.json')
        gates.append(dict(run_id=run,**batch))
        if not batch['cases']:continue
        assert 'pbr-large-batch-report' in names
        rows=read_json(collector.get(run,'pbr-large-batch-report'),'pbr-points.json')
        assert len(rows)==len(batch['cases'])
        for row in rows:
            path=collector.get(run,'pbr-validated-'+row['id'])
            assert read_json(path,'validated.json')==row
            row['run_id']=run
            if row['count']==100:row['paired_time_bounds']=speedup_bounds(row['processes'])
            points.append(row)
    pilots={(r['n'],r['family'],r['seed']):r for r in points if r['count']==10}
    for row in points:
        key=(row['n'],row['family'],row['seed'])
        source=pilots.get(key)
        row['frozen_pilot_control_status']=source['control_status'] if source else 'PILOT_NOT_RUN'
        if row['count']==100:assert source and row['task_sha256']==source['task_sha256']
    areas=[]
    for size in (100000,1000000):
        for family in ('F1','F2'):
            bases=[r for r in nominal if r['n']==size and r['family']==family]
            rows=[r for r in points if r['n']==size and r['family']==family and r['count']==100]
            if size==100000 and all(r['input_status']=='NOMINALLY_ADMISSIBLE' for r in bases):
                assert len(rows)==9,'Required admitted main rounds are not finished'
            if not rows:
                decisions=[decision for gate in gates if gate['count']==100 and
                    gate['nominal_run']==registry['pbr_nominal_runs'][str(size)]
                    for decision in gate['decisions'] if decision['family']==family]
                assert decisions and all(not d['allowed'] for d in decisions),'Missing explicit main-series gate'
            assert len({(r['seed'],r['round']) for r in rows})==len(rows)
            complete=[r for r in rows if r.get('paired_speedup') is not None and r['correctness_status']=='VALID']
            round_groups=[]
            for round_id in (1,2,3):
                for cpu in sorted({r['CPU_model'] for r in rows if r['round']==round_id}):
                    group=[r for r in complete if r['round']==round_id and r['CPU_model']==cpu]
                    round_groups.append(dict(round=round_id,CPU_model=cpu,complete_pairs=len(group),
                        G=math.exp(statistics.mean(math.log(r['paired_speedup']) for r in group)) if group else None))
            full=len(complete)==9 and {(r['seed'],r['round']) for r in complete}=={(s,r) for s in (101,102,103) for r in (1,2,3)}
            g=math.exp(statistics.mean(math.log(r['paired_speedup']) for r in complete)) if full else None
            processes=[p for r in rows for p in r['processes']]
            hypothesis='INCONCLUSIVE'
            # CPU strata remain separate; an incomplete stratum is never silently pooled.
            homogeneous=full and len(round_groups)==3 and all(gp['complete_pairs']==3 for gp in round_groups)
            if homogeneous:hypothesis='SUPPORTED' if g>=2 and all(gp['G']>1 for gp in round_groups) else 'NOT_SUPPORTED'
            areas.append(dict(n=size,family=family,expected_pairs=9,expected_processes=36,
                attempted_pairs=len(rows),complete_correct_pairs=len(complete),attempted_processes=len(processes),
                not_run_processes=36-len(processes),measured_processes=sum(p['performance_status']=='MEASURED' for p in processes),
                timeouts=sum(p['performance_status']=='TIMEOUT' for p in processes),G=g,
                round_cpu_groups=round_groups,hypothesis_status=hypothesis,
                nominal_statuses={r['seed']:r['input_status'] for r in bases},
                execution_status='COMPLETE' if full else 'PARTIAL'))
    dump(out/'pbr-nominal-admissions.json',nominal);dump(out/'pbr-points.json',points)
    dump(out/'pbr-gates.json',gates);dump(out/'pbr-summary.json',areas)
    primary=[]
    for row in points:
        for process in row['processes']:
            primary.append({**{k:row.get(k) for k in ('run_id','id','n','family','seed','round','count','CPU_model','task_sha256','frozen_pilot_control_status')},
                **{k:process.get(k) for k in ('engine','label','performance_status','correctness_status','T_total_s','T_total_lower_bound_s','scenarios_completed','cpu_s')},
                'VmHWM_bytes':process.get('metadata',{}).get('VmHWM_bytes')})
    with (out/'pbr-processes.csv').open('w',newline='',encoding='utf-8') as file:
        writer=csv.DictWriter(file,fieldnames=list(primary[0]));writer.writeheader();writer.writerows(primary)
    return areas,points


def reserve_evidence(collector,registry,out):
    regions={};selections=[];tardiness_rows=[]
    for size,run in registry['reserve_pilot_runs'].items():
        assert run,'Missing size-level reserve pilot'
        for name,path in collector.matching(run,'reserve-pilot-*'):
            pilot=read_json(path,'pilot/reserve-pilot.json')
            key=(pilot['family'],pilot['n'],pilot['law']);assert key not in regions
            assert pilot['n']==int(size)
            regions[key]=dict(family=key[0],n=key[1],law=key[2],execution_status='NOT_RUN',
                reason=pilot.get('reason','REGION_GATE_REQUIRED'),pilot=pilot,statistics={})
    assert len(regions)==8
    for run in registry['reserve_region_runs']:
        names={a['name'] for a in collector.listing(run)}
        gate=read_json(collector.get(run,'reserve-region-admission'),'gate/reserve-admission.json')
        key=(gate['family'],gate['n'],gate['law']);assert key in regions
        row=regions[key];assert 'region_run' not in row,'Region must not be retried silently'
        row.update(region_run=run,gate=gate,reason=gate['reason'])
        if not gate['allowed']:continue
        assert 'reserve-frozen-selection' in names and 'reserve-holdout-evidence' in names
        selected_path=collector.get(run,'reserve-frozen-selection')
        collector.get(run,'reserve-selection-evidence')
        holdout_path=collector.get(run,'reserve-holdout-evidence')
        with zipfile.ZipFile(selected_path) as selected,zipfile.ZipFile(holdout_path) as holdout:
            selection_bytes=selected.read('selection.json');selection=json.loads(selection_bytes)
            results=json.loads(holdout.read('holdout/reserve-statistics.json'))
            assert (selection['family'],selection['n'],selection['law'])==key==(results['family'],results['n'],results['law'])
            assert hashlib.sha256(selection_bytes).hexdigest()==results['selection_sha256']
            assert selection['execution_status']=='COMPLETE' and selection['holdout_generated'] is False
            assert results['execution_status']=='COMPLETE' and results['observations']==1000
            assert hashlib.sha256(Path('Sheaft_Execution_Instructions_v2_2_RU.md').read_bytes()).hexdigest()==selection['statistics_spec_sha256']
            assert hashlib.sha256(selected.read('ranking.json')).hexdigest()==selection['ranking_sha256']
            assert hashlib.sha256(selected.read('selection-bank.json')).hexdigest()==selection['selection_bank_sha256']
            assert hashlib.sha256(selected.read('calibration-bank.json')).hexdigest()==selection['calibration_bank_sha256']
            assert hashlib.sha256(json.dumps(selection['candidates'],separators=(',',':')).encode()).hexdigest()==selection['candidates_sha256']
            assert min(selection['selection_effects'],key=lambda r:(-r['mean_gain'],r['machine']))['machine']==selection['selected']
            previous={r['seed_text'] for r in json.loads(selected.read('namespace.json'))}
            new=json.loads(holdout.read('holdout/namespace.json'))
            assert len(new)==1000 and len({r['seed_text'] for r in new})==1000
            assert not previous.intersection(r['seed_text'] for r in new),'Reused selection/calibration namespace'
            paired=json.loads(holdout.read('holdout/paired-evaluation.json'))
            assert len(paired)==1000 and len({r['scenario_id'] for r in paired})==1000
            indices=np.load(io.BytesIO(holdout.read('holdout/bootstrap-indices.npy')),allow_pickle=False)
            assert indices.shape==(10000,1000) and indices.min()>=0 and indices.max()<1000
            jobs=len(json.loads(selected.read('input.json'))['jobs'])
            for deadline,metric in [('D_fixed','Q_fixed'),('D_cal','Q_cal')]:
                if selection[deadline] is None:continue
                vectors={str(machine):np.array([r['configurations'][str(machine)][metric]/jobs for r in paired],dtype=float)
                    for machine in selection['configurations']}
                assert all(np.all((values>=0)&(values<=1)) for values in vectors.values())
                for comparison,control in [('base',None),('load',selection['load_control'])]:
                    observed=effect(vectors[str(selection['selected'])]-vectors[str(control)],indices)
                    saved=results['statistics'][deadline][comparison]
                    for field in ('mean','median','p_raw','sd','improved_fraction','worsened_fraction','unchanged_fraction'):
                        assert math.isclose(observed[field],saved[field],rel_tol=1e-10,abs_tol=1e-13),(key,deadline,comparison,field)
                    assert np.allclose(observed['ci95'],saved['ci95'],rtol=1e-10,atol=1e-13)
                for machine in selection['configurations']:
                    records=[r['configurations'][str(machine)] for r in paired]
                    tardiness_rows.append(dict(family=key[0],n=key[1],law=key[2],deadline=deadline,machine=machine,
                        **tardiness(records,selection[deadline])))
            selections.append(dict(run_id=run,**selection))
            row.update(**results,reason='COMPLETE_HOLDOUT',statistics_recomputed='MATCH',
                primary_records_sha256=hashlib.sha256(holdout.read('holdout/paired-evaluation.json')).hexdigest())
    assert all(r['reason']!='REGION_GATE_REQUIRED' for r in regions.values()),'An undecided reserve gate remains'
    hypotheses=[]
    for key,row in sorted(regions.items()):
        for deadline in ('D_fixed','D_cal'):
            stats=row['statistics'].get(deadline,{})
            complete=row['execution_status']=='COMPLETE' and stats.get('status')=='COMPLETE'
            for comparison in ('base','load'):
                values=stats.get(comparison,{}) if complete else {}
                hypotheses.append(dict(family=key[0],n=key[1],law=key[2],deadline=deadline,comparison=comparison,
                    observation_status='COMPLETE' if complete else 'INCOMPLETE',p_raw=values.get('p_raw',1.),
                    mean=values.get('mean'),ci95=values.get('ci95')))
    adjusted=holm32([h['p_raw'] for h in hypotheses])
    for row,pvalue in zip(hypotheses,adjusted):row.update(p_holm=pvalue,reject=pvalue<=.05)
    for key,row in regions.items():
        decisions={}
        for deadline in ('D_fixed','D_cal'):
            pair=[h for h in hypotheses if (h['family'],h['n'],h['law'])==key and h['deadline']==deadline]
            assert len(pair)==2
            base=next(h for h in pair if h['comparison']=='base')
            if any(h['observation_status']!='COMPLETE' for h in pair):verdict='INCONCLUSIVE'
            else:verdict='SUPPORTED' if base['mean']>=.01 and all(h['ci95'][0]>0 and h['reject'] for h in pair) else 'NOT_SUPPORTED'
            decisions[deadline]=verdict
        row['hypothesis_status']=decisions
    rows=[regions[key] for key in sorted(regions)]
    dump(out/'reserve-regions.json',rows);dump(out/'reserve-selection.json',selections)
    dump(out/'reserve-holm32.json',hypotheses);dump(out/'reserve-tardiness.json',tardiness_rows)
    with (out/'reserve-holm32.csv').open('w',newline='',encoding='utf-8') as file:
        writer=csv.DictWriter(file,fieldnames=list(hypotheses[0]));writer.writeheader();writer.writerows(hypotheses)
    return rows,hypotheses


def publication_chain(collector,registry,out):
    releases=[]
    for key in ('prior_campaign_release','e4_release','first_package_release','aps_release'):
        tag=registry[key];release=api(f'repos/{collector.repo}/releases/tags/{tag}')
        assert not release['draft']
        releases.append(dict(role=key,tag=tag,url=release['html_url'],published_at=release['published_at'],
            assets=[{k:a.get(k) for k in ('name','size','digest','browser_download_url')} for a in release['assets']]))
    for folder in ('e4','first-package','aps-first','aps-matrix'):
        source=Path('docs/results/revision-v2')/folder
        assert source.is_dir()
        shutil.copytree(source,out/'previous'/folder)
    dump(out/'previous-releases.json',releases)
    return releases


def write_report(out,areas,points,regions,hypotheses,registry,ledger):
    aps=json.loads((out/'previous/aps-matrix/execution-status.json').read_text())
    first=json.loads((out/'previous/first-package/execution-status.json').read_text())
    assert aps['execution_status']=='COMPLETE' and aps['validated_primary_processes']==60
    assert first['PBR_preliminary_inputs']==36 and first['K10_complete']==30
    admission=json.loads((out/'previous/first-package/pbr-admission.json').read_text())
    assert admission['status']=='PASS'
    assert sum(r['scenarios'] for r in admission['combined'].values())==135
    assert sum(r['mission_state_comparisons'] for r in admission['combined'].values())==405
    pf=json.loads((out/f'previous/first-package/flow-admission-{registry["flow_run"]}.json').read_text())
    assert pf['execution_status']=='COMPLETE' and len(pf['cases'])==6
    assert all(case['status']=='ADMITTED' for case in pf['cases'])
    complete_regions=[r for r in regions if r['execution_status']=='COMPLETE']
    status=dict(protocol='2.2',execution_status='PARTIAL',authorized_work_status='EXPERIMENTS_CLOSED_AT_PROTOCOL_GATES',
        publication_status='READY_FOR_PUBLICATION_AND_SEPARATE_DOWNLOAD_VERIFICATION',
        APS='COMPLETE',PBR_correctness='COMPLETE',PBR_screen='COMPLETE',
        PBR_large='PARTIAL',reserve_holdout='COMPLETE' if len(complete_regions)==8 else 'PARTIAL',
        reserve_completed_regions=len(complete_regions),reserve_expected_regions=8,
        PF='COMPLETE_DIAGNOSTICS',APS_presentation_N_seconds=aps['presentation_N_seconds'],
        correctness_scope='Exact admitted core/extended comparisons; observed large trajectory prefixes only when a process timed out',
        incomplete_obligations=[dict(series='PBR',n=a['n'],family=a['family'],
            reason=a['nominal_statuses'],missing_complete_pairs=9-a['complete_correct_pairs']) for a in areas if a['execution_status']!='COMPLETE']+
            [dict(series='reserve',n=r['n'],family=r['family'],law=r['law'],reason=r['reason']) for r in regions if r['execution_status']!='COMPLETE'])
    dump(out/'execution-status.json',status)
    text=['# Sheaft v2.2: итог исполнения и границы результатов','',
        '**Все допущенные процессы запущены, результаты и остановки сохранены. Научный статус кампании — PARTIAL:** обязательная матрица '
        'не заполнена из-за таймаутов, номинальных взаимных блокировок и опубликованных правил допуска. '
        'Успешное завершение workflow не превращает эти пропуски в положительный результат.','',
        'Предыдущая кампания и её отрицательные результаты сохранены. Новая PBR-модель имеет конечные буферы '
        'и общие ресурсы; она не заменяет прежнюю постановку с фиксированными очередями и не пересматривает старую H3.','',
        '## Повторное использование E4','',
        'Оба полных архива E4 проверены по заданным контрольным хешам и сохранены в публичном release. '
        'Выпуск пересчитан из старых produced_jobs без повторного моделирования. В F1 все конфигурации '
        'выпускают 10 000 заказов к сроку; различий нет. В F2 найдены небольшие различия количества готовых заказов '
        'при нулевом полном выполнении задания. Это разведочный пересчёт прежних контролей; старая H5 остаётся '
        'NOT_SUPPORTED. Полные сроки незавершённых заданий из прежних записей не восстанавливаются. '
        '[Таблицы и ограничения пересчёта](previous/e4/REUSE_REPORT_V2_RU.md).','',
        '## APS: построение нового плана','',
        f"Полностью выполнены 60 основных процессов: десять уникальных входов на каждом из двух размеров, три независимых повтора. "
        f"Все планы VALID. Для миллиона операций **N={aps['presentation_N_seconds']:.2f} с** — максимум медиан по десяти входам. "
        'Время включает чтение, назначение оборудования, построение очередей и полный вывод; проверка выполняется после таймера.','',
        f"[Полная APS-матрица](https://github.com/{registry['repository']}/releases/tag/{registry['aps_release']}); "
        '[качество, память и все повторы](previous/aps-matrix/APS_MATRIX_REPORT_RU.md). '
        'SHEAFT-LIST-v1 — конструктивная эвристика планирования. Этот результат не является временем исполнения TSFG.','',
        f"Отношение опубликованных 2700 с BFG к измеренному N равно **{aps['ratio_of_published_vendor_time_to_measured_N']:.2f}**. "
        'Это отношение двух показателей при разных условиях, а не очное сравнение на общем входе. '
        '[Показатель поставщика](https://bfg.ai/bfg-aps/); [измерение и рыночная гипотеза](APS_MARKET_COMPARISON_RU.md).','',
        '## Точность расширенного исполнения','',
        'Сохранено оригинальное ядро S1; публичный адаптер TSFG и независимый DES-EXT реализуют PBR-EXACT-v2.2. '
        'Рациональный эталон, ручные случаи порядка переходов и блокировок, затронутая регрессия, '
        '135 сочетаний Mk01 и 405 состояний к сроку прошли проверку. '
        'Обработаны все 36 предварительных входов: 30 полных K=10; шесть F2/10k/PB/PBR блокируются уже в M0. '
        'Сильный контроль совместного действия ограничений найден лишь один; слабые контроли не исключались.','',
        'Полные исходные очереди сохранены. Последовательный план использовался только там, где это заранее разрешено '
        'для Mk01; неисполняемый большой вход не заменялся удобным для измерения.','',
        '## Большие парные процессы PBR','',
        '| Размер | Семейство | Запущено / ожидается процессов | Завершено по времени | Таймауты | Полных корректных пар / 9 | Вывод |',
        '|---:|---|---:|---:|---:|---:|---|']
    for a in areas:
        text.append(f"| {a['n']} | {a['family']} | {a['attempted_processes']} / 36 | {a['measured_processes']} | {a['timeouts']} | {a['complete_correct_pairs']} / 9 | {a['hypothesis_status']} |")
    text.extend(['','Отдельный процесс имеет K=100 и предел 300 с. Порядок BAAB/ABBA задан до измерений; '
        'A=TSFG, B=DES. Все четыре процесса пары выполняются последовательно на одной VM. '
        'Раунд и модель CPU сохранены. Число завершённых по времени процессов не означает полного междвижкового '
        'сопоставления: при таймауте второго движка сравниваются только общие целые траектории.','',
        '| Вход | Раунд / CPU | DES, с | TSFG, с | Проверено общих сценариев | S или граница |',
        '|---|---|---|---|---:|---|'])
    for row in points:
        if row['count']!=100:continue
        def times(engine):
            return ', '.join(f"{p['T_total_s']:.3f}" if p['performance_status']=='MEASURED' else
                f">{p['T_total_lower_bound_s']} (TIMEOUT)" if p['performance_status']=='TIMEOUT' else p['performance_status']
                for p in row['processes'] if p['engine']==engine)
        bound=row['paired_time_bounds'];speed=row.get('paired_speedup')
        formatted=f'{speed:.6f}' if speed is not None else (f"S < {bound['upper']:.6f}, условная граница" if bound['status']=='CENSORED_BOUND' and bound['upper'] is not None else 'неизвестно')
        text.append(f"| {row['id']} | {row['round']} / {row['CPU_model']} | {times('des')} | {times('tsfg')} | {row['compared_scenarios']} | {formatted} |")
    text.extend(['','[Все первичные измерения](pbr-processes.csv), [допуски](pbr-gates.json), '
        '[номинальные состояния](pbr-nominal-admissions.json), [все парные точки и их хеши](pbr-points.json). '
        'Время TIMEOUT хранится как null с нижней границей 300 с. Условные границы S не участвуют в принятии гипотезы. '
        'Если нет всех девяти корректных завершённых пар, G не вычисляется.','',
        'Полный обход всех операций на каждой границе устранён, но этот вариант S1 по-прежнему проходит '
        'фиксированную временную сетку Δ=0,05 с. Его стоимость зависит также от моделируемого горизонта; '
        'DES обрабатывает события. Потоковая агрегация Ozon и точное индивидуальное исполнение — разные '
        'вычислительные представления. Результат Ozon не доказывает ускорение этого пооперационного варианта.','',
        'Миллионный K=10 не был открыт: у F1 два из трёх исходных seed не завершили номинальный TSFG за 300 с; '
        'у F2 все три исходных плана дали DEADLOCK. Поэтому миллионный K=100 закрыт по номинальному допуску. '
        'Это не измеренный провал порога 25 с на миллионном K=10. '
        'K=10 на 100 тысячах — отдельный банк и не заменяет миллионную предварительную серию.','',
        'Класс контроля зафиксирован по предварительным данным и публикуется в frozen_pilot_control_status. '
        'Допущенные большие F1 являются слабыми контролями: прослеженной связи между ожиданием ресурса '
        'и удержанием станка не найдено. Поэтому преимущество именно при сильном совместном действии '
        'ограничений на большом масштабе остаётся непроверенным. '
        'Семантически одинаковые F1/DENSE с разными seed не являются тремя различными задачами; '
        'равные task_sha256 раскрывают это ограничение.','',
        '## Усиления: независимая проверка рекомендаций','',
        f'Полные оценочные банки: {len(complete_regions)} из 8 областей, по 1000 новых сценариев. '
        'Сначала сохранены ранжирование, 100 калибровочных и 100 выборочных сценариев, выбранное усиление и хеши. '
        'Оценочный банк открыт в следующем job. Исполнение DES-EXT проверяет физические инварианты каждой траектории; '
        'сама модель предварительно сопоставлена с S1 и рациональным эталоном. '
        'Эти 1000 сценариев не объявляются отдельной серией TSFG/DES на скорость.','',
        '| Область | Статус | Причина / D_fixed | D_cal |', '|---|---|---|---|'])
    for r in regions:
        text.append(f"| {r['family']} / {r['n']} / {r['law']} | {r['execution_status']} | {r['hypothesis_status']['D_fixed']} ({r['reason']}) | {r['hypothesis_status']['D_cal']} |")
    text.extend(['','| Область / срок | Средний прирост к базе | 95% CI к базе | Средний прирост к загрузке | 95% CI к загрузке | p Холма: база / загрузка |',
        '|---|---:|---|---:|---|---|'])
    for r in complete_regions:
        for deadline in ('D_fixed','D_cal'):
            st=r['statistics'].get(deadline,{})
            if st.get('status')!='COMPLETE':continue
            hs=[h for h in hypotheses if (h['family'],h['n'],h['law'],h['deadline'])==(r['family'],r['n'],r['law'],deadline)]
            p_text=' / '.join(format(h['p_holm'],'.6g') for h in hs)
            text.append(f"| {r['family']} / {r['n']} / {r['law']} / {deadline} | {st['base']['mean']:.8f} | {st['base']['ci95']} | {st['load']['mean']:.8f} | {st['load']['ci95']} | {p_text} |")
    text.extend(['','Прирост выражен долей заказов, а не процентными пунктами. Общая семья Холма содержит ровно 32 проверки; '
        'недоступные области и сроки получили p=1. Порог полезности: прирост к базе ≥0,01, обе нижние границы CI >0 '
        'и обе скорректированные проверки значимы. Сводчик повторно пересчитал эффекты и интервалы из парных записей '
        'с сохранёнными bootstrap-индексами; совпадение проверено.','',
        '[Выбор усилений](reserve-selection.json), [все 32 проверки](reserve-holm32.csv), '
        '[области, доли улучшений и полное выполнение](reserve-regions.json), [дополнительное опоздание](reserve-tardiness.json). '
        'Полное среднее/медиана/p95 опоздания задания вычисляются лишь при известных сроках всех 1000 сценариев; '
        'иначе остаются null с числом неизвестных и нижними границами. Горизонт остановки не подставляется вместо срока.','',
        'Выбор по D_fixed при одинаковом выпуске всех кандидатов разрешает равенство минимальным machine_id. '
        'В таком случае метод выбора не использует заметную разницу эффектов; результаты при D_cal не дают права '
        'сменить выбранный станок задним числом. Контроли по критичности и случайному выбору сохранены как вторичные сравнения.','',
        '## Потоковая агрегация и продукт','',
        'Все шесть заранее заданных непрерывных диагностик PF прошли пороги точности после исправления фактического '
        'шага S1. Первый ошибочный запуск (фактические 0,1 с вместо 0,005 с) сохранён отдельно. '
        'Исправление использует масштаб времени ×32 и проверяет фактический шаг; ядро S1 не менялось. '
        'Новые случайные PF-сценарии не запускались: вероятность ложного успеха NOT_ESTIMABLE, ускорение не измерялось.','',
        'Практическое разделение продукта: LIST строит APS-BASIC-план; DAG быстро проверяет готовые фиксированные '
        'очереди при неограниченных буферах; DES проверяет исполнение с конечными буферами и общими ресурсами. '
        'TSFG с агрегацией имеет отдельную область допустимости для совместимых непрерывных потоков. '
        'Индивидуальный TSFG-адаптер не получает вычислительного преимущества только от добавления операций. '
        'План LIST, допустимый в APS-BASIC, может блокироваться после добавления PBR-ограничений — это выявленный '
        'предел продукта, требующий отдельного построения/исправления плана с такими ограничениями.','',
        '## Сохранность и бюджет','',
        '[Реестр источников](evidence.json) связывает каждый архив с run, commit, artifact ID и SHA-256. '
        'Новые исходные ZIP сохранены в долговременном release; прежние кампании связаны через '
        '[реестр опубликованных архивов](previous-releases.json). Сохранены все наблюдения по заказам, '
        'сигнатуры полных состояний, заранее выбранные полные трассы и непрошедшие допуски. '
        'Полные промежуточные выводы остальных больших PBR-траекторий остаются Actions-артефактами с ограниченным '
        'сроком хранения; долговременный набор содержит требуемые показатели и проверочные трассы.','',
        'Все вычисления, сборки, проверки и сборка этого отчёта выполнены в GitHub Actions. '
        'Ни таймаут, ни OOM не повторялись автоматически. Технические неудачи и первоначальное отклонение '
        'учёта старого CI отражены в реестре бюджета. Лимиты между пакетами не переносились.','',
        '| Пакет | Фактически до итоговой публикации, ч | Лимит, ч |', '|---|---:|---:|'])
    for name,limit in ledger['packages'].items():text.append(f"| {name} | {ledger['actual_seconds'][name]/3600:.3f} | {limit/3600:g} |")
    text.extend(['',f"На текущую итоговую сборку и независимую проверку скачивания зарезервировано {ledger['reservation_seconds']/3600:.3f} ч. "
        'Таблица отражает завершённые предыдущие jobs, включая неудачные попытки; текущая публикация не выдается '
        'за уже завершённое время. Полные записи — budget-ledger.jsonl и budget-v2.json.','',
        'Дальнейшие обязательные наблюдения, не полученные в разрешённых лимитах, перечислены в execution-status.json. '
        'Повторная кампания потребует новой спецификации входов/лимитов; текущие пробелы не заменены пилотами.'])
    (out/'FINAL_REPORT_RU.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    shutil.copy2(out/'previous/aps-matrix/APS_MARKET_COMPARISON_RU.md',out/'APS_MARKET_COMPARISON_RU.md')
    shutil.copy2(out/'previous/aps-matrix/APS_MATRIX_REPORT_RU.md',out/'APS_MATRIX_REPORT_RU.md')
    return status


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    registry=json.loads(Path('provenance/revision-v2.json').read_text())
    assert registry['experiments_closed'],'Required experimental work remains'
    root=Path('final-package');out=root/'report';out.mkdir(parents=True,exist_ok=True)
    collector=Collector(root,registry['repository'])
    publication_chain(collector,registry,out)
    areas,points=pbr_evidence(collector,registry,out)
    regions,hypotheses=reserve_evidence(collector,registry,out)
    ledger=json.loads(Path('artifacts/budget/budget-v2.json').read_text())
    assert not ledger['active_other_jobs'],'Final package cannot close while experiments remain active'
    assert all(ledger['actual_seconds'][key]<=limit for key,limit in ledger['packages'].items())
    assert sum(ledger['actual_seconds'].values())+ledger['reservation_seconds']<=ledger['total_runner_seconds']
    shutil.copy2('artifacts/budget/budget-v2.json',out/'budget-v2.json')
    shutil.copy2('artifacts/budget/budget-ledger.jsonl',out/'budget-ledger.jsonl')
    shutil.copy2('artifacts/stats-environment/versions.json',out/'report-statistics-environment.json')
    entries=[json.loads(line) for line in (out/'budget-ledger.jsonl').read_text().splitlines()]
    dump(out/'failed-jobs.json',[row for row in entries if row['kind']=='ACTUAL' and row['conclusion'] not in ('success','skipped')])
    status=write_report(out,areas,points,regions,hypotheses,registry,ledger)
    dump(out/'evidence.json',collector.evidence);dump(out/'source-runs.json',collector.runs)
    dump(out/'revision-v2.json',registry)
    public_code={p.as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('scripts','experiments','validation','engines','references','planning')
        for p in sorted(Path(folder).rglob('*')) if p.is_file() and p.suffix in ('.py','.cpp','.go','.h','.hpp')}
    dump(out/'report-source.json',dict(source_sha=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],
        python=sys.version,platform=platform.platform(),public_code=public_code))
    files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}
    dump(root/'SHA256.json',files)
    print(json.dumps(status,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
