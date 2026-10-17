"""Fakes and builders shared by the tests of the OOM search (the oom package)."""
import argparse

import csvio
import results_report
from oom import model as m
from oom import state as st

OWN = ("26.1.10", "eclipse-temurin:21-jdk")
SIB = ("26.1.8", "wolfi-jdk:21")


def package_combo(version, image):
    return m.Combo(f"/x/dremio-enterprise-{version}-202605070149260956-31448f13.tar.gz", image)


class FakeRunner:
    """The test of a combination: passes below limit(heap) million rows; `errors` heap sizes end in an ERROR."""
    def __init__(self, limit, errors=()):
        self.limit, self.errors, self.calls = limit, set(errors), []

    def run(self, heap, rows_m):
        self.calls.append((heap, rows_m))
        if heap in self.errors:
            return m.ERROR
        return m.PASS if rows_m < self.limit(heap) else m.FAIL

    @property
    def rows(self):
        """The row counts of the runs, in the order they were made."""
        return [rows_m for _, rows_m in self.calls]


def make_args(tmp_path, **kw):
    a = dict(heap_start=512, heap_step=64, heap_max=768, rows_low=10, rows_high=1440, precision=10, window=150,
             max_skipped=3, retry_errors=False)
    a.update(kw)
    return argparse.Namespace(**a)


def combo():
    return package_combo("26.1.10", "wolfi-jdk:21")


def read(path):
    return csvio.read_rows(path, missing_ok=True)


def mean_of(row):
    return results_report.parse_rows(row["Mean rows"]) / 10**6


def combos4():
    return [m.Combo(f"/x/dremio-enterprise-{v}-1.tar.gz", img) for v in ("26.1.8", "26.1.10") for img in ("a", "b")]


class FakeFleet:
    """One FakeRunner per combination; remembers the order of the runs and the deleted containers."""
    def __init__(self, limit, order, deleted):
        self.runners, self.limit, self.order, self.deleted = {}, limit, order, deleted

    def __call__(self, combo):
        if combo not in self.runners:
            runner = FakeRunner(lambda heap, c=combo: self.limit(c, heap))
            runner.delete = lambda c=combo: self.deleted.append(c)
            run = runner.run
            runner.run = lambda heap, rows, c=combo, run=run: (self.order.append((c, heap)), run(heap, rows))[1]
            self.runners[combo] = runner
        return self.runners[combo]


def sibling_state(tmp_path, rows):
    """A State over the recorded runs `rows`: tuples (Dremio ver, Java image, heap, rows in millions, outcome)."""
    lines = ["Timestamp,Dremio ver,Java image,Heap MB,Rows,Outcome"] + [f"t,{v},{i},{h},{r},{o}" for v, i, h, r, o in rows]
    (tmp_path / "runs.csv").write_text("\n".join(lines) + "\n")
    return st.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")


def history_rows(sibling_at_576):
    """Own history 118M -> 378M (+260M per heap step), the sibling 188M -> 448M, i.e. always 70M higher."""
    rows = []
    for (v, i), brackets in ((OWN, ((448, 108, 128), (512, 368, 388))), (SIB, ((448, 178, 198), (512, 438, 458)))):
        for heap, p, f in brackets:
            rows += [(v, i, heap, p, "PASS"), (v, i, heap, f, "FAIL")]
    return rows + [(*SIB, 576, r, o) for r, o in sibling_at_576]
