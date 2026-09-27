"""Complete APS matrix: all three repeats, conservative presentation N and quality."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.aps_million_gate_v2 import read_report
from scripts.aps_remaining_v2 import previous
from scripts.aps_batch_v2 import report
from scripts.collect_evidence import artifacts,artifact_download

REPO='a-a-k/sheaft-tsfg-experiments'


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    p=argparse.ArgumentParser();p.add_argument('--million-runs',required=True);args=p.parse_args()
    root=Path('aps-matrix');raw=root/'raw';out=root/'report';raw.mkdir(parents=True,exist_ok=True);out.mkdir(exist_ok=True)
    rows=[];evidence=[]
    for run in (36308210267,36308617954,36308875750,36309164491):
        batch,source=read_report(run);rows.extend(batch);evidence.append(source)
    runs=[int(v) for v in args.million_runs.split(',')];assert len(runs)==len(set(runs))==7
    for run in runs:
        batch,source=previous(run);rows.extend(batch);evidence.append(source)
        for item in artifacts(REPO,run):
            if item['name'].startswith('aps-measured-'):
                path=raw/f'{run}-{item["name"]}.zip';digest=artifact_download(REPO,item,path)
                evidence.append(dict(run_id=run,artifact_id=item['id'],name=item['name'],sha256=digest))
    small=[r for r in rows if r['operation_count']==100000];large=[r for r in rows if r['operation_count']==1000000]
    assert len(rows)==70 and len(small)==len(large)==30
    assert all(r['correctness_status']=='VALID' and r['performance_status']=='MEASURED' for r in rows)
    assert len({json.dumps(r['measurement_code_sha256'],sort_keys=True) for r in rows})==1
    collected=Path('collected');collected.mkdir(exist_ok=True)
    for i,row in enumerate(rows):
        folder=collected/str(i);folder.mkdir(exist_ok=True);(folder/'validated.json').write_text(json.dumps(row))
    report(SimpleNamespace(root=collected,output=out,expected=70))
    aggregates=[]
    for n,observations in [(100000,small),(1000000,large)]:
        assert len({r['task_sha256'] for r in observations})==10
        for task in sorted({r['task_sha256'] for r in observations}):
            group=[r for r in observations if r['task_sha256']==task]
            assert {r['repeat'] for r in group}=={1,2,3}
            assert len({r['run_id'] for r in group})==3
            assert len({r['output_sha256'] for r in group})==1,'Non-deterministic schedule output'
            values=[r['measurement']['T_total_s'] for r in group];first=group[0]
            aggregates.append(dict(task_sha256=task,operation_count=n,aliases=first['aliases'],family=first['family'],density=first['density'],
                median_s=statistics.median(values),minimum_s=min(values),maximum_s=max(values),
                max_VmHWM_bytes=max(r['measurement']['VmHWM_bytes'] for r in group),
                Cmax_ticks=first['quality']['Cmax_ticks'],LB_ticks=first['quality']['LB_ticks'],
                gap_bound=first['quality']['gap_bound'],quality_status=first['quality_status'],repeats=3))
    million=[r for r in aggregates if r['operation_count']==1000000]
    n_value=max(r['median_s'] for r in million);ratio=2700/n_value
    status=dict(execution_status='COMPLETE',scope='Full deduplicated APS-BASIC matrix',campaign_execution_status='PARTIAL',
        unique_tasks_per_size=10,repeats_per_task=3,validated_primary_processes=60,diagnostic_processes=10,
        presentation_N_seconds=n_value,N_definition='Maximum of the three-repeat medians across every unique required million-operation input',
        BFG_published_seconds=2700,ratio_of_published_vendor_time_to_measured_N=ratio,
        measured_result='Complete APS-BASIC matrix with independent validation and quality bounds',
        market_hypothesis='Sheaft способен сократить время построения крупных производственных планов по сравнению с классом APS; первый рыночный ориентир — BFG APS',
        market_extrapolation_assumption='Representativeness of BFG for other APS products and comparability of tasks and quality have not been experimentally established')
    (out/'execution-status.json').write_text(json.dumps(status,indent=2,ensure_ascii=False)+'\n')
    (out/'aps-aggregates.json').write_text(json.dumps(aggregates,indent=2)+'\n')
    (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    text=['# APS-BASIC: полная матрица v2.2','',
        '**Завершены все 60 обязательных измерительных процессов после дедупликации: по три повтора '
        'для 10 уникальных задач каждого размера. Все планы VALID. Общая кампания APS/PBR/резервов ещё продолжается.**','',
        f'Консервативная сводная величина **N = {n_value:.2f} с**: максимум медиан по всем десяти миллионным входам. '
        'Вход каждой медианы посчитан трижды на отдельных VM. Минимальное время всей серии этой величиной не подменяется.','',
        '| Миллионный вход | Медиана, с | Диапазон, с | Пик памяти, байт | Качество | Граница разрыва |',
        '|---|---:|---:|---:|---|---:|']
    for row in sorted(million,key=lambda r:r['aliases'][0]):
        text.append(f"| {row['aliases'][0]} | {row['median_s']:.2f} | {row['minimum_s']:.2f}–{row['maximum_s']:.2f} | {row['max_VmHWM_bytes']} | {row['quality_status']} | {100*row['gap_bound']:.3f}% |")
    text.extend(['','SHEAFT-LIST-v1 получает маршруты и альтернативное оборудование без готового плана. '
        'Полное время включает запуск процесса, чтение компактного входа, построение назначений/очередей и полный вывод. '
        'Десять дополнительных диагностик на 10 тысячах операций выполнены до основной матрицы. '
        'Хеши входов, неизменного измеряемого кода, полного вывода и сведения каждой VM опубликованы в aps-processes.json.','',
        'Среда: GitHub-hosted Ubuntu 24.04, закреплённый Python 3.12 container, 1 CPU, cpuset 0, 4 GiB без дополнительного swap. '
        'Используется собственный пик VmHWM после exec, проверенный отдельно от памяти родительского процесса. '
        'Валидация ограничений, независимые нижние границы и DAG-воспроизведение выполнены после измерений. '
        'Одинаковый хеш расписания во всех трёх повторах каждой задачи проверен при сборке отчёта.','',
        'GAP_BOUNDED означает оценку качества через нижнюю границу; OPTIMAL_CERTIFIED означает совпадение Cmax с доказуемой границей. '
        'Первичные 24 задачи двух размеров дали 20 уникальных семантических входов. Таблица aliases сохраняет связь с исходными seed.','',
        'Эта матрица характеризует планировщик LIST, а не скорость проверки исполнения TSFG. '
        'Конечные буферы и общие ресурсы исследуются в отдельной PBR-серии. '
        'Как показали номинальные PBR-проверки, допустимый план APS-BASIC может блокироваться после добавления этих ограничений.','',
        'В архиве сохранены исходные ZIP с полными расписаниями всех 30 миллионных запусков. '
        'Полные компактные миллионные входы и их индексы также сохранены в '
        '[первом APS-архиве](https://github.com/'+REPO+'/releases/tag/revision-v2-aps-first-c2c51bbdecce).'])
    (out/'APS_MATRIX_REPORT_RU.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    market=['# APS: измерение и рыночная гипотеза','',
        'Согласованная гипотеза: «Sheaft способен сократить время построения крупных производственных планов '
        'по сравнению с классом APS; первый рыночный ориентир — BFG APS». Сопоставимость BFG с другими APS '
        'по вычислительной производительности остаётся допущением этой гипотезы.','',
        '| Показатель | Время | Основание |', '|---|---:|---|',
        '| BFG: миллион операций | 2700 с | Заявление поставщика |',
        f'| Sheaft: миллион операций | {n_value:.2f} с | Максимум медиан 10 входов × 3 повтора, APS-BASIC, все VALID |','',
        f'**2700/N = {ratio:.2f}** — отношение опубликованного времени BFG к нашему измерению. '
        'Это не коэффициент очного сравнения на одинаковых задачах. '
        '[Источник показателя BFG](https://bfg.ai/bfg-aps/).','',
        'Наши условия и качество раскрыты в APS_MATRIX_REPORT_RU.md. Для показателя поставщика не установлены '
        'совпадающие входы, оборудование, состав ограничений, критерий качества и методика измерения. '
        'BFG описывает дополнительные производственные ограничения, которые APS-BASIC не проверяет. '
        'Измеренный результат поддерживает дальнейшую проверку рыночной гипотезы; '
        'он не доказывает преимущество перед всем классом APS при одинаковом качестве и ограничениях.']
    (out/'APS_MARKET_COMPARISON_RU.md').write_text('\n'.join(market)+'\n',encoding='utf-8')
    hashes={str(p.relative_to(root)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob('*')) if p.is_file()}
    (root/'SHA256.json').write_text(json.dumps(hashes,indent=2)+'\n')
    print(json.dumps(status,ensure_ascii=False))


if __name__=='__main__':main()
