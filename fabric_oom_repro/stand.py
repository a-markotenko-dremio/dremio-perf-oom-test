"""What a run of the stand ran on: the Dremio package of every container (the tarball and its sha256, recorded in the
container config by install_dremio of scripts/lib/container.sh) and the commit of this repository."""
import shlex
import subprocess
from collections import namedtuple
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGE_KEYS = ("user.dremio.package", "user.dremio.package-sha256")  # the config keys install_dremio sets

Stand = namedtuple("Stand", "commit packages")  # packages: container -> "tarball sha256"


def node(container):
    """The host (empty for this one) and the container name of an OOM_CONTAINERS entry (host:container)."""
    host, _, name = container.rpartition(":")
    return host, name


def run_on(host, command):
    """Runs the command on the host (over ssh, or here when the host is empty); its output and exit status."""
    # ssh joins its arguments into one remote command line, so they must be quoted for it
    return subprocess.run(["ssh", "-o", "BatchMode=yes", host, shlex.join(command)] if host else command,
                          capture_output=True, text=True)


def package(container):
    """The Dremio tarball the container was installed from and its sha256, as install_dremio recorded them."""
    host, name = node(container)
    values = [run_on(host, ["incus", "config", "get", name, key]).stdout.strip() for key in PACKAGE_KEYS]
    assert all(values), f"{container} has no {PACKAGE_KEYS} in its config: it was deployed before install_dremio recorded the package"
    return " ".join(values)


def commit():
    """The commit this repository is at (`-dirty` with uncommitted changes)."""
    return subprocess.run(["git", "describe", "--always", "--dirty"], cwd=REPO, capture_output=True, text=True,
                          check=True).stdout.strip()


def stand_of(containers):
    return Stand(commit(), {c: package(c) for c in containers})
