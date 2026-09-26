"""Build unchanged private S1 plus public operation adapter, only on Actions."""
import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Actions only")
source = Path(".private/upstream")
commit = "8510baf28673758f1e437d2dbc5a51ead9843a3b"
actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
if actual != commit:
    raise SystemExit("Wrong TSFG source commit")
engine = source / "engine"
parser = argparse.ArgumentParser()
parser.add_argument("--upstream-test-evidence", type=Path)
args = parser.parse_args()
if args.upstream_test_evidence:
    evidence = json.loads(args.upstream_test_evidence.read_text())
    if evidence.get("source_commit") != commit or evidence.get("status") != "PASS" or evidence.get("tests_passed",0) < 157:
        raise SystemExit("Invalid upstream test evidence")
    summary = dict(evidence, reused_test_evidence=True,
                   evidence_sha256=hashlib.sha256(args.upstream_test_evidence.read_bytes()).hexdigest())
else:
    result = subprocess.run(["go", "test", "-json", "./..."], cwd=engine, capture_output=True, text=True)
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    summary = {"source_commit": commit, "status": "PASS" if result.returncode == 0 else "FAIL",
               "tests_passed": sum(e.get("Action") == "pass" and bool(e.get("Test")) for e in events)}
out = Path("artifacts/build")
out.mkdir(parents=True, exist_ok=True)
(out / "upstream-tests.json").write_text(json.dumps(summary, indent=2) + "\n")
if summary["status"] != "PASS":
    raise SystemExit("Upstream regression tests failed; private diagnostics omitted")
adapter = Path("engines/tsfg_op/operation_adapter.go")
shutil.copyfile(adapter, engine / "cmd/ozon-engine/operation_adapter.go")
extended_adapter = Path("engines/tsfg_op/extended_adapter.go")
shutil.copyfile(extended_adapter, engine / "cmd/ozon-engine/extended_adapter.go")
binary = Path(".private/runtime/tsfg").resolve()
binary.parent.mkdir(parents=True, exist_ok=True)
result = subprocess.run(["go", "build", "-trimpath", "-o", str(binary), "./cmd/ozon-engine"],
                        cwd=engine, capture_output=True, text=True)
if result.returncode:
    for line in result.stderr.splitlines():
        if "operation_adapter.go:" in line or "extended_adapter.go:" in line:
            print(line)
    raise SystemExit("TSFG build failed; other private diagnostics omitted")
summary.update(go_version=subprocess.check_output(["go", "version"], text=True).strip(),
               adapter_sha256=hashlib.sha256(adapter.read_bytes()).hexdigest(),
               extended_adapter_sha256=hashlib.sha256(extended_adapter.read_bytes()).hexdigest(),
               binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
               source_modified=False, public_binary=False)
(out / "tsfg-provenance.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary))
