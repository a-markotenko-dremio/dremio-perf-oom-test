#!/usr/bin/env python3
"""Finds, for every Java heap size, the row count where the test starts to fail with a Java heap OOM.

    ./oom_ranges.py [--plan] [options]

Combinations: every Dremio package x every Java image (by default Dremio 26.1.8 and 26.1.10 x
eclipse-temurin:21-jdk and wolfi-jdk:21 = 4), each in its own container of --container-mb with
--direct-mb of direct memory and --cpus CPUs. All combinations walk the heap sizes together: at every
heap size each of them does its step, one after the other, so that the chart grows for all at once.

The heap grows from --heap-start by --heap-step (512, 576, 640, ... MB) until it reaches the memory
of the container (container - direct - --reserve-mb) or, for a combination, until the test passes
at the highest row count (--rows-high): a larger heap would pass too. At every heap size a binary
search over the row count finds the pass/fail frontier: a run that PASSes moves the lower end up,
a run that FAILs moves the upper end down, until they are --precision apart. The first step searches
--rows-low..--rows-high, the next ones (also the first step of a combination when another one already
has a result) a window of ±--window around the previous result (the
frontier moves slowly while the heap grows by 64 MB); the window moves on when the frontier is
outside it. The result of a step is the range [highest PASS, lowest FAIL] and its middle, "Mean rows".

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
import csv
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import results_report
from report.runs import short_version

ROOT = Path(__file__).resolve().parent
DOWNLOADS = Path("/mnt/ubuntu-var/dremio/Downloads")
PASS, FAIL, ERROR = "PASS", "FAIL", "ERROR"
# Dremio's own heap monitor cancels the query ("Heap monitor detected that the heap is almost full",
# OutOfHeapMemoryException) before the JVM throws; the JVM errors cover a heap that filled up faster.
HEAP_OOM = re.compile(r"OutOfHeapMemoryException|Heap monitor detected that the heap is almost full"
                      r"|OutOfMemoryError: (Java heap space|GC overhead limit exceeded)")
RANGES_COLUMNS = ["Dremio ver", "Java image", "Heap MB", "Pass max rows", "Fail min rows", "Mean rows", "Status"]
RUNS_COLUMNS = ["Timestamp", "Dremio ver", "Java image", "Heap MB", "Rows", "Outcome"]


class StepSkipped(Exception):
    """A run ended in neither PASS nor a heap OOM: this heap step gives no result."""


@dataclass
class Result:
    status: str                  # RANGE | ALL_PASS (no failure up to the highest row count) | ALL_FAIL (fails at the lowest)
    pass_max: int | None = None  # millions of rows
    fail_min: int | None = None

    @property
    def mean(self):
        if self.pass_max is not None and self.fail_min is not None:
            return (self.pass_max + self.fail_min) / 2
        return None


@dataclass(frozen=True)
class Combo:
    package: str
    image: str

    @property
    def version(self):
        return short_version(os.path.basename(self.package).removesuffix(".tar.gz"))


# ------------------------------------------------------------------ the search (pure logic)
def heap_sizes(start, step, maximum):
    return list(range(start, maximum + 1, step))


def search(run, lo, hi, precision, floor, ceil):
    """Binary search of the row count (millions) where `run(rows_m) -> PASS | FAIL` starts to fail.

    Starts with the window lo..hi. If nothing failed in it the window moves up (twice as wide as before),
    if nothing passed it moves down, until `ceil` / `floor` is reached: ALL_PASS / ALL_FAIL."""
    width = hi - lo
    memo = {}

    def verdict(rows):
        if rows not in memo:
            memo[rows] = run(rows)
        return memo[rows]

    pass_max = fail_min = None
    while True:
        while hi - lo > precision:
            mid = (lo + hi) // 2
            if verdict(mid) == PASS:
                lo, pass_max = mid, mid
            else:
                hi, fail_min = mid, mid
        if fail_min is None:                      # nothing failed: is the upper end a failure?
            if verdict(hi) == FAIL:
                fail_min = hi
            else:
                if hi >= ceil:
                    return Result("ALL_PASS", pass_max=hi)
                width *= 2
                lo, hi, pass_max = hi, min(hi + width, ceil), hi
                continue
        if pass_max is None:                      # nothing passed: is the lower end a pass?
            if verdict(lo) == PASS:
                pass_max = lo
            else:
                if lo <= floor:
                    return Result("ALL_FAIL", fail_min=lo)
                width *= 2
                lo, hi, fail_min = max(lo - width, floor), lo, lo
                continue
        return Result("RANGE", pass_max, fail_min)


def window_around(center, half, floor, ceil):
    return max(floor, round(center - half)), min(ceil, round(center + half))


# ------------------------------------------------------------------ recorded state
def read_csv(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def append_csv(path, columns, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        if new:
            w.writeheader()
        w.writerow(row)


class State:
    """What earlier runs of the script recorded: the finished steps and the single runs."""

    def __init__(self, ranges_csv, runs_csv):
        self.ranges_csv, self.runs_csv = ranges_csv, runs_csv
        self.steps = {(r["Dremio ver"], r["Java image"], int(r["Heap MB"])): r for r in read_csv(ranges_csv)}
        self.runs = {(r["Dremio ver"], r["Java image"], int(r["Heap MB"]), int(r["Rows"])): r["Outcome"]
                     for r in read_csv(runs_csv)}

    def run_outcome(self, combo, heap, rows_m):
        return self.runs.get((combo.version, combo.image, heap, rows_m))

    def add_run(self, combo, heap, rows_m, outcome):
        self.runs[combo.version, combo.image, heap, rows_m] = outcome
        append_csv(self.runs_csv, RUNS_COLUMNS, {
            "Timestamp": results_report.timestamp(), "Dremio ver": combo.version, "Java image": combo.image,
            "Heap MB": heap, "Rows": rows_m, "Outcome": outcome})

    def step(self, combo, heap):
        return self.steps.get((combo.version, combo.image, heap))

    def add_step(self, combo, heap, result):
        fmt = lambda m: "" if m is None else results_report.format_rows(round(m * 10**6))
        row = {"Dremio ver": combo.version, "Java image": combo.image, "Heap MB": heap,
               "Pass max rows": fmt(result.pass_max), "Fail min rows": fmt(result.fail_min),
               "Mean rows": fmt(result.mean), "Status": result.status}
        self.steps[combo.version, combo.image, heap] = row
        append_csv(self.ranges_csv, RANGES_COLUMNS, row)


def step_center(row):
    """The middle of a recorded step in millions of rows, None when it has none (ALL_FAIL / ALL_PASS)."""
    return results_report.parse_rows(row["Mean rows"]) / 10**6 if row["Mean rows"] else None


# ------------------------------------------------------------------ one combination
class Progress:
    """Where the walk over the heap sizes stands for one combination."""

    def __init__(self):
        self.center = None       # middle of the last finished step, millions of rows
        self.skipped = 0         # heap steps skipped in a row
        self.finished = False    # nothing fails any more: larger heaps pass too


def run_step(args, combo, heap, runner, state, progress, log=print):
    """The step of a combination at one heap size. `runner.run(heap, rows_m) -> PASS | FAIL | ERROR`."""
    done = state.step(combo, heap)
    if done:
        log(f"### {combo.version} {combo.image} heap={heap}: recorded ({done['Status']}, mean {done['Mean rows'] or '-'})")
        progress.finished = done["Status"] == "ALL_PASS"
        if done["Status"] != "ALL_PASS":
            progress.center = step_center(done) if done["Status"] == "RANGE" else args.rows_low + args.window
        return
    if progress.center is None:
        lo, hi = args.rows_low, args.rows_high
    else:
        lo, hi = window_around(progress.center, args.window, args.rows_low, args.rows_high)
    log(f"### {combo.version} {combo.image} heap={heap}: searching {lo}M..{hi}M")

    def run(rows_m):
        known = state.run_outcome(combo, heap, rows_m)
        if known in (PASS, FAIL) or (known == ERROR and not args.retry_errors):
            outcome = known
            log(f"    {rows_m}M: recorded {outcome}")
        else:
            outcome = runner.run(heap, rows_m)
            state.add_run(combo, heap, rows_m, outcome)
            log(f"    {rows_m}M: {outcome}")
        if outcome == ERROR:
            raise StepSkipped(f"{rows_m}M")
        return outcome

    try:
        result = search(run, lo, hi, args.precision, args.rows_low, args.rows_high)
    except StepSkipped as e:
        progress.skipped += 1
        log(f"    heap={heap} skipped: the run at {e} ended with an error that is not a heap OOM "
            f"({progress.skipped} in a row)")
        if progress.skipped >= args.max_skipped:
            raise SystemExit(f"{progress.skipped} heap steps in a row skipped: stopping, check the environment")
        return
    progress.skipped = 0
    state.add_step(combo, heap, result)
    log(f"    heap={heap}: {result.status}" + (f", PASS up to {result.pass_max}M, FAIL from {result.fail_min}M, "
                                              f"mean {result.mean:g}M" if result.status == "RANGE" else ""))
    if result.status == "ALL_PASS":
        log("    no failure at the highest row count: a larger heap passes too, this combination is done")
        progress.finished = True
    else:
        progress.center = result.mean if result.status == "RANGE" else args.rows_low + args.window


def run_all(args, combos, runner_for, state, log=print):
    """Walks the heap sizes of all combinations together: at every heap size each combination does its step, so
    all the lines of the chart grow at the same time. The container of a step is deleted when the step is done
    (the next heap size needs a new one anyway), so only one container exists at a time."""
    progress = {c: Progress() for c in combos}
    for heap in heap_sizes(args.heap_start, args.heap_step, args.heap_max):
        for combo in combos:
            if progress[combo].finished:
                continue
            if progress[combo].center is None:      # no result of its own yet: start near another combination's
                progress[combo].center = next((p.center for p in progress.values() if p.center is not None), None)
            runner = runner_for(combo)
            try:
                run_step(args, combo, heap, runner, state, progress[combo], log)
            finally:
                getattr(runner, "delete", lambda: None)()
        if all(p.finished for p in progress.values()):
            return


# ------------------------------------------------------------------ the real runs
def container_cli():
    for cli in ("incus", "lxc"):
        if shutil.which(cli):
            return cli
    raise SystemExit("neither incus nor lxc found in PATH")


def container_name(combo, args):
    """The name deploy_dremio.sh builds by default (the same shell function)."""
    script = 'source scripts/lib/common.sh; JAVA_IMAGE=$1; default_container_name "$2" "$(java_label)" "$3" "$4"'
    return subprocess.run(["bash", "-c", script, "_", combo.image, combo.package, str(args.container_mb), str(args.cpus)],
                          cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


class Runner:
    """Deploys the container of a combination for a heap size and runs the test in it.

    One container serves all runs of a heap step; it is deployed again after a run that did not pass, as
    the JVM of a Dremio that hit an OOM is not in a state to measure anything."""

    def __init__(self, args, combo):
        self.args, self.combo = args, combo
        self.cli = container_cli()
        self.name = container_name(combo, args)
        self.deployed_heap = None

    def deploy(self, heap):
        a = self.args
        cmd = [str(ROOT / "deploy_dremio.sh"), "--package", self.combo.package,
               "--storage-path", f"{a.storage_root}/{self.name}", "--java-image", self.combo.image, "--name", self.name,
               "--container-memory-mb", str(a.container_mb), "--cpus", str(a.cpus),
               "--heap-memory-mb", str(heap), "--direct-memory-mb", str(a.direct_mb),
               "--accept-eula", "--recreate", "--dry-run"]
        print("==> " + " ".join(cmd), flush=True)
        ok = subprocess.run(cmd, cwd=ROOT).returncode == 0
        self.deployed_heap = heap if ok else None
        return ok

    def run(self, heap, rows_m):
        if self.deployed_heap != heap and not self.deploy(heap):
            return ERROR
        env = {**os.environ, "BLOCKS_DIR": os.environ.get("BLOCKS_DIR", f"{self.args.storage_root}/blocks")}
        started = time.time()
        proc = subprocess.Popen(["make", "test-container", f"CONTAINER={self.name}", f"ROW_COUNT={rows_m}M"],
                                cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines = []
        for line in proc.stdout:
            print(line, end="", flush=True)
            lines.append(line)
        if proc.wait() == 0:
            return PASS
        self.deployed_heap = None                  # redeploy before the next run
        return FAIL if classify_failure("".join(lines), self.dremio_log(started)) else ERROR

    def dremio_log(self, since):
        """The log of Dremio (systemd journal in the container) since a time, "" when unreachable."""
        r = subprocess.run([self.cli, "exec", self.name, "--", "journalctl", "-u", "dremio", "--no-pager",
                            "--since", f"@{int(since) - 2}"], capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else ""

    def delete(self):
        subprocess.run([self.cli, "delete", "-f", self.name], capture_output=True)
        self.deployed_heap = None


def classify_failure(test_output, dremio_log):
    """True when a failed run died with a Java heap OOM: in the output of the test or in the Dremio log."""
    return bool(HEAP_OOM.search(test_output) or HEAP_OOM.search(dremio_log))


# ------------------------------------------------------------------ command line
def find_package(version):
    found = sorted(DOWNLOADS.glob(f"dremio-enterprise-{version}-*.tar.gz"))
    if not found:
        raise SystemExit(f"no package dremio-enterprise-{version}-*.tar.gz in {DOWNLOADS} (pass --packages FILE...)")
    return str(found[-1])


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--packages", nargs="+", metavar="FILE", help="Dremio tarballs (default: 26.1.8 and 26.1.10 in %s)" % DOWNLOADS)
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
    ap.add_argument("--window", type=int, default=10, metavar="M", help="half width of the search window around the previous result after the first step (default 10)")
    ap.add_argument("--max-skipped", type=int, default=3, help="stop after this many skipped heap steps in a row")
    ap.add_argument("--retry-errors", action="store_true", help="run again the runs recorded as ERROR")
    ap.add_argument("--storage-root", default="/mnt/ubuntu-var/dremio", help="a combination stores its data in <root>/<container name>")
    ap.add_argument("--ranges-csv", default=str(ROOT / "data" / "oom_ranges.csv"))
    ap.add_argument("--runs-csv", default=str(ROOT / "data" / "oom_runs.csv"))
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
          f"rows {args.rows_low}M..{args.rows_high}M, precision {args.precision}M, window +-{args.window}M")
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
