"""Offline tests of the OOM frontier search (oom_ranges.py): the search, the steps over the heap sizes, the resume."""
import argparse

import pytest

import oom_ranges as o
import results_report


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


def mean_of(row):
    return results_report.parse_rows(row["Mean rows"]) / 10**6


def test_steps_follow_the_heap_and_start_at_the_recorded_frontier(tmp_path):
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    runner = FakeRunner(lambda heap: 100 + (heap - 512) * 2)          # frontier 100M, 228M, 356M, 484M, 612M
    o.run_all(make_args(tmp_path), [combo()], lambda c: runner, state, log=lambda *a: None)
    rows = read(tmp_path / "ranges.csv")
    assert [r["Heap MB"] for r in rows] == ["512", "576", "640", "704", "768"]
    assert all(r["Status"] == "RANGE" for r in rows)
    means = [mean_of(r) for r in rows]
    assert means == sorted(means) and abs(means[0] - 100) <= 10 and abs(means[-1] - 612) <= 10
    first_runs = {}
    for heap, rows_m in runner.calls:
        first_runs.setdefault(heap, rows_m)
    assert first_runs[576] == round(means[0])                       # the first run is at the previous frontier
    assert abs(first_runs[768] - 612) < abs(first_runs[576] - 228)  # the trend of the last steps is followed


def test_heap_steps_stop_when_everything_passes(tmp_path):
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    runner = FakeRunner(lambda heap: 10**9 if heap >= 640 else 200)
    o.run_all(make_args(tmp_path, heap_max=2048), [combo()], lambda c: runner, state, log=lambda *a: None)
    rows = read(tmp_path / "ranges.csv")
    assert [r["Status"] for r in rows] == ["RANGE", "RANGE", "ALL_PASS"] and rows[-1]["Heap MB"] == "640"
    assert not any(heap > 640 for heap, _ in runner.calls)


def test_a_step_with_an_error_is_skipped_and_the_next_one_goes_on(tmp_path):
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    runner = FakeRunner(lambda heap: 300, errors={576})
    o.run_all(make_args(tmp_path), [combo()], lambda c: runner, state, log=lambda *a: None)
    assert [r["Heap MB"] for r in read(tmp_path / "ranges.csv")] == ["512", "640", "704", "768"]
    assert "ERROR" in [r["Outcome"] for r in read(tmp_path / "runs.csv")]


def test_too_many_skipped_steps_in_a_row_stop_the_script(tmp_path):
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    runner = FakeRunner(lambda heap: 300, errors={512, 576, 640})
    with pytest.raises(SystemExit, match="3 heap steps in a row"):
        o.run_all(make_args(tmp_path), [combo()], lambda c: runner, state, log=lambda *a: None)


def test_a_second_run_repeats_nothing(tmp_path):
    args = make_args(tmp_path)
    first = FakeRunner(lambda heap: 300)
    o.run_all(args, [combo()], lambda c: first, o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv"), log=lambda *a: None)
    second = FakeRunner(lambda heap: 300)
    o.run_all(args, [combo()], lambda c: second, o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv"), log=lambda *a: None)
    assert first.calls and not second.calls
    assert len(read(tmp_path / "ranges.csv")) == 5


def test_resume_after_an_interrupted_step_reuses_its_runs(tmp_path):
    args = make_args(tmp_path, heap_max=512)
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    runner = FakeRunner(lambda heap: 300)
    o.run_all(args, [combo()], lambda c: runner, state, log=lambda *a: None)
    full = len(runner.calls)
    (tmp_path / "ranges.csv").unlink()                  # the step did not finish, its runs are recorded
    again = FakeRunner(lambda heap: 300)
    o.run_all(args, [combo()], lambda c: again, o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv"), log=lambda *a: None)
    assert full > 0 and not again.calls
    assert len(read(tmp_path / "ranges.csv")) == 1


def test_recorded_errors_are_retried_only_on_request(tmp_path):
    args = make_args(tmp_path, heap_max=512, max_skipped=9)
    first = FakeRunner(lambda heap: 300, errors={512})
    o.run_all(args, [combo()], lambda c: first, o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv"), log=lambda *a: None)
    same = FakeRunner(lambda heap: 300)
    o.run_all(args, [combo()], lambda c: same, o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv"), log=lambda *a: None)
    assert not same.calls and not read(tmp_path / "ranges.csv")
    retry = FakeRunner(lambda heap: 300)
    o.run_all(make_args(tmp_path, heap_max=512, retry_errors=True), [combo()], lambda c: retry,
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


def combos4():
    return [o.Combo(f"/x/dremio-enterprise-{v}-1.tar.gz", img) for v in ("26.1.8", "26.1.10") for img in ("a", "b")]


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


def test_all_combinations_do_each_heap_size_together(tmp_path):
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    order, deleted = [], []
    combos = combos4()
    o.run_all(make_args(tmp_path), combos, FakeFleet(lambda c, heap: 300 + heap, order, deleted), state, log=lambda *a: None)
    rows = read(tmp_path / "ranges.csv")
    assert [r["Heap MB"] for r in rows] == [str(h) for h in (512, 576, 640, 704, 768) for _ in combos]  # heap by heap
    assert [(r["Dremio ver"], r["Java image"]) for r in rows[:4]] == [(c.version, c.image) for c in combos]
    heaps_in_run_order = [h for _, h in dict.fromkeys(order)]
    assert heaps_in_run_order == sorted(heaps_in_run_order)
    assert len(deleted) == 5 * 4                    # the container of every step is deleted when the step is done


def test_a_combination_that_only_passes_drops_out_the_others_go_on(tmp_path):
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    combos = combos4()
    limit = lambda c, heap: 10**9 if c == combos[0] and heap >= 576 else 300 + heap
    o.run_all(make_args(tmp_path), combos, FakeFleet(limit, [], []), state, log=lambda *a: None)
    per_combo = {}
    for r in read(tmp_path / "ranges.csv"):
        per_combo.setdefault((r["Dremio ver"], r["Java image"]), []).append(r["Heap MB"])
    key = lambda c: (c.version, c.image)
    assert per_combo[key(combos[0])] == ["512", "576"] and len(per_combo[key(combos[1])]) == 5


def test_a_combination_without_a_result_starts_in_a_window_around_another_ones(tmp_path):
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    combos = combos4()[:2]
    o.run_all(make_args(tmp_path, heap_max=512), combos, FakeFleet(lambda c, heap: 300 + heap, [], []), state, log=lambda *a: None)
    runs = read(tmp_path / "runs.csv")
    first = [int(r["Rows"]) for r in runs if r["Java image"] == combos[0].image and r["Dremio ver"] == combos[0].version]
    second = [int(r["Rows"]) for r in runs if r["Java image"] == combos[1].image and r["Dremio ver"] == combos[1].version]
    assert first[0] == 725 and abs(second[0] - 812) <= 150


def guided(limit, lo=None, hi=None, guess=100, step=10, precision=10, floor=10, ceil=1440):
    calls = []

    def run(rows):
        calls.append(rows)
        return o.PASS if rows < limit else o.FAIL
    return o.search_guided(run, lo, hi, guess, step, precision, floor, ceil), calls


def test_guided_search_with_a_good_guess_needs_three_runs():
    r, calls = guided(limit=107, guess=105, step=10)
    assert r.status == "RANGE" and r.pass_max < 107 <= r.fail_min and r.fail_min - r.pass_max <= 10 and len(calls) <= 3


def test_guided_search_gallops_away_from_a_wrong_guess_in_few_runs():
    r, calls = guided(limit=700, guess=100)                   # 600M above the guess: 10, 20, 40, ... steps
    assert r.pass_max < 700 <= r.fail_min and r.fail_min - r.pass_max <= 10 and len(calls) <= 12
    r, calls = guided(limit=30, guess=500)
    assert r.pass_max < 30 <= r.fail_min and r.fail_min - r.pass_max <= 10 and len(calls) <= 12


def test_guided_search_from_a_known_end_does_not_run_it_again():
    r, calls = guided(limit=300, lo=250)
    assert 250 not in calls and r.pass_max < 300 <= r.fail_min
    r, calls = guided(limit=300, hi=400)
    assert 400 not in calls and r.pass_max < 300 <= r.fail_min
    r, calls = guided(limit=300, lo=290, hi=305)               # a bracket of the recorded runs: halving only
    assert calls == [297] and r.status == "RANGE"


def test_guided_search_all_pass_and_all_fail():
    assert guided(limit=10**9, guess=100)[0].status == "ALL_PASS"
    r, calls = guided(limit=0, guess=100)
    assert r.status == "ALL_FAIL" and r.mean is None and min(calls) == 10


def test_bracket_of_mixed_runs_is_taken_below_the_lowest_fail():
    assert o.bracket({50: o.PASS, 100: o.FAIL, 200: o.PASS, 300: o.FAIL}) == (50, 100)
    assert o.bracket({50: o.PASS}) == (50, None) and o.bracket({50: o.FAIL}) == (None, 50) and o.bracket({}) == (None, None)


def test_predict_start_follows_the_trend_and_a_lower_bound():
    full = lambda h, e: (h, e, "full")
    assert o.predict_start([], 576, 10) is None
    assert o.predict_start([full(512, 500)], 576, 10) == (500, 10)                       # one step: no trend, flat
    assert o.predict_start([full(512, 500), full(576, 600)], 640, 10) == (700, 50)       # +100M per 64 MB
    assert o.predict_start([full(512, 600), full(576, 500)], 640, 10) == (500, 10)       # the frontier does not fall
    assert o.predict_start([full(512, 500), full(576, 600), (640, 750, "lower")], 704, 10)[0] == 800
    assert o.predict_start([full(512, 500), full(576, 600), (640, 900, "lower")], 704, 10)[0] == 900
    assert o.predict_start([(512, 658, "lower")], 576, 10) == (658, 10)


def test_estimates_use_the_runs_of_the_smaller_heap_sizes_only():
    runs = {512: {400: o.PASS, 500: o.FAIL}, 576: {600: o.PASS}, 640: {300: o.FAIL}, 704: {1: o.PASS}}
    assert o.estimates(runs, 704) == [(512, 450.0, "full"), (576, 600, "lower"), (640, 300, "upper")]


def test_a_step_with_recorded_runs_does_not_repeat_them_and_a_known_bracket_needs_no_search(tmp_path):
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    for rows, outcome in ((460, o.PASS), (530, o.FAIL), (495, o.PASS), (512, o.FAIL)):
        state.add_run(combo(), 512, rows, outcome)
    runner = FakeRunner(lambda heap: 500)
    o.run_all(make_args(tmp_path, heap_max=512), [combo()], lambda c: runner, state, log=lambda *a: None)
    assert runner.calls == [(512, 503)]                                  # only the halving of [495, 512]
    assert read(tmp_path / "ranges.csv")[0]["Status"] == "RANGE"


def test_a_moving_frontier_costs_few_runs_per_step(tmp_path):
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    runner = FakeRunner(lambda heap: 300 + (heap - 512) * 3)             # +192M per heap step
    o.run_all(make_args(tmp_path, heap_max=1024, precision=20), [combo()], lambda c: runner, state, log=lambda *a: None)
    per_heap = {}
    for heap, _ in runner.calls:
        per_heap[heap] = per_heap.get(heap, 0) + 1
    assert all(n <= 6 for h, n in per_heap.items() if h >= 704), per_heap   # once the trend is known


RECORDED_RUNS = """Timestamp,Dremio ver,Java image,Heap MB,Rows,Outcome
2026-10-17_10-02-10,26.1.8,wolfi-jdk:21,576,578,PASS
2026-10-17_10-07-30,26.1.8,wolfi-jdk:21,576,658,PASS
2026-10-17_10-11-32,26.1.8,wolfi-jdk:21,576,698,FAIL
2026-10-17_10-18-07,26.1.8,wolfi-jdk:21,576,678,PASS
"""


def package_combo(version, image):
    return o.Combo(f"/x/dremio-enterprise-{version}-202605070149260956-31448f13.tar.gz", image)


def test_first_run_of_a_new_combination_is_near_the_result_of_another(tmp_path):
    """Heap 576 of 26.1.8 / wolfi-jdk:21 has PASS at 578, 658, 678 and FAIL at 698: the bracket is [678, 698], its middle 688.
    26.1.10 / eclipse-temurin:21-jdk has no runs of its own at heap 576: its first run goes to 688M."""
    (tmp_path / "runs.csv").write_text(RECORDED_RUNS)
    state = o.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    old, new = package_combo("26.1.8", "wolfi-jdk:21"), package_combo("26.1.10", "eclipse-temurin:21-jdk")
    assert o.bracket(state.heap_runs(old)[576]) == (678, 698)
    assert o.first_guess(make_args(tmp_path, window=10), state, new, [old], 576) == (688, 10)

    calls = []
    runner = FakeRunner(lambda heap: 690)                                  # the new combination fails from 690M
    runner.run = lambda heap, rows, run=runner.run: (calls.append(rows), run(heap, rows))[1]
    # the bracket of the old one is 20M wide, so with precision 20 its step needs no run and the first run is the new one's
    o.run_all(make_args(tmp_path, heap_start=576, heap_max=576, window=10, precision=20), [old, new],
              lambda c: runner, state, log=lambda *a: None)
    assert calls[0] == 688                                                 # the first measured value


def test_a_known_pass_is_followed_by_the_prediction_not_by_a_doubling_step():
    """Recorded PASS at 428M, 558M; predicted frontier 638M, first step 130M: the next run is 638M. A doubling step from the
    last PASS would be 558 + 260 = 818M, far above where the frontier is expected."""
    calls = []

    def run(rows):
        calls.append(rows)
        return o.PASS if rows < 690 else o.FAIL
    r = o.search_guided(run, 558, None, 638, 130, 20, 10, 1440)
    assert calls[0] == 638 and 818 not in calls and len(calls) <= 5
    assert r.status == "RANGE" and r.pass_max < 690 <= r.fail_min and r.fail_min - r.pass_max <= 20


def test_a_known_fail_is_followed_by_the_prediction_from_below():
    calls = []

    def run(rows):
        calls.append(rows)
        return o.PASS if rows < 300 else o.FAIL
    r = o.search_guided(run, None, 500, 320, 40, 20, 10, 1440)
    assert calls[0] == 320 and r.pass_max < 300 <= r.fail_min
