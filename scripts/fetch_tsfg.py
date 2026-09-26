"""Fetch the authorized private dependency with the existing read-only key."""
import os
from pathlib import Path
import subprocess
import tempfile

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Actions only")
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    key = root / "source_key"
    key.write_text(os.environ.pop("TSFG_SOURCE_SSH_KEY").replace("\r", "").strip()+"\n")
    key.chmod(0o600)
    # Correct the literal two-quote passphrase passed by Windows ssh-keygen.
    # This only normalizes the already-authorized key in runner temporary storage.
    normalized = False
    for old_passphrase in ('', '""'):
        result = subprocess.run(["ssh-keygen", "-p", "-P", old_passphrase, "-N", "", "-f", str(key)],
                                capture_output=True)
        if result.returncode == 0:
            normalized = True
            break
    if not normalized:
        raise SystemExit("Cannot load the read-only source key; secret content omitted")
    hosts = root / "known_hosts"
    hosts.write_text("github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n")
    source = Path(".private/upstream")
    source.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GIT_SSH_COMMAND": f"ssh -i {key} -o IdentitiesOnly=yes -o BatchMode=yes "
           f"-o StrictHostKeyChecking=yes -o HostKeyAlgorithms=ssh-ed25519 -o UserKnownHostsFile={hosts}"}
    commands = [["git","init","--quiet",str(source)],
                ["git","-C",str(source),"fetch","--quiet","--depth=1",
                 "git@github.com:a-a-k/ozone-tech_mb3r_lab_1084.git",
                 "8510baf28673758f1e437d2dbc5a51ead9843a3b"],
                ["git","-C",str(source),"checkout","--quiet","--detach","FETCH_HEAD"]]
    for command in commands:
        result = subprocess.run(command, env=env, capture_output=True)
        if result.returncode:
            raise SystemExit("Private TSFG fetch failed; authentication details omitted")
print("Pinned private TSFG source fetched; temporary key removed")
