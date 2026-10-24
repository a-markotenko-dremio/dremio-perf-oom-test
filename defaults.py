"""Locations shared by all the tools: the one definition of where the data and the Dremio packages live.

Read from Python (`import defaults`), from the Makefile and from the shell (`python3 -c 'import defaults; ...'`).
"""
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent             # the repository
DATA_DIR = ROOT_DIR / "data"                         # the SQL files and the result CSVs
STORAGE_ROOT = Path("/mnt/ubuntu-var/dremio")       # default STORAGE_PATH: <root>/input, <root>/output, <root>/blocks
PACKAGES_DIR = STORAGE_ROOT / "Downloads"           # the Dremio tarballs
BLOCKS_SUBDIR = "blocks"                            # generated data blocks inside a storage
OOM_REPRO_SUBDIR = "qa-oom-repro"                   # tables of the fabric OOM repro inside a storage: TestCaseData, TestSuiteInfo
OOM_REPRO_SOURCE = "OOM Repro"                      # the Dremio NAS source over that directory
OOM_REPRO_COORDINATOR = "d25-2-0-j21-14G-4cpu"      # containers of the two-host stand of the fabric OOM repro
OOM_REPRO_EXECUTOR_HOST = "den"                     # the host of the second container (name as in /etc/hosts and ssh)
OOM_REPRO_EXECUTOR = "d25-2-0-j21-10G-16cpu"
OOM_REPRO_EXECUTOR_REPO = Path("/home/dremio/src/dremio-perf-oom-test")  # this repository on that host
