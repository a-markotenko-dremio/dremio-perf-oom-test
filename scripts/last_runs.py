"""Prints the last N runs of a report CSV, one per line: rows,heap_mb,direct_mb,verdict (used by run_set.sh).

usage: last_runs.py CSV N
"""
import csv
import sys

path, count = sys.argv[1], int(sys.argv[2])
with open(path, newline="") as f:
    runs = list(csv.DictReader(f))
for r in runs[-count:]:
    print(",".join((r["Rows"], r["DREMIO_MAX_HEAP_MEMORY_SIZE_MB"], r["DREMIO_MAX_DIRECT_MEMORY_SIZE_MB"], r["Verdict"])))
