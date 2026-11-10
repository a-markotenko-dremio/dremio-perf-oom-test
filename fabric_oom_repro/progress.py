"""Where a run stands while it waits. A run of the fabric OOM takes an hour between its two printed results (the data
set is generated on every host, the queries spill for tens of minutes), so every step says when it happened and the
long waits report themselves. pytest shows the lines as they come only with -s."""
import time


def progress(message):
    """One line of the run's progress, with the time of day it happened."""
    print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)
