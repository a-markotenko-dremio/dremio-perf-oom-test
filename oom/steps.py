"""The walk over the heap sizes. At every heap size each combination first runs until it has a PASS and a FAIL (a preliminary
result), one after the other; then they take turns, one run each, until every one has reached the precision."""
from .model import ERROR, FAIL, PASS
from .predict import bracket, first_guess, sibling_fail_cap, sibling_passes
from .search import heap_sizes, next_rows


class Progress:
    """Where the walk over the heap sizes stands for one combination."""

    def __init__(self):
        self.skipped = 0         # heap sizes skipped in a row
        self.finished = False    # nothing fails any more: larger heaps pass too


def plan_run(args, state, combo, others, heap):
    """(row count of the next run of a combination at a heap size, what the choice is based on); the row count is None
    when the step is finished."""
    notes = []
    guess = first_guess(args, state, combo, others, heap, notes)
    cap = sibling_fail_cap(state, others, heap)
    outcomes = state.heap_runs(combo).get(heap, {})
    lo, hi = bracket(outcomes)
    if cap is not None and (lo is None or cap > lo):
        notes.append(f"runs upwards stop at {cap}M, where another combination failed")
    start, step = guess if guess else (None, None)
    rows_m = next_rows(outcomes, start, step, args.precision, args.rows_low, args.rows_high, cap,
                       sibling_passes(state, others, heap))
    return rows_m, f"PASS up to {lo or '-'}M, FAIL from {hi or '-'}M" + (f"; {'; '.join(notes)}" if notes else "")


def run_once(args, combo, heap, rows_m, runner, state, log):
    """One run (or the recorded outcome of it); the outcome."""
    known = state.run_outcome(combo, heap, rows_m)
    if known in (PASS, FAIL) or (known == ERROR and not args.retry_errors):
        log(f"    {rows_m}M: recorded {known}")
        return known
    outcome = runner.run(heap, rows_m)
    state.add_run(combo, heap, rows_m, outcome)
    log(f"    {rows_m}M: {outcome}")
    return outcome


def runs_to_do(state, combos, heap):
    """The combinations that take the next turn at a heap size: those without a PASS and a FAIL yet, and when there are
    none, those whose bracket is wider than the precision."""
    steps = {c: state.step(c, heap) for c in combos}
    return [c for c in combos if steps[c] is None] or [c for c in combos if steps[c] is not None and not steps[c].done]


def run_all(args, combos, runner_for, state, log=print):
    """Walks the heap sizes of all combinations together. At a heap size a combination without a PASS and a FAIL runs until it
    has both; then the next one does the same. When all have a bracket, the ones wider than the precision take turns, one run
    each. The container is deleted when a combination hands the turn over, so only one container exists at a time."""
    progress = {c: Progress() for c in combos}
    for heap in heap_sizes(args.heap_start, args.heap_step, args.heap_max):
        skipped = set()                                 # combinations with a run that ended in an error at this heap size

        def run_turn(combo):
            """A turn of a combination: one run, or runs until its first PASS and FAIL; False when it has nothing to run."""
            bracketing, ran = state.step(combo, heap) is None, False
            runner = runner_for(combo)
            try:
                while True:
                    rows_m, why = plan_run(args, state, combo, [c for c in combos if c != combo], heap)
                    if rows_m is None:
                        return ran
                    ran = True
                    log(f"### {combo.version} {combo.image} heap={heap}: run at {rows_m}M ({why})")
                    if run_once(args, combo, heap, rows_m, runner, state, log) == ERROR:
                        skipped.add(combo)
                        progress[combo].skipped += 1
                        log(f"    heap={heap} skipped: the run at {rows_m}M ended with an error that is not a heap OOM "
                            f"({progress[combo].skipped} in a row)")
                        if progress[combo].skipped >= args.max_skipped:
                            raise SystemExit(f"{progress[combo].skipped} heap steps in a row skipped: stopping, check the environment")
                        return ran
                    result = state.step(combo, heap)
                    if result is not None and result.status == "ALL_PASS":
                        log("    no failure at the highest row count: a larger heap passes too, this combination is done")
                        progress[combo].finished = True
                    if not (bracketing and result is None):
                        return ran
            finally:
                getattr(runner, "delete", lambda: None)()

        while True:
            turn = runs_to_do(state, [c for c in combos if not progress[c].finished and c not in skipped], heap)
            if not turn:
                break
            if not any([run_turn(combo) for combo in turn]):
                break
        for combo in combos:
            result = state.step(combo, heap)
            if combo not in skipped and result is not None:
                progress[combo].skipped = 0
                log(f"### {combo.version} {combo.image} heap={heap}: {result.status}" + (
                    f", PASS up to {result.pass_max}M, FAIL from {result.fail_min}M, mean {result.mean:g}M"
                    if result.mean is not None else ""))
        if all(p.finished for p in progress.values()):
            return
