"""Separate-job correctness admission against physical-checked full DAG replay.

Every timed participant still wrote full SCHEDULE JSONL. Canonical SHA-256 binds
all required arrays; replay regenerates every row before it admits any point.
No success can be inferred from a hash without a completed independent replay.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.scale_data import read_binary, sha256
from validation.checks import SIGNATURE, validate_result


def main():
    if os.environ.get("GITHUB_ACTIONS")!="true":raise SystemExit("Actions only")
    p=argparse.ArgumentParser()
    p.add_argument("--dataset",type=Path,required=True)
    p.add_argument("--results",type=Path,required=True)
    args=p.parse_args()
    paths=sorted(args.results.glob("*/measurement.json"))
    if not paths:raise SystemExit("No measured processes")
    records=[json.loads(path.read_text()) for path in paths]
    scenario_path=paths[0].parent/"scenarios.json"
    scenarios=json.loads(scenario_path.read_text())
    manifest=json.loads((args.dataset/"manifest.json").read_text())
    fingerprint=sha256(args.dataset/"input.bin")
    assert fingerprint==manifest["files"]["input.bin"]
    assert all(r["input_sha256"]==fingerprint and r["scenarios_sha256"]==sha256(scenario_path) for r in records)
    assert all(r["K"]==len(scenarios) and r["mode"]=="MISSION" and r["output_profile"]=="SCHEDULE" for r in records)
    data=read_binary(args.dataset/"input.bin")
    replay=args.results/"independent-replay.jsonl"
    binary=Path("artifacts/build/simulator")
    build=json.loads(Path("artifacts/build/environment.json").read_text())
    assert sha256(binary)==build["binary_sha256"]
    binary.chmod(0o755)
    subprocess.run([str(binary),"dag",str(args.dataset/"input.bin"),str(scenario_path),str(replay),
                    "MISSION",str(manifest["metadata"]["D_ticks"]),"100"],check=True,timeout=1200)
    hashes=[]
    with replay.open() as stream:
        for i,line in enumerate(stream):
            row=json.loads(line)
            assert row["scenario_id"]==scenarios[i]["id"]
            validate_result(data,scenarios[i],row)
            if scenarios[i]["id"]=="M0":
                assert row["start"]==[o["planned_start"] for o in data["operations"]]
                assert row["finish"]==[o["planned_end"] for o in data["operations"]]
            hashes.append(hashlib.sha256(json.dumps({k:row[k] for k in SIGNATURE},sort_keys=True,separators=(",",":")).encode()).hexdigest())
    assert len(hashes)==len(scenarios)
    for path,record in zip(paths,records):
        signatures=record["signatures"]
        correct=len(signatures)<=len(hashes)
        correct&=all(s["scenario_id"]==scenarios[i]["id"] and s["sha256"]==hashes[i] for i,s in enumerate(signatures))
        record["validated_prefix_scenarios"]=len(signatures) if correct else 0
        record["completion_validated"]=correct and record["status"]=="OK" and len(signatures)==record["K"]
        record["validation_status"]="PASS" if record["completion_validated"] else "PARTIAL" if correct else "FAIL"
        record["validation_method"]="Independent full DAG replay + physical invariants + canonical SHA256 of every required field"
        if not correct:record["status"]="INCORRECT"
        path.write_text(json.dumps(record,indent=2))
    summary=dict(status="PASS" if all(r["validation_status"]!="FAIL" for r in records) else "FAIL",
        invariant_checks=len(hashes),measurements=len(records),completed_correct=sum(r["completion_validated"] for r in records),
        timeout=sum(r["status"]=="TIMEOUT" for r in records),reference="Fresh DAG process in separate job",
        signature_fields=list(SIGNATURE),replay_sha256=sha256(replay),scenario_signatures=hashes)
    (args.results/"validation.json").write_text(json.dumps(summary,indent=2))
    if summary["status"]=="PASS":replay.unlink()
    print(json.dumps({k:v for k,v in summary.items() if k!="scenario_signatures"}))
    if summary["status"]!="PASS":raise SystemExit(1)


if __name__=="__main__":main()
