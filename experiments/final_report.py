"""Build the research deliverable from completed Actions evidence, never locally."""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import textwrap

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np


def read(path):return json.loads(path.read_text())
def read_rows(path):
    rows={}
    with path.open() as source:
        for line in source:
            if not line.endswith('\n'):break
            row=json.loads(line);rows[row['scenario_id']]=row
    return rows
def num(value):return '—' if value is None else f'{value:.3g}'
def max_known(values):return max((v for v in values if v is not None),default=None)
def table(headers,rows):
    return ['| '+' | '.join(headers)+' |','|'+'|'.join('---' for _ in headers)+'|',
            *['| '+' | '.join(map(str,row))+' |' for row in rows],'']
def records(root):
    return [dict(read(p),evidence_path=str(p)) for p in sorted(root.glob('**/measurements/*/measurement.json'))]
def write_csv(path,rows,fields):
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)


def timeout_bounds(rows):
    result=[]
    for dataset,label in sorted({(r['dataset_id'],r['label']) for r in rows}):
        group=[r for r in rows if (r['dataset_id'],r['label'])==(dataset,label)]
        a=[r for r in group if r['engine']=='tsfg']
        for reference in ('des','dag'):
            b=[r for r in group if r['engine']==reference]
            if len(a)!=2 or len(b)!=2:continue
            if any(r['status'] not in ('OK','TIMEOUT') for r in a+b):continue
            if any(r['status']=='OK' and not r['completion_validated'] for r in a+b):continue
            if len({r['input_sha256'] for r in a+b})!=1 or len({r['scenarios_sha256'] for r in a+b})!=1:continue
            ta,tb=any(r['status']=='TIMEOUT' for r in a),any(r['status']=='TIMEOUT' for r in b)
            if ta==tb:continue  # All complete, or both sides censored: no one-sided bound here.
            times=[r['T_total_s'] if r['status']=='OK' else r['T_total_lower_bound_s'] for r in b+a]
            bound=math.sqrt(times[0]*times[1]/times[2]/times[3])
            result.append(dict(dataset_id=dataset,label=label,reference=reference,
                direction='UPPER' if ta else 'LOWER',S_total_bound=bound,
                eligible_for_H3=False,scope='Process completion time only; censored final correctness is unknown'))
    return result


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
    parser=argparse.ArgumentParser()
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--preview',action='store_true',help='Explicitly incomplete publication, never a completed campaign')
    args=parser.parse_args();root=args.evidence;out=args.output;out.mkdir(parents=True,exist_ok=True)
    screen=read(root/'screen/summary.json');main_result=read(root/'main/summary.json')
    main_rows=records(root/'main-points');extra_rows=records(root/'extras')
    for row in main_rows+extra_rows:
        meta=row.get('engine_meta',{})
        row['T_batch_s']=meta.get('T_batch_with_output_s')
        progress=meta.get('prefix_batch_s',row.get('last_progress',{}).get('prefix_batch_s',{}))
        row['prefix_K100_batch_s']=progress.get('100')
    environments=[dict(read(p),evidence_path=str(p)) for p in sorted((root/'main-environment').glob('*/build/environment.json'))]
    assert len(environments)==72 or args.preview
    assert {r['commit'] for r in main_rows}=={'afb7081898506524e3591af4e727461fc46efa2d'}
    for dataset in {r['dataset_id'] for r in main_rows}:
        points=[r for r in main_rows if r['dataset_id']==dataset]
        assert len({r['input_sha256'] for r in points})==1
        assert len({r['scenarios_sha256'] for r in points})==1
    e3=[read(p) for p in sorted((root/'e3').glob('*/summary.json'))]
    e4=[read(p) for p in sorted((root/'e4').glob('*/summary.json'))]
    ranking=[read(p) for p in sorted((root/'ranking').glob('*/g2-ranking/summary.json'))]
    extended=read(root/'core/e1x/summary.json')
    gate=read(root/'core/e3-gate/summary.json')
    audit=read(root/'audit/audit/ozon-reproduction-check.json')
    numeric=read(root/'numeric/g2-numeric/summary.json') if (root/'numeric/g2-numeric/summary.json').exists() else None
    memory_probe=read(root/'memory/summary.json') if (root/'memory/summary.json').exists() else None
    witnesses=[read(p) for p in sorted((root/'witness').glob('*/witness/summary.json'))]
    diagnostics=read(out/'input-diagnostics.json')
    assert len(witnesses)==4 and all(w['status']=='PASS' for w in witnesses)
    assert len(diagnostics)==48
    runs=read(root/'runs.json')
    expected=dict(screen_processes=144,main_processes=432,e3_datasets=48,e4_families=2,extra_processes=171)
    actual=dict(screen_processes=screen['records'],main_processes=len(main_rows),e3_datasets=len(e3),
                e4_families=len(e4),extra_processes=len(extra_rows))
    all_present=actual==expected
    assert screen['datasets_present']==48 and not screen['missing_datasets']
    assert all(v['status'].startswith('PASS') for v in e3)
    assert extended['status']==gate['status']==audit['status']=='PASS'
    if not args.preview:
        assert numeric is not None and numeric['status']=='PASS'
        assert memory_probe is not None and memory_probe['status']=='PASS'
        assert len(ranking)==2 and {r['family'] for r in ranking}=={'F1','F2'}
        assert all(r['conclusion']=='success' for r in runs.values()),'A campaign failed; report must disclose/reconcile it first'
        assert all_present,(expected,actual)
    summary=dict(status='PRELIMINARY_INCOMPLETE' if args.preview else 'COMPLETED_WITH_DISCLOSED_LIMITATIONS',expected=expected,actual=actual,
        H1='SUPPORTED_ON_TESTED_EXACT_PROFILE',H2='SUPPORTED_ON_TESTED_EXACT_PROFILE',H3=main_result['decisions'],
        H4=[],H5=[dict(family=s['family'],series=s['series']) for s in e4],
        E0_aggregation=gate,E1X=extended,ozon_reproduction=audit,ranking=ranking,runs=runs,witnesses=witnesses,
        G2_numeric_regression=numeric,
        memory_counter_audit=memory_probe,
        memory_comparison_status='UNSUPPORTED_AS_ISOLATED_ENGINE_PEAK',
        environment_records=len(environments),
        deviations='docs/EXECUTION_DEVIATIONS_RU.md')
    e3_rows=[];strict_deadlines=[]
    for item in e3:
        metadata=item['metadata'];by={(r['mode'],r['label']):r for r in item['measurements']}
        accuracy=item['accuracy']
        complete=len(accuracy)==11
        admitted=complete and all(a['mission_class']=='APPROX-MISSION-1' for a in accuracy)
        g0,g2=by[('MISSION','G0-tsfg')],by[('MISSION','G2-tsfg')]
        des,dag=by[('MISSION','G0-des')],by[('MISSION','G0-dag')]
        def ratio(reference):
            return reference['T_total_s']/g2['T_total_s'] if reference['status']==g2['status']=='OK' else None
        row=dict(dataset_id=item['dataset_id'],family=metadata['family'],density=metadata['density'],n=metadata['n'],seed=metadata['seed'],
            scenarios_compared=len(accuracy),accuracy_coverage='COMPLETE' if complete else 'PARTIAL' if accuracy else 'UNASSESSED',
            false_successes=sum(a['false_success'] for a in accuracy),
            false_failures=sum(a['false_failure'] for a in accuracy),mission_admitted=admitted,
            diagnostic_admitted=complete and all(a['diagnostic_class']=='APPROX-DIAGNOSTIC-1' for a in accuracy),
            max_produced_error=max((a['errors']['produced_fraction'] for a in accuracy),default=None),
            max_queue_error=max((max(a['errors']['queue_at_D_fraction'],a['errors']['queue_max_fraction']) for a in accuracy),default=None),
            max_wip_error=max((a['errors']['wip_integral_relative'] for a in accuracy),default=None),
            S_G0_over_G2=ratio(g0),S_DES_over_G2=ratio(des),S_DAG_over_G2=ratio(dag),
            G1_types=item['representation']['type_count'],individual_states=item['representation']['individual_state_count'],
            G1_bytes=item['representation']['input_bytes'],G0_bytes=item['representation']['G0_input_bytes'],
            G1_preparation_s=item['representation']['preparation_wall_s'],
            G0_status=g0['status'],G2_status=g2['status'],DES_status=des['status'],DAG_status=dag['status'])
        e3_rows.append(row)
        raw=root/'e3-raw'/f"e3-{metadata['family']}-{metadata['density']}-{metadata['n']}-{metadata['seed']}"/'e3'
        exact_diagnostic=read_rows(raw/'DIAGNOSTIC-G0-des.jsonl')
        fluid_diagnostic=read_rows(raw/'DIAGNOSTIC-G2-tsfg.jsonl')
        assert all(row['algorithm_id']=='tsfg-g2-fluid-s1-v2' for row in fluid_diagnostic.values())
        for ratio in (1.,1.01):
            deadline=metadata['C0_ticks']*int(round(ratio*100))/100
            assessed=[]
            for scenario in exact_diagnostic.keys()&fluid_diagnostic.keys():
                a,b=exact_diagnostic[scenario],fluid_diagnostic[scenario]
                if a['cmax'] is None or b['cmax'] is None:continue
                assessed.append((a['cmax']<=deadline,b['cmax']<=deadline))
            strict_deadlines.append(dict(dataset_id=item['dataset_id'],deadline_ratio=ratio,scenarios=len(assessed),
                exact_successes=sum(a for a,b in assessed),false_successes=sum(b and not a for a,b in assessed),
                false_failures=sum(a and not b for a,b in assessed),analysis='POST_HOC diagnostic projection; no queue/WIP class at these deadlines'))
    summary['H4']=e3_rows
    summary['strict_deadline_diagnostic_projection']=strict_deadlines
    summary['E2_screen']=screen
    bounds=timeout_bounds(main_rows);summary['timeout_ratio_bounds']=bounds
    summary['supplementary']=dict(processes=len(extra_rows),complete_correct=sum(r['completion_validated'] for r in extra_rows),
        timeouts=sum(r['status']=='TIMEOUT' for r in extra_rows),
        validated_prefix_scenarios=sum(r.get('validated_prefix_scenarios',0) for r in extra_rows))
    fields=['dataset_id','engine','K','label','status','completion_validated','scenarios_completed','validated_prefix_scenarios',
            'T_total_s','T_batch_s','prefix_K100_batch_s','T_total_lower_bound_s','process_wall_observed_s','rss_peak_bytes','cpu_s','input_sha256','scenarios_sha256','commit','run_id']
    write_csv(out/'main-processes.csv',main_rows,fields)
    write_csv(out/'timeout-ratio-bounds.csv',bounds,['dataset_id','label','reference','direction','S_total_bound','eligible_for_H3','scope'])
    write_csv(out/'supplementary-processes.csv',extra_rows,fields)
    write_csv(out/'aggregation.csv',e3_rows,list(e3_rows[0]) if e3_rows else ['dataset_id','accuracy_coverage'])
    write_csv(out/'strict-deadlines-post-hoc.csv',strict_deadlines,list(strict_deadlines[0]) if strict_deadlines else ['dataset_id','deadline_ratio','scenarios'])
    extra_groups={}
    for row in extra_rows:
        key=(re.sub(r'-s\d+(?=-|$)','',row['dataset_id']),row['K'])
        extra_groups.setdefault(key,[]).append(row)
    supplementary=[]
    for (dataset,k),group in sorted(extra_groups.items()):
        row=dict(dataset=dataset,K=k)
        for engine in ('tsfg','des','dag'):
            selected=[r for r in group if r['engine']==engine]
            complete=[r for r in selected if r['completion_validated']]
            row[engine+'_completed']=len(complete)
            row[engine+'_processes']=len(selected)
            row[engine+'_timeouts']=sum(r['status']=='TIMEOUT' for r in selected)
            row[engine+'_median_total_s']=statistics.median([r['T_total_s'] for r in complete]) if complete else None
        supplementary.append(row)
    write_csv(out/'supplementary-summary.csv',supplementary,list(supplementary[0]) if supplementary else ['dataset','K'])
    shutil.copyfile(root/'screen/measurements.csv',out/'screen-processes.csv')
    shutil.copyfile(root/'main/measurements.csv',out/'H3-measurements.csv')
    lines=['# TSFG: проверка исполнения производственного расписания','',
        ('ПРЕДВАРИТЕЛЬНЫЙ ОТЧЁТ. Основные кампании ещё выполняются; ниже только доступные '
         'проверенные результаты. Это не итоговая приёмка всей кампании. ' if args.preview else
         'Итог фактически выполненной кампании 26–27 сентября 2026 года. ')+'Все исполнения, '
        'измерения и построение этого отчёта выполнены в GitHub-hosted Actions.', '']
    decisions=main_result['decisions']
    decision_counts={status:sum(d['status']==status for d in decisions)
                     for status in ('SUPPORTED','NOT_SUPPORTED','INSUFFICIENT_COMPLETED')}
    admitted_rows=[r for r in e3_rows if r['mission_admitted']]
    lines+=['## Основные результаты','',
        'DES-REF и DAG-REF — наши независимые открытые исследовательские реализации. '
        'DAG-REF рассчитывает исполнение по графу технологических зависимостей и '
        'фиксированных очередей станков. Коммерческие BFG и PlantTwin в этой кампании '
        'не запускались; коэффициенты ниже не описывают их производительность.', '',
        'Точный пооперационный профиль прошёл Mk01 и независимые проверки опубликованных '
        'больших траекторий. Это подтверждает корректность на проверенных данных; '
        'вычислительное преимущество оценивается отдельно.', '',
        f"H3: из {len(decisions)} решений по семейству, плотности, размеру и эталону "
        f"ускорение подтверждено в {decision_counts['SUPPORTED']}, "
        f"не подтверждено при полной серии в {decision_counts['NOT_SUPPORTED']}; "
        f"для {decision_counts['INSUFFICIENT_COMPLETED']} недостаточно завершённых корректных пар. "
        'Последняя категория не заменяется положительным или отрицательным результатом.', '',
        f"G2 прошёл весь допуск состояния к сроку на {len(admitted_rows)} из {len(e3_rows)} "
        'доступных наборов. Среди допущенных наборов время G2 меньше времени '
        f"пооперационного TSFG на {sum(r['S_G0_over_G2'] is not None and r['S_G0_over_G2']>1 for r in admitted_rows)}, "
        f"DES — на {sum(r['S_DES_over_G2'] is not None and r['S_DES_over_G2']>1 for r in admitted_rows)}, "
        f"DAG — на {sum(r['S_DAG_over_G2'] is not None and r['S_DAG_over_G2']>1 for r in admitted_rows)}. "
        'Это описательные K=11, а не парный критерий H3; точность полного срока '
        'проверяется отдельным классом DIAGNOSTIC.', '',
        'Изолированное сравнение памяти не получено: счётчик RSS включает историю '
        'запуска до exec. Оценка резервов относится к заданным сериям отказов; '
        'постоянные исходы выполнения ограничивают её информативность. '
        'Непроведённые проверки и отклонения перечислены в конце отчёта.', '',
        '## Ответ на вопрос о корректности и кейсе Ozon','',
        'На проверенном точном профиле исходное ядро S1 с пооперационным адаптером даёт '
        'те же результаты, что независимые DES и DAG. Найдены и исправлены накладные '
        'расходы адаптера: повторное форматирование идентификаторов, выделение списка '
        'завершений и обслуживание остатка горизонта после полного выполнения.', '',
        'В парном аудите N=10000, K=100 исправление сократило время на 31–32%. '
        'Все 2000 непрофилированных траекторий совпали по обязательным индивидуальным полям. '
        'Исходные файлы S1 не изменялись.', '',
        'Исходный Ozon healthy_100k воспроизведён с тем же отпечатком и восемью совпадениями '
        'метрик в двух запусках. Исторические 2,8–7,4× — аналитическая оценка scheduling-work, '
        'а не измеренное отношение времени TSFG к производственному DES. Пооперационная '
        'постановка сохраняет индивидуальные назначения, предшественников и фиксированные '
        'очереди. Потоковая модель Ozon обслуживает агрегированные объёмы. Одинаковая '
        'прикладная цель не делает эти вычислительные модели эквивалентными.', '']
    lines+=table(['F1/F2, K=100','Старый адаптер, с','Исправленный, с','DES, с','DAG, с'],[
        ['F1','26,78 / 26,90','18,18 / 18,15','0,84 / 0,84','0,28 / 0,29'],
        ['F2','18,02 / 17,89','12,46 / 12,47','0,93 / 0,94','0,29 / 0,29']])
    lines+=['В первом G2 отдельно обнаружен численный дефект сопряжения: порог S1 1e-6 '
            'отбрасывал малые внешние переносы, уже учтённые адаптером. На первом миллионном '
            'F1 номинальный выпуск достиг 100000 заказов, но остаток не позволял зафиксировать '
            'полное завершение к 10D. Эта версия сохраняется как e3_v1 с известным дефектом. '
            'G2 v2 масштабирует внутренние объёмы и мощности на 2^20, возвращая выход в заказы; '
            'допуски точности не расширены. После отдельного регрессионного допуска '
            +('выполняется повтор всей E3 и ранжирования. ' if args.preview else
              'повторены вся E3 и ранжирование. ')+
            'Данная ошибка не затрагивает пооперационную H3.','']
    lines+=['Это сравнение конкретных реализаций: Go S1 с универсальным графовым обслуживанием '
            'и C++ DES/DAG. Оно не доказывает предел быстродействия всех реализаций TSFG. '
            'Минимальный C++ GRID остаётся отдельным вспомогательным участником.','',
        '## Корректность и расширения','',
        'Mk01: CP-SAT доказал C0=40; 481 полная траектория, 52910 сравнений времён операций '
        'и 1443 классификации трёх сроков на движок. Расхождений и обоих видов ошибочной '
        'классификации нет. Исходный S1 прошёл 157 регрессионных тестов. E0 проверяет '
        'атомарные завершения, поступления, отказы, работу на границе D и сохранение материала.','',
        'E1X: буферы 1/2/4 — по 481 сценарию и 1443 исхода; дополнительный ресурс — '
        '15 сценариев и 45 исходов. Совпадение с независимым непрерывным эталоном проверено. '
        'Дробная скорость — отдельный приблизительный профиль: 90 сценариев, шаги 0,05 и 0,01; '
        'максимальная ошибка индивидуального времени 0,10556 и 0,03 единицы. Более мелкий '
        'шаг не ухудшил ни один из 90 результатов. Буферные исходные планы при необходимости '
        'заменялись заранее допустимым последовательным планом; это не исходный план Mk01.','',
        'Для публичной ручной проверки дополнительно сохранены 36 полных трасс по миллиону '
        'операций: F1/F2 × DENSE/SPARSE, seed101, M0/S0000/S0003, три движка. Сохранены '
        'все индивидуальные состояния MISSION на [0,D], включая незавершённые операции. '
        'Массивы и физические инварианты совпали. Это отдельные контрольные запуски, не повтор H3.','',
        '## Основное время и память E2','',
        f"Предварительно: 48 наборов, {screen['correct_complete']}/144 полных корректных процессов, "
        f"{screen['timeouts']} таймаутов. Основная серия: {main_result['correct_complete']}/432 полных "
        f"корректных процессов, {main_result['timeouts']} таймаутов.", '',
        'H3 использует самостоятельный K=100, три независимые VM для каждого seed и два '
        'повтора каждого движка внутри VM. S=sqrt(T_REF,1×T_REF,2 / (T_TSFG,1×T_TSFG,2)). '
        'Для области и размера нужны все девять корректных завершённых пар, геометрическое '
        'среднее G≥2 и среднее каждого runner_round>1. Таймауты не заменены пределами.','']
    lines+=table(['Область','N','Эталон','Пар / 9','G, T_batch','G, T_total','Решение'],[
        [f"{d['family']}/{d['density']}",d['n'],d['reference'],len(d['points']),num(d.get('G')),num(d.get('G_total')),d['status']]
        for d in main_result['decisions']])
    lines+=['Границы отношения полного времени при одностороннем таймауте приведены ниже. '
            'Для UPPER истинное S_total меньше опубликованной границы, для LOWER — больше. '
            'В каждой строке диапазон границ отдельных VM; это не доверительный интервал. '
            'Используются два запуска каждого движка на одной VM. Обе цензурированные '
            'стороны не дают конечной границы. Эти значения не участвуют в принятии H3 и '
            'не подтверждают корректность неизвестного окончания прерванного процесса.','']
    bound_groups={}
    for r in bounds:
        key=(re.sub(r'-s\d+$','',r['dataset_id']),r['reference'],r['direction'])
        bound_groups.setdefault(key,[]).append(r['S_total_bound'])
    lines+=table(['Область и размер','Эталон','Вид границы','Точек','Минимум','Максимум'],[
        [dataset,reference,direction,len(values),num(min(values)),num(max(values))]
        for (dataset,reference,direction),values in sorted(bound_groups.items())])
    lines+=['Номинальные горизонты и фактические пустые промежутки:','']
    lines+=table(['Набор, seed101','C0, с','Нижняя оценка, с','Доля пустого времени','Наибольший пустой интервал, с'],[
        [r['dataset_id'],num(r['C0_ticks']/100),num(r['lower_bound_ticks']/100),num(r['global_idle_fraction']),num(r['longest_global_idle_ticks']/100)]
        for r in diagnostics if r['operations']==1000000 and r['dataset_id'].endswith('-s101')])
    lines+=['Полные диагностики всех 48 планов, загрузка каждого станка и интервалы между '
            'границами событий находятся в input-diagnostics.json.','']
    lines+=['Полные строки времени, RSS, CPU, завершённых сценариев и границ при TIMEOUT '
            'сохранены в main-processes.csv. Измеряется полный одинаковый SCHEDULE. '
            'Контрольные точки префикса внутри K=1000 не подменяют отдельный K=100.','',
        'RSS ниже — ru_maxrss всей истории запуска процесса, а не изолированный пик образа '
        'движка. Отдельный контроль воспроизвёл влияние состояния до exec: ru_maxrss '
        '278300 KiB при VmHWM нового образа 10888 KiB. Linux сохраняет учёт ресурсов '
        'через exec ([getrusage](https://man7.org/linux/man-pages/man2/getrusage.2.html)). '
        'По этой памяти не принимается вывод о преимуществе движков. Изолированный '
        'пик памяти всех основных процессов не измерен; исходные значения не исправляются '
        'вычитанием предполагаемого фона. Замеры времени H3 сохраняются.','',
        'Медиана и максимум счётчика RSS ниже относятся только к завершённым корректным процессам. '
        'RSS прерванного процесса остаётся наблюдённой памятью до остановки и опубликован '
        'в CSV отдельно; его нельзя считать пиком неизвестного полного исполнения.','']
    memory=[]
    for n in (100000,1000000):
        for engine in ('tsfg','des','dag'):
            selected=[r for r in main_rows if r['engine']==engine and f'-N{n}-' in r['dataset_id']]
            rss=[r['rss_peak_bytes']/2**20 for r in selected if r['completion_validated']]
            memory.append([n,engine,f'{len(rss)}/{len(selected)}',num(statistics.median(rss) if rss else None),num(max_known(rss))])
    lines+=table(['N','Движок','Полных процессов','Медиана ru_maxrss, MiB','Максимум ru_maxrss, MiB'],memory)
    lines+=['![Парные ускорения E2](H3.png)','',
        '## Агрегирование G1 и G2','',
        f"E3, исправленная G2 v2: {len(e3_rows)} наборов, M0 и 10 воздействий; отдельные MISSION и DIAGNOSTIC. "
        f"Все 11 сценариев прошли APPROX-MISSION-1 на {sum(r['mission_admitted'] for r in e3_rows)} наборах; "
        f"APPROX-DIAGNOSTIC-1 — на {sum(r['diagnostic_admitted'] for r in e3_rows)}. "
        f"Всего ложных успехов G2: {sum(r['false_successes'] for r in e3_rows)}; "
        f"ложных срывов: {sum(r['false_failures'] for r in e3_rows)}.", '',
        'G1 разделяет описания типов, но сохраняет N индивидуальных динамических состояний. '
        'Полный обратный декодер проверен для каждого входа; полные времена G0/G1 сравниваются '
        'на допуске, общие наблюдаемые показатели — на всей серии. Подготовка и размер файла '
        'публикуются отдельно. Сокращение файла само по себе не считается ускорением расчёта.','',
        'G2 — делимый поток через десять стадий поверх S1. Отбрасываются индивидуальная '
        'совместимость, s0 и очередность; доступные мощности групп делятся между стадиями '
        'по долям суммарной работы. Это отдельная приближённая модель. При одинаковом выходе '
        'AGG-MISSION время всех участников включает расчёт очередей и интеграла НЗП. '
        'Индивидуальные сроки G2 имеют статус UNSUPPORTED.','']
    lines+=table(['Семейство/плотность','N','Допуск MISSION / 3 seed','Сравнено / 33','Ложных успехов','Макс. ошибка НЗП'],[
        [f'{f}/{d}',n,sum(r['mission_admitted'] for r in e3_rows if (r['family'],r['density'],r['n'])==(f,d,n)),
         sum(r['scenarios_compared'] for r in e3_rows if (r['family'],r['density'],r['n'])==(f,d,n)),
         sum(r['false_successes'] for r in e3_rows if (r['family'],r['density'],r['n'])==(f,d,n)),
         num(max_known(r['max_wip_error'] for r in e3_rows if (r['family'],r['density'],r['n'])==(f,d,n)))]
        for f in ('F1','F2') for d in ('DENSE','SPARSE') for n in (1000,10000,100000,1000000)])
    lines+=['Максимумы взяты по M0 и десяти сценариям; ошибка НЗП — доля, 0,05 соответствует 5%. '
            'Скорость приближения, не прошедшего класс точности, не считается подтверждением H4. '
            'Неполное сравнение не считается допуском всех 11 сценариев; отсутствие данных '
            'не подменено ошибкой 0. Эти K=11 и один порядок процессов не являются парной H3.','',
        'При D=1,10C0 исходы основной сетки могут быть малоинформативны: синхронный отказ '
        'подмножества станков длительностью не более 0,10C0 не хуже остановки всех станков '
        'на этот интервал. В основной фиксированной постановке такая остановка добавляет '
        'не более своей длительности к Cmax. После округления границ до секунды интервал '
        'может оказаться длиннее 0,10C0 менее чем на секунду; такие пограничные срывы '
        'сохраняются и проверяются без допуска на классификацию. Совпадение успехов не заменяет '
        'проверку индивидуальных времён, очередей и НЗП.','',
        'Дополнительно после просмотра первых результатов из полных DIAGNOSTIC-траекторий '
        'спроецированы только исходы для D=C0 и D=1,01C0. Это явно послерезультатный анализ '
        'чувствительности, а не изменение заранее выбранного класса MISSION; очереди и '
        'НЗП на этих новых горизонтах этим анализом не проверяются.','']
    lines+=table(['D/C0','Проверенных исходов','Ложных успехов G2','Ложных срывов G2'],[
        [ratio,sum(r['scenarios'] for r in strict_deadlines if r['deadline_ratio']==ratio),
         sum(r['false_successes'] for r in strict_deadlines if r['deadline_ratio']==ratio),
         sum(r['false_failures'] for r in strict_deadlines if r['deadline_ratio']==ratio)] for ratio in (1.,1.01)])
    lines+=[
        '![Скорость и ошибка G2](aggregation.png)','',
        '## Ресурсы и резервы E4','',
        'На F1/F2 DENSE, N=100000, seed101 каждый из 200 ресурсов ранжирован по 15 одинаковым '
        'одиночным отказам. Три критичных и три контрольных ресурса фиксируются до независимой '
        'оценки. Основное вмешательство — +10% скорости одного станка. Постоянная скорость '
        'представлена точным масштабированием времени ×11 и работы ускоренного станка ×10, '
        'без округления длительности. Отдельный допуск этого преобразования прошёл на TSFG/DES/DAG.','']
    lines+=table(['Семейство','Серия','Успех до / 1000','Средний эффект T','95% интервал','H5'],[
        [s['family'],label,item['configurations'][0]['successes'],num(item['mean_e_T']),str(item['e_T_ci95']),item['status']]
        for s in e4 for label,item in s['series'].items()])
    lines+=['Большой E4 проверен точными DES/DAG и физическими инвариантами. Он оценивает '
            'полезность ранжирования, а не производительность TSFG. Независимые отказы и '
            'общая причина — отдельные серии. Полученные вероятности относятся только к '
        'заданному исследовательскому профилю, а не к неизвестной статистике предприятия. '
        'Постоянные бинарные исходы 0/1000 или 1000/1000 ограничивают информативность '
        'сравнения вмешательств. Неподтверждение H5 не доказывает бесполезность любой '
        'диагностики или иных бюджетов усиления.','',
        '![Доля выполнения E4](reserves.png)','']
    lines+=table(['Согласие рангов G2','Завершено / 3000','Top-3 общих','Спирмен','Статус'],[
        [r['family'],r['completed'],r.get('top3_overlap','—'),num(r.get('spearman_average_ties')),r['status']] for r in ranking])
    lines+=['## Дополнительные серии и границы вывода','',
        f"План дополнительных серий: 57 наборов — BURST 24, рост оборудования 9, сборка F3 12, "
        f"самостоятельный K=1000 12. Доступно процессов {len(extra_rows)}, завершённых корректных "
        f"{summary['supplementary']['complete_correct']}, таймаутов {summary['supplementary']['timeouts']}.", '',
        'Следующая таблица содержит медианы T_total только полных корректных процессов; '
        'в скобках — число таких процессов / число запущенных. Это описательные '
        'одноразовые измерения, а не парные коэффициенты H3. Все времена, достигнутые '
        'префиксы K=100 внутри K=1000 и границы опубликованы в supplementary-processes.csv.','']
    lines+=table(['Набор','K','TSFG, с (полнота)','DES, с (полнота)','DAG, с (полнота)'],[
        [r['dataset'],r['K'],*[f"{num(r[e+'_median_total_s'])} ({r[e+'_completed']}/{r[e+'_processes']})" for e in ('tsfg','des','dag')]]
        for r in supplementary])
    lines+=[
        'BURST имеет четыре партии и проверенные пустые промежутки. GRID их не пропускает. '
        'В серии роста оборудования F2 имеет ровно две альтернативы при 20/200/2000 станках. '
        'Дополнительный K=1000 на миллионе операций не запускался в текущем бюджете. '
        'Переналадка, ограниченный транспорт, миграция незавершённой работы, резервный станок '
        'и новый алгоритм пропуска времени не реализованы и не объявляются проверенными. '
        'Приближённый Mk01 с грубыми шагами 1 и 0,25 также не запускался; проверенные '
        'шаги дробно-скоростного E1X — отдельный опыт.','',
        'Выявлено отклонение от §6.2: фактический генератор использует первые 8 байт SHA-256 '
        'для PCG64 вместо 16 в тексте плана. Это записано в manifest и EXECUTION_DEVIATIONS_RU.md. '
        'Файлы после просмотра результатов не заменялись. Все сравниваемые движки получают '
        'одинаковые входы. Буквальное воспроизведение 16-байтовой схемы не выполнено.','',
        'Данные недостаточны для утверждений о производительности PlantTwin или BFG APS. '
        'Заявленные BFG 45 минут относятся к построению плана; здесь проверяется исполнение '
        'уже выбранного расписания. DAG применим к фиксированным очередям без конечных '
        'буферов и конкурирующих дополнительных ресурсов.','',
        '## Следствия для продукта: DAG как кандидат на основное ядро','',
        'Для продукта проверки исполнения готовых производственных расписаний DAG-REF '
        'является обоснованным кандидатом на основной точный расчётный движок. Он сохраняет '
        'индивидуальные операции и на проверенных данных даёт тот же результат, что '
        'независимое пооперационное моделирование, при меньших измеренных затратах времени. '
        'Архитектуру продукта не требуется привязывать к TSFG: выбор движка должен следовать '
        'постановке задачи, требуемой точности и измерениям. Это вывод о направлении '
        'разработки по исследовательским данным, а не утверждение о готовности продукта.', '',
        'Предлагаемый первый продуктовый контур: импорт расписания и календарей оборудования; '
        'пакетный расчёт сценариев отказов и изменений длительности; прогноз опозданий '
        'заказов с объяснением цепочек задержек; сравнение заранее заданных изменений '
        'мощности и вариантов расписания. DAG выполняет расчёт исполнения. Продуктовая '
        'работа также включает интеграции, проверку исходных данных и понятное представление '
        'причин и последствий. Это предложение состава продукта; перечисленные интеграции '
        'и интерфейс в данной кампании не реализованы.', '',
        'Граница текущего DAG-REF — заранее заданные назначения, технологические зависимости '
        'и очереди станков при неограниченных буферах и отсутствии дополнительных '
        'конкурирующих ресурсов. Изменённое, но вновь фиксированное расписание можно '
        'представить отдельным графом и проверить заново. Динамическое переназначение, '
        'диспетчеризация очередей и блокировки конечных буферов требуют отдельного '
        'алгоритма и допуска; возможен событийный движок. Текущий DAG-REF не объявляется '
        'универсальным решателем этих расширений.', '',
        'Построение оптимального расписания — отдельный контур: требуется выбирать '
        'назначения или порядок и оптимизировать целевую функцию. Например, '
        '[OR-Tools описывает job shop через CP-SAT](https://developers.google.com/optimization/scheduling/job_shop). '
        'Быстрая проверка выбранного плана не доказывает такую же скорость поиска '
        'оптимального плана.', '',
        'TSFG и агрегированный G2 следует рассматривать как дополнительные режимы '
        'для конкретных классов задач, где подтверждены нужная точность и полезный '
        'выигрыш. Ускорение G2 относительно пооперационного TSFG само по себе не '
        'обосновывает выбор G2 вместо точного DAG. Допуск состояния к сроку не '
        'означает допуска индивидуальных времён или полного срока завершения.', '',
        'Следующая проверка продуктовой гипотезы должна использовать реальные планы '
        'и наблюдения исполнения: качество прогноза опозданий, объяснимость задержек '
        'и эффект предлагаемых изменений. Производственные вероятности требуют '
        'проверенной модели отказов и длительностей. E4 этой кампании не подтвердила '
        'полезность выбора резервов по принятому критерию; более быстрый расчёт не '
        'заменяет это доказательство. Сравнения с коммерческими продуктами также '
        'остаются отдельными испытаниями.', '',
        '## Происхождение и воспроизведение','',
        'Код: https://github.com/a-a-k/sheaft-tsfg-experiments. Исходный частный S1: '
        '8510baf28673758f1e437d2dbc5a51ead9843a3b. Частный код, Go-бинарник и ключи в архив '
        'не включены; повтор TSFG требует доступа к исходному S1. Открытые DES/DAG '
        'и генератор воспроизводятся из публичного репозитория.','']
    for role,run_info in runs.items():
        lines.append(f"- {role}: [Actions {run_info['id']}]({run_info['html_url']}), commit `{run_info['head_sha']}`.")
    lines+=['','Полные таблицы, контрольные суммы и сырые компактные свидетельства входят в '
            'публикационный архив. Неизвестные сроки сохранены как null с нижней границей; '
            'срок остановки не подставлялся вместо фактического завершения.']
    (out/'REPORT_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    plt.rcParams.update({'font.family':'DejaVu Sans','axes.spines.top':False,'axes.spines.right':False})
    figures=[]
    fig,ax=plt.subplots(figsize=(11,6),layout='constrained')
    labels=[]
    for i,d in enumerate(main_result['decisions']):
        labels.append(f"{d['family']}/{d['density']}\nN={d['n']}\n{d['reference']}")
        values=[p['S_batch'] for p in d['points']]
        if values:ax.scatter(np.linspace(i-.18,i+.18,len(values)),values,s=23,color='#28659d')
        if d.get('G') is not None:ax.scatter(i,d['G'],marker='D',color='#ae3c35',s=40)
        ax.text(i,.98,f"{len(values)}/9",transform=ax.get_xaxis_transform(),ha='center',va='top',fontsize=8)
    ax.axhline(1,color='black',lw=.8);ax.axhline(2,color='#ae3c35',ls='--',lw=1)
    ax.set_yscale('log');ax.set_xticks(range(len(labels)),labels,rotation=90,fontsize=7)
    ax.set_ylabel('S = T эталона / T TSFG, парный T_batch');ax.set_title('H3: завершённые корректные пары; сверху — полнота')
    fig.savefig(out/'H3.png',dpi=180);figures.append(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,5),layout='constrained')
    for family,color in [('F1','#2878a0'),('F2','#cf643b')]:
        rows=[r for r in e3_rows if r['family']==family]
        for ax,key in zip(axes,('S_G0_over_G2','S_DAG_over_G2')):
            for admitted,marker in ((True,'o'),(False,'x')):
                selected=[r for r in rows if r[key] is not None and r['max_wip_error'] is not None
                          and r['accuracy_coverage']=='COMPLETE' and r['mission_admitted']==admitted]
                ax.scatter([r[key] for r in selected],[max(1e-5,r['max_wip_error'])*100 for r in selected],
                    marker=marker,color=color,label=family+(' допущен' if admitted else 'вне класса'))
            ax.set_xscale('log');ax.set_yscale('log');ax.axhline(5,color='gray',ls='--');ax.axvline(1,color='black',lw=.8)
            ax.set_xlabel('T '+('G0 TSFG' if key=='S_G0_over_G2' else 'DAG')+' / T G2');ax.set_ylabel('Макс. ошибка интеграла НЗП, %')
    axes[0].legend(fontsize=8);fig.suptitle('G2: цена уменьшения состояния; одинаковый AGG-MISSION')
    fig.savefig(out/'aggregation.png',dpi=180);figures.append(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    for ax,item in zip(axes,sorted(e4,key=lambda s:s['family'])):
        configs=item['series']['independent']['configurations'];values=[c['probability'] for c in configs]
        errors=np.array([[max(0,c['probability']-c['wilson95'][0]),max(0,c['wilson95'][1]-c['probability'])] for c in configs]).T
        ax.bar(range(7),values,color=['#6b7786']+['#c66542']*3+['#4484a6']*3,yerr=errors,capsize=3)
        ax.set_xticks(range(7),['Исходный','T1','T2','T3','B1','B2','B3']);ax.set_ylim(-.02,1.06)
        ax.set_title(item['family']+'; независимые отказы');ax.set_ylabel('Доля выполнения; 95% Уилсон')
    fig.savefig(out/'reserves.png',dpi=180);figures.append(fig)
    with PdfPages(out/'REPORT_RU.pdf',metadata={'Title':'TSFG — производственный эксперимент','Author':'Sheaft research campaign'}) as pdf:
        plain=[]
        for line in lines:
            if line.startswith('![') or line.startswith('|---'):continue
            line=re.sub(r'\[([^]]+)\]\([^)]+\)',r'\1',line).replace('`','').replace('#','')
            plain.extend(textwrap.wrap(line,width=112,break_long_words=True) or [''])
        for offset in range(0,len(plain),57):
            page=plt.figure(figsize=(8.27,11.69))
            page.text(.055,.955,'\n'.join(plain[offset:offset+57]),va='top',fontsize=8.2,family='DejaVu Sans Mono',linespacing=1.35)
            page.text(.94,.025,str(offset//57+1),ha='right',fontsize=8);pdf.savefig(page);plt.close(page)
        for fig in figures:pdf.savefig(fig)
    for fig in figures:plt.close(fig)
    hashes={}
    for p in sorted(out.iterdir()):
        if p.is_file() and p.name!='SHA256.json':
            with p.open('rb') as source:hashes[p.name]=hashlib.file_digest(source,'sha256').hexdigest()
    (out/'SHA256.json').write_text(json.dumps(hashes,indent=2))
    print(json.dumps(dict(status=summary['status'],actual=actual,H3=[d['status'] for d in summary['H3']],
        G2_admitted_datasets=sum(r['mission_admitted'] for r in e3_rows))))


if __name__=='__main__':main()
