"""What a run of the stand ran on: the Dremio package of every container (the tarball and its sha256, recorded in the
container config by install_dremio of scripts/lib/container.sh) and the commit of this repository."""
import shlex
import subprocess
from collections import namedtuple
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
METADATA_PACKAGE_URL = "http://metadata.google.internal/computeMetadata/v1/instance/attributes/dremio_pkg_url"
PACKAGE_KEYS = ("user.dremio.package", "user.dremio.package-sha256")  # the config keys install_dremio sets

Stand = namedtuple("Stand", "commit packages")  # packages: container -> "tarball sha256"


def split_scheme(entry):
    """(scheme, host) of an OOM_CONTAINERS entry of a node that is not a container (dremio://host, yarn://host), else ("", "")."""
    scheme, _, host = entry.partition("://")
    return (scheme, host) if host else ("", "")


def node(container):
    """The host (empty for this one) and the container name of an OOM_CONTAINERS entry (host:container)."""
    host, _, name = container.rpartition(":")
    return host, name


def host_of(entry):
    """The host an OOM_CONTAINERS entry runs on (empty for this one)."""
    return split_scheme(entry)[1] or node(entry)[0]


def hosts(entries):
    """The other hosts the OOM_CONTAINERS entries run on, without repeats, in the order of the entries."""
    return list(dict.fromkeys(filter(None, map(host_of, entries))))


def run_on(host, command):
    """Runs the command on the host (over ssh, or here when the host is empty); its output and exit status."""
    # ssh joins its arguments into one remote command line, so they must be quoted for it
    return subprocess.run(["ssh", "-o", "BatchMode=yes", host, shlex.join(command)] if host else command,
                          capture_output=True, text=True)


def package(container):
    """The Dremio tarball the container was installed from and its sha256, as install_dremio recorded them; of a node
    that is no container the package URL of its VM (the dremio_pkg_url attribute the cluster was built from)."""
    if host := split_scheme(container)[1]:
        out = run_on(host, ["curl", "-sf", "-H", "Metadata-Flavor: Google", METADATA_PACKAGE_URL])
        assert out.returncode == 0 and out.stdout, f"{container} has no dremio_pkg_url in its VM metadata: {out.stderr}"
        return out.stdout.strip()
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
