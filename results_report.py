"""Appends one row per test run to a CSV with the same columns as 'Per tests OOM results'."""
import getpass
import math
import os
import platform
import socket
import time

import csvio
import quantities

COLUMNS = ["Timestamp", "Host src", "Data src", "Host dst", "Data dst", "Dremio ver", "JVM ver", "Host RAM", "CPUs",
           "DREMIO_MAX_DIRECT_MEMORY_SIZE_MB", "DREMIO_MAX_HEAP_MEMORY_SIZE_MB", "Rows",
           "Duration (minutes)", "Verdict", "Run by"]


def timestamp(t=None):
    """'2026-10-16_03-18-11': the CSV column and the test_result_<timestamp>.log name use this same value."""
    return time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(t))


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


def parse_rows(text):
    """'10M' -> 10000000, '1.44G' -> 1440000000, '100K' -> 100000, '12345' -> 12345 (decimal units)."""
    try:
        value = quantities.parse_quantity(text)
    except ValueError:
        raise ValueError(f"invalid row count {text!r}: use a number with an optional K/M/G suffix, e.g. 10M, 1.44G") from None
    if value != value.to_integral_value():
        raise ValueError(f"row count {text!r} is not a whole number of rows")
    return int(value)


def cpus():
    """CPUs available to Dremio: the container's (CONTAINER_CPUS) or, run directly, this host's."""
    return int(os.environ.get("CONTAINER_CPUS") or os.cpu_count() or 0)


def format_rows(n):
    """1440000000 -> '1.44G', 10000000 -> '10M', 100000 -> '100K'."""
    return quantities.format_quantity(n)


def run_by():
    return os.environ.get("RUN_BY") or getpass.getuser()


def append_row(path, row):
    """Appends `row` (a dict keyed by COLUMNS), writing the header when the file is new."""
    csvio.append_row(path, COLUMNS, row)
