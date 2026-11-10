"""The data set of a run on every node: generated on each host of the nodes (the generator is deterministic, so the
copies are the same, and nothing is copied between the hosts), at the same path on all of them: a NAS source needs
one path on all nodes. A host that has the data set keeps it."""
import re
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor

from fabric_oom_repro import generate_oom_data
from fabric_oom_repro.stand import REPO, host_of, hosts, run_on

REMOTE_DIR = ".cache/fabric-oom"  # of the home of the user on a remote host: the venv with duckdb and the generator
REMOTE_PYTHON = "3.12"            # the system python of the hosts (3.9) is too old for the duckdb of requirements.txt; uv fetches this one
GENERATOR = REPO / "fabric_oom_repro" / "generate_oom_data.py"


def duckdb_requirement():
    """The line of requirements.txt that pins duckdb: the remote venv gets the same version as the local one."""
    return re.search(r"^duckdb==\S+$", (REPO / "requirements.txt").read_text(), re.M)[0]


def run_checked(host, command):
    out = run_on(host, command)
    assert out.returncode == 0, f"{' '.join(command)} on {host or 'this host'} failed: {out.stdout}{out.stderr}"
    return out.stdout


def make_data_dir(host, path):
    """Makes the directory of the data set on the host. Its parent belongs to root on a cloud VM (`/data`), where the
    user the tests log in as cannot create it, so the plain mkdir is followed by sudo, which the hosts allow without a
    password; a host that allows neither fails the run with the output of both."""
    quoted = shlex.quote(str(path))
    run_checked(host, ["bash", "-c", f"mkdir -p {quoted} || sudo -n install -d -o $(id -un) -g $(id -gn) {quoted}"])


def generate_remote(host, path, scale, log):
    """Runs the generator on the host in a venv of its own (created on the first run), unless it has the data set.
    Generating takes tens of minutes, so the host says when it starts as well as what it ended with."""
    venv, uv = f"{REMOTE_DIR}/venv", f"{REMOTE_DIR}/uv"
    log(f"{host}: preparing the data set {path} at scale {scale}")
    make_data_dir(host, path)
    setup = (f"mkdir -p {REMOTE_DIR} && {venv}/bin/python -c 'import duckdb' 2>/dev/null || "
             f"{{ python3 -m venv {uv} && {uv}/bin/pip install -q uv && {uv}/bin/uv venv -q --clear --python {REMOTE_PYTHON} {venv} && "
             f"{uv}/bin/uv pip install -q --python {venv}/bin/python {duckdb_requirement()}; }}")
    run_checked(host, ["bash", "-c", setup])
    subprocess.run(["rsync", "-a", str(GENERATOR), f"{host}:{REMOTE_DIR}/"], check=True)
    log(run_checked(host, [f"{REMOTE_DIR}/venv/bin/python", f"{REMOTE_DIR}/{GENERATOR.name}", str(path), "--scale", str(scale)]).strip()
        or f"{host}: has the data set {path}")


def prepare(path, scale, containers, log=print):
    """Makes `path` hold the data set on this host when a container of the stand runs on it, and on every other host of the nodes."""
    if not all(map(host_of, containers)):
        generate_oom_data.ensure(path, scale, log=log)
    with ThreadPoolExecutor() as pool:
        list(pool.map(lambda host: generate_remote(host, path, scale, log), hosts(containers)))
