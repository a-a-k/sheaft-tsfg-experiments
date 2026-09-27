"""Generate a reproducible interim APS report from completed Actions evidence only."""
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.aps_million_gate_v2 import read_report
from scripts.aps_batch_v2 import report
from scripts.collect_evidence import api,artifacts,artifact_download

REPO='a-a-k/sheaft-tsfg-experiments'
RUNS=[36308210267,36308617954,36308875750,36309164491,36309782620]


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    root=Path('publication-input');raw=root/'raw';out=root/'report'
    raw.mkdir(parents=True,exist_ok=True);out.mkdir(exist_ok=True)
    collected=Path('collected');collected.mkdir(exist_ok=True)
    rows=[];sources=[]
    for run in RUNS:
        batch,source=read_report(run);rows.extend(batch);sources.append(source)
    assert len(rows)==42
    assert all(r['correctness_status']=='VALID' and r['performance_status']=='MEASURED' for r in rows)
    small=[r for r in rows if r['operation_count']==100000]
    large=[r for r in rows if r['operation_count']==1000000]
    assert len(small)==30 and len(large)==2
    assert len({r['task_sha256'] for r in small})==10
    for task in {r['task_sha256'] for r in small}:
        assert {r['repeat'] for r in small if r['task_sha256']==task}=={1,2,3}
    assert len({json.dumps(r['measurement_code_sha256'],sort_keys=True) for r in rows})==1
    for i,row in enumerate(rows):
        directory=collected/str(i);directory.mkdir(exist_ok=True)
        (directory/'validated.json').write_text(json.dumps(row))
    report(SimpleNamespace(root=collected,output=out,expected=42))
    downloads=[(36307972828,'aps-inputs-index-100k'),(36309476853,'aps-inputs-index-1m'),
               (36309476853,'aps-inputs-1m')]
    downloads.extend((36309782620,'aps-measured-'+r['task_sha256']) for r in large)
    for run,name in downloads:
        found=[a for a in artifacts(REPO,run) if a['name']==name and not a['expired']]
        assert len(found)==1
        target=raw/(name+'.zip');digest=artifact_download(REPO,found[0],target)
        sources.append(dict(run_id=run,artifact_id=found[0]['id'],name=name,artifact_sha256=digest,
            source_sha=api(f'repos/{REPO}/actions/runs/{run}')['head_sha']))
        if name.startswith('aps-measured-'):
            with zipfile.ZipFile(target) as archive:
                row=next(r for r in large if name.endswith(r['task_sha256']))
                with archive.open('schedule.jsonl') as file:
                    assert hashlib.file_digest(file,'sha256').hexdigest()==row['output_sha256']
        if name.startswith('aps-inputs-index-'):
            with zipfile.ZipFile(target) as archive:
                (out/(name+'.json')).write_bytes(archive.read('aps-inputs-index.json'))
    status=dict(execution_status='PARTIAL',first_APS_package='COMPLETE',
        diagnostic_valid=10,hundred_thousand_valid=30,million_valid=2,
        million_expected_after_deduplication=30,presentation_N_seconds=None,
        outstanding=['28 remaining million-operation APS measurements and validation',
                     '36 preliminary PBR results and admission estimates',
                     'Admitted large PBR series','Independent reserve holdout','Six PF diagnostics','Final completeness audit'],
        interpretation='First APS package completed; the revision campaign remains PARTIAL.')
    (out/'execution-status.json').write_text(json.dumps(status,indent=2)+'\n')
    (out/'evidence.json').write_text(json.dumps(dict(sources=sources,publication_source=os.environ['GITHUB_SHA']),indent=2)+'\n')
    lines=['# APS: первый пакет измерений по инструкции 2.2','',
        '**Первый пакет APS выполнен. Полная кампания 2.2 остаётся PARTIAL.**','',
        'SHEAFT-LIST-v1 строит назначения и очереди из маршрутов и альтернативного оборудования. '
        'Готовое расписание на вход планировщику не передаётся. Проверки допустимости и независимый DAG-пересчёт выполнены после измерения.','',
        'Завершены 10 диагностических запусков на 10 тысячах операций и 30 запусков на 100 тысячах: '
        '10 уникальных задач по три повтора на отдельных виртуальных машинах. Все результаты VALID. '
        'На миллионе операций пока выполнено по одному повтору F1/DENSE/s101 и F2/DENSE/s101.','',
        '| Задача | Полное время, с | Пиковая память, байт | Cmax, тики | Нижняя граница, тики | Верхняя граница разрыва с оптимумом |',
        '|---|---:|---:|---:|---:|---:|']
    for row in sorted(large,key=lambda r:r['family']):
        m=row['measurement'];q=row['quality']
        lines.append(f"| {row['family']} / DENSE / s101 | {m['T_total_s']:.2f} | {m['VmHWM_bytes']} | {q['Cmax_ticks']} | {q['LB_ticks']} | {100*q['gap_bound']:.3f}% |")
    lines.extend(['','Оба миллионных плана имеют статус GAP_BOUNDED. Это оценка качества через независимую нижнюю границу; '
        'оптимальность этих двух расписаний не установлена. Единица модельного времени — 0,01 секунды.','',
        'Условия измерения: GitHub-hosted Ubuntu 24.04; закреплённый контейнер Python 3.12; '
        'один CPU, cpuset 0, память 4 GiB без дополнительного swap. Полное время включает запуск процесса, '
        'чтение компактного входа, построение расписания и запись всех назначений и очередей. '
        'VmHWM берётся из /proc/self/status после exec; отдельная проверка счётчика выполнена до измерений. '
        'Модель CPU, версии, хеши кода и входов сохранены для каждого процесса в aps-processes.json.','',
        'Исходные 12 задач каждого размера сведены к 10 уникальным по хешу раскрытой семантики. '
        'Альтернативное оборудование хранится общим неизменяемым каталогом. Полные первичные наблюдения — '
        '[aps-processes.csv](aps-processes.csv), показатели качества — [aps-quality.csv](aps-quality.csv).','',
        'Долговременный архив содержит исходные ZIP с двумя полными миллионными расписаниями, '
        'все компактные миллионные входы, индексы задач, первичные наблюдения и хеши. '
        'Планы повторно моделировались только в первоначальной независимой валидации; этот отчёт собирается из сохранённых артефактов.','',
        'Эти измерения характеризуют планировщик LIST. Они не устанавливают вычислительное преимущество TSFG. '
        'Предыдущая кампания, включая отрицательные результаты TSFG и агрегации, сохраняется. '
        'Для проверки фиксированных очередей без конечных буферов и общих ресурсов DAG остаётся подходящим быстрым ядром продукта; '
        'для новой расширенной постановки сравниваются независимый DES-EXT и адаптер оригинального S1.','',
        'До завершения трёх повторов всей обязательной APS-матрицы сводное презентационное N неизвестно. '
        'Нельзя подменять его лучшим единичным временем.','',
        'Источники измерений: '+', '.join(f'[run {run}](https://github.com/{REPO}/actions/runs/{run})' for run in RUNS)+'.'])
    (out/'APS_FIRST_REPORT_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (out/'APS_MARKET_COMPARISON_RU.md').write_text('# APS: рыночный ориентир и границы сравнения\n\n'
        'Проверяемая рыночная гипотеза — возможность преимущества Sheaft перед классом APS; первым ориентиром выбран BFG. '
        'Поставщик сообщает о расчёте производственного плана на миллион операций за 45 минут. '
        '[Источник: BFG APS](https://bfg.ai/bfg-aps/).\n\n'
        'В нашей постановке APS-BASIC первые валидные миллионные планы получены за '
        +', '.join(f"{r['measurement']['T_total_s']:.2f} с ({r['family']})" for r in sorted(large,key=lambda r:r['family']))+
        '. Это по одному повтору на двух входах. Полная серия не завершена, сводное N пока null.\n\n'
        'Время поставщика и наши измерения относятся к разным экспериментальным условиям. '
        'Не установлены совпадение данных, оборудования, состава ограничений, целевой функции и качества плана. '
        'BFG описывает также дополнительные производственные ограничения, которые APS-BASIC не проверяет. '
        'Поэтому отношение 2700/N после получения N будет отношением опубликованных времён, '
        'а не результатом очного сравнения равных задач или доказательством преимущества перед всем классом APS.\n',encoding='utf-8')
    hashes={str(p.relative_to(root)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}
    (root/'SHA256.json').write_text(json.dumps(hashes,indent=2)+'\n')
    print(json.dumps(status))


if __name__=='__main__':main()
