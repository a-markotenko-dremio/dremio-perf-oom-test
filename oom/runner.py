"""The real runs: deploys the container of a combination, runs the test in it and tells a heap OOM from other failures."""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import defaults
from .model import ERROR, FAIL, PASS

ROOT = defaults.ROOT_DIR
# The directory name of a container storage under the storage root: the container name of default_container_name
# ("d26-1-8-wolfi-jdk-21-8G-4cpu"). Nothing else in the root (Downloads, blocks, ...) is taken for one.
STORAGE_DIR = re.compile(r"^d\d+-\d+-\d+-.+-\d+[GM]-\d+cpu$")
# Dremio's own heap monitor cancels the query ("Heap monitor detected that the heap is almost full",
# OutOfHeapMemoryException) before the JVM throws; the JVM errors cover a heap that filled up faster.
HEAP_OOM = re.compile(r"OutOfHeapMemoryException|Heap monitor detected that the heap is almost full"
                      r"|OutOfMemoryError: (Java heap space|GC overhead limit exceeded)")


def common_sh(script, *args):
    """Runs a snippet of bash after sourcing scripts/lib/common.sh (the one place that knows the container CLI and the
    container names) and returns its output; `args` are $1, $2, ... of the snippet."""
    r = subprocess.run(["bash", "-c", f"source scripts/lib/common.sh; {script}", "_", *args], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(r.stderr.strip() or f"shell snippet failed: {script}")
    return r.stdout.strip()


def container_cli():
    """The container CLI of the shell scripts, incus or lxc."""
    return common_sh('detect_container_cli; echo "$CT"')


def container_name(combo, args):
    """The name deploy_dremio.sh builds by default."""
    return common_sh('JAVA_IMAGE=$1; default_container_name "$2" "$(java_label)" "$3" "$4"',
                     combo.image, combo.package, str(args.container_mb), str(args.cpus))


def remove_storage(root, name, keep=None):
    """Deletes <root>/<name>, the storage of a container: the tables of a test and what a failed run left behind. The
    shared data blocks are not in it (it holds links to them: a link is removed, not what it points to); `keep`, a
    directory that must survive, is refused when it lies inside."""
    root, path = Path(root), Path(root) / name
    if name in ("", ".", "..") or Path(name).name != name:
        raise ValueError(f"{name!r} is not a directory directly under {root}")
    if keep is not None and Path(keep).resolve().is_relative_to(path.resolve()):
        raise ValueError(f"{keep} is inside {path}: refusing to delete it")
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def stale_storage_dirs(root, existing):
    """The container storages under `root` whose container does not exist any more (`existing` are the container names)."""
    root = Path(root)
    if not root.is_dir():
        return []
    return [p.name for p in sorted(root.iterdir())
            if p.is_dir() and not p.is_symlink() and STORAGE_DIR.match(p.name) and p.name not in existing]


def list_containers(cli):
    """The names of all containers; stops when they cannot be listed (nothing is deleted on a guess)."""
    r = subprocess.run([cli, "list", "--format", "csv", "-c", "n"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"cannot list the containers: {r.stderr.strip()}")
    return set(r.stdout.split())


class Runner:
    """Deploys the container of a combination for a heap size and runs the test in it.

    One container serves all runs of a heap step; it is deployed again after a run that did not pass, as
    the JVM of a Dremio that hit an OOM is not in a state to measure anything."""

    def __init__(self, args, combo):
        self.args, self.combo = args, combo
        self.cli = container_cli()
        self.name = container_name(combo, args)
        self.deployed_heap = None

    @property
    def blocks_dir(self):
        """The directory of the shared data blocks (the storage of a container links to it)."""
        return os.environ.get("BLOCKS_DIR", f"{self.args.storage_root}/{defaults.BLOCKS_SUBDIR}")

    def deploy(self, heap):
        """A new container with Dremio of this heap. The previous container and its storage go first: a failed run leaves
        files behind (the half-written output table is tens of GB), and every combination has a storage of its own."""
        self.delete()
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
        env = {**os.environ, "BLOCKS_DIR": self.blocks_dir}
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
        """Deletes the container and its storage (what is left on the disk after a step, passed or failed)."""
        subprocess.run([self.cli, "delete", "-f", self.name], capture_output=True)
        self.deployed_heap = None
        remove_storage(self.args.storage_root, self.name, keep=self.blocks_dir)


def classify_failure(test_output, dremio_log):
    """True when a failed run died with a Java heap OOM: in the output of the test or in the Dremio log."""
    return bool(HEAP_OOM.search(test_output) or HEAP_OOM.search(dremio_log))
