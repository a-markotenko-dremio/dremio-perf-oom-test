"""
Offline tests of fabric_oom_repro.fabric_oom on lines of the server.log of the stand: 25.2.0 (runs of 2026-10-22 and
2026-10-27) and 27.0.0-main (runs of 2026-10-29), which logs the same bug through other loggers.
"""
from datetime import datetime, timedelta

from fabric_oom_repro import fabric_oom

FABRIC_ERROR = ("2026-10-22 22:38:16,908 [FABRIC-4] ERROR com.dremio.exec.rpc.MessageDecoder - "
                "Query was cancelled because it exceeded the memory limits set by the administrator.")
CAUSED_BY = ("Caused by: io.netty.util.internal.OutOfDirectMemoryError: failed to allocate 4194304 byte(s) of direct "
             "memory (used: 6439172371, max: 6442450944)")
SHRINK = ("2026-10-22 20:33:43,022 [MA-memory-monitor-thread-1] INFO  c.d.sabot.memory.MemoryArbiterImpl - Asking operator "
          "15258cdc-ced8-89fe-7b9c-c91519dc5c00:frag:4:2:3(shrinkable memory: 0)(operator state: CAN_PRODUCE PROBE_OUT) "
          "to shrink memory. Current shrinkable memory is 24412160 bytes (23 MiB)")
PLANNING = ("2026-10-22 20:14:02,947 [15259175-55ba-db94-09e0-47a26c46d400:execution-planning] ERROR "
            "c.d.e.util.MemoryAllocationUtilities - Query was cancelled because it exceeded the memory limits set by the administrator.")
FAILED = ("2026-10-22 20:14:02,947 [15259175-55ba-db94-09e0-47a26c46d400:foreman] INFO  c.d.exec.work.foreman.AttemptManager - "
          "15259175-55ba-db94-09e0-47a26c46d400: State change requested STARTING --> FAILED, Exception "
          "com.dremio.common.exceptions.UserException: Query was cancelled because it exceeded the memory limits set by the administrator.")
# a failure the memory arbiter caused (run of 2026-10-27): the arbiter's message is inside the exception of the failure line
ARBITER_FAILED = [
    "2026-10-27 02:14:58,418 [Fabric-RPC-Offload4] INFO  c.d.exec.work.foreman.AttemptManager - 151ff6e0-a221-b068-ddc5-558aac8e4600: "
    "State change requested RUNNING --> FAILED, Exception com.dremio.common.exceptions.UserRemoteException: OUT_OF_MEMORY ERROR: "
    "Query was cancelled because it exceeded the memory limits set by the administrator.",
    "MemoryArbiter detected no memory available",
    "  (org.apache.arrow.memory.OutOfMemoryException) MemoryArbiter detected no memory available",
]
UNREGISTERED = "2026-10-27 02:08:55,355 [executor-selection-service-queue] INFO  tracker.logger - nodesUnregistered d25-2-0-j21-14G-4cpu:45678"
# 27.0.0-main (run of 2026-10-29, 3 of 3 reproduced): MessageDecoder only logs INFO and the OOM arrives through
# RpcExceptionHandler, whose line also carries the netty memory and the allocators, then ExecTransportExceptionHandler
DIRECT_EXHAUSTED = (
    "2026-10-29 18:33:15,212 [FABRIC-4] ERROR c.d.exec.rpc.RpcExceptionHandler - Direct memory exhausted on channel "
    "[id: 0x50a8155f, L:/10.97.177.24:45678 - R:/192.168.1.66:48462]: netty direct memory used 6143 of 6144 MB; outbound "
    "queued 0 messages (0 bytes), 0 requests awaiting response; connection allocator fabric-allocator allocated 5 MB "
    "(peak 37 MB); RPC allocators (allocated/peak MB): fabric-allocator=5/37, fragment-work-manager=494/494, "
    "send-rpc-buffer=0/31; top 10 root allocators (allocated/peak MB): "
    "queue-3cd7d794-cfc6-4436-a24f-5d10a60f97ea=4477/5592, fragment-work-manager=494/494, fabric-allocator=5/37, "
    "query-planning=0/13, WebServer=0/0, queue-dbaf7ce2-3698-49fe-b86a-58cf42c8b006=0/0, flight-service-allocator=0/0, "
    "queue-7b25f7e3-39a3-4b07-b878-7e1097b7bd88=0/0, sysflight-producer=0/3, coord-exec-rpc=0/0")
TRANSPORT = ("2026-10-29 18:33:15,213 [FABRIC-4] ERROR c.d.s.e.r.ExecTransportExceptionHandler - Transport-level exception "
             "detected on connection /10.97.177.24:45678 <--> /192.168.1.66:48462 (fabric server). Failing all active fragments.")
OOM_STACK = "org.apache.arrow.memory.OutOfMemoryException: Failure allocating buffer."
CAUSED_BY_27 = ("Caused by: io.netty.util.internal.OutOfDirectMemoryError: failed to allocate 4194304 byte(s) of direct "
                "memory (used: 6442297855, max: 6442450944)")
DECODER_INFO = ("2026-10-29 18:33:16,514 [FABRIC-4] INFO  com.dremio.exec.rpc.MessageDecoder - Channel is closed, "
                "discarding remaining 339254 byte(s) in buffer.")
SHRINK_27 = ("2026-10-29 18:32:30,774 [MA-memory-monitor-thread] INFO  c.d.sabot.memory.MemoryArbiterImpl - Asking operator "
             "151c6ee3-64eb-b641-43e1-fd18eda34100:frag:2:11:2(shrinkable memory: 417005568)(heap shrinkable memory: 438192)"
             "(operator state: CAN_CONSUME NONE) to shrink memory due to direct memory pressure. Current shrinkable memory "
             "is 376897536 bytes (359 MiB)")
# the eighth job of the same run: the bug does not give every victim the same error
CHANNEL_CLOSED = ("2026-10-29 18:36:46,440 [Fabric-RPC-Offload15] INFO  c.d.exec.work.foreman.AttemptManager - "
                  "151c6e21-629c-7fb1-11fd-e1aa842cd000: State change requested RUNNING --> FAILED, Exception "
                  "com.dremio.common.exceptions.UserRemoteException: SYSTEM ERROR: ChannelClosedException: [FABRIC]: "
                  "Channel closed /10.103.137.130:34498 <--> /192.168.1.75:45678 (fabric client)")


def at(seconds, line=FAILED, job="15259175-55ba-db94-09e0-47a26c46d400"):
    """The line with its time moved to 22:38:16 + seconds and, for a job line, the job id replaced."""
    ts = datetime(2026, 10, 22, 22, 38, 16, 908000) + timedelta(seconds=seconds)
    return ts.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3] + line[23:].replace("15259175-55ba-db94-09e0-47a26c46d400", job)


def test_a_fabric_read_that_exhausted_direct_memory_is_the_fabric_oom():
    events = fabric_oom.parse([FABRIC_ERROR, "\tat io.netty...", CAUSED_BY])
    assert events["fabric_oom"] == [(datetime(2026, 10, 22, 22, 38, 16, 908000), 4194304, 6439172371, 6442450944)]


def test_the_same_error_on_an_executor_thread_is_not_the_fabric_oom():
    line = FABRIC_ERROR.replace("[FABRIC-4]", "[e0 - 15258cdc-ced8-89fe-7b9c-c91519dc5c00:frag:1:0]").replace(
        "com.dremio.exec.rpc.MessageDecoder", "c.d.sabot.exec.fragment.FragmentExecutor")
    assert not fabric_oom.parse([line, CAUSED_BY])["fabric_oom"]


def test_a_failed_allocation_with_free_memory_is_not_the_fabric_oom():
    assert not fabric_oom.parse([FABRIC_ERROR, CAUSED_BY.replace("used: 6439172371", "used: 1000000")])["fabric_oom"]


def test_a_decoder_error_with_another_cause_is_not_the_fabric_oom():
    assert not fabric_oom.parse([FABRIC_ERROR, "Caused by: java.io.IOException: Connection reset by peer"])["fabric_oom"]


def test_every_fabric_error_with_its_own_cause_is_one_event():
    assert len(fabric_oom.parse([FABRIC_ERROR, CAUSED_BY, at(0.026, FABRIC_ERROR), CAUSED_BY])["fabric_oom"]) == 2


def test_the_other_memory_events_are_told_apart():
    events = fabric_oom.parse([SHRINK, *ARBITER_FAILED, PLANNING, FAILED, UNREGISTERED])
    assert not events["fabric_oom"]
    assert events["shrink"] == [(datetime(2026, 10, 22, 20, 33, 43, 22000), "15258cdc-ced8-89fe-7b9c-c91519dc5c00")]
    assert events["job_failed"] == [
        (datetime(2026, 10, 27, 2, 14, 58, 418000), "151ff6e0-a221-b068-ddc5-558aac8e4600", "FAILED", "arbiter"),
        (datetime(2026, 10, 22, 20, 14, 2, 947000), "15259175-55ba-db94-09e0-47a26c46d400", "FAILED", "planning")]
    assert events["node_unregistered"] == [(datetime(2026, 10, 27, 2, 8, 55, 355000), "d25-2-0-j21-14G-4cpu:45678")]
    assert fabric_oom.arbiter_cancellations(events) == [datetime(2026, 10, 27, 2, 14, 58, 418000)]


def test_a_failure_without_a_named_cause_and_an_arbiter_message_elsewhere_are_not_mixed_up():
    events = fabric_oom.parse([ARBITER_FAILED[1], FAILED, SHRINK, ARBITER_FAILED[1]])
    assert events["job_failed"] == [(datetime(2026, 10, 22, 20, 14, 2, 947000), "15259175-55ba-db94-09e0-47a26c46d400", "FAILED", "")]


def test_jobs_that_failed_right_after_the_fabric_oom_are_attributed_to_it():
    events = fabric_oom.parse([at(-5, job="aaaaaaaa-0000-0000-0000-000000000001"), FABRIC_ERROR, CAUSED_BY,
                               at(1, job="aaaaaaaa-0000-0000-0000-000000000002"),
                               at(10, job="aaaaaaaa-0000-0000-0000-000000000003")])
    assert fabric_oom.failures_after_fabric_oom(events) == ["aaaaaaaa-0000-0000-0000-000000000002"]


def test_the_node_going_down_is_many_failures_in_one_second():
    events = fabric_oom.parse([at(1, job="aaaaaaaa-0000-0000-0000-000000000001"), at(1.05, job="aaaaaaaa-0000-0000-0000-000000000002"),
                               at(30, job="aaaaaaaa-0000-0000-0000-000000000003")])
    assert fabric_oom.most_failures_in_one_second(events) == 2
    assert fabric_oom.most_failures_in_one_second(fabric_oom.parse([])) == 0


def test_the_events_of_the_containers_are_merged_in_time_order():
    merged = fabric_oom.merge({"den": fabric_oom.parse([at(3)]), "home4": fabric_oom.parse([at(1), FABRIC_ERROR, CAUSED_BY])})
    assert [ts.second for ts, *_ in merged["job_failed"]] == [17, 19]
    assert len(merged["fabric_oom"]) == 1


def test_the_fabric_oom_of_27_0_is_counted_although_the_decoder_no_longer_logs_it():
    events = fabric_oom.parse([DIRECT_EXHAUSTED, TRANSPORT, OOM_STACK, "\tat io.netty...", CAUSED_BY_27, DECODER_INFO])
    assert events["fabric_oom"] == [(datetime(2026, 10, 29, 18, 33, 15, 213000), 4194304, 6442297855, 6442450944)]


def test_the_27_0_oom_is_counted_on_the_lines_the_zgrep_pattern_keeps():
    """The parser reads the zgrep output, where the transport line in between is gone."""
    events = fabric_oom.parse([DIRECT_EXHAUSTED, CAUSED_BY_27])
    assert events["fabric_oom"] == [(datetime(2026, 10, 29, 18, 33, 15, 212000), 4194304, 6442297855, 6442450944)]


def test_the_decoder_closing_the_channel_after_the_oom_is_not_a_second_event():
    assert not fabric_oom.parse([DECODER_INFO, CAUSED_BY_27])["fabric_oom"]


def test_a_27_0_shrink_request_is_counted():
    assert fabric_oom.parse([SHRINK_27])["shrink"] == [
        (datetime(2026, 10, 29, 18, 32, 30, 774000), "151c6ee3-64eb-b641-43e1-fd18eda34100")]


def test_a_victim_whose_channel_was_closed_is_a_failure_without_a_named_cause():
    events = fabric_oom.parse([DIRECT_EXHAUSTED, CAUSED_BY_27, CHANNEL_CLOSED])
    assert events["job_failed"] == [
        (datetime(2026, 10, 29, 18, 36, 46, 440000), "151c6e21-629c-7fb1-11fd-e1aa842cd000", "FAILED", "")]


def test_the_zgrep_pattern_keeps_every_line_the_parser_needs():
    import re
    for line in (FABRIC_ERROR, CAUSED_BY, SHRINK, *ARBITER_FAILED, PLANNING, FAILED, UNREGISTERED,
                 DIRECT_EXHAUSTED, CAUSED_BY_27, SHRINK_27, CHANNEL_CLOSED):
        assert re.search(fabric_oom.PATTERN, line), line
