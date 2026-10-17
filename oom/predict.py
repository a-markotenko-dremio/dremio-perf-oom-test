"""Where to start the search of a heap size: a guess from the runs recorded before (own history, other combinations)."""
from .model import FAIL, PASS


def bracket(outcomes):
    """(highest PASS below the lowest FAIL, lowest FAIL) of the runs {rows_m: PASS | FAIL}; None for an unknown end."""
    fails = [r for r, o in outcomes.items() if o == FAIL]
    fail_min = min(fails) if fails else None
    passes = [r for r, o in outcomes.items() if o == PASS and (fail_min is None or r < fail_min)]
    return (max(passes) if passes else None), fail_min


def estimates(heap_runs, below_heap):
    """[(heap, frontier estimate, kind)] of the heap sizes under `below_heap`, from their recorded runs. The estimate
    is the middle of a full bracket ("full"), else the only known end: "lower" with only PASS (the frontier is
    above it), "upper" with only FAIL (below it)."""
    out = []
    for heap in sorted(h for h in heap_runs if h < below_heap):
        p, f = bracket(heap_runs[heap])
        if p is not None and f is not None:
            out.append((heap, (p + f) / 2, "full"))
        elif p is not None:
            out.append((heap, p, "lower"))
        elif f is not None:
            out.append((heap, f, "upper"))
    return out


def predict_start(found, heap, window):
    """(the row count of the first run, the first step of the search) for `heap` from the estimates of the smaller
    heap sizes, None without any. The frontier does not fall with a growing heap: it is extrapolated by the trend of
    the last two full brackets, and is not put below a lower bound found at a later heap size."""
    if not found:
        return None
    guess, step = found[-1][1], window
    full = [e for e in found if e[2] == "full"]
    if len(full) >= 2:
        (h0, e0, _), (h1, e1, _) = full[-2], full[-1]
        guess = e1 + max(0.0, (e1 - e0) / (h1 - h0)) * (heap - h1)
        step = max(window, round(abs(guess - e1) / 2))
    lower = [e[1] for e in found if e[2] == "lower" and (not full or e[0] > full[-1][0])]
    if lower:
        guess = max(guess, max(lower))
    return round(guess), step


def first_guess(args, state, combo, others, heap, notes=None):
    """The start of the search of a step from the recorded runs: (row count of the first run, first step), None when
    nothing is recorded.

    Candidates: the own trend of the combination (predict_start) and, for every other combination that has a full
    bracket at this very heap size, the middle of that bracket moved by the usual distance between the two (at the
    last heap size where both have one). The guess is their average. A PASS of another combination at this heap size
    is not to be probed below: the guess is not lower than the highest of them. Without any of this the latest result
    of another combination starts the search. `notes`, if given, gets the parts of the guess for the log."""
    notes = [] if notes is None else notes
    own = estimates(state.heap_runs(combo), heap)
    base = predict_start(own, heap, args.window)
    own_full = {h: e for h, e, kind in own if kind == "full"}
    candidates = [base[0]] if base else []
    if base:
        notes.append(f"own trend {base[0]}M")
    highest_pass = None
    for other in others:
        runs = state.heap_runs(other)
        p, f = bracket(runs.get(heap, {}))
        if p is not None:
            highest_pass = p if highest_pass is None else max(highest_pass, p)
        if p is None or f is None:
            continue
        theirs = {h: e for h, e, kind in estimates(runs, heap) if kind == "full"}
        common = [h for h in own_full if h in theirs]
        offset = own_full[max(common)] - theirs[max(common)] if common else 0
        candidates.append((p + f) / 2 + offset)
        notes.append(f"{other.version} {other.image} {(p + f) / 2:g}M {offset:+g}M = {candidates[-1]:g}M")
    if not candidates:
        for other in others:                       # nothing of its own and nothing of the others at this heap size
            found = estimates(state.heap_runs(other), heap + 1)[-1:]
            if found:
                base = predict_start(found, heap, args.window)
                candidates = [base[0]]
                notes.append(f"latest result of {other.version} {other.image} {base[0]}M")
                break
    if not candidates:
        return None
    guess = round(sum(candidates) / len(candidates))
    if highest_pass is not None and highest_pass > guess:
        notes.append(f"raised to the PASS {highest_pass}M of another combination at this heap")
        guess = highest_pass
    step = max(base[1] if base else args.window, round((max(candidates) - min(candidates)) / 2))
    return guess, step


def sibling_fail_cap(state, others, heap):
    """The lowest FAIL of the other combinations at this heap size, None when none of them has failed there."""
    fails = [bracket(state.heap_runs(other).get(heap, {}))[1] for other in others]
    return min((f for f in fails if f is not None), default=None)


def sibling_passes(state, others, heap):
    """The row counts where the other combinations passed at this heap size."""
    return sorted({r for other in others for r, outcome in state.heap_runs(other).get(heap, {}).items() if outcome == PASS})
