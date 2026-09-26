"""Admission-control tests: true equality, corrupted hash, and censored prefix."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.scale_run import run_one


def main():
    if os.environ.get("GITHUB_ACTIONS")!="true":raise SystemExit("Actions only")
    root=Path("artifacts/replay-core");root.mkdir(parents=True,exist_ok=True)
    data=root/"dataset"
    subprocess.run([sys.executable,"experiments/scale_data.py","--n","1000","--family","F2", "--seed","902","--output",str(data)],check=True)
    rows=root/"valid"
    for engine in ("tsfg","des","dag"):
        run_one(data,engine,5,rows/engine,label="admission-positive-control",retain_trace=False)
    command=[sys.executable,"validation/scale_replay.py","--dataset",str(data),"--results"]
    subprocess.run([*command,str(rows)],check=True)
    assert json.loads((rows/"validation.json").read_text())["completed_correct"]==3
    for kind in ("corrupt","timeout"):
        folder=root/kind
        shutil.copytree(rows,folder)
        path=folder/"tsfg"/"measurement.json"
        record=json.loads(path.read_text());record["label"]="SYNTHETIC-ADMISSION-NEGATIVE-CONTROL"
        if kind=="corrupt":record["signatures"][2]["sha256"]="0"*64
        else:
            record.update(status="TIMEOUT",signatures=record["signatures"][:2],scenarios_completed=2,T_total_s=None)
        path.write_text(json.dumps(record))
        result=subprocess.run([*command,str(folder)])
        after=json.loads(path.read_text())
        if kind=="corrupt":assert result.returncode!=0 and after["status"]=="INCORRECT"
        else:assert result.returncode==0 and after["validation_status"]=="PARTIAL" and after["validated_prefix_scenarios"]==2
        assert not after["completion_validated"]
    (root/"summary.json").write_text(json.dumps(dict(status="PASS",positive_processes=3,
        negative_controls=["corrupted required-field digest rejected","timeout prefix cannot admit full K"]),indent=2))


if __name__=="__main__":main()
