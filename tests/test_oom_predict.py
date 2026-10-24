"""Offline tests of the guess where a search starts (oom.predict)."""
from oom import model as m
from oom import predict as p
from oom import steps as sp
from oom.model import FAIL, PASS
from oom_helpers import FakeRunner, OWN, SIB, history_rows, make_args, package_combo, sibling_state


def test_bracket_of_mixed_runs_is_taken_below_the_lowest_fail():
    assert p.bracket({50: m.PASS, 100: m.FAIL, 200: m.PASS, 300: m.FAIL}) == (50, 100)
    assert p.bracket({50: m.PASS}) == (50, None) and p.bracket({50: m.FAIL}) == (None, 50) and p.bracket({}) == (None, None)


def test_predict_start_follows_the_trend_and_a_lower_bound():
    full = lambda h, e: (h, e, "full")
    assert p.predict_start([], 576, 10) is None
    assert p.predict_start([full(512, 500)], 576, 10) == (500, 10)                       # one step: no trend, flat
    assert p.predict_start([full(512, 500), full(576, 600)], 640, 10) == (700, 50)       # +100M per 64 MB
    assert p.predict_start([full(512, 600), full(576, 500)], 640, 10) == (500, 10)       # the frontier does not fall
    assert p.predict_start([full(512, 500), full(576, 600), (640, 750, "lower")], 704, 10)[0] == 800
    assert p.predict_start([full(512, 500), full(576, 600), (640, 900, "lower")], 704, 10)[0] == 900
    assert p.predict_start([(512, 658, "lower")], 576, 10) == (658, 10)


def test_estimates_use_the_runs_of_the_smaller_heap_sizes_only():
    runs = {512: {400: m.PASS, 500: m.FAIL}, 576: {600: m.PASS}, 640: {300: m.FAIL}, 704: {1: m.PASS}}
    assert p.estimates(runs, 704) == [(512, 450.0, "full"), (576, 600, "lower"), (640, 300, "upper")]


def test_first_run_of_a_new_combination_is_near_the_result_of_another(tmp_path):
    """Heap 576 of 26.1.8 / wolfi-jdk:21 has PASS at 578, 658, 678 and FAIL at 698: the bracket is [678, 698], its middle 688.
    26.1.10 / eclipse-temurin:21-jdk has no runs of its own at heap 576: its first run goes to 688M."""
    args = make_args(tmp_path, heap_start=576, heap_max=576, window=10, precision=20)
    state = sibling_state(tmp_path, [(*SIB, 576, r, o) for r, o in ((578, PASS), (658, PASS), (698, FAIL), (678, PASS))], args)
    old, new = package_combo(*SIB), package_combo(*OWN)
    assert p.bracket(state.heap_runs(old)[576]) == (678, 698)
    assert p.first_guess(args, state, new, [old], 576) == (688, 10)

    runner = FakeRunner(lambda heap: 690)                                  # the new combination fails from 690M
    # the bracket of the old one is 20M wide, so with precision 20 its step needs no run and the first run is the new one's
    sp.run_all(args, [old, new], lambda c: runner, state, log=lambda *a: None)
    assert runner.rows[0] == 688                                           # the first measured value


def test_without_a_sibling_at_this_heap_the_guess_is_the_own_trend(tmp_path):
    state = sibling_state(tmp_path, history_rows([]))
    assert p.first_guess(make_args(tmp_path, window=10), state, package_combo(*OWN), [package_combo(*SIB)], 576) == (638, 130)


def test_the_guess_averages_the_own_trend_and_the_sibling_moved_by_the_usual_distance(tmp_path):
    """Own trend 378 + 260 = 638M. The sibling's bracket at heap 576 is [600, 698], middle 649M, and the sibling is 70M higher
    than this combination at both earlier heap sizes -> 579M. The average is 608.5M (rounded to 608), above the sibling's PASS 600."""
    state = sibling_state(tmp_path, history_rows([(698, "FAIL"), (600, "PASS")]))
    guess, step = p.first_guess(make_args(tmp_path, window=10), state, package_combo(*OWN), [package_combo(*SIB)], 576)
    assert guess == 608 and step >= 130


def test_a_sibling_pass_above_the_average_raises_the_guess_to_it(tmp_path):
    """The sibling's [678, 698] -> 688 - 70 = 618M; with the own trend 638M the average is 628M, but the sibling passed
    at 678M: a run below it is expected to pass and tells little, so the guess is 678M."""
    state = sibling_state(tmp_path, history_rows([(698, "FAIL"), (678, "PASS")]))
    assert p.first_guess(make_args(tmp_path, window=10), state, package_combo(*OWN), [package_combo(*SIB)], 576)[0] == 678
