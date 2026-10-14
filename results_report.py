"""Appends one row per test run to a CSV with the same columns as 'Per tests OOM results'."""
import csv
import getpass
import math
import os
import platform
import socket
from pathlib import Path

COLUMNS = ["Host src", "Data src", "Host dst", "Data dst", "Dremio ver", "JVM ver", "Host RAM",
           "DREMIO_MAX_DIRECT_MEMORY_SIZE_MB", "DREMIO_MAX_HEAP_MEMORY_SIZE_MB", "Rows",
           "Duration (minutes)", "Verdict", "Run by"]


def host_name():
    """Like 'Linux-Home4' on Linux (the host name is capitalized), the plain host name elsewhere."""
    short = socket.gethostname().split(".")[0]
    return f"Linux-{short.capitalize()}" if platform.system() == "Linux" else socket.gethostname()


def host_ram():
    """RAM available to Dremio, e.g. '4G': the container memory limit (CONTAINER_RAM_MB, set by
    deploy_dremio.sh and `make test-container`) or, when run directly on a host, its physical RAM
    rounded up to whole GB (the OS reserves some)."""
    limit_mb = os.environ.get("CONTAINER_RAM_MB")
    if limit_mb:
        mb = int(limit_mb)
        return f"{mb // 1024}G" if mb % 1024 == 0 else f"{mb}M"
    total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    return f"{math.ceil(total / 2**30)}G"


def format_rows(n):
    """1440000000 -> '1.44G', 10000000 -> '10M', 100000 -> '100K'."""
    for unit, size in (("G", 10**9), ("M", 10**6), ("K", 10**3)):
        if n >= size:
            return f"{n / size:.2f}".rstrip("0").rstrip(".") + unit
    return str(n)


def run_by():
    return os.environ.get("RUN_BY") or getpass.getuser()


def append_row(path, row):
    """Appends `row` (a dict keyed by COLUMNS), writing the header when the file is new."""
    path = Path(path)
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)
