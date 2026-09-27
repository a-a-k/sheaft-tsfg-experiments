"""Post-hoc E4 output analysis using only verified saved records."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.preserve_e4_v2 import digest


def validate(evidence, scenarios, frozen, jobs):
    assert evidence['status'] == 'PASS' and evidence['engines'] == ['dag', 'des']
    assert evidence['targets'] == [-1, *frozen['T'], *frozen['B']]
    assert evidence['time_scale'] == 11
    assert evidence['D_scaled_ticks'] == frozen['common_D_ticks'] * 11
    rows = evidence['records']
    assert len(rows) == len(scenarios) == 1000
    ids = [r['scenario_id'] for r in rows]
    assert len(set(ids)) == len(ids) and ids == [s['id'] for s in scenarios]
    for row in rows:
        assert row['exact_engine_agreement'] is True
        assert all(len(row[key]) == 7 for key in ('outcomes', 'produced_jobs', 'cmax_scaled_ticks'))
        for count, outcome, end in zip(row['produced_jobs'], row['outcomes'], row['cmax_scaled_ticks']):
            assert type(count) is int and 0 <= count <= jobs
            assert type(outcome) is bool and outcome == (count == jobs)
            if outcome:
                assert type(end) is int and 0 <= end <= evidence['D_scaled_ticks']
            else:
                assert end is None, 'MISSION cannot supply a full completion time for an incomplete plan'
    return rows


def paired_summary(values, source=None, replicas=10000, indices=None):
    """Columns retain their pairing: every draw selects whole scenario rows."""
    values = np.asarray(values, dtype=np.float64)
    assert values.ndim == 2 and len(values) > 0
    boots = []
    for begin in range(0, replicas, 100):
        selected = (source.integers(0, len(values), size=(min(100, replicas-begin), len(values)))
                    if indices is None else indices[begin:begin+100])
        boots.append(values[selected].mean(axis=1))
    bounds = np.quantile(np.concatenate(boots), [.025, .975], axis=0, method='linear')
    return [dict(mean=float(col.mean()), median=float(np.median(col)),
                 improved_fraction=float((col > 0).mean()), worsened_fraction=float((col < 0).mean()),
                 unchanged_fraction=float((col == 0).mean()), ci95=bounds[:, k].tolist())
            for k, col in enumerate(values.T)]


def analyze(evidence, scenarios, frozen, jobs, family, law, indices_path=None):
    rows = validate(evidence, scenarios, frozen, jobs)
    task_sha256 = frozen['dataset_sha256']
    seed_text = f'20260927|2.2|{task_sha256}|e4_reanalysis_bootstrap:{family}:{law}|all'
    seed = int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], 'little')
    source = np.random.Generator(np.random.PCG64(seed))
    indices = source.integers(0, len(rows), size=(10000, len(rows)), dtype=np.uint16)
    if indices_path is not None:
        np.save(indices_path, indices, allow_pickle=False)
    produced = np.asarray([r['produced_jobs'] for r in rows], dtype=np.int64)
    differences = produced[:, 1:] - produced[:, [0]]
    effects = paired_summary(differences, indices=indices)
    cmax = [r['cmax_scaled_ticks'] for r in rows]
    complete_all = all(all(c is not None for c in row) for row in cmax)
    if complete_all:
        # Positive means improvement for both metrics. Original time unit is
        # 0.01 s, and reserve_main transformed all times by another factor 11.
        cmax = np.asarray(cmax, dtype=np.int64)
        reductions = (cmax[:, [0]] - cmax[:, 1:]) / 1100
        time_effects = paired_summary(reductions, indices=indices)
    else:
        time_effects = [None] * 6
    configurations = []
    for k, target in enumerate(evidence['targets'][1:]):
        fraction_effect = dict(effects[k], mean=effects[k]['mean']/jobs, median=effects[k]['median']/jobs,
                               ci95=[v/jobs for v in effects[k]['ci95']])
        configurations.append(dict(machine=target, group='T' if k < 3 else 'B',
            produced_jobs_effect=effects[k], mean_output_fraction=float(produced[:, k+1].mean()/jobs),
            output_fraction_effect=fraction_effect,
            mission_success_fraction=float((produced[:, k+1] == jobs).mean()),
            cmax_reduction_seconds=time_effects[k]))
    return dict(family=family, law=law, status='DERIVED_FROM_SAVED_OUTPUT',
        analysis='POST_HOC_EXPLORATORY', original_H5='NOT_SUPPORTED', scenarios=len(rows), jobs=jobs,
        baseline_mean_produced_jobs=float(produced[:, 0].mean()),
        baseline_mission_success_fraction=float((produced[:, 0] == jobs).mean()),
        task_sha256=task_sha256, task_hash_definition='SHA256 of original fixed-plan input.bin',
        bootstrap=dict(unit='whole scenario record, all configurations together', method='percentile',
                       replicas=10000, seed_text=seed_text, seed=seed, coverage='pointwise, no multiplicity claim'),
        cmax_status='ALL_KNOWN' if complete_all else 'UNKNOWN_FOR_INCOMPLETE_MISSIONS',
        configurations=configurations)


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Actions only')
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    index = json.loads((args.source / 'evidence-v2.json').read_text())
    results = []
    for entry in index['entries']:
        for name, expected in entry['files'].items():
            assert digest(args.source / 'extracted' / name) == expected
        root = args.source / 'extracted' / 'e4' / entry['family']
        with (root / 'input.bin').open('rb') as file:
            assert file.read(8) == b'TSFGBIN1'
            operations, jobs, machines = struct.unpack('<III', file.read(12))
        assert (operations, jobs, machines) == (100000, 10000, 200)
        frozen = json.loads((root / 'frozen-interventions.json').read_text())
        for law in ('independent', 'common-cause'):
            saved = json.loads((root / f'evaluation-{law}.json').read_text())
            if entry['family'] == 'F2' and law == 'independent':
                first = saved['records'][0]
                assert first['scenario_id'] == 'h5_evaluation-0000'
                assert first['produced_jobs'][0] == 7038
                assert first['produced_jobs'][saved['targets'].index(193)] == 7220
            indices_path = args.output / f"bootstrap-{entry['family']}-{law}.npy"
            result = analyze(saved,
                             json.loads((root / f'scenarios-{law}.json').read_text()),
                             frozen, jobs, entry['family'], law, indices_path)
            result.update(source_artifact=entry['id'], source_archive_sha256=entry['sha256'],
                          evidence_sha256=digest(root / f'evaluation-{law}.json'),
                          bootstrap_indices_sha256=digest(indices_path), numpy_version=np.__version__)
            results.append(result)
    summary = dict(status='COMPLETE', simulations_run=0, regions=results,
        limitation='Post-hoc output effects do not revise H5; pointwise intervals are not confirmatory tests. '
                   'Zero sample effect and degenerate bootstrap intervals do not establish population equivalence.')
    (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    fields = ['family', 'law', 'group', 'machine', 'baseline_mean_jobs', 'mean_effect_jobs',
              'median_effect_jobs', 'improved_fraction', 'worsened_fraction', 'ci95_low', 'ci95_high',
              'cmax_reduction_seconds', 'cmax_ci95_low', 'cmax_ci95_high',
              'mean_effect_fraction', 'median_effect_fraction', 'ci95_fraction_low', 'ci95_fraction_high', 'unchanged_fraction']
    report = ['# E4: повторный анализ сохранённого выпуска', '',
        'Дополнительный исследовательский анализ после просмотра исходных результатов. '
        'Повторных запусков движков: 0. Прежняя H5 остаётся неподтверждённой.', '',
        'Эффект выпуска: усиление минус исходная конфигурация; положительное значение означает улучшение. '
        'Интервалы: парный percentile-bootstrap, 10 000 повторов, целая сценарная запись. '
        'Показаны отдельные 95% интервалы без поправки на множественные сравнения.', '',
        '| Семейство / отказы | Группа / станок | Средний выпуск без усиления | Средний эффект, заказов | 95% интервал | Улучшение / ухудшение |',
        '|---|---|---:|---:|---|---|']
    with (args.output / 'e4-output-reanalysis.csv').open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for region in results:
            for config in region['configurations']:
                effect, timing = config['produced_jobs_effect'], config['cmax_reduction_seconds']
                writer.writerow(dict(family=region['family'], law=region['law'], group=config['group'], machine=config['machine'],
                    baseline_mean_jobs=region['baseline_mean_produced_jobs'], mean_effect_jobs=effect['mean'],
                    median_effect_jobs=effect['median'], improved_fraction=effect['improved_fraction'],
                    worsened_fraction=effect['worsened_fraction'], ci95_low=effect['ci95'][0], ci95_high=effect['ci95'][1],
                    cmax_reduction_seconds=timing['mean'] if timing else None,
                    cmax_ci95_low=timing['ci95'][0] if timing else None, cmax_ci95_high=timing['ci95'][1] if timing else None,
                    mean_effect_fraction=effect['mean']/region['jobs'], median_effect_fraction=effect['median']/region['jobs'],
                    ci95_fraction_low=effect['ci95'][0]/region['jobs'], ci95_fraction_high=effect['ci95'][1]/region['jobs'],
                    unchanged_fraction=effect['unchanged_fraction']))
                report.append(f"| {region['family']} / {region['law']} | {config['group']} / {config['machine']} | "
                    f"{region['baseline_mean_produced_jobs']:.3f} | {effect['mean']:.3f} | "
                    f"[{effect['ci95'][0]:.3f}; {effect['ci95'][1]:.3f}] | "
                    f"{effect['improved_fraction']:.1%} / {effect['worsened_fraction']:.1%} |")
    report += ['', 'Полные сроки сравниваются только если они известны во всех записях области. '
        'Неизвестные сроки остаются null; сроки не подменяются D. Для известных сроков масштаб ×11 '
        'и исходные тики 0,01 с преобразованы в секунды; положительный эффект означает сокращение срока. '
        'Эти оценки приведены в e4-output-reanalysis.csv и summary.json. Группа B — низ старого ранжирования, '
        'а не новый контроль по загрузке.', '',
        'Нулевой выборочный эффект и вырожденный интервал не доказывают нулевой эффект в генеральной совокупности.', '']
    (args.output / 'REUSE_REPORT_V2_RU.md').write_text('\n'.join(report), encoding='utf-8')
    derived = dict(index)
    derived['entries'] = [*index['entries'], *[dict(status=r['status'], family=r['family'], law=r['law'],
        artifact_id=r['source_artifact'], input_sha256=r['task_sha256'], output_sha256=r['evidence_sha256'],
        semantics='P0 v1.1', engine_commit=index['source_run']['head_sha'],
        reason='Paired output differences derived without simulation') for r in results]]
    (args.output / 'evidence-v2.json').write_text(json.dumps(derived, indent=2) + '\n')
    checksums = {p.name: digest(p) for p in args.output.iterdir() if p.is_file() and p.name != 'SHA256.json'}
    (args.output / 'SHA256.json').write_text(json.dumps(checksums, indent=2) + '\n')
    print(json.dumps(dict(status=summary['status'], regions=len(results), simulations_run=0)))


if __name__ == '__main__':
    main()
