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


STORAGES = ("fs", "s3")                             # where the tables of a test run live: files of STORAGE_PATH, or a bucket of an S3 server
STORAGE = "fs"                                      # the default of STORAGES
TEST_STORAGES = (*STORAGES, "hdfs")                 # STORAGE of a pytest run; hdfs: a directory of an existing HDFS (scripts/test_container.sh and the OOM search do not serve it)

def storage_file(filename, storage=STORAGE):
    """A file of the OOM search in DATA_DIR for a storage: the results of each storage are kept apart (they are not comparable),
    oom_runs.csv for the default storage, oom_runs_s3.csv for s3."""
    return DATA_DIR / (filename if storage == STORAGE else f"{Path(filename).stem}_{storage}{Path(filename).suffix}")


TEST_S3 = "perf-s3"                                 # the container of the S3 server of the runs with STORAGE=s3 (credentials and port: OOM_REPRO_S3_*)
BLOCKS_SUBDIR = "blocks"                            # generated data blocks inside a storage
OOM_REPRO_DIR = STORAGE_ROOT / "fabric-oom-repro"   # data sets of the fabric OOM stand, mounted into every node at this path
OOM_REPRO_SCALE = 0.0175                            # of the master repro data: 1/57, as 2 x 6 GB direct memory to 7 x 96 GB
OOM_REPRO_DATA = OOM_REPRO_DIR / f"scale-{OOM_REPRO_SCALE}"  # the data set of the stand (OOM_DATA); the generator is deterministic, so the scale names it
OOM_REPRO_SOURCE = "OOM Repro"                      # the Dremio NAS source over the data set
# The distributed store (paths.dist) of the stand: an S3 server (the SeaweedFS gateway) on the coordinator host,
# reached by both nodes through the address of that host. Dremio needs one store shared by all nodes, and S3 has no
# POSIX users, so the nodes write each other's Iceberg metadata whatever uid their containers run as. Disposable:
# the store is recreated with the stand.
OOM_REPRO_S3 = "dist-store"                         # the container that runs it, on the coordinator host
OOM_REPRO_S3_PORT = 9000
OOM_REPRO_S3_KEY = "dremio"                         # test credentials, this stand only
OOM_REPRO_S3_SECRET = "dremio123"
OOM_REPRO_DIST_BUCKET = "dremio-dist"
OOM_REPRO_EXECUTOR_HOST = "den"                     # the host of the second node of the stand (name as in /etc/hosts and ssh)
OOM_REPRO_EXECUTOR_REPO = Path("/home/dremio/src/dremio-perf-oom-test")  # this repository on that host
