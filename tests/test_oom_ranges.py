"""Offline tests of the OOM frontier search (oom_ranges.py): the search, the steps over the heap sizes, the resume."""
import argparse

import pytest

import oom_ranges as o


def threshold_run(limit, calls=None):
    """A test that passes below `limit` million rows and fails from it on."""
    def run(rows):
        if calls is not None:
            calls.append(rows)
        return o.PASS if rows < limit else o.FAIL
    return run


def search(run, lo=10, hi=1440, precision=10, floor=10, ceil=1440):
    return o.search(run, lo, hi, precision, floor, ceil)


def test_search_finds_the_frontier_within_the_precision():
    calls = []
    r = search(threshold_run(300, calls))
    assert r.status == "RANGE" and r.pass_max < 300 <= r.fail_min and r.fail_min - r.pass_max <= 10
    assert r.mean == (r.pass_max + r.fail_min) / 2
    assert len(calls) == len(set(calls)) <= 9          # no row count is run twice


def test_search_moves_the_window_up_when_nothing_fails_in_it():
    r = search(threshold_run(900), lo=100, hi=400)
    assert r.status == "RANGE" and r.pass_max < 900 <= r.fail_min and r.fail_min - r.pass_max <= 10


def test_search_moves_the_window_down_when_nothing_passes_in_it():
    r = search(threshold_run(120), lo=800, hi=1100)
    assert r.status == "RANGE" and r.pass_max < 120 <= r.fail_min and r.fail_min - r.pass_max <= 10


def test_search_all_pass_and_all_fail():
    assert search(threshold_run(10**9)).status == "ALL_PASS"
    r = search(threshold_run(0))
    assert r.status == "ALL_FAIL" and r.mean is None


def test_search_stops_at_the_first_error():
    def run(rows):
        raise o.StepSkipped(rows)
    with pytest.raises(o.StepSkipped):
        search(run)


def test_window_is_clipped_to_the_row_range():
    assert o.window_around(100, 150, 10, 1440) == (10, 250)
    assert o.window_around(1400, 150, 10, 1440) == (1250, 1440)


def test_heap_sizes():
    assert o.heap_sizes(512, 64, 2048)[:3] == [512, 576, 640] and o.heap_sizes(512, 64, 2048)[-1] == 2048
    assert o.heap_sizes(512, 64, 500) == []


@pytest.mark.parametrize("output, heap_oom", [
    ("java.lang.OutOfMemoryError: Java heap space", True),
    ("SYSTEM ERROR: OutOfMemoryError: GC overhead limit exceeded", True),
    ("OUT_OF_MEMORY ERROR: Query was cancelled because it exceeded the memory limits set by the administrator.\n"
     "  Heap monitor detected that the heap is almost full\n  ErrorOrigin: EXECUTOR\n"
     "(com.dremio.common.exceptions.OutOfHeapMemoryException) Heap monitor detected that the heap is almost full", True),
    ("OUT_OF_MEMORY ERROR: Query was cancelled because it exceeded the memory limits set by the administrator.\n"
     "  Unable to allocate buffer of size 4096 due to memory limit. Current allocation: 4294967296", False),
    ("Unable to allocate buffer of size 1048576 due to memory limit (direct memory)", False),
    ("OutOfMemoryError: Direct buffer memory", False),
    ("requests.exceptions.ReadTimeout", False)])
def test_only_a_heap_oom_is_a_failure(output, heap_oom):
    assert o.classify_failure(output, "") is heap_oom
    assert o.classify_failure("", output) is heap_oom


class FakeRunner:
    """The test of a combination: passes below limit(heap) million rows; `errors` heap sizes end in an ERROR."""
    def __init__(self, limit, errors=()):
        self.limit, self.errors, self.calls = limit, set(errors), []

    def run(self, heap, rows_m):
        self.calls.append((heap, rows_m))
        if heap in self.errors:
            return o.ERROR
        return o.PASS if rows_m < self.limit(heap) else o.FAIL


def make_args(tmp_path, **kw):
    a = dict(heap_start=512, heap_step=64, heap_max=768, rows_low=10, rows_high=1440, precision=10, window=150,
             max_skipped=3, retry_errors=False)
    a.update(kw)
    return argparse.Namespace(**a)


def combo():
    return o.Combo("/x/dremio-enterprise-26.1.10-202607291955500295-6a7e3d8c.tar.gz", "wolfi-jdk:21")


def read(path):
    return o.read_csv(path)


def test_combo_version_is_short():
    assert combo().version == "26.1.10"


def test_steps_follow_the_heap_and_use_a_window_after_the_first(tmp_path):
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    runner = FakeRunner(lambda heap: 100 + (heap - 512) * 2)          # frontier 100M, 228M, 356M
    o.run_combo(make_args(tmp_path), combo(), runner, state, log=lambda *a: None)
    rows = read(tmp_path / "ranges.csv")
    assert [r["Heap MB"] for r in rows] == ["512", "576", "640", "704", "768"]
    assert all(r["Status"] == "RANGE" for r in rows)
    means = [o.step_center(r) for r in rows]
    assert means == sorted(means) and abs(means[0] - 100) <= 10 and abs(means[-1] - 612) <= 10
    second_step = [rows_m for heap, rows_m in runner.calls if heap == 576]
    assert min(second_step) >= round(means[0]) - 150 - 1 and max(second_step) <= round(means[0]) + 150 + 1


def test_heap_steps_stop_when_everything_passes(tmp_path):
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    runner = FakeRunner(lambda heap: 10**9 if heap >= 640 else 200)
    o.run_combo(make_args(tmp_path, heap_max=2048), combo(), runner, state, log=lambda *a: None)
    rows = read(tmp_path / "ranges.csv")
    assert [r["Status"] for r in rows] == ["RANGE", "RANGE", "ALL_PASS"] and rows[-1]["Heap MB"] == "640"
    assert not any(heap > 640 for heap, _ in runner.calls)


def test_a_step_with_an_error_is_skipped_and_the_next_one_goes_on(tmp_path):
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    runner = FakeRunner(lambda heap: 300, errors={576})
    o.run_combo(make_args(tmp_path), combo(), runner, state, log=lambda *a: None)
    assert [r["Heap MB"] for r in read(tmp_path / "ranges.csv")] == ["512", "640", "704", "768"]
    assert "ERROR" in [r["Outcome"] for r in read(tmp_path / "runs.csv")]


def test_too_many_skipped_steps_in_a_row_stop_the_script(tmp_path):
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    runner = FakeRunner(lambda heap: 300, errors={512, 576, 640})
    with pytest.raises(SystemExit, match="3 heap steps in a row"):
        o.run_combo(make_args(tmp_path), combo(), runner, state, log=lambda *a: None)


def test_a_second_run_repeats_nothing(tmp_path):
    args = make_args(tmp_path)
    first = FakeRunner(lambda heap: 300)
    o.run_combo(args, combo(), first, o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv"), log=lambda *a: None)
    second = FakeRunner(lambda heap: 300)
    o.run_combo(args, combo(), second, o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv"), log=lambda *a: None)
    assert first.calls and not second.calls
    assert len(read(tmp_path / "ranges.csv")) == 5


def test_resume_after_an_interrupted_step_reuses_its_runs(tmp_path):
    args = make_args(tmp_path, heap_max=512)
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    runner = FakeRunner(lambda heap: 300)
    o.run_combo(args, combo(), runner, state, log=lambda *a: None)
    full = len(runner.calls)
    (tmp_path / "ranges.csv").unlink()                  # the step did not finish, its runs are recorded
    again = FakeRunner(lambda heap: 300)
    o.run_combo(args, combo(), again, o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv"), log=lambda *a: None)
    assert full > 0 and not again.calls
    assert len(read(tmp_path / "ranges.csv")) == 1


def test_recorded_errors_are_retried_only_on_request(tmp_path):
    args = make_args(tmp_path, heap_max=512, max_skipped=9)
    first = FakeRunner(lambda heap: 300, errors={512})
    o.run_combo(args, combo(), first, o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv"), log=lambda *a: None)
    same = FakeRunner(lambda heap: 300)
    o.run_combo(args, combo(), same, o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv"), log=lambda *a: None)
    assert not same.calls and not read(tmp_path / "ranges.csv")
    retry = FakeRunner(lambda heap: 300)
    o.run_combo(make_args(tmp_path, heap_max=512, retry_errors=True), combo(), retry,
                o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv"), log=lambda *a: None)
    assert retry.calls and len(read(tmp_path / "ranges.csv")) == 1


def test_mean_is_written_with_the_row_suffix(tmp_path):
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    state.add_step(combo(), 512, o.Result("RANGE", 50, 200))
    row = read(tmp_path / "ranges.csv")[0]
    assert (row["Pass max rows"], row["Fail min rows"], row["Mean rows"]) == ("50M", "200M", "125M")
    assert row["Dremio ver"] == "26.1.10" and row["Java image"] == "wolfi-jdk:21"


def test_default_heap_max_is_the_container_without_direct_and_reserve(tmp_path, monkeypatch):
    monkeypatch.setattr(o, "find_package", lambda v: f"/x/dremio-enterprise-{v}-1.tar.gz")
    a = o.parse_args([])
    assert a.heap_max == 8192 - 4096 - 2048 and len(a.packages) == 2 and a.java_images == ["eclipse-temurin:21-jdk", "wolfi-jdk:21"]
    with pytest.raises(SystemExit, match="even"):
        o.parse_args(["--heap-step", "63"])
