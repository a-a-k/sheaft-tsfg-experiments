"""Collect the completed first package, including every blocked nominal input."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.collect_evidence import api,artifacts,artifact_download
from scripts.pbr_batch_v2 import report
from types import SimpleNamespace

RUNS=[36311024572,36311244860,36311541782,36311760421,36312122851,36312383270]
REPO='a-a-k/sheaft-tsfg-experiments'


def get(run_id,name,folder):
    run=api(f'repos/{REPO}/actions/runs/{run_id}');assert run['conclusion']=='success'
    item=next(a for a in artifacts(REPO,run_id) if a['name']==name and not a['expired'])
    path=folder/f'{run_id}-{name}.zip';digest=artifact_download(REPO,item,path)
    return path,dict(run_id=run_id,source_sha=run['head_sha'],artifact_id=item['id'],name=name,sha256=digest)


def main():
    assert os.environ.get('GITHUB_ACTIONS')=='true'
    root=Path('first-package');raw=root/'raw';out=root/'report';raw.mkdir(parents=True,exist_ok=True);out.mkdir(exist_ok=True)
    rows=[];evidence=[]
    for run in RUNS:
        path,source=get(run,'pbr-screen-batch-report',raw);evidence.append(source)
        with zipfile.ZipFile(path) as archive:batch=json.loads(archive.read('pbr-screen.json'))
        rows.extend(batch)
        for row in batch:
            _,source=get(run,'pbr-screen-'+row['id'],raw);evidence.append(source)
    assert len(rows)==36 and len({r['id'] for r in rows})==36
    assert all(r['execution_status']=='COMPLETE' and r['correctness_status']=='VALID' for r in rows)
    collected=Path('collected');collected.mkdir(exist_ok=True)
    for row in rows:
        folder=collected/row['id'];folder.mkdir(exist_ok=True);(folder/'screen.json').write_text(json.dumps(row))
    report(SimpleNamespace(root=collected,output=out))
    for run,name in [(36310562250,'pbr-rational-controls'),(36311747232,'fluid-diagnostic-v2'),(36311526885,'fluid-diagnostic-v2')]:
        path,source=get(run,name,raw);evidence.append(source)
        with zipfile.ZipFile(path) as archive:
            target='pbr-mk01/pbr-admission.json' if name=='pbr-rational-controls' else 'pf/flow-admission.json'
            (out/('pbr-admission.json' if name=='pbr-rational-controls' else f'flow-admission-{run}.json')).write_bytes(archive.read(target))
    status=dict(execution_status='COMPLETE',scope='First package PR1-4; PF diagnostics also available',
        campaign_execution_status='PARTIAL',PBR_preliminary_inputs=36,
        K10_complete=sum(r.get('K10_status')=='COMPLETE_VALID' for r in rows),
        nominal_deadlocks=[r['id'] for r in rows if r.get('nominal_status')=='DEADLOCK'],
        strong_controls=[r['id'] for r in rows if r.get('control_status')=='STRONG_CONTROL'],
        weak_controls=[r['id'] for r in rows if r.get('control_status')=='WEAK_CONTROL'],
        outstanding=['Remaining million APS repeats','Large admitted PBR pairs and explicit gates',
                     'Independent reserve holdout and fixed-family Holm analysis','Final evidence and budget audit'])
    (out/'execution-status.json').write_text(json.dumps(status,indent=2)+'\n')
    (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    text=['# Первый пакет Sheaft v2.2','',
        '**Первый пакет обработан полностью. Общая кампания остаётся PARTIAL.**','',
        'E4 сохранена в [долговременном архиве](https://github.com/'+REPO+'/releases/tag/revision-v2-e4-1bab7db283f5). '
        'Повторный анализ выпуска выполнен без моделирования; прежняя H5 не пересматривается.','',
        'APS: 30 валидных измерений на 100 тысячах операций и первые два миллионных плана '
        'опубликованы в [отдельном отчёте и архиве](https://github.com/'+REPO+'/releases/tag/revision-v2-aps-first-c2c51bbdecce). '
        'Полная APS-матрица выполняется отдельно.','',
        'PBR: ручные случаи, прежняя регрессия, 135 комбинированных сценариев Mk01 и 405 проверок состояния '
        'к сроку прошли сопоставление Fraction / DES-EXT / оригинального S1 с адаптером.','',
        f"Обработаны все 36 предварительных экземпляров. K=10 выполнено и сопоставлено для {status['K10_complete']}; "
        f"у {len(status['nominal_deadlocks'])} доказана номинальная взаимная блокировка. Для них K=10 не запускалось: "
        'это NO_ADMISSIBLE_INPUT, а не нулевое время или неудачный отказной сценарий. '
        'Оба движка согласны по индивидуальным состояниям; очереди не заменялись.','',
        f"Сильных контролей: {len(status['strong_controls'])}; слабых: {len(status['weak_controls'])}. "
        'Сильный контроль требует одновременно ожидания ресурса, удержания станка после обработки '
        'и прослеженной связи между ними. Ёмкости и seed после просмотра результатов не менялись.','',
        '| Вход | K10 | Класс контроля | TSFG, с | DES, с |', '|---|---|---|---:|---:|']
    for row in rows:
        times={p['engine']:p['T_total_s'] for p in row['processes'] if p['label']=='K10-standalone'}
        fmt=lambda name:f"{times[name]:.3f}" if name in times else '—'
        text.append(f"| {row['id']} | {row['K10_status']} | {row.get('control_status','NO_ADMISSIBLE_INPUT')} | {fmt('tsfg')} | {fmt('des')} |")
    text.extend(['','Это предварительные измерения на разных VM. Внешний таймер опрашивает процесс с периодом 20 мс; '
        'для коротких DES-процессов эта дискретность заметна. Их нельзя использовать как точный парный коэффициент. '
        'В основных больших парных опытах используется уведомление Linux pidfd без такой дискретности.','',
        'F1/DENSE с разными исходными seed может иметь одинаковую семантику: совпадения хешей публикуются. '
        'Три обозначения seed сами по себе не доказывают разнообразие производственных входов.','',
        'PF: после исправления масштаба времени шесть фиксированных непрерывных потоковых случаев прошли допуск, '
        'ложных успехов на детерминированной сетке нет. Первый запуск фактически использовал шаг 0,1 с '
        'вместо 0,005 с; его артефакты сохранены как ошибка реализации шага. Исправленный запуск проверяет '
        'фактический шаг каждого вызова S1. Это не доказательство точности дискретного производства и не замер ускорения.','',
        'Ограничение продукта: быстрый APS-BASIC строит план для своей постановки, но его фиксированные очереди '
        'могут оказаться невыполнимыми при добавлении конечных буферов. Проверка исполнения и построение плана '
        'с учётом этих ограничений остаются разными функциями. DAG сохраняет область применения прежней модели.'])
    (out/'FIRST_PACKAGE_REPORT_RU.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    hashes={str(p.relative_to(root)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob('*')) if p.is_file()}
    (root/'SHA256.json').write_text(json.dumps(hashes,indent=2)+'\n')
    print(json.dumps(status))


if __name__=='__main__':main()
