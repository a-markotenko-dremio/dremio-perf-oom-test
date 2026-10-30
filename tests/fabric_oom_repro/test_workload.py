"""
Offline tests of fabric_oom_repro.workload on the job errors of the runs of the stand (2026-10-29 and 2026-10-30):
which of them is a memory failure the bug can explain and which is not about memory at all.
"""
from fabric_oom_repro.workload import Outcome, slowest_completed, unrelated_failures

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
TIMEOUT = Outcome("151b2142-a53e-d36a-dd25-27cddd150a00",
                  "Job 151b2142-a53e-d36a-dd25-27cddd150a00 did not finish within 2400s (state=RUNNING)", 2400)
DONE = Outcome("151b2142-ee93-ddf2-d53a-f1cc3d6f1f00", "COMPLETED", 29)


def test_the_memory_failures_of_a_run_are_not_counted_as_unrelated():
    assert not unrelated_failures([OOM, CHANNEL_CLOSED, NODE_GONE, DONE])


def test_a_failure_on_the_input_file_is_unrelated():
    assert unrelated_failures([OOM, BROKEN_INPUT, DONE]) == ["151b2142-cb9e-ab22-7001-940566fed600"]


def test_a_query_that_ran_out_of_time_is_unrelated():
    assert unrelated_failures([TIMEOUT]) == ["151b2142-a53e-d36a-dd25-27cddd150a00"]


def test_the_slowest_served_query_is_the_cost_of_surviving():
    """The run of 12:28 on 2026-10-30: seven queries spilled instead of failing, the slowest answered after 31 min."""
    served = [DONE._replace(seconds=228), DONE._replace(job="151b1e3b-bb23-66c6-0f40-a927211ff200", seconds=1839)]
    assert slowest_completed([*served, OOM]).seconds == 1839


def test_a_run_where_nothing_was_served_has_no_slowest_query():
    assert slowest_completed([OOM, BROKEN_INPUT]) is None
