"""Offline tests of the walk over the heap sizes (oom.steps) with a fake runner."""
import pytest

from oom import model as m
from oom import predict as p
from oom import steps as sp
from oom_helpers import (FakeFleet, FakeRunner, OWN, SIB, combo, combos4, history_rows, make_args, make_state, mean_of, package_combo, read,
                         sibling_state)


def test_steps_follow_the_heap_and_start_at_the_recorded_frontier(tmp_path):
    args = make_args(tmp_path)
    state = make_state(tmp_path, args)
    runner = FakeRunner(lambda heap: 100 + (heap - 512) * 2)          # frontier 100M, 228M, 356M, 484M, 612M
    sp.run_all(args, [combo()], lambda c: runner, state, log=lambda *a: None)
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
    args = make_args(tmp_path, heap_max=2048)
    state = make_state(tmp_path, args)
    runner = FakeRunner(lambda heap: 10**9 if heap >= 640 else 200)
    sp.run_all(args, [combo()], lambda c: runner, state, log=lambda *a: None)
    rows = read(tmp_path / "ranges.csv")
    assert [r["Status"] for r in rows] == ["RANGE", "RANGE", "ALL_PASS"] and rows[-1]["Heap MB"] == "640"
    assert not any(heap > 640 for heap, _ in runner.calls)


def test_a_step_with_an_error_is_skipped_and_the_next_one_goes_on(tmp_path):
    args = make_args(tmp_path)
    state = make_state(tmp_path, args)
    runner = FakeRunner(lambda heap: 300, errors={576})
    sp.run_all(args, [combo()], lambda c: runner, state, log=lambda *a: None)
    assert [r["Heap MB"] for r in read(tmp_path / "ranges.csv")] == ["512", "640", "704", "768"]
    assert "ERROR" in [r["Outcome"] for r in read(tmp_path / "runs.csv")]


def test_too_many_skipped_steps_in_a_row_stop_the_script(tmp_path):
    args = make_args(tmp_path)
    state = make_state(tmp_path, args)
    runner = FakeRunner(lambda heap: 300, errors={512, 576, 640})
    with pytest.raises(SystemExit, match="3 heap steps in a row"):
        sp.run_all(args, [combo()], lambda c: runner, state, log=lambda *a: None)


def test_a_second_run_repeats_nothing(tmp_path):
    args = make_args(tmp_path)
    first = FakeRunner(lambda heap: 300)
    sp.run_all(args, [combo()], lambda c: first, make_state(tmp_path, args), log=lambda *a: None)
    second = FakeRunner(lambda heap: 300)
    sp.run_all(args, [combo()], lambda c: second, make_state(tmp_path, args), log=lambda *a: None)
    assert first.calls and not second.calls
    assert len(read(tmp_path / "ranges.csv")) == 5


def test_recorded_errors_are_retried_only_on_request(tmp_path):
    args = make_args(tmp_path, heap_max=512, max_skipped=9)
    first = FakeRunner(lambda heap: 300, errors={512})
    sp.run_all(args, [combo()], lambda c: first, make_state(tmp_path, args), log=lambda *a: None)
    same = FakeRunner(lambda heap: 300)
    sp.run_all(args, [combo()], lambda c: same, make_state(tmp_path, args), log=lambda *a: None)
    assert not same.calls and not read(tmp_path / "ranges.csv")
    retry = FakeRunner(lambda heap: 300)
    retry_args = make_args(tmp_path, heap_max=512, retry_errors=True)
    sp.run_all(retry_args, [combo()], lambda c: retry, make_state(tmp_path, retry_args), log=lambda *a: None)
    assert retry.calls and len(read(tmp_path / "ranges.csv")) == 1


def test_all_combinations_do_each_heap_size_together(tmp_path):
    args = make_args(tmp_path)
    state = make_state(tmp_path, args)
    order, deleted = [], []
    combos = combos4()
    sp.run_all(args, combos, FakeFleet(lambda c, heap: 300 + heap, order, deleted), state, log=lambda *a: None)
    rows = read(tmp_path / "ranges.csv")
    assert sorted((r["Dremio ver"], r["Java image"], r["Heap MB"]) for r in rows) == \
        sorted((c.version, c.image, str(h)) for c in combos for h in (512, 576, 640, 704, 768))
    heaps_in_run_order = [h for _, h in dict.fromkeys(order)]
    assert heaps_in_run_order == sorted(heaps_in_run_order)      # heap by heap
    switches = 1 + sum(1 for x, y in zip(order, order[1:]) if x[0] != y[0])
    assert switches <= len(deleted) <= len(order)   # a container is deleted when the turn goes to another combination


def test_a_combination_that_only_passes_drops_out_the_others_go_on(tmp_path):
    args = make_args(tmp_path)
    state = make_state(tmp_path, args)
    combos = combos4()
    limit = lambda c, heap: 10**9 if c == combos[0] and heap >= 576 else 300 + heap
    sp.run_all(args, combos, FakeFleet(limit, [], []), state, log=lambda *a: None)
    per_combo = {}
    for r in read(tmp_path / "ranges.csv"):
        per_combo.setdefault((r["Dremio ver"], r["Java image"]), []).append(r["Heap MB"])
    key = lambda c: (c.version, c.image)
    assert per_combo[key(combos[0])] == ["512", "576"] and len(per_combo[key(combos[1])]) == 5


def test_a_combination_without_a_result_starts_in_a_window_around_another_ones(tmp_path):
    args = make_args(tmp_path, heap_max=512)
    state = make_state(tmp_path, args)
    combos = combos4()[:2]
    sp.run_all(args, combos, FakeFleet(lambda c, heap: 300 + heap, [], []), state, log=lambda *a: None)
    runs = read(tmp_path / "runs.csv")
    first = [int(r["Rows"]) for r in runs if r["Java image"] == combos[0].image and r["Dremio ver"] == combos[0].version]
    second = [int(r["Rows"]) for r in runs if r["Java image"] == combos[1].image and r["Dremio ver"] == combos[1].version]
    assert first[0] == 725 and abs(second[0] - 812) <= 150


def test_a_step_with_recorded_runs_does_not_repeat_them_and_a_known_bracket_needs_no_search(tmp_path):
    args = make_args(tmp_path, heap_max=512)
    state = make_state(tmp_path, args)
    for rows, outcome in ((460, m.PASS), (530, m.FAIL), (495, m.PASS), (512, m.FAIL)):
        state.add_run(combo(), 512, rows, outcome)
    runner = FakeRunner(lambda heap: 500)
    sp.run_all(args, [combo()], lambda c: runner, state, log=lambda *a: None)
    assert runner.calls == [(512, 503)]                                  # only the halving of [495, 512]
    assert read(tmp_path / "ranges.csv")[0]["Status"] == "RANGE"


def test_a_moving_frontier_costs_few_runs_per_step(tmp_path):
    args = make_args(tmp_path, heap_max=1024, precision=20)
    state = make_state(tmp_path, args)
    runner = FakeRunner(lambda heap: 300 + (heap - 512) * 3)             # +192M per heap step
    sp.run_all(args, [combo()], lambda c: runner, state, log=lambda *a: None)
    per_heap = {}
    for heap, _ in runner.calls:
        per_heap[heap] = per_heap.get(heap, 0) + 1
    assert all(n <= 6 for h, n in per_heap.items() if h >= 704), per_heap   # once the trend is known


def test_a_real_case_the_next_run_after_a_pass_at_558(tmp_path):
    """The log of the real runs: own PASS at 388, 408, 428, 558; the sibling (26.1.8 / wolfi-jdk) PASS 658, 678, FAIL 698
    at heap 576; own history 118M -> 378M. The next run is 678M: the sibling passed there, so a lower run would be idle."""
    rows = history_rows([(658, "PASS"), (698, "FAIL"), (678, "PASS")]) + [(*OWN, 576, r, "PASS") for r in (388, 408, 428, 558)]
    args = make_args(tmp_path, heap_start=576, heap_max=576, window=10, precision=20)
    state = sibling_state(tmp_path, rows, args)
    old, new = package_combo(*SIB), package_combo(*OWN)
    assert p.bracket(state.heap_runs(new)[576]) == (558, None)
    assert p.first_guess(args, state, new, [old], 576)[0] == 678
    runner = FakeRunner(lambda heap: 700)
    sp.run_all(args, [old, new],
              lambda c: runner, state, log=lambda *a: None)
    assert runner.rows[0] == 678 and 818 not in runner.rows


def test_the_real_case_goes_to_678_and_then_698_and_nothing_above(tmp_path):
    rows = history_rows([(658, "PASS"), (698, "FAIL"), (678, "PASS")]) + [(*OWN, 576, r, "PASS") for r in (388, 408, 428, 558)]
    args = make_args(tmp_path, heap_start=576, heap_max=576, window=10, precision=20)
    state = sibling_state(tmp_path, rows, args)
    old, new = package_combo(*SIB), package_combo(*OWN)
    assert p.sibling_fail_cap(state, [old], 576) == 698 and p.sibling_fail_cap(state, [new], 576) is None
    runner = FakeRunner(lambda heap: 690)
    sp.run_all(args, [old, new],
              lambda c: runner, state, log=lambda *a: None)
    assert runner.rows == [678, 698]                                                   # two runs, bracket [678, 698]


def test_the_real_case_after_a_fail_at_678_the_next_run_is_the_sibling_pass_658(tmp_path):
    rows = history_rows([(658, "PASS"), (698, "FAIL"), (678, "PASS")]) + \
        [(*OWN, 576, r, "PASS") for r in (388, 408, 428, 558)] + [(*OWN, 576, 678, "FAIL")]
    args = make_args(tmp_path, heap_start=576, heap_max=576, window=10, precision=20)
    state = sibling_state(tmp_path, rows, args)
    old, new = package_combo(*SIB), package_combo(*OWN)
    assert p.sibling_passes(state, [old], 576) == [658, 678]
    runner = FakeRunner(lambda heap: 670)
    sp.run_all(args, [old, new],
              lambda c: runner, state, log=lambda *a: None)
    assert runner.rows == [658]


def brackets_over_time(runs_rows):
    """For every recorded run: did its combination already have both a PASS and a FAIL when the run was made?"""
    seen, out = {}, []
    for r in runs_rows:
        key = (r["Dremio ver"], r["Java image"])
        out.append({m.PASS, m.FAIL} <= seen.setdefault(key, set()))
        seen[key].add(r["Outcome"])
    return out


def test_every_combination_gets_a_pass_and_a_fail_before_any_of_them_is_refined(tmp_path):
    args = make_args(tmp_path, heap_max=512)
    combos = combos4()
    limits = {combos[0]: 300, combos[1]: 650, combos[2]: 120, combos[3]: 900}
    sp.run_all(args, combos, FakeFleet(lambda c, heap: limits[c], [], []), make_state(tmp_path, args), log=lambda *a: None)
    runs = read(tmp_path / "runs.csv")
    refined = brackets_over_time(runs)
    first_refined = refined.index(True)
    complete = {}
    for r in runs[:first_refined]:
        complete.setdefault((r["Dremio ver"], r["Java image"]), set()).add(r["Outcome"])
    assert len(complete) == 4 and all(v == {m.PASS, m.FAIL} for v in complete.values())   # nobody is still without a bracket


def test_the_refining_runs_take_turns_and_a_combination_at_its_precision_is_skipped(tmp_path):
    args = make_args(tmp_path, heap_max=512)
    combos = combos4()[:2]
    limits = {combos[0]: 300, combos[1]: 650}
    sp.run_all(args, combos, FakeFleet(lambda c, heap: limits[c], [], []), make_state(tmp_path, args), log=lambda *a: None)
    runs = read(tmp_path / "runs.csv")
    refining = [r["Java image"] for r, bracketed in zip(runs, brackets_over_time(runs)) if bracketed]
    assert refining[:4] == ["a", "b", "a", "b"]                      # one run each, in turn
    assert refining.count("a") + refining.count("b") == len(refining)
    last = runs[-1]["Java image"]
    assert refining[-1] == last
    finished_at = {c: max(i for i, x in enumerate(runs) if x["Java image"] == c) for c in "ab"}
    assert min(finished_at.values()) < max(finished_at.values())      # one finished and was skipped while the other went on
    assert all(r["Status"] == "RANGE" for r in read(tmp_path / "ranges.csv"))


def test_a_combination_runs_until_it_has_a_pass_and_a_fail_before_the_next_one_starts(tmp_path):
    args = make_args(tmp_path, heap_max=512)
    combos = combos4()[:3]
    limits = {combos[0]: 300, combos[1]: 650, combos[2]: 120}
    sp.run_all(args, combos, FakeFleet(lambda c, heap: limits[c], [], []), make_state(tmp_path, args), log=lambda *a: None)
    runs = read(tmp_path / "runs.csv")
    first_refined = brackets_over_time(runs).index(True)
    blocks = []                                                     # the runs of the bracketing pass, one block per combination
    for r in runs[:first_refined]:
        key = (r["Dremio ver"], r["Java image"])
        if not blocks or blocks[-1][0] != key:
            blocks.append((key, set()))
        blocks[-1][1].add(r["Outcome"])
    assert [k for k, _ in blocks] == list(dict.fromkeys(k for k, _ in blocks))        # no combination comes back
    assert all(v == {m.PASS, m.FAIL} for _, v in blocks)                          # each stayed until it had both verdicts
