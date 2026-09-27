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
parser.add_argument("--audit-baseline", action="store_true")
parser.add_argument("--g2-baseline", action="store_true")
args = parser.parse_args()
if args.upstream_test_evidence:
    evidence = json.loads(args.upstream_test_evidence.read_text())
    if evidence.get("source_commit") != commit or evidence.get("status") != "PASS" or evidence.get("tests_passed",0) < 157:
        raise SystemExit("Invalid upstream test evidence")
    if evidence.get("go_version") and evidence["go_version"] != subprocess.check_output(["go","version"],text=True).strip():
        raise SystemExit("Upstream evidence uses a different Go version")
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
pbr_adapter = Path('engines/tsfg_op/pbr_adapter.go')
shutil.copyfile(pbr_adapter, engine / 'cmd/ozon-engine/pbr_adapter.go')
audit_adapter = Path("engines/tsfg_op/audit_adapter.go")
shutil.copyfile(audit_adapter, engine / "cmd/ozon-engine/audit_adapter.go")
aggregate_adapter = Path("engines/tsfg_op/aggregate_adapter.go")
shutil.copyfile(aggregate_adapter, engine / "cmd/ozon-engine/aggregate_adapter.go")
binary = Path(".private/runtime/tsfg").resolve()
binary.parent.mkdir(parents=True, exist_ok=True)
result = subprocess.run(["go", "build", "-trimpath", "-o", str(binary), "./cmd/ozon-engine"],
                        cwd=engine, capture_output=True, text=True)
if result.returncode:
    for line in result.stderr.splitlines():
        if any(name in line for name in ("operation_adapter.go:", "extended_adapter.go:", "pbr_adapter.go:", "audit_adapter.go:", "aggregate_adapter.go:")):
            print(line)
    raise SystemExit("TSFG build failed; other private diagnostics omitted")
summary.update(go_version=subprocess.check_output(["go", "version"], text=True).strip(),
               adapter_sha256=hashlib.sha256(adapter.read_bytes()).hexdigest(),
               extended_adapter_sha256=hashlib.sha256(extended_adapter.read_bytes()).hexdigest(),
               pbr_adapter_sha256=hashlib.sha256(pbr_adapter.read_bytes()).hexdigest(),
               audit_adapter_sha256=hashlib.sha256(audit_adapter.read_bytes()).hexdigest(),
               aggregate_adapter_sha256=hashlib.sha256(aggregate_adapter.read_bytes()).hexdigest(),
               binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
               source_modified=False, public_binary=False)
(out / "tsfg-provenance.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary))
if args.g2_baseline:
    old_ref='1ffd2a2bd69e3c5e7fb0a9cc051b85e85d761617'
    private_adapter=engine/'cmd/ozon-engine/aggregate_adapter.go'
    previous=subprocess.check_output(['git','-c',f'safe.directory={Path.cwd()}',
                                     'show',f'{old_ref}:{aggregate_adapter.as_posix()}'])
    previous_binary=binary.with_name('tsfg-g2-v1')
    try:
        private_adapter.write_bytes(previous)
        build=subprocess.run(['go','build','-trimpath','-o',str(previous_binary),'./cmd/ozon-engine'],
                             cwd=engine,capture_output=True,text=True)
        if build.returncode:raise SystemExit('G2 baseline build failed; private diagnostics omitted')
        (out/'g2-v1-provenance.json').write_text(json.dumps(dict(
            source_commit=commit,aggregate_adapter_commit=old_ref,
            adapter_sha256=hashlib.sha256(previous).hexdigest(),
            binary_sha256=hashlib.sha256(previous_binary.read_bytes()).hexdigest(),source_modified=False),indent=2))
    finally:
        shutil.copyfile(aggregate_adapter,private_adapter)
if args.audit_baseline:
    baseline_ref = "2ade199735cf49eae328d8402b2b0a984b7d2e49"
    baseline_files = (adapter, extended_adapter, audit_adapter)
    try:
        for public in baseline_files:
            previous = subprocess.check_output(["git", "-c", f"safe.directory={Path.cwd()}",
                                                "show", f"{baseline_ref}:{public.as_posix()}"])
            (engine / "cmd/ozon-engine" / public.name).write_bytes(previous)
        previous_binary = binary.with_name("tsfg-baseline")
        result = subprocess.run(["go", "build", "-trimpath", "-o", str(previous_binary), "./cmd/ozon-engine"],
                                cwd=engine, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit("Audit baseline build failed; private diagnostics omitted")
        (out / "baseline-provenance.json").write_text(json.dumps(dict(
            source_commit=commit, public_adapter_commit=baseline_ref,
            binary_sha256=hashlib.sha256(previous_binary.read_bytes()).hexdigest(),
            source_modified=False, public_binary=False), indent=2)+"\n")
    finally:
        for public in baseline_files:
            shutil.copyfile(public, engine / "cmd/ozon-engine" / public.name)
