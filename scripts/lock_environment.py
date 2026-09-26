"""Resolve the pinned research environment only inside GitHub Actions."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile
from email.parser import BytesParser

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Environment preparation is restricted to GitHub Actions")

root = Path("artifacts/bootstrap")
wheels = root / "wheels"
wheels.mkdir(parents=True, exist_ok=True)
subprocess.run([sys.executable, "-m", "pip", "download", "--only-binary=:all:",
                "--dest", str(wheels), "-r", "requirements.in"], check=True)
pins = []
for wheel in sorted(wheels.glob("*.whl")):
    with zipfile.ZipFile(wheel) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(name))
    pins.append(f"{metadata['Name']}=={metadata['Version']} --hash=sha256:"
                f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}")
(root / "requirements.lock").write_text("\n".join(sorted(pins, key=str.lower)) + "\n")

sources = {
    "mk01.txt": "https://raw.githubusercontent.com/SchedulingLab/fjsp-instances/"
                "f960b0b75b132488ddba9ec17a3b1ce77ab751db/brandimarte/mk01.txt",
    "json.hpp": "https://raw.githubusercontent.com/nlohmann/json/"
                "9cca280a4d0ccf0c08f47a99aa71d1b0e52f8d03/single_include/nlohmann/json.hpp",
}
manifest = {"github_run_id": os.environ["GITHUB_RUN_ID"], "sources": {}}
for name, url in sources.items():
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    (root / name).write_bytes(data)
    manifest["sources"][name] = {"url": url, "sha256": hashlib.sha256(data).hexdigest()}
(root / "sources.json").write_text(json.dumps(manifest, indent=2) + "\n")
(root / "compiler.txt").write_text(subprocess.check_output(["g++", "--version"], text=True))
print("Prepared immutable dependency pins and source provenance in Actions")

