"""Predeclared E2/H3 decision rules; missing points cannot improve the verdict."""
import argparse
import csv
import itertools
import json
import math
import os
from pathlib import Path
import re


def main():
    if os.environ.get("GITHUB_ACTIONS")!="true":raise SystemExit("Actions only")
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--stage",choices=["screen","main"],required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    records=[]
    for path in args.input.glob("**/measurements/*/measurement.json"):
        record=json.loads(path.read_text())
        match=re.fullmatch(r"(F[12])-(DENSE|SPARSE)-N(\d+)-M200-s(\d+)",record["dataset_id"])
        if not match:continue
        family,density,n,seed=match.groups()
        record.update(family=family,density=density,n=int(n),seed=int(seed),
                      runner_round=int(record["label"].split("-")[1]) if record["label"].startswith("round-") else 0)
        baseline=path.parents[2]/"baseline"/"validation.json"
        record["baseline_admitted"]=baseline.exists() and json.loads(baseline.read_text()).get("completed_correct")==3
        records.append(record)
    columns=("dataset_id","family","density","n","seed","runner_round","engine","K","status", "completion_validated",
             "baseline_admitted","scenarios_completed","T_total_s","T_batch_s","rss_peak_bytes","cpu_s","commit","run_id")
    with (args.output/"measurements.csv").open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader()
        for record in records:
            row={k:record.get(k) for k in columns};row["T_batch_s"]=record.get("engine_meta",{}).get("T_batch_with_output_s")
            writer.writerow(row)
    summary=dict(stage=args.stage,records=len(records),correct_complete=sum(r["completion_validated"] for r in records),
                 timeouts=sum(r["status"]=="TIMEOUT" for r in records),decisions=[])
    if args.stage=="screen":
        expected={(f,d,n,s) for f,d,n,s in itertools.product(("F1","F2"),("DENSE","SPARSE"),(1000,10000,100000,1000000),(101,102,103))}
        present={(r["family"],r["density"],r["n"],r["seed"]) for r in records}
        summary.update(expected_datasets=48,datasets_present=len(present),missing_datasets=sorted(expected-present))
        # Publish a conservative process budget before launching main; cap is not a predicted runtime.
        estimate=0;terms=[]
        for dataset in sorted(expected):
            f,d,n,s=dataset
            if n<100000:continue
            for engine in ("tsfg","des","dag"):
                candidates=[r for r in records if (r["family"],r["density"],r["n"],r["seed"],r["engine"])==(*dataset,engine)]
                value=300
                if len(candidates)==1 and candidates[0]["status"]=="OK":
                    r=candidates[0];meta=r.get("engine_meta",{})
                    value=min(300,meta.get("T_import_s",0)+meta.get("T_build_s",0)+10*meta.get("T_batch_with_output_s",300))
                estimate+=6*value # two repeats, three independently allocated rounds
                terms.append(dict(family=f,density=d,n=n,seed=s,engine=engine,predicted_capped_process_s=value))
        summary["main_budget"]=dict(extrapolated_process_runner_hours=estimate/3600,
            extrapolated_process_wall_hours_at_two_workers=estimate/7200,
            hard_process_runner_hours=36,job_limit_runner_hours=72,
            assumptions="Linear K=10 to K=100 extrapolation capped at 300 s; setup, generation, validation, transfer and queues are additional.",terms=terms)
    else:
        for family,density,n,reference in itertools.product(("F1","F2"),("DENSE","SPARSE"),(100000,1000000),("des","dag")):
            points=[];missing=[]
            for seed,rr in itertools.product((101,102,103),(0,1,2)):
                group=[r for r in records if (r["family"],r["density"],r["n"],r["seed"],r["runner_round"],r["K"])==(family,density,n,seed,rr,100)]
                a=[r for r in group if r["engine"]=="tsfg"];b=[r for r in group if r["engine"]==reference]
                eligible=len(a)==2 and len(b)==2 and all(r["status"]=="OK" and r["completion_validated"] and r["baseline_admitted"] for r in a+b)
                eligible&=len({r["input_sha256"] for r in a+b})==1 and len({r["scenarios_sha256"] for r in a+b})==1
                eligible&=len({r["commit"] for r in a+b})==1 and len({r["run_id"] for r in a+b})==1
                if not eligible:
                    missing.append(dict(seed=seed,runner_round=rr,statuses=[r["status"] for r in a+b],
                                        reason="Missing, incomplete, incorrect or unadmitted mandatory pair"))
                    continue
                def ratio(key):
                    values=[r["engine_meta"]["T_batch_with_output_s"] if key=="batch" else r["T_total_s"] for r in b+a]
                    return math.sqrt(values[0]*values[1]/values[2]/values[3])
                points.append(dict(seed=seed,runner_round=rr,S_batch=ratio("batch"),S_total=ratio("total")))
            decision=dict(family=family,density=density,n=n,reference=reference,points=points,missing=missing,
                          status="INSUFFICIENT_COMPLETED")
            if not missing:
                g=math.exp(sum(math.log(p["S_batch"]) for p in points)/9)
                by_round=[math.exp(sum(math.log(p["S_batch"]) for p in points if p["runner_round"]==rr)/3) for rr in (0,1,2)]
                gt=math.exp(sum(math.log(p["S_total"]) for p in points)/9)
                tr=[math.exp(sum(math.log(p["S_total"]) for p in points if p["runner_round"]==rr)/3) for rr in (0,1,2)]
                decision.update(G=g,G_round=by_round,G_total=gt,G_total_round=tr,
                                status="SUPPORTED" if g>=2 and min(by_round)>1 else "NOT_SUPPORTED",
                                total_advantage=gt>1 and min(tr)>1)
            summary["decisions"].append(decision)
    (args.output/"summary.json").write_text(json.dumps(summary,indent=2))
    lines=[f"# E2: {args.stage}","",f"Сохранено процессов: {len(records)}. Завершённых корректных: {summary['correct_complete']}. Таймаутов: {summary['timeouts']}.",""]
    if args.stage=="screen":
        b=summary["main_budget"]
        lines += [f"Наборов: {summary['datasets_present']}/48. H3 здесь не принимается.","",
                  f"Экстраполяция измеряемых процессов основной серии: {b['extrapolated_process_runner_hours']:.2f} runner-часа; при двух одновременных процессах — {b['extrapolated_process_wall_hours_at_two_workers']:.2f} часа.",
                  "Подготовка, проверка, передача файлов и очередь добавляются отдельно. Это прогноз по K=10, а не гарантированный срок."]
    else:
        lines += ["| Область | N | Эталон | Решение | G |","|---|---:|---|---|---:|"]
        for d in summary["decisions"]:
            lines.append(f"| {d['family']}/{d['density']} | {d['n']} | {d['reference']} | {d['status']} | {d.get('G','—')} |")
        lines += ["","Отсутствующие точки и таймауты не заменены лимитами или средними завершённых подмножеств."]
    (args.output/"REPORT_RU.md").write_text("\n".join(lines)+"\n")
    print(json.dumps({k:v for k,v in summary.items() if k not in ("main_budget","decisions")},ensure_ascii=False))


if __name__=="__main__":main()
