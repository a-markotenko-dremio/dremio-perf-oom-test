"""The search of the row count where the test starts to fail: pure logic, no I/O."""
from .model import FAIL, PASS, Result
from .predict import bracket


def heap_sizes(start, step, maximum):
    return list(range(start, maximum + 1, step))


def step_result(outcomes, precision, floor, ceil):
    """The Result of a step from its recorded runs {rows_m: PASS | FAIL}, None while the step is not finished: RANGE when
    the highest PASS and the lowest FAIL are `precision` close, ALL_PASS when the highest PASS reached `ceil` without a
    FAIL, ALL_FAIL when the lowest FAIL is at `floor` without a PASS."""
    lo, hi = bracket(outcomes)
    if lo is not None and hi is not None:
        return Result("RANGE", lo, hi) if hi - lo <= precision else None
    if hi is None and lo is not None and lo >= ceil:
        return Result("ALL_PASS", pass_max=lo)
    if lo is None and hi is not None and hi <= floor:
        return Result("ALL_FAIL", fail_min=hi)
    return None


def search(run, lo, hi, precision, floor, ceil):
    """Binary search of the row count (millions) where `run(rows_m) -> PASS | FAIL` starts to fail.

    Starts with the window lo..hi. If nothing failed in it the window moves up (twice as wide as before),
    if nothing passed it moves down, until `ceil` / `floor` is reached: ALL_PASS / ALL_FAIL."""
    width = hi - lo
    memo = {}

    def verdict(rows):
        if rows not in memo:
            memo[rows] = run(rows)
        return memo[rows]

    pass_max = fail_min = None
    while True:
        while hi - lo > precision:
            mid = (lo + hi) // 2
            if verdict(mid) == PASS:
                lo, pass_max = mid, mid
            else:
                hi, fail_min = mid, mid
        if fail_min is None:                      # nothing failed: is the upper end a failure?
            if verdict(hi) == FAIL:
                fail_min = hi
            else:
                if hi >= ceil:
                    return Result("ALL_PASS", pass_max=hi)
                width *= 2
                lo, hi, pass_max = hi, min(hi + width, ceil), hi
                continue
        if pass_max is None:                      # nothing passed: is the lower end a pass?
            if verdict(lo) == PASS:
                pass_max = lo
            else:
                if lo <= floor:
                    return Result("ALL_FAIL", fail_min=lo)
                width *= 2
                lo, hi, fail_min = max(lo - width, floor), lo, lo
                continue
        return Result("RANGE", pass_max, fail_min)


def search_guided(run, lo, hi, guess, step, precision, floor, ceil, cap=None, hints=()):
    """The search of a step that starts from what is known: `lo` is the highest known PASS and `hi` the lowest
    known FAIL (millions of rows, None when unknown), `guess` the predicted frontier where the first run goes.

    An unknown end is found by moving from the known one by `step`, doubling it after every run in the same
    direction (PASS up, FAIL down), up to `ceil` / `floor`: ALL_PASS / ALL_FAIL. Then the bracket is halved.

    `cap` is a row count where another combination already failed at this heap size: the first runs upwards do not
    go beyond it (a run at the cap itself does; if that passes, the cap is gone and the search goes on above it).

    `hints` are row counts where another combination passed at this heap size. When halving the bracket, a run below
    such a PASS is expected to pass and tells little, so the run goes to the highest hint inside the bracket instead of
    its middle."""
    if guess is not None:
        guess = min(max(guess, floor), ceil)
        if cap is not None and (lo is None or cap > lo):
            guess = min(guess, cap)
    # the first run is the guess; with an end already known the guess is still the first thing to try on the open side
    # (a recorded PASS at 558M and a guess of 638M: the next run is 638M, not 558M plus a doubling step)
    if guess is not None and ((lo is None and hi is None) or (hi is None and guess > lo) or (lo is None and guess < hi)):
        if run(guess) == PASS:
            lo = guess
        else:
            hi = guess
    move = step
    while hi is None:                              # a PASS is known: look up for a FAIL
        if lo >= ceil:
            return Result("ALL_PASS", pass_max=lo)
        nxt = min(lo + move, ceil)
        clipped = cap is not None and lo < cap < nxt
        if clipped:
            nxt = cap
        if run(nxt) == PASS:
            lo = nxt
            if cap is not None and lo >= cap:
                cap = None                              # passed where the other failed: nothing to hold on to
            if not clipped:
                move *= 2                               # a step shortened by the cap says nothing about the distance
        else:
            hi = nxt
    move = step
    while lo is None:                              # a FAIL is known: look down for a PASS
        if hi <= floor:
            return Result("ALL_FAIL", fail_min=hi)
        nxt = max(hi - move, floor)
        if run(nxt) == FAIL:
            hi, move = nxt, move * 2
        else:
            lo = nxt
    while hi - lo > precision:
        mid = (lo + hi) // 2
        mid = max([mid] + [h for h in hints if mid < h < hi])
        if run(mid) == PASS:
            lo = mid
        else:
            hi = mid
    return Result("RANGE", lo, hi)
