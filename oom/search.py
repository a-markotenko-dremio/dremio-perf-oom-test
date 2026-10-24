"""The search of the row count where the test starts to fail: pure logic, no I/O. A step is not a loop that makes its
runs: from the runs recorded so far `next_rows` says what to run next, so that the steps of several combinations can
take turns, one run each."""
from .model import FAIL, PASS, Result
from .predict import bracket


def heap_sizes(start, step, maximum):
    return list(range(start, maximum + 1, step))


def step_result(outcomes, precision, floor, ceil):
    """The Result of a step from its recorded runs {rows_m: PASS | FAIL}, None while there is no PASS and no FAIL yet:
    RANGE when the highest PASS and the lowest FAIL are `precision` close, ROUGH when they are further apart (a preliminary
    result), ALL_PASS when the highest PASS reached `ceil` without a FAIL, ALL_FAIL when the lowest FAIL is at `floor`
    without a PASS."""
    lo, hi = bracket(outcomes)
    if lo is not None and hi is not None:
        return Result("RANGE" if hi - lo <= precision else "ROUGH", lo, hi)
    if hi is None and lo is not None and lo >= ceil:
        return Result("ALL_PASS", pass_max=lo)
    if lo is None and hi is not None and hi <= floor:
        return Result("ALL_FAIL", fail_min=hi)
    return None


def next_rows(outcomes, guess, step, precision, floor, ceil, cap=None, hints=()):
    """The row count (millions) of the next run of a step, None when the step is finished (RANGE, ALL_PASS or ALL_FAIL).

    `outcomes` are the recorded runs {rows_m: PASS | FAIL}: the highest PASS below the lowest FAIL and the lowest FAIL
    are the known ends of the frontier. `guess` is the predicted frontier where the next run goes while an end of the
    bracket is open on its side, `step` the distance of a run from a known end (None: half the way to `floor` / `ceil`).

    An unknown end is found by moving from the known one by `step`, doubled for every earlier move in the same
    direction (twice the last gap between the recorded PASS, FAIL), up to `ceil` / `floor`. Then the bracket is halved.

    `cap` is a row count where another combination already failed at this heap size: the runs upwards do not go beyond
    it (a run at the cap itself does; if that passes, the cap is gone and the search goes on above it).

    `hints` are row counts where another combination passed at this heap size. When halving the bracket, a run below
    such a PASS is expected to pass and tells little, so the run goes to the highest hint inside the bracket instead of
    its middle."""
    lo, hi = bracket(outcomes)
    if guess is not None:
        guess = min(max(guess, floor), ceil)
        if cap is not None and (lo is None or cap > lo):
            guess = min(guess, cap)
    elif lo is None and hi is None:
        return (floor + ceil) // 2
    # the guess is the first thing to try on the open side (a recorded PASS at 558M and a guess of 638M: the next run
    # is 638M, not 558M plus a doubling step)
    if guess is not None and ((lo is None and hi is None) or (hi is None and guess > lo) or (lo is None and guess < hi)):
        return guess
    if hi is None:                                 # a PASS is known: look up for a FAIL
        if lo >= ceil:
            return None
        passes = sorted(r for r, o in outcomes.items() if o == PASS)
        gap = passes[-1] - passes[-2] if len(passes) > 1 else 0
        nxt = min(lo + (max(step, 2 * gap) if step else max(precision, (ceil - lo) // 2)), ceil)
        return cap if cap is not None and lo < cap < nxt else nxt
    if lo is None:                                 # a FAIL is known: look down for a PASS
        if hi <= floor:
            return None
        fails = sorted(r for r, o in outcomes.items() if o == FAIL)
        gap = fails[1] - fails[0] if len(fails) > 1 else 0
        return max(hi - (max(step, 2 * gap) if step else max(precision, (hi - floor) // 2)), floor)
    if hi - lo <= precision:
        return None
    mid = (lo + hi) // 2
    return max([mid] + [h for h in hints if mid < h < hi])
