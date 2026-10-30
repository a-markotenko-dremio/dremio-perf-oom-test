"""Locations shared by all the tools: the one definition of where the data and the Dremio packages live.

Read from Python (`import defaults`), from the Makefile and from the shell (`default` and `storage_path` of scripts/lib/common.sh).
"""
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent             # the repository
DATA_DIR = ROOT_DIR / "data"                         # the SQL files and the result CSVs
STORAGE_ROOT = Path("/mnt/ubuntu-var/dremio")       # the storages of all containers; never mounted itself, see storage_path
PACKAGES_DIR = STORAGE_ROOT / "Downloads"           # the Dremio tarballs


def storage_path(container, root=STORAGE_ROOT):
    """The storage of a container (its STORAGE_PATH: <storage>/input, <storage>/output, <storage>/blocks)."""
    return Path(root) / container


BLOCKS_SUBDIR = "blocks"                            # generated data blocks inside a storage
OOM_REPRO_DIR = STORAGE_ROOT / "fabric-oom-repro"   # data sets of the fabric OOM stand, mounted into every node at this path
OOM_REPRO_SCALE = 0.0175                            # of the master repro data: 1/57, as 2 x 6 GB direct memory to 7 x 96 GB
OOM_REPRO_DATA = OOM_REPRO_DIR / f"scale-{OOM_REPRO_SCALE}"  # the data set of the stand (OOM_DATA); the generator is deterministic, so the scale names it
OOM_REPRO_SOURCE = "OOM Repro"                      # the Dremio NAS source over the data set
OOM_REPRO_EXECUTOR_HOST = "den"                     # the host of the second node of the stand (name as in /etc/hosts and ssh)
OOM_REPRO_EXECUTOR_REPO = Path("/home/dremio/src/dremio-perf-oom-test")  # this repository on that host
