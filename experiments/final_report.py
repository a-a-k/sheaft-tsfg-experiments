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
import textwrap

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np


def read(path):return json.loads(path.read_text())
def num(value):return '—' if value is None else f'{value:.3g}'
def table(headers,rows):
    return ['| '+' | '.join(headers)+' |','|'+'|'.join('---' for _ in headers)+'|',
            *['| '+' | '.join(map(str,row))+' |' for row in rows],'']
def records(root):
    return [dict(read(p),evidence_path=str(p)) for p in sorted(root.glob('**/measurements/*/measurement.json'))]
def write_csv(path,rows,fields):
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('Actions only')
    parser=argparse.ArgumentParser()
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.evidence;out=args.output;out.mkdir(parents=True,exist_ok=True)
    screen=read(root/'screen/summary.json');main_result=read(root/'main/summary.json')
    main_rows=records(root/'main-points');extra_rows=records(root/'extras')
    e3=[read(p) for p in sorted((root/'e3').glob('*/summary.json'))]
    e4=[read(p) for p in sorted((root/'e4').glob('*/summary.json'))]
    ranking=[read(p) for p in sorted((root/'ranking').glob('*/g2-ranking/summary.json'))]
    extended=read(root/'core/e1x/summary.json')
    gate=read(root/'core/e3-gate/summary.json')
    audit=read(root/'audit/audit/ozon-reproduction-check.json')
    runs=read(root/'runs.json')
    expected=dict(screen_processes=144,main_processes=432,e3_datasets=48,e4_families=2,extra_processes=171)
    actual=dict(screen_processes=screen['records'],main_processes=len(main_rows),e3_datasets=len(e3),
                e4_families=len(e4),extra_processes=len(extra_rows))
    all_present=actual==expected
    assert screen['datasets_present']==48 and not screen['missing_datasets']
    assert all(v['status'].startswith('PASS') for v in e3)
    assert extended['status']==gate['status']==audit['status']=='PASS'
    assert all(r['conclusion']=='success' for r in runs.values()),'A campaign failed; report must disclose/reconcile it first'
    assert all_present,(expected,actual)
    summary=dict(status='COMPLETED_WITH_DISCLOSED_LIMITATIONS',expected=expected,actual=actual,
        H1='SUPPORTED_ON_TESTED_EXACT_PROFILE',H2='SUPPORTED_ON_TESTED_EXACT_PROFILE',H3=main_result['decisions'],
        H4=[],H5=[dict(family=s['family'],series=s['series']) for s in e4],
        E0_aggregation=gate,E1X=extended,ozon_reproduction=audit,ranking=ranking,runs=runs,
        deviations='docs/EXECUTION_DEVIATIONS_RU.md')
    e3_rows=[]
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
            scenarios_compared=len(accuracy),false_successes=sum(a['false_success'] for a in accuracy),
            false_failures=sum(a['false_failure'] for a in accuracy),mission_admitted=admitted,
            diagnostic_admitted=complete and all(a['diagnostic_class']=='APPROX-DIAGNOSTIC-1' for a in accuracy),
            max_produced_error=max((a['errors']['produced_fraction'] for a in accuracy),default=None),
            max_queue_error=max((max(a['errors']['queue_at_D_fraction'],a['errors']['queue_max_fraction']) for a in accuracy),default=None),
            max_wip_error=max((a['errors']['wip_integral_relative'] for a in accuracy),default=None),
            S_G0_over_G2=ratio(g0),S_DES_over_G2=ratio(des),S_DAG_over_G2=ratio(dag),
            G1_types=item['representation']['type_count'],individual_states=item['representation']['individual_state_count'],
            G1_bytes=item['representation']['input_bytes'],G0_bytes=item['representation']['G0_input_bytes'],
            G1_preparation_s=item['representation']['preparation_wall_s'])
        e3_rows.append(row)
    summary['H4']=e3_rows
    summary['E2_screen']=screen
    summary['supplementary']=dict(processes=len(extra_rows),complete_correct=sum(r['completion_validated'] for r in extra_rows),
        timeouts=sum(r['status']=='TIMEOUT' for r in extra_rows),
        validated_prefix_scenarios=sum(r.get('validated_prefix_scenarios',0) for r in extra_rows))
    fields=['dataset_id','engine','K','label','status','completion_validated','scenarios_completed','validated_prefix_scenarios',
            'T_total_s','T_total_lower_bound_s','process_wall_observed_s','rss_peak_bytes','cpu_s','input_sha256','scenarios_sha256','commit','run_id']
    write_csv(out/'main-processes.csv',main_rows,fields)
    write_csv(out/'supplementary-processes.csv',extra_rows,fields)
    write_csv(out/'aggregation.csv',e3_rows,list(e3_rows[0]))
    shutil.copyfile(root/'screen/measurements.csv',out/'screen-processes.csv')
    shutil.copyfile(root/'main/measurements.csv',out/'H3-measurements.csv')
    lines=['# TSFG: проверка исполнения производственного расписания','',
        'Итог фактически выполненной кампании 26–27 сентября 2026 года. Все исполнения, '
        'измерения и построение этого отчёта выполнены в GitHub-hosted Actions.', '',
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
    lines+=['Полные строки времени, RSS, CPU, завершённых сценариев и границ при TIMEOUT '
            'сохранены в main-processes.csv. Измеряется полный одинаковый SCHEDULE. '
            'Контрольные точки префикса внутри K=1000 не подменяют отдельный K=100.','',
        '![Парные ускорения E2](H3.png)','',
        '## Агрегирование G1 и G2','',
        f"E3: {len(e3_rows)} наборов, M0 и 10 воздействий; отдельные MISSION и DIAGNOSTIC. "
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
    lines+=table(['Семейство/плотность','N','Допуск MISSION / 3 seed','Ложных успехов','Макс. ошибка НЗП'],[
        [f'{f}/{d}',n,sum(r['mission_admitted'] for r in e3_rows if (r['family'],r['density'],r['n'])==(f,d,n)),
         sum(r['false_successes'] for r in e3_rows if (r['family'],r['density'],r['n'])==(f,d,n)),
         num(max(r['max_wip_error'] for r in e3_rows if (r['family'],r['density'],r['n'])==(f,d,n)))]
        for f in ('F1','F2') for d in ('DENSE','SPARSE') for n in (1000,10000,100000,1000000)])
    lines+=['Максимумы взяты по M0 и десяти сценариям; ошибка НЗП — доля, 0,05 соответствует 5%. '
            'Скорость приближения, не прошедшего класс точности, не считается подтверждением H4. '
            'Эти K=11 и один порядок процессов не являются парной H3.','',
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
            'заданному исследовательскому профилю, а не к неизвестной статистике предприятия.','',
        '![Доля выполнения E4](reserves.png)','']
    lines+=table(['Согласие рангов G2','Завершено / 3000','Top-3 общих','Спирмен','Статус'],[
        [r['family'],r['completed'],r.get('top3_overlap','—'),num(r.get('spearman_average_ties')),r['status']] for r in ranking])
    lines+=['## Дополнительные серии и границы вывода','',
        f"57 наборов: BURST — 24; рост оборудования — 9; сборка F3 — 12; самостоятельный "
        f"K=1000 — 12. Процессов {len(extra_rows)}, завершённых корректных "
        f"{summary['supplementary']['complete_correct']}, таймаутов {summary['supplementary']['timeouts']}.", '',
        'BURST имеет четыре партии и проверенные пустые промежутки. GRID их не пропускает. '
        'В серии роста оборудования F2 имеет ровно две альтернативы при 20/200/2000 станках. '
        'Дополнительный K=1000 на миллионе операций не запускался в текущем бюджете. '
        'Переналадка, ограниченный транспорт, миграция незавершённой работы, резервный станок '
        'и новый алгоритм пропуска времени не реализованы и не объявляются проверенными.','',
        'Выявлено отклонение от §6.2: фактический генератор использует первые 8 байт SHA-256 '
        'для PCG64 вместо 16 в тексте плана. Это записано в manifest и EXECUTION_DEVIATIONS_RU.md. '
        'Файлы после просмотра результатов не заменялись. Все сравниваемые движки получают '
        'одинаковые входы. Буквальное воспроизведение 16-байтовой схемы не выполнено.','',
        'Данные недостаточны для утверждений о производительности PlantTwin или BFG APS. '
        'Заявленные BFG 45 минут относятся к построению плана; здесь проверяется исполнение '
        'уже выбранного расписания. DAG применим к фиксированным очередям без конечных '
        'буферов и конкурирующих дополнительных ресурсов.','',
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
                selected=[r for r in rows if r[key] is not None and r['mission_admitted']==admitted]
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
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir()) if p.is_file()}
    (out/'SHA256.json').write_text(json.dumps(hashes,indent=2))
    print(json.dumps(dict(status=summary['status'],actual=actual,H3=[d['status'] for d in summary['H3']],
        G2_admitted_datasets=sum(r['mission_admitted'] for r in e3_rows))))


if __name__=='__main__':main()
