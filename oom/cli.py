#!/usr/bin/env python3
"""Finds, for every Java heap size, the row count where the test starts to fail with a Java heap OOM.

    ./oom_ranges.py [--plan] [options]

Combinations: every Dremio package x every Java image (by default Dremio 26.1.8 and 26.1.10 x
eclipse-temurin:21-jdk and wolfi-jdk:21 = 4), each in its own container of --container-mb with
--direct-mb of direct memory and --cpus CPUs. All combinations walk the heap sizes together: at every
heap size each of them does its step, one after the other, so that the chart grows for all at once.

The heap grows from --heap-start by --heap-step (512, 576, 640, ... MB) until it reaches the memory
of the container (container - direct - --reserve-mb) or, for a combination, until the test passes
at the highest row count (--rows-high): a larger heap would pass too. At every heap size the script
finds the pass/fail frontier of the row count, to --precision. Runs cost hours, so it starts with a
guess made from the runs already recorded in data/oom_runs.csv: the runs of this heap size narrow the
bracket [highest PASS, lowest FAIL] first; without them the frontier of the previous heap sizes of the
combination is extrapolated by its trend (more heap never gives fewer rows) and averaged with the result
of every other combination at this heap size (moved by its usual distance from this one); the guess is not
lower than a PASS of another combination at this heap size. Without a history of its own the result of
another combination is taken. The first run is at that guess; runs upwards do not go beyond a FAIL of
another combination at this heap size (the first of them goes there at most), and halving a bracket
does not run below a PASS of another combination inside it (the run goes to that PASS). A PASS moves the search
up, a FAIL down, by --window (the step is wider when the frontier moved faster between the last heap
sizes) and doubling, until the frontier is bracketed, then the bracket is halved down to --precision. Without
any recorded run the first step searches --rows-low..--rows-high by halving. The result of a step is the
range [highest PASS, lowest FAIL] and its middle, "Mean rows".

A run counts as FAIL only when it died with a Java heap OOM ("Heap monitor detected that the heap is almost
full" / OutOfHeapMemoryException of Dremio, or "OutOfMemoryError: Java heap space" / "GC overhead limit
exceeded" of the JVM, in the output of the test or in the Dremio log). Any other failure (direct
memory, a timeout, a failed deploy) makes the run an ERROR and the whole heap step is skipped: no
row for it, the next step goes on from the last successful one. After --max-skipped steps in a row
the script stops: the environment is probably broken.

Files (resumable: what is recorded is not run again; --retry-errors runs ERROR runs again):
  data/oom_ranges.csv  one row per finished step: Dremio ver, Java image, Heap MB, Pass max rows,
                       Fail min rows, Mean rows, Status (RANGE | ALL_PASS | ALL_FAIL)
  data/oom_runs.csv    every run of the search with its outcome (PASS | FAIL | ERROR)
  data/test_results.csv  the usual row of every test run (REPORT_CSV)
Run with PLAN=1 or --plan to see the combinations, the heap sizes and what is already recorded.
"""
import argparse
import os
import sys

import defaults
from .model import Combo
from .runner import Runner
from .search import heap_sizes
from .state import State
from .steps import run_all



def find_package(version):
    found = sorted(defaults.PACKAGES_DIR.glob(f"dremio-enterprise-{version}-*.tar.gz"))
    if not found:
        raise SystemExit(f"no package dremio-enterprise-{version}-*.tar.gz in {defaults.PACKAGES_DIR} (pass --packages FILE...)")
    return str(found[-1])


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--packages", nargs="+", metavar="FILE", help="Dremio tarballs (default: 26.1.8 and 26.1.10 in %s)" % defaults.PACKAGES_DIR)
    ap.add_argument("--java-images", nargs="+", default=["eclipse-temurin:21-jdk", "wolfi-jdk:21"], metavar="IMAGE")
    ap.add_argument("--container-mb", type=int, default=8192)
    ap.add_argument("--direct-mb", type=int, default=4096)
    ap.add_argument("--cpus", type=int, default=4)
    ap.add_argument("--reserve-mb", type=int, default=2048,
                    help="memory of the container kept free of heap and direct memory (default 2048, as in deploy_dremio.sh)")
    ap.add_argument("--heap-start", type=int, default=512, metavar="MB")
    ap.add_argument("--heap-step", type=int, default=64, metavar="MB")
    ap.add_argument("--heap-max", type=int, metavar="MB", help="default: container - direct - reserve")
    ap.add_argument("--rows-low", type=int, default=10, metavar="M", help="lowest row count, millions (default 10)")
    ap.add_argument("--rows-high", type=int, default=1440, metavar="M", help="highest row count, millions (default 1440 = 1.44G)")
    ap.add_argument("--precision", type=int, default=10, metavar="M", help="the search stops when PASS and FAIL are this close (default 10)")
    ap.add_argument("--window", type=int, default=10, metavar="M", help="the first step of the search away from the guess, millions of rows (default 10); it doubles while the frontier is not bracketed")
    ap.add_argument("--max-skipped", type=int, default=3, help="stop after this many skipped heap steps in a row")
    ap.add_argument("--retry-errors", action="store_true", help="run again the runs recorded as ERROR")
    ap.add_argument("--storage-root", default=str(defaults.STORAGE_ROOT), help="a combination stores its data in <root>/<container name>")
    ap.add_argument("--ranges-csv", default=str(defaults.DATA_DIR / "oom_ranges.csv"))
    ap.add_argument("--runs-csv", default=str(defaults.DATA_DIR / "oom_runs.csv"))
    ap.add_argument("--plan", action="store_true", help="only print what would run")
    args = ap.parse_args(argv)
    if os.environ.get("PLAN"):
        args.plan = True
    if args.packages is None:
        args.packages = [find_package("26.1.8"), find_package("26.1.10")]
    if args.heap_max is None:
        args.heap_max = args.container_mb - args.direct_mb - args.reserve_mb
    for what, value in (("--heap-start", args.heap_start), ("--heap-step", args.heap_step)):
        if value % 2:
            raise SystemExit(f"{what} must be even: the JVM rounds odd heap sizes up")
    if args.heap_max < args.heap_start:
        raise SystemExit(f"--heap-max {args.heap_max} is below --heap-start {args.heap_start}")
    if not 0 < args.rows_low < args.rows_high <= 2147:
        raise SystemExit("--rows-low and --rows-high must be 0 < low < high <= 2147 (millions; at most 2147483647 rows)")
    return args


def main(argv=None):
    args = parse_args(argv)
    combos = [Combo(p, i) for p in args.packages for i in args.java_images]
    state = State(args.ranges_csv, args.runs_csv)
    heaps = heap_sizes(args.heap_start, args.heap_step, args.heap_max)
    print(f"{len(combos)} combinations x heap {heaps[0]}..{heaps[-1]} MB step {args.heap_step} ({len(heaps)} steps), "
          f"container {args.container_mb} MB, direct {args.direct_mb} MB, {args.cpus} CPUs, "
          f"rows {args.rows_low}M..{args.rows_high}M, precision {args.precision}M, first step {args.window}M")
    for combo in combos:
        recorded = sum(1 for h in heaps if state.step(combo, h))
        print(f"  {combo.version:<12} {combo.image:<24} {recorded}/{len(heaps)} steps recorded")
    if args.plan:
        return
    runners = {}

    def runner_for(combo):
        if combo not in runners:
            runners[combo] = Runner(args, combo)
        return runners[combo]

    try:
        run_all(args, combos, runner_for, state)
    finally:
        for runner in runners.values():
            runner.delete()


if __name__ == "__main__":
    sys.exit(main())
