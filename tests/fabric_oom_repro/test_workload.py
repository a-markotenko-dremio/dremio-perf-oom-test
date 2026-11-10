"""
Offline tests of fabric_oom_repro.workload on the job errors of the runs of the stand (2026-10-29 and 2026-10-30):
which of them is a memory failure the bug can explain and which is not about memory at all.
"""
import pytest

from dremio_client import JobFailed
from fabric_oom_repro.workload import (HEARTBEAT, INNOCENT, OVER_THE_LIMIT, PROBE_RETRY, QUERIES, READY_WAIT,
                                       Outcome, StandNotReady, marked, over_the_limit, run_query, slowest_completed,
                                       unrelated_failures, wait_for, wait_until_ready)

OOM = Outcome("151b2143-37c8-7a5b-8f79-4f2d935a3a00", "Job 151b2143-37c8-7a5b-8f79-4f2d935a3a00 FAILED: OUT_OF_MEMORY "
              "ERROR: Query was cancelled because it exceeded the memory limits set by the administrator. The executor "
              "became unreachable mid-query - typically caused by a restart, eviction, or out-of-memory failure.", 137)
CHANNEL_CLOSED = Outcome("151c6e21-629c-7fb1-11fd-e1aa842cd000", "Job 151c6e21-629c-7fb1-11fd-e1aa842cd000 FAILED: "
                         "SYSTEM ERROR: ChannelClosedException: [FABRIC]: Channel closed", 188)
NODE_GONE = Outcome("151b20b3-4cef-828e-1400-cce703ddf800", "Job 151b20b3-4cef-828e-1400-cce703ddf800 FAILED: Dremio "
                    "could not execute the query because required compute nodes became unavailable.", 228)
# the run of 12:15 on 2026-10-30: one of the eight queries failed on the input file, not on memory
BROKEN_INPUT = Outcome("151b2142-cb9e-ab22-7001-940566fed600", "Job 151b2142-cb9e-ab22-7001-940566fed600 FAILED: "
                       "DATA_READ ERROR: Snappy decompression failed on column TestName::varchar. If this exception "
                       "continues to occur, then ensure the file exists and is valid: /mnt/ubuntu-var/dremio/"
                       "fabric-oom-repro/scale-0.0175/TestCaseData/2026/data_1.parquet", 23)
# the run of 13:50 on 2026-10-30: the queries that were served took 1627-2235 s, far past a 600 s limit
CUT_OFF = Outcome("151afcf2-8d57-0cb9-dff6-e58cc20ef700", OVER_THE_LIMIT, 600)
DONE = Outcome("151b2142-ee93-ddf2-d53a-f1cc3d6f1f00", "COMPLETED", 29)


def test_no_query_of_a_run_repeats_the_text_of_another_run():
    """The result cache answered a repeat of the same query in a second (2026-10-30, 13:24: three sessions measured
    nothing). It stays on because switching it off stopped the bug from reproducing, so the text changes instead."""
    first = {marked(sql, "20261031-061500") for sql in [*QUERIES, INNOCENT]}
    second = {marked(sql, "20261031-073000") for sql in [*QUERIES, INNOCENT]}
    assert len(first) == len(QUERIES) + 1 and not first & second


def test_a_marked_query_returns_what_it_returned_plus_the_marker():
    assert marked("SELECT COUNT(*) AS n FROM t", "20261031-061500") == (
        "SELECT '20261031-061500' AS run, * FROM (SELECT COUNT(*) AS n FROM t) m")


def test_the_memory_failures_of_a_run_are_not_counted_as_unrelated():
    assert not unrelated_failures([OOM, CHANNEL_CLOSED, NODE_GONE, DONE])


def test_a_failure_on_the_input_file_is_unrelated():
    assert unrelated_failures([OOM, BROKEN_INPUT, DONE]) == ["151b2142-cb9e-ab22-7001-940566fed600"]


def test_a_query_the_run_cut_off_is_not_a_failure_of_the_product():
    """The time limit is the run's own, so the query it cancels is a failure on the limit and dirties nothing."""
    assert not unrelated_failures([CUT_OFF, DONE])
    assert over_the_limit([CUT_OFF, DONE]) == ["151afcf2-8d57-0cb9-dff6-e58cc20ef700"]


def test_a_query_the_run_cut_off_was_not_served():
    assert slowest_completed([CUT_OFF]) is None


def test_the_slowest_served_query_is_the_cost_of_surviving():
    """The run of 12:28 on 2026-10-30: seven queries spilled instead of failing, the slowest answered after 31 min."""
    served = [DONE._replace(seconds=228), DONE._replace(job="151b1e3b-bb23-66c6-0f40-a927211ff200", seconds=1839)]
    assert slowest_completed([*served, OOM]).seconds == 1839


def test_a_run_where_nothing_was_served_has_no_slowest_query():
    assert slowest_completed([OOM, BROKEN_INPUT]) is None


# the run of 16:09 on 2026-11-04, session 2: every query failed this way within 30 s, the executor was still
# cancelling the queries of session 1
FRAGMENT_TIMEOUT = ("Job 15144f77-f3db-f45d-7d85-b018d6c36e00 FAILED: Exceeded timeout (30000) while waiting after "
                    "sending work fragments to remote nodes. Sent 2 and only heard response back from 1 nodes")


class StandAnsweringAfter:
    """A Dremio that fails the first `failures` queries the way the executor of 2026-11-04 did, then answers."""

    def __init__(self, failures):
        self.failures, self.sql = failures, []

    def run_sql(self, sql, timeout=None):
        self.sql.append(sql)
        if len(self.sql) <= self.failures:
            raise JobFailed(f"{FRAGMENT_TIMEOUT}\nSQL: {sql[:200]}")
        return {"id": "15144f1a-a9af-a0d0-a2a4-6f29797edd00"}


class Clock:
    def __init__(self, step):
        self.now, self.step, self.slept = 0, step, []

    def __call__(self):
        self.now += self.step
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)


def test_the_run_waits_for_the_stand_to_answer_the_probe():
    dremio, clock = StandAnsweringAfter(2), Clock(1)
    probes = wait_until_ready(dremio, now=clock, sleep=clock.sleep)
    assert [p.state for p in probes] == [FRAGMENT_TIMEOUT, FRAGMENT_TIMEOUT, "COMPLETED"]
    assert clock.slept == [PROBE_RETRY, PROBE_RETRY]
    assert len(set(dremio.sql)) == 3 and all(INNOCENT in sql for sql in dremio.sql)


def test_a_stand_that_does_not_answer_makes_the_run_an_error():
    dremio, clock = StandAnsweringAfter(100), Clock(READY_WAIT)
    with pytest.raises(StandNotReady, match="the run cannot start.*Exceeded timeout \\(30000\\)"):
        wait_until_ready(dremio, now=clock, sleep=clock.sleep)
    assert len(dremio.sql) == 2  # the probe before the deadline and the one that found it passed


class SleepClock:
    """A clock the waiting moves: only sleeping passes time."""

    def __init__(self):
        self.seconds = 0

    def now(self):
        return self.seconds

    def sleep(self, seconds):
        self.seconds += seconds


class Query:
    """A submitted query that is done once the clock passes `finishes`."""

    def __init__(self, clock, finishes):
        self.clock, self.finishes = clock, finishes

    def done(self):
        return self.clock.seconds >= self.finishes


def test_a_run_that_is_still_waiting_says_how_many_queries_are_left(capsys):
    """Between the first and the last query of a run there is nothing to read for tens of minutes otherwise."""
    clock = SleepClock()
    wait_for([Query(clock, HEARTBEAT), Query(clock, 2.5 * HEARTBEAT)], sleep=clock.sleep, now=clock.now)
    assert clock.seconds == 3 * HEARTBEAT
    assert [line.split(" ", 1)[1] for line in capsys.readouterr().out.splitlines()] == [
        "1 of 2 queries finished, 1 min gone", "1 of 2 queries finished, 2 min gone", "2 of 2 queries finished, 3 min gone"]


def test_a_run_whose_queries_are_over_waits_for_nothing(capsys):
    clock = SleepClock()
    wait_for([Query(clock, 0)], sleep=clock.sleep, now=clock.now)
    assert clock.seconds == 0 and capsys.readouterr().out == ""


def test_a_query_reports_how_it_ended_as_soon_as_it_does(capsys):
    """The outcomes of the run are printed when all of it is over, which is an hour after the first query ended."""
    assert run_query(StandAnsweringAfter(0), "SELECT 1", name="query 3/8").state == "COMPLETED"
    assert "query 3/8 15144f1a-a9af-a0d0-a2a4-6f29797edd00: COMPLETED after 0s" in capsys.readouterr().out


def test_a_probe_that_failed_names_the_probe_and_the_error(capsys):
    dremio, clock = StandAnsweringAfter(1), Clock(1)
    wait_until_ready(dremio, now=clock, sleep=clock.sleep)
    printed = capsys.readouterr().out
    assert "probe 1 15144f77-f3db-f45d-7d85-b018d6c36e00: Job 15144f77" in printed and "probe 2 " in printed
