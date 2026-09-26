"""Independent admission, outside engine timers, streamed scenario by scenario."""
import argparse
import gzip
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.scale_data import read_binary
from validation.checks import compare, validate_result


def main():
    if os.environ.get("GITHUB_ACTIONS")!="true":raise SystemExit("Actions only")
    p=argparse.ArgumentParser()
    p.add_argument("--dataset",type=Path,required=True)
    p.add_argument("--results",type=Path,required=True)
    args=p.parse_args()
    data=read_binary(args.dataset/"input.bin")
    paths=sorted(args.results.glob("*/measurement.json"))
    records=[json.loads(path.read_text()) for path in paths]
    reference=next((i for i,r in enumerate(records) if r["engine"]=="dag" and r["status"]=="OK"),None)
    if reference is None:reference=next((i for i,r in enumerate(records) if r["engine"]=="des" and r["status"]=="OK"),None)
    invariant_checks=0
    for index,(path,record) in enumerate(zip(paths,records)):
        scenarios=json.loads((path.parent/"scenarios.json").read_text())
        reference_file=None
        try:
            if reference is not None:reference_file=gzip.open(paths[reference].parent/"result.jsonl.gz","rt")
            with gzip.open(path.parent/"result.jsonl.gz","rt") as stream:
                count=0
                for line in stream:
                    row=json.loads(line)
                    assert row["scenario_id"]==scenarios[count]["id"]
                    validate_result(data,scenarios[count],row)
                    if scenarios[count]["id"]=="M0":
                        assert row["start"]==[o["planned_start"] for o in data["operations"]]
                        assert row["finish"]==[o["planned_end"] for o in data["operations"]]
                    invariant_checks+=1
                    if reference_file is not None:
                        expected=json.loads(next(reference_file))
                        compare(expected,row)
                    count+=1
            record["validated_prefix_scenarios"]=count
            record["completion_validated"]=(reference is not None and record["status"]=="OK" and count==record["K"])
            record["validation_status"]="PASS" if record["completion_validated"] else "PARTIAL"
        except Exception as error:
            record["validation_status"]="FAIL"
            record["validation_error"]=str(error)
            if record["status"]=="OK":record["status"]="INCORRECT"
        finally:
            if reference_file is not None:reference_file.close()
        path.write_text(json.dumps(record,indent=2))
    summary=dict(status="PASS" if all(r["validation_status"]!="FAIL" for r in records) else "FAIL",
                 invariant_checks=invariant_checks,measurements=len(records),
                 completed_correct=sum(r["completion_validated"] for r in records),
                 timeout=sum(r["status"]=="TIMEOUT" for r in records))
    (args.results/"validation.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary),flush=True)
    if summary["status"]=="FAIL":raise SystemExit(1)


if __name__=="__main__":main()
