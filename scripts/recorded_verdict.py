"""Prints PASS/FAIL if the report CSV already has this combination, nothing otherwise (used by cyrcle.sh).

usage: recorded_verdict.py CSV DREMIO_VERSION HOST_RAM CPUS DIRECT_MB HEAP_MB ROWS
"""
import csv
import sys

path, ver, ram, cpus, direct, heap, rows = sys.argv[1:]
with open(path, newline="") as f:
    for r in csv.DictReader(f):
        if (r["Dremio ver"], r["Host RAM"], r["DREMIO_MAX_DIRECT_MEMORY_SIZE_MB"],
            r["DREMIO_MAX_HEAP_MEMORY_SIZE_MB"], r["Rows"]) == (ver, ram, direct, heap, rows) \
           and r.get("CPUs", "") == cpus:
            print(r["Verdict"])
            break
