"""Locations shared by all the tools: the one definition of where the data and the Dremio packages live.

Read from Python (`import defaults`), from the Makefile and from the shell (`python3 -c 'import defaults; ...'`).
"""
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent             # the repository
DATA_DIR = ROOT_DIR / "data"                         # the SQL files and the result CSVs
STORAGE_ROOT = Path("/mnt/ubuntu-var/dremio")       # default STORAGE_PATH: <root>/input, <root>/output, <root>/blocks
PACKAGES_DIR = STORAGE_ROOT / "Downloads"           # the Dremio tarballs
BLOCKS_SUBDIR = "blocks"                            # generated data blocks inside a storage
