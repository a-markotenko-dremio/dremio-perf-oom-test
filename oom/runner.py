"""The real runs: deploys the container of a combination, runs the test in it and tells a heap OOM from other failures."""
import os
import re
import shutil
import subprocess
import time

import defaults
from .model import ERROR, FAIL, PASS

ROOT = defaults.ROOT_DIR
# Dremio's own heap monitor cancels the query ("Heap monitor detected that the heap is almost full",
# OutOfHeapMemoryException) before the JVM throws; the JVM errors cover a heap that filled up faster.
HEAP_OOM = re.compile(r"OutOfHeapMemoryException|Heap monitor detected that the heap is almost full"
                      r"|OutOfMemoryError: (Java heap space|GC overhead limit exceeded)")


def container_cli():
    for cli in ("incus", "lxc"):
        if shutil.which(cli):
            return cli
    raise SystemExit("neither incus nor lxc found in PATH")


def container_name(combo, args):
    """The name deploy_dremio.sh builds by default (the same shell function)."""
    script = 'source scripts/lib/common.sh; JAVA_IMAGE=$1; default_container_name "$2" "$(java_label)" "$3" "$4"'
    return subprocess.run(["bash", "-c", script, "_", combo.image, combo.package, str(args.container_mb), str(args.cpus)],
                          cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


class Runner:
    """Deploys the container of a combination for a heap size and runs the test in it.

    One container serves all runs of a heap step; it is deployed again after a run that did not pass, as
    the JVM of a Dremio that hit an OOM is not in a state to measure anything."""

    def __init__(self, args, combo):
        self.args, self.combo = args, combo
        self.cli = container_cli()
        self.name = container_name(combo, args)
        self.deployed_heap = None

    def deploy(self, heap):
        a = self.args
        cmd = [str(ROOT / "deploy_dremio.sh"), "--package", self.combo.package,
               "--storage-path", f"{a.storage_root}/{self.name}", "--java-image", self.combo.image, "--name", self.name,
               "--container-memory-mb", str(a.container_mb), "--cpus", str(a.cpus),
               "--heap-memory-mb", str(heap), "--direct-memory-mb", str(a.direct_mb),
               "--accept-eula", "--recreate", "--dry-run"]
        print("==> " + " ".join(cmd), flush=True)
        ok = subprocess.run(cmd, cwd=ROOT).returncode == 0
        self.deployed_heap = heap if ok else None
        return ok

    def run(self, heap, rows_m):
        if self.deployed_heap != heap and not self.deploy(heap):
            return ERROR
        env = {**os.environ, "BLOCKS_DIR": os.environ.get("BLOCKS_DIR", f"{self.args.storage_root}/{defaults.BLOCKS_SUBDIR}")}
        started = time.time()
        proc = subprocess.Popen(["make", "test-container", f"CONTAINER={self.name}", f"ROW_COUNT={rows_m}M"],
                                cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines = []
        for line in proc.stdout:
            print(line, end="", flush=True)
            lines.append(line)
        if proc.wait() == 0:
            return PASS
        self.deployed_heap = None                  # redeploy before the next run
        return FAIL if classify_failure("".join(lines), self.dremio_log(started)) else ERROR

    def dremio_log(self, since):
        """The log of Dremio (systemd journal in the container) since a time, "" when unreachable."""
        r = subprocess.run([self.cli, "exec", self.name, "--", "journalctl", "-u", "dremio", "--no-pager",
                            "--since", f"@{int(since) - 2}"], capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else ""

    def delete(self):
        subprocess.run([self.cli, "delete", "-f", self.name], capture_output=True)
        self.deployed_heap = None


def classify_failure(test_output, dremio_log):
    """True when a failed run died with a Java heap OOM: in the output of the test or in the Dremio log."""
    return bool(HEAP_OOM.search(test_output) or HEAP_OOM.search(dremio_log))
