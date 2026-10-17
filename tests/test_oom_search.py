"""Offline tests of the search of the frontier (oom.search)."""
import pytest

from oom import model as m
from oom import search as s


def threshold_run(limit, calls=None):
    """A test that passes below `limit` million rows and fails from it on."""
    def run(rows):
        if calls is not None:
            calls.append(rows)
        return m.PASS if rows < limit else m.FAIL
    return run


def search(run, lo=10, hi=1440, precision=10, floor=10, ceil=1440):
    return s.search(run, lo, hi, precision, floor, ceil)


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
        raise m.StepSkipped(rows)
    with pytest.raises(m.StepSkipped):
        search(run)


def test_heap_sizes():
    assert s.heap_sizes(512, 64, 2048)[:3] == [512, 576, 640] and s.heap_sizes(512, 64, 2048)[-1] == 2048
    assert s.heap_sizes(512, 64, 500) == []


def guided(limit, lo=None, hi=None, guess=100, step=10, precision=10, floor=10, ceil=1440):
    calls = []

    def run(rows):
        calls.append(rows)
        return m.PASS if rows < limit else m.FAIL
    return s.search_guided(run, lo, hi, guess, step, precision, floor, ceil), calls


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


def test_a_known_pass_is_followed_by_the_prediction_not_by_a_doubling_step():
    """Recorded PASS at 428M, 558M; predicted frontier 638M, first step 130M: the next run is 638M. A doubling step from the
    last PASS would be 558 + 260 = 818M, far above where the frontier is expected."""
    calls = []

    def run(rows):
        calls.append(rows)
        return m.PASS if rows < 690 else m.FAIL
    r = s.search_guided(run, 558, None, 638, 130, 20, 10, 1440)
    assert calls[0] == 638 and 818 not in calls and len(calls) <= 5
    assert r.status == "RANGE" and r.pass_max < 690 <= r.fail_min and r.fail_min - r.pass_max <= 20


def test_a_known_fail_is_followed_by_the_prediction_from_below():
    calls = []

    def run(rows):
        calls.append(rows)
        return m.PASS if rows < 300 else m.FAIL
    r = s.search_guided(run, None, 500, 320, 40, 20, 10, 1440)
    assert calls[0] == 320 and r.pass_max < 300 <= r.fail_min


def guided_cap(limit, lo, guess, step, cap, precision=20):
    calls = []

    def run(rows):
        calls.append(rows)
        return m.PASS if rows < limit else m.FAIL
    return s.search_guided(run, lo, None, guess, step, precision, 10, 1440, cap), calls


def test_a_cap_stops_the_first_run_upwards_at_the_fail_of_another_combination():
    """PASS at 678M is known, the step is 130M, another combination failed at 698M: the next run is 698M, not 808M."""
    r, calls = guided_cap(limit=690, lo=678, guess=None, step=130, cap=698)
    assert calls == [698] and (r.pass_max, r.fail_min) == (678, 698)


def test_a_cap_that_was_passed_is_gone_and_the_step_after_it_is_not_doubled():
    r, calls = guided_cap(limit=800, lo=678, guess=None, step=130, cap=698)
    assert calls[:2] == [698, 828] and r.pass_max < 800 <= r.fail_min       # 698 passed: back to the own step of 130M


def test_a_cap_below_a_known_pass_is_ignored_and_the_guess_is_held_at_the_cap():
    r, calls = guided_cap(limit=1000, lo=700, guess=None, step=130, cap=698)    # the other failed below our PASS
    assert calls[0] == 830
    calls = []
    s.search_guided(lambda rows: (calls.append(rows), m.PASS if rows < 600 else m.FAIL)[1], None, None, 800, 130, 20, 10, 1440, 698)
    assert calls[0] == 698                                                       # a guess above the cap is brought to it


def test_halving_a_bracket_goes_to_the_highest_sibling_pass_inside_it():
    """Own PASS at 558M, own FAIL at 678M; the sibling passed at 658M and 678M. The middle 618M is below a PASS of the sibling,
    so the run goes to 658M; a PASS there closes the bracket [658, 678] (precision 20) with one run."""
    calls = []

    def run(rows):
        calls.append(rows)
        return m.PASS if rows < 670 else m.FAIL
    r = s.search_guided(run, 558, 678, None, 130, 20, 10, 1440, None, [658, 678])
    assert calls == [658] and (r.pass_max, r.fail_min) == (658, 678)
    calls.clear()
    run2 = lambda rows: (calls.append(rows), m.PASS if rows < 600 else m.FAIL)[1]       # a FAIL at 658M: halving goes on below
    r = s.search_guided(run2, 558, 678, None, 130, 20, 10, 1440, None, [658, 678])
    assert calls[0] == 658 and calls[1] == 608 and r.pass_max < 600 <= r.fail_min


def test_a_sibling_pass_outside_the_bracket_changes_nothing():
    calls = []

    def run(rows):
        calls.append(rows)
        return m.PASS if rows < 640 else m.FAIL
    s.search_guided(run, 558, 678, None, 130, 20, 10, 1440, None, [400, 700])
    assert calls[0] == 618
