"""The data side of the report: reads the result CSVs and works out the PASS/FAIL frontier.

Runs are grouped as {version: {rows: {(heap_mb, direct_mb): [passes, fails]}}}. Rows without a
verdict (unfinished runs) are skipped. Runs are pooled over container RAM and CPUs.
"""
import csv
import re
from collections import defaultdict

import results_report


def short_version(v):
    """'dremio-enterprise-26.1.10-202607291955500295-6a7e3d8c' -> '26.1.10'."""
    v = re.sub(r"^dremio-(enterprise|community)-", "", v.strip())
    return re.sub(r"-\d{10,}.*$", "", v)


def load(paths):
    """({version: {rows: {(heap_mb, direct_mb): [passes, fails]}}}, set of Host RAM values)."""
    data, rams = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0, 0]))), set()
    for path in paths:
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                verdict = (r.get("Verdict") or "").strip().upper()
                if verdict not in ("PASS", "FAIL") or not r.get("Dremio ver"):
                    continue
                try:
                    heap = int(r["DREMIO_MAX_HEAP_MEMORY_SIZE_MB"])
                    direct = int(r["DREMIO_MAX_DIRECT_MEMORY_SIZE_MB"])
                    rows = results_report.parse_rows(r["Rows"])
                except (ValueError, KeyError):
                    continue
                data[short_version(r["Dremio ver"])][rows][(heap, direct)][0 if verdict == "PASS" else 1] += 1
                if r.get("Host RAM"):
                    rams.add(r["Host RAM"])
    return data, rams


def by_heap(runs):
    """{heap: [passes, fails]} pooled over direct memory."""
    out = defaultdict(lambda: [0, 0])
    for (heap, _), (p, f) in runs.items():
        out[heap][0] += p
        out[heap][1] += f
    return out


def frontier(runs):
    """(highest failed heap | None, safe heap | None): the safe heap is the lowest tested heap above
    the highest failed one that passed, so every larger tested heap passed too."""
    heaps = by_heap(runs)
    fails = [h for h, (p, f) in heaps.items() if f]
    bad = max(fails) if fails else None
    safe = [h for h, (p, f) in heaps.items() if p and (bad is None or h > bad)]
    return bad, (min(safe) if safe else None)


def summary(data):
    for ver in sorted(data):
        print(f"Dremio {ver}")
        for rows in sorted(data[ver]):
            bad, safe = frontier(data[ver][rows])
            print(f"  {results_report.format_rows(rows):>6} rows: highest FAIL heap "
                  f"{bad if bad is not None else '-':>5}, safe heap {safe if safe is not None else '-':>5}")
