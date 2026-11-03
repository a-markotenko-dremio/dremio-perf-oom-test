"""
Offline tests of fabric_oom_repro.workload on the job errors of the runs of the stand (2026-10-29 and 2026-10-30):
which of them is a memory failure the bug can explain and which is not about memory at all.
"""
from fabric_oom_repro.workload import (INNOCENT, OVER_THE_LIMIT, QUERIES, Outcome, marked, over_the_limit,
                                       slowest_completed, unrelated_failures)

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
    """The time limit is the run's own, so the query it cancels belongs to P-06 and dirties nothing."""
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
