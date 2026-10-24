"""Offline tests of the search of the frontier (oom.search): what to run next from the runs recorded so far."""
from oom import model as m
from oom import search as s


def drive(limit, outcomes=None, guess=None, step=None, precision=10, floor=10, ceil=1440, cap=None, hints=()):
    """Makes the runs `next_rows` asks for, on a test that passes below `limit` million rows, until it says the step is
    finished: (the Result of the runs, the row counts run)."""
    outcomes, calls = dict(outcomes or {}), []
    while True:
        rows = s.next_rows(outcomes, guess, step, precision, floor, ceil, cap, hints)
        if rows is None:
            return s.step_result(outcomes, precision, floor, ceil), calls
        assert rows not in outcomes, f"{rows}M is run twice"
        calls.append(rows)
        outcomes[rows] = m.PASS if rows < limit else m.FAIL
        assert len(calls) < 60, calls


def within(r, limit, precision=10):
    return r.pass_max < limit <= r.fail_min and r.fail_min - r.pass_max <= precision


def test_without_any_hint_the_search_halves_from_the_middle_of_the_limits():
    r, calls = drive(300)
    assert calls[0] == 725 and r.status == "RANGE" and within(r, 300) and len(calls) <= 10
    assert r.mean == (r.pass_max + r.fail_min) / 2


def test_without_any_hint_all_pass_and_all_fail():
    assert drive(10**9)[0].status == "ALL_PASS"
    r, calls = drive(0)
    assert r.status == "ALL_FAIL" and r.mean is None and min(calls) == 10


def test_a_bracket_wider_than_the_precision_is_a_rough_result_with_a_mean():
    assert s.step_result({100: m.PASS, 130: m.FAIL}, 10, 10, 1440) == m.Result("ROUGH", 100, 130)
    assert not m.Result("ROUGH", 100, 130).done and m.Result("ROUGH", 100, 130).mean == 115
    assert s.step_result({100: m.PASS, 110: m.FAIL}, 10, 10, 1440).done


def test_heap_sizes():
    assert s.heap_sizes(512, 64, 2048)[:3] == [512, 576, 640] and s.heap_sizes(512, 64, 2048)[-1] == 2048
    assert s.heap_sizes(512, 64, 500) == []




def guided(limit, lo=None, hi=None, guess=100, step=10, precision=10, floor=10, ceil=1440):
    seed = {**({lo: m.PASS} if lo is not None else {}), **({hi: m.FAIL} if hi is not None else {})}
    return drive(limit, seed, guess, step, precision, floor, ceil)


def test_guided_search_with_a_good_guess_needs_three_runs():
    r, calls = guided(limit=107, guess=105, step=10)
    assert r.status == "RANGE" and within(r, 107) and len(calls) <= 3


def test_guided_search_gallops_away_from_a_wrong_guess_in_few_runs():
    r, calls = guided(limit=700, guess=100)                   # 600M above the guess: 10, 20, 40, ... steps
    assert within(r, 700) and len(calls) <= 12
    r, calls = guided(limit=30, guess=500)
    assert within(r, 30) and len(calls) <= 12


def test_guided_search_from_a_known_end_does_not_run_it_again():
    r, calls = guided(limit=300, lo=250)
    assert 250 not in calls and within(r, 300)
    r, calls = guided(limit=300, hi=400)
    assert 400 not in calls and within(r, 300)
    r, calls = guided(limit=300, lo=290, hi=305)               # a bracket of the recorded runs: halving only
    assert calls == [297] and r.status == "RANGE"


def test_guided_search_all_pass_and_all_fail():
    assert guided(limit=10**9, guess=100)[0].status == "ALL_PASS"
    r, calls = guided(limit=0, guess=100)
    assert r.status == "ALL_FAIL" and r.mean is None and min(calls) == 10


def test_a_known_pass_is_followed_by_the_prediction_not_by_a_doubling_step():
    """Recorded PASS at 428M, 558M; predicted frontier 638M, first step 130M: the next run is 638M. A doubling step from the
    last PASS would be 558 + 260 = 818M, far above where the frontier is expected."""
    r, calls = drive(690, {428: m.PASS, 558: m.PASS}, 638, 130, 20)
    assert calls[0] == 638 and 818 not in calls and len(calls) <= 5 and within(r, 690, 20)


def test_a_known_fail_is_followed_by_the_prediction_from_below():
    r, calls = drive(300, {500: m.FAIL}, 320, 40, 20)
    assert calls[0] == 320 and within(r, 300, 20)


def test_the_gallop_doubles_its_step_with_every_move_in_the_same_direction():
    assert s.next_rows({100: m.PASS}, None, 10, 10, 10, 1440) == 110
    assert s.next_rows({100: m.PASS, 110: m.PASS}, None, 10, 10, 10, 1440) == 130        # the gap 10 -> step 20
    assert s.next_rows({100: m.PASS, 110: m.PASS, 130: m.PASS}, None, 10, 10, 10, 1440) == 170
    assert s.next_rows({500: m.FAIL, 490: m.FAIL}, None, 10, 10, 10, 1440) == 470


def capped(limit, lo, step, cap, guess=None, precision=20):
    return drive(limit, {lo: m.PASS}, guess, step, precision, 10, 1440, cap)


def test_a_cap_stops_the_first_run_upwards_at_the_fail_of_another_combination():
    """PASS at 678M is known, the step is 130M, another combination failed at 698M: the next run is 698M, not 808M."""
    r, calls = capped(limit=690, lo=678, step=130, cap=698)
    assert calls == [698] and (r.pass_max, r.fail_min) == (678, 698)


def test_a_cap_that_was_passed_is_gone_and_the_step_after_it_is_not_doubled():
    r, calls = capped(limit=800, lo=678, step=130, cap=698)
    assert calls[:2] == [698, 828] and within(r, 800, 20)                   # 698 passed: back to the own step of 130M


def test_a_cap_below_a_known_pass_is_ignored_and_the_guess_is_held_at_the_cap():
    r, calls = capped(limit=1000, lo=700, step=130, cap=698)                # the other failed below our PASS
    assert calls[0] == 830
    assert s.next_rows({}, 800, 130, 20, 10, 1440, 698) == 698               # a guess above the cap is brought to it


def test_halving_a_bracket_goes_to_the_highest_sibling_pass_inside_it():
    """Own PASS at 558M, own FAIL at 678M; the sibling passed at 658M and 678M. The middle 618M is below a PASS of the sibling,
    so the run goes to 658M; a PASS there closes the bracket [658, 678] (precision 20) with one run."""
    r, calls = drive(670, {558: m.PASS, 678: m.FAIL}, None, 130, 20, hints=[658, 678])
    assert calls == [658] and (r.pass_max, r.fail_min) == (658, 678)
    r, calls = drive(600, {558: m.PASS, 678: m.FAIL}, None, 130, 20, hints=[658, 678])      # a FAIL at 658M: halving goes on below
    assert calls[0] == 658 and calls[1] == 608 and within(r, 600, 20)


def test_a_sibling_pass_outside_the_bracket_changes_nothing():
    assert drive(640, {558: m.PASS, 678: m.FAIL}, None, 130, 20, hints=[400, 700])[1][0] == 618
