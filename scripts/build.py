"""Build exactly once in the campaign, on a GitHub-hosted runner."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Builds are restricted to GitHub Actions")
out = Path("artifacts/build")
out.mkdir(parents=True, exist_ok=True)
sources = json.loads(Path("provenance/sources.json").read_text())["sources"]
for path, key in [(Path("fixtures/mk01/mk01.txt"), "mk01.txt"),
                  (Path("vendor/nlohmann/json.hpp"), "json.hpp")]:
    if hashlib.sha256(path.read_bytes()).hexdigest() != sources[key]["sha256"]:
        raise SystemExit("Source checksum mismatch: " + str(path))
flags = ["-std=c++20", "-O3", "-DNDEBUG", "-Wall", "-Wextra", "-Werror", "-Ivendor"]
command = ["g++", *flags, "engines/main.cpp", "engines/tsfg_op/grid.cpp",
           "engines/des_ref/des.cpp", "engines/dag_ref/dag.cpp", "-o", str(out / "simulator")]
subprocess.run(command, check=True)
subprocess.run(["g++", *flags, "engines/reserve_main.cpp", "engines/des_ref/des.cpp",
                "engines/dag_ref/dag.cpp", "-o", str(out / "reserve")], check=True)
environment = {
    "commit": os.environ["GITHUB_SHA"], "run_id": os.environ["GITHUB_RUN_ID"],
    "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    "run_url": f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
    "container": "python:3.12-bookworm@sha256:dbbe4ceb97851e2e5fa83798b239811f871cb743b259ba3563737349f6bcfaa0",
    "python": sys.version, "kernel": platform.release(), "machine": platform.machine(),
    "compiler": subprocess.check_output(["g++", "--version"], text=True),
    "flags": flags, "allowed_cpus": sorted(os.sched_getaffinity(0)),
    "image_version": os.environ.get("ImageVersion"),
    "cpuinfo": Path("/proc/cpuinfo").read_text(),
    "binary_sha256": hashlib.sha256((out / "simulator").read_bytes()).hexdigest(),
    "reserve_binary_sha256": hashlib.sha256((out / "reserve").read_bytes()).hexdigest(),
    "requirements_sha256": hashlib.sha256(Path("requirements.lock").read_bytes()).hexdigest(),
    "cgroup": {},
}
for name in ("memory.max", "memory.swap.max", "cpu.max", "cpuset.cpus.effective"):
    p = Path("/sys/fs/cgroup") / name
    if p.exists(): environment["cgroup"][name] = p.read_text().strip()
(out / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")
print("Built simulator", environment["binary_sha256"])
