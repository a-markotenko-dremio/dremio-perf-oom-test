"""What earlier runs of the script recorded (data/oom_ranges.csv, data/oom_runs.csv): the finished steps and the single runs."""
import csvio
import results_report
from .model import FAIL, PASS

RANGES_COLUMNS = ["Dremio ver", "Java image", "Heap MB", "Pass max rows", "Fail min rows", "Mean rows", "Status"]
RUNS_COLUMNS = ["Timestamp", "Dremio ver", "Java image", "Heap MB", "Rows", "Outcome"]


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
