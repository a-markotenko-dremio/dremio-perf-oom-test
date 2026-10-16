"""Prints PASS/FAIL if the report CSV already has this combination, nothing otherwise (used by cyrcle.sh).

usage: recorded_verdict.py CSV DREMIO_VERSION HOST_RAM CPUS DIRECT_MB HEAP_MB ROWS [JAVA_IMAGE]

With a Java image only the runs of that image count (the "JVM ver" column ends with "(IMAGE)"),
without one only the runs that were not made with an image.
"""
import csv
import sys

path, ver, ram, cpus, direct, heap, rows, *image = sys.argv[1:]
image = image[0] if image else ""
with open(path, newline="") as f:
    for r in csv.DictReader(f):
        if (r["Dremio ver"], r["Host RAM"], r["DREMIO_MAX_DIRECT_MEMORY_SIZE_MB"],
            r["DREMIO_MAX_HEAP_MEMORY_SIZE_MB"], r["Rows"]) == (ver, ram, direct, heap, rows) \
           and r.get("CPUs", "") == cpus \
           and ((f"({image})" in r["JVM ver"]) if image else not r["JVM ver"].endswith(")")):
            print(r["Verdict"])
            break
