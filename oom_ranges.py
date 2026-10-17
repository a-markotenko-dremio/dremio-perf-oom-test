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
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import csvio
import defaults
import results_report
from report.runs import short_version

ROOT = Path(__file__).resolve().parent
DOWNLOADS = defaults.PACKAGES_DIR
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


def search_guided(run, lo, hi, guess, step, precision, floor, ceil, cap=None, hints=()):
    """The search of a step that starts from what is known: `lo` is the highest known PASS and `hi` the lowest
    known FAIL (millions of rows, None when unknown), `guess` the predicted frontier where the first run goes.

    An unknown end is found by moving from the known one by `step`, doubling it after every run in the same
    direction (PASS up, FAIL down), up to `ceil` / `floor`: ALL_PASS / ALL_FAIL. Then the bracket is halved.

    `cap` is a row count where another combination already failed at this heap size: the first runs upwards do not
    go beyond it (a run at the cap itself does; if that passes, the cap is gone and the search goes on above it).

    `hints` are row counts where another combination passed at this heap size. When halving the bracket, a run below
    such a PASS is expected to pass and tells little, so the run goes to the highest hint inside the bracket instead of
    its middle."""
    if guess is not None:
        guess = min(max(guess, floor), ceil)
        if cap is not None and (lo is None or cap > lo):
            guess = min(guess, cap)
    # the first run is the guess; with an end already known the guess is still the first thing to try on the open side
    # (a recorded PASS at 558M and a guess of 638M: the next run is 638M, not 558M plus a doubling step)
    if guess is not None and ((lo is None and hi is None) or (hi is None and guess > lo) or (lo is None and guess < hi)):
        if run(guess) == PASS:
            lo = guess
        else:
            hi = guess
    move = step
    while hi is None:                              # a PASS is known: look up for a FAIL
        if lo >= ceil:
            return Result("ALL_PASS", pass_max=lo)
        nxt = min(lo + move, ceil)
        clipped = cap is not None and lo < cap < nxt
        if clipped:
            nxt = cap
        if run(nxt) == PASS:
            lo = nxt
            if cap is not None and lo >= cap:
                cap = None                              # passed where the other failed: nothing to hold on to
            if not clipped:
                move *= 2                               # a step shortened by the cap says nothing about the distance
        else:
            hi = nxt
    move = step
    while lo is None:                              # a FAIL is known: look down for a PASS
        if hi <= floor:
            return Result("ALL_FAIL", fail_min=hi)
        nxt = max(hi - move, floor)
        if run(nxt) == FAIL:
            hi, move = nxt, move * 2
        else:
            lo = nxt
    while hi - lo > precision:
        mid = (lo + hi) // 2
        mid = max([mid] + [h for h in hints if mid < h < hi])
        if run(mid) == PASS:
            lo = mid
        else:
            hi = mid
    return Result("RANGE", lo, hi)


def bracket(outcomes):
    """(highest PASS below the lowest FAIL, lowest FAIL) of the runs {rows_m: PASS | FAIL}; None for an unknown end."""
    fails = [r for r, o in outcomes.items() if o == FAIL]
    fail_min = min(fails) if fails else None
    passes = [r for r, o in outcomes.items() if o == PASS and (fail_min is None or r < fail_min)]
    return (max(passes) if passes else None), fail_min


def estimates(heap_runs, below_heap):
    """[(heap, frontier estimate, kind)] of the heap sizes under `below_heap`, from their recorded runs. The estimate
    is the middle of a full bracket ("full"), else the only known end: "lower" with only PASS (the frontier is
    above it), "upper" with only FAIL (below it)."""
    out = []
    for heap in sorted(h for h in heap_runs if h < below_heap):
        p, f = bracket(heap_runs[heap])
        if p is not None and f is not None:
            out.append((heap, (p + f) / 2, "full"))
        elif p is not None:
            out.append((heap, p, "lower"))
        elif f is not None:
            out.append((heap, f, "upper"))
    return out


def predict_start(found, heap, window):
    """(the row count of the first run, the first step of the search) for `heap` from the estimates of the smaller
    heap sizes, None without any. The frontier does not fall with a growing heap: it is extrapolated by the trend of
    the last two full brackets, and is not put below a lower bound found at a later heap size."""
    if not found:
        return None
    guess, step = found[-1][1], window
    full = [e for e in found if e[2] == "full"]
    if len(full) >= 2:
        (h0, e0, _), (h1, e1, _) = full[-2], full[-1]
        guess = e1 + max(0.0, (e1 - e0) / (h1 - h0)) * (heap - h1)
        step = max(window, round(abs(guess - e1) / 2))
    lower = [e[1] for e in found if e[2] == "lower" and (not full or e[0] > full[-1][0])]
    if lower:
        guess = max(guess, max(lower))
    return round(guess), step


# ------------------------------------------------------------------ recorded state
class State:
    """What earlier runs of the script recorded: the finished steps and the single runs."""

    def __init__(self, ranges_csv, runs_csv):
        self.ranges_csv, self.runs_csv = ranges_csv, runs_csv
        self.steps = {(r["Dremio ver"], r["Java image"], int(r["Heap MB"])): r for r in csvio.read_rows(ranges_csv, missing_ok=True)}
        self.runs = {(r["Dremio ver"], r["Java image"], int(r["Heap MB"]), int(r["Rows"])): r["Outcome"]
                     for r in csvio.read_rows(runs_csv, missing_ok=True)}

    def heap_runs(self, combo):
        """{heap: {rows_m: PASS | FAIL}} of the recorded runs of a combination (ERROR runs say nothing about the frontier)."""
        out = {}
        for (version, image, heap, rows_m), outcome in self.runs.items():
            if (version, image) == (combo.version, combo.image) and outcome in (PASS, FAIL):
                out.setdefault(heap, {})[rows_m] = outcome
        return out

    def run_outcome(self, combo, heap, rows_m):
        return self.runs.get((combo.version, combo.image, heap, rows_m))

    def add_run(self, combo, heap, rows_m, outcome):
        self.runs[combo.version, combo.image, heap, rows_m] = outcome
        csvio.append_row(self.runs_csv, RUNS_COLUMNS, {
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
        csvio.append_row(self.ranges_csv, RANGES_COLUMNS, row)


# ------------------------------------------------------------------ one combination
class Progress:
    """Where the walk over the heap sizes stands for one combination."""

    def __init__(self):
        self.skipped = 0         # heap steps skipped in a row
        self.finished = False    # nothing fails any more: larger heaps pass too


def first_guess(args, state, combo, others, heap, notes=None):
    """The start of the search of a step from the recorded runs: (row count of the first run, first step), None when
    nothing is recorded.

    Candidates: the own trend of the combination (predict_start) and, for every other combination that has a full
    bracket at this very heap size, the middle of that bracket moved by the usual distance between the two (at the
    last heap size where both have one). The guess is their average. A PASS of another combination at this heap size
    is not to be probed below: the guess is not lower than the highest of them. Without any of this the latest result
    of another combination starts the search. `notes`, if given, gets the parts of the guess for the log."""
    notes = [] if notes is None else notes
    own = estimates(state.heap_runs(combo), heap)
    base = predict_start(own, heap, args.window)
    own_full = {h: e for h, e, kind in own if kind == "full"}
    candidates = [base[0]] if base else []
    if base:
        notes.append(f"own trend {base[0]}M")
    highest_pass = None
    for other in others:
        runs = state.heap_runs(other)
        p, f = bracket(runs.get(heap, {}))
        if p is not None:
            highest_pass = p if highest_pass is None else max(highest_pass, p)
        if p is None or f is None:
            continue
        theirs = {h: e for h, e, kind in estimates(runs, heap) if kind == "full"}
        common = [h for h in own_full if h in theirs]
        offset = own_full[max(common)] - theirs[max(common)] if common else 0
        candidates.append((p + f) / 2 + offset)
        notes.append(f"{other.version} {other.image} {(p + f) / 2:g}M {offset:+g}M = {candidates[-1]:g}M")
    if not candidates:
        for other in others:                       # nothing of its own and nothing of the others at this heap size
            found = estimates(state.heap_runs(other), heap + 1)[-1:]
            if found:
                base = predict_start(found, heap, args.window)
                candidates = [base[0]]
                notes.append(f"latest result of {other.version} {other.image} {base[0]}M")
                break
    if not candidates:
        return None
    guess = round(sum(candidates) / len(candidates))
    if highest_pass is not None and highest_pass > guess:
        notes.append(f"raised to the PASS {highest_pass}M of another combination at this heap")
        guess = highest_pass
    step = max(base[1] if base else args.window, round((max(candidates) - min(candidates)) / 2))
    return guess, step


def sibling_fail_cap(state, others, heap):
    """The lowest FAIL of the other combinations at this heap size, None when none of them has failed there."""
    fails = [bracket(state.heap_runs(other).get(heap, {}))[1] for other in others]
    return min((f for f in fails if f is not None), default=None)


def sibling_passes(state, others, heap):
    """The row counts where the other combinations passed at this heap size."""
    return sorted({r for other in others for r, outcome in state.heap_runs(other).get(heap, {}).items() if outcome == PASS})


def run_step(args, combo, heap, runner, state, progress, log=print, others=()):
    """The step of a combination at one heap size. `runner.run(heap, rows_m) -> PASS | FAIL | ERROR`."""
    done = state.step(combo, heap)
    if done:
        log(f"### {combo.version} {combo.image} heap={heap}: recorded ({done['Status']}, mean {done['Mean rows'] or '-'})")
        progress.finished = done["Status"] == "ALL_PASS"
        return
    lo, hi = bracket(state.heap_runs(combo).get(heap, {}))
    notes = []
    guess = first_guess(args, state, combo, others, heap, notes)
    cap = sibling_fail_cap(state, others, heap)
    if cap is not None and (lo is None or cap > lo):
        notes.append(f"runs upwards stop at {cap}M, where another combination failed")
    start, step = guess if guess else (None, args.window)
    if lo is not None or hi is not None:
        log(f"### {combo.version} {combo.image} heap={heap}: recorded runs give PASS up to {lo or '-'}M, FAIL from {hi or '-'}M"
            + (f"; guess {start}M, step {step}M ({'; '.join(notes)})" if guess else ""))
    elif guess:
        log(f"### {combo.version} {combo.image} heap={heap}: first run at {start}M, step {step}M ({'; '.join(notes)})")
    else:
        log(f"### {combo.version} {combo.image} heap={heap}: nothing recorded, searching {args.rows_low}M..{args.rows_high}M")

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
        if lo is None and hi is None and not guess:
            result = search(run, args.rows_low, args.rows_high, args.precision, args.rows_low, args.rows_high)
        else:
            result = search_guided(run, lo, hi, start, step, args.precision, args.rows_low, args.rows_high, cap,
                                   sibling_passes(state, others, heap))
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


def run_all(args, combos, runner_for, state, log=print):
    """Walks the heap sizes of all combinations together: at every heap size each combination does its step, so
    all the lines of the chart grow at the same time. The container of a step is deleted when the step is done
    (the next heap size needs a new one anyway), so only one container exists at a time."""
    progress = {c: Progress() for c in combos}
    for heap in heap_sizes(args.heap_start, args.heap_step, args.heap_max):
        for combo in combos:
            if progress[combo].finished:
                continue
            runner = runner_for(combo)
            try:
                run_step(args, combo, heap, runner, state, progress[combo], log, others=[c for c in combos if c != combo])
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
        env = {**os.environ, "BLOCKS_DIR": os.environ.get("BLOCKS_DIR", f"{self.args.storage_root}/{defaults.BLOCKS_SUBDIR}")}
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
    ap.add_argument("--window", type=int, default=10, metavar="M", help="the first step of the search away from the guess, millions of rows (default 10); it doubles while the frontier is not bracketed")
    ap.add_argument("--max-skipped", type=int, default=3, help="stop after this many skipped heap steps in a row")
    ap.add_argument("--retry-errors", action="store_true", help="run again the runs recorded as ERROR")
    ap.add_argument("--storage-root", default=str(defaults.STORAGE_ROOT), help="a combination stores its data in <root>/<container name>")
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
