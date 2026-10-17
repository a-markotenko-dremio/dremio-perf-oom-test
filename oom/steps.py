"""The walk over the heap sizes: for every combination a step, which is a search whose runs are made by a runner."""
from .model import ERROR, FAIL, PASS, StepSkipped
from .predict import bracket, first_guess, sibling_fail_cap, sibling_passes
from .search import heap_sizes, search, search_guided


class Progress:
    """Where the walk over the heap sizes stands for one combination."""

    def __init__(self):
        self.skipped = 0         # heap steps skipped in a row
        self.finished = False    # nothing fails any more: larger heaps pass too


def run_step(args, combo, heap, runner, state, progress, log=print, others=()):
    """The step of a combination at one heap size. `runner.run(heap, rows_m) -> PASS | FAIL | ERROR`."""
    done = state.step(combo, heap)
    if done:
        log(f"### {combo.version} {combo.image} heap={heap}: recorded ({done.status}, mean "
            f"{'-' if done.mean is None else f'{done.mean:g}M'})")
        progress.finished = done.status == "ALL_PASS"
        return
    lo, hi = bracket(state.heap_runs(combo).get(heap, {}))
    notes = []
    guess = first_guess(args, state, combo, others, heap, notes)
    cap = sibling_fail_cap(state, others, heap)
    if cap is not None and (lo is None or cap > lo):
        notes.append(f"runs upwards stop at {cap}M, where another combination failed")
    start, step = guess if guess else (None, args.window)
    if lo is not None or hi is not None:
        log(f"### {combo.version} {combo.image} heap={heap}: recorded runs give PASS up to {lo or '-'}M, FAIL from {hi or '-'}M"
            + (f"; guess {start}M, step {step}M ({'; '.join(notes)})" if guess else ""))
    elif guess:
        log(f"### {combo.version} {combo.image} heap={heap}: first run at {start}M, step {step}M ({'; '.join(notes)})")
    else:
        log(f"### {combo.version} {combo.image} heap={heap}: nothing recorded, searching {args.rows_low}M..{args.rows_high}M")

    def run(rows_m):
        known = state.run_outcome(combo, heap, rows_m)
        if known in (PASS, FAIL) or (known == ERROR and not args.retry_errors):
            outcome = known
            log(f"    {rows_m}M: recorded {outcome}")
        else:
            outcome = runner.run(heap, rows_m)
            state.add_run(combo, heap, rows_m, outcome)
            log(f"    {rows_m}M: {outcome}")
        if outcome == ERROR:
            raise StepSkipped(f"{rows_m}M")
        return outcome

    try:
        if lo is None and hi is None and not guess:
            result = search(run, args.rows_low, args.rows_high, args.precision, args.rows_low, args.rows_high)
        else:
            result = search_guided(run, lo, hi, start, step, args.precision, args.rows_low, args.rows_high, cap,
                                   sibling_passes(state, others, heap))
    except StepSkipped as e:
        progress.skipped += 1
        log(f"    heap={heap} skipped: the run at {e} ended with an error that is not a heap OOM "
            f"({progress.skipped} in a row)")
        if progress.skipped >= args.max_skipped:
            raise SystemExit(f"{progress.skipped} heap steps in a row skipped: stopping, check the environment")
        return
    progress.skipped = 0
    log(f"    heap={heap}: {result.status}" + (f", PASS up to {result.pass_max}M, FAIL from {result.fail_min}M, "
                                              f"mean {result.mean:g}M" if result.status == "RANGE" else ""))
    if result.status == "ALL_PASS":
        log("    no failure at the highest row count: a larger heap passes too, this combination is done")
        progress.finished = True


def run_all(args, combos, runner_for, state, log=print):
    """Walks the heap sizes of all combinations together: at every heap size each combination does its step, so
    all the lines of the chart grow at the same time. The container of a step is deleted when the step is done
    (the next heap size needs a new one anyway), so only one container exists at a time."""
    progress = {c: Progress() for c in combos}
    for heap in heap_sizes(args.heap_start, args.heap_step, args.heap_max):
        for combo in combos:
            if progress[combo].finished:
                continue
            runner = runner_for(combo)
            try:
                run_step(args, combo, heap, runner, state, progress[combo], log, others=[c for c in combos if c != combo])
            finally:
                getattr(runner, "delete", lambda: None)()
        if all(p.finished for p in progress.values()):
            return
