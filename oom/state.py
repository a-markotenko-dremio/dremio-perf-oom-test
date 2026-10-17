"""What earlier runs of the script recorded: the single runs (data/oom_runs.csv), the only primary data. The finished
steps are derived from them; data/oom_ranges.csv is written from them for the chart and never read."""
import csvio
import results_report
from .model import FAIL, PASS
from .search import step_result

RANGES_COLUMNS = ["Dremio ver", "Java image", "Heap MB", "Pass max rows", "Fail min rows", "Mean rows", "Status"]
RUNS_COLUMNS = ["Timestamp", "Dremio ver", "Java image", "Heap MB", "Rows", "Outcome"]


def rows_text(millions):
    return "" if millions is None else results_report.format_rows(round(millions * 10**6))


class State:
    """The recorded runs. `args` gives the precision and the row count limits that decide when a step is finished."""

    def __init__(self, ranges_csv, runs_csv, args):
        self.ranges_csv, self.runs_csv, self.args = ranges_csv, runs_csv, args
        self.runs = {(r["Dremio ver"], r["Java image"], int(r["Heap MB"]), int(r["Rows"])): r["Outcome"]
                     for r in csvio.read_rows(runs_csv, missing_ok=True)}

    def _heap_runs(self, version, image):
        out = {}
        for (v, i, heap, rows_m), outcome in self.runs.items():
            if (v, i) == (version, image) and outcome in (PASS, FAIL):
                out.setdefault(heap, {})[rows_m] = outcome
        return out

    def heap_runs(self, combo):
        """{heap: {rows_m: PASS | FAIL}} of the recorded runs of a combination (ERROR runs say nothing about the frontier)."""
        return self._heap_runs(combo.version, combo.image)

    def run_outcome(self, combo, heap, rows_m):
        return self.runs.get((combo.version, combo.image, heap, rows_m))

    def step(self, combo, heap):
        """The Result of the step of a combination at a heap size when its runs have found the frontier, else None."""
        outcomes = self.heap_runs(combo).get(heap)
        return outcomes and step_result(outcomes, self.args.precision, self.args.rows_low, self.args.rows_high)

    def add_run(self, combo, heap, rows_m, outcome):
        """Records a run and writes the ranges file again."""
        self.runs[combo.version, combo.image, heap, rows_m] = outcome
        csvio.append_row(self.runs_csv, RUNS_COLUMNS, {
            "Timestamp": results_report.timestamp(), "Dremio ver": combo.version, "Java image": combo.image,
            "Heap MB": heap, "Rows": rows_m, "Outcome": outcome})
        self.write_ranges()

    def write_ranges(self):
        """Writes the ranges file (one row per finished step) from the recorded runs, replacing the old one."""
        rows = []
        for version, image in sorted({(v, i) for v, i, _, _ in self.runs}):
            for heap, outcomes in sorted(self._heap_runs(version, image).items()):
                result = step_result(outcomes, self.args.precision, self.args.rows_low, self.args.rows_high)
                if result:
                    rows.append({"Dremio ver": version, "Java image": image, "Heap MB": heap,
                                 "Pass max rows": rows_text(result.pass_max), "Fail min rows": rows_text(result.fail_min),
                                 "Mean rows": rows_text(result.mean), "Status": result.status})
        csvio.write_rows(self.ranges_csv, RANGES_COLUMNS, rows)
