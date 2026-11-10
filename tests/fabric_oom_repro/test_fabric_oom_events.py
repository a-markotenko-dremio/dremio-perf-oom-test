"""
Offline tests of fabric_oom_repro.fabric_oom on lines of the server.log of the stand: 25.2.0 (runs of 2026-10-22 and
2026-10-27) and 27.0.0-main (runs of 2026-10-29), which logs the same bug through other loggers. The lines of the read pause and the escalation are
built from the format strings of PR #30964 and PR #30766: no log of a build with the changes has been read yet.
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


# the stand, not the bug (run of 2026-10-30): the executor on the other host lost its ZooKeeper session, the
# coordinator unregistered it and failed every query it was running, all within the same second
ZK_SUSPENDED = ("2026-10-30 18:21:12,365 [Curator-ConnectionStateManager-0] WARN  c.d.s.c.zk.ZKClusterCoordinator - "
                "ZK connection suspended for service executor. Endpoint updates paused.")
NODE_LOST = ("2026-10-30 18:21:35,157 [executor-selection-service-queue] INFO  tracker.logger - "
             "nodesUnregistered 192.168.1.66:45678")
LOST_NODE_FAILED = [
    "2026-10-30 18:21:35,154 [Curator-TreeCache-0] INFO  c.d.exec.work.foreman.AttemptManager - "
    "151b20b2-bb1e-d7df-67a9-d4b588918000: State change requested RUNNING --> FAILED, Exception "
    "com.dremio.common.exceptions.UserException: Dremio could not execute the query because required compute nodes "
    "became unavailable. Executors were removed from the cluster or lost network connectivity. Failed nodes: "
    "['192.168.1.66:45678'].",
    "2026-10-30 18:21:35,155 [Curator-TreeCache-0] INFO  c.d.exec.work.foreman.AttemptManager - "
    "151b20b3-4cef-828e-1400-cce703ddf800: State change requested RUNNING --> FAILED, Exception "
    "com.dremio.common.exceptions.UserException: Dremio could not execute the query because required compute nodes "
    "became unavailable. Executors were removed from the cluster or lost network connectivity. Failed nodes: "
    "['192.168.1.66:45678'].",
]

# the read pause (PR #30964) and the escalation (PR #30766), built from the format strings of the PRs
CHANNEL = "[id: 0x50a8155f, L:/10.97.177.24:45678 - R:/192.168.1.66:48462]"
SOCKET_READ_FRAMES = ["\tat org.apache.arrow.memory.ArrowByteBufAllocator.ioBuffer(ArrowByteBufAllocator.java:85)",
                      "\tat io.netty.channel.DefaultMaxMessagesRecvByteBufAllocator$MaxMessageHandle.allocate(DefaultMaxMessagesRecvByteBufAllocator.java:114)"]
READ_PAUSE = (f"2026-11-03 10:00:00,100 [FABRIC-4] WARN  c.d.exec.rpc.RpcExceptionHandler - Socket read could not allocate direct "
              f"memory on channel {CHANNEL}; paused reads for 400 ms (episode 1550 ms, retry 4, node total pauses 7), "
              "netty direct memory used 6143 of 6144 MB.")
GIVE_UP = (f"2026-11-03 10:01:00,200 [FABRIC-4] ERROR c.d.exec.rpc.RpcExceptionHandler - Channel {CHANNEL} still can't allocate "
           "after pausing reads for 60012 ms (65 retries); failing it.")
TRANSPORT_CHANNEL = (f"2026-11-03 10:01:00,201 [FABRIC-4] ERROR c.d.exec.rpc.RpcExceptionHandler - Transport-level exception "
                     f"detected on channel {CHANNEL}. Failing all fragments on this executor.")
# the pause report that triggers the escalation: its episode is the pause the WARN names, and it comes right before it
ESCALATION_PAUSE = READ_PAUSE.replace("10:00:00,100", "10:00:02,250").replace("episode 1550 ms, retry 4", "episode 2150 ms, retry 6")
ESCALATION = ("2026-11-03 10:00:02,300 [BlockedTaskMonitor] WARN  c.d.sabot.memory.MemoryArbiterImpl - MemoryArbiter escalating "
              "direct memory pressure: socket reads paused for 2150ms because direct memory could not be allocated. Direct memory "
              "used 6.0 GiB of 6.0 GiB, root allocator headroom 1.2 GiB, memory granted 4.8 GiB, shrinkable operators 12, "
              "spilling operators 3, blocked tasks 2")
CLAW_BACK = ("2026-11-03 10:00:02,310 [BlockedTaskMonitor] INFO  c.d.sabot.exec.FailGreediestQueriesStrategy - Canceling 1 "
             "queries that together consume 80% of memory (cancellation of up to 5% of memory was requested by "
             "MEMORY_ARBITER_DIRECT). Queries are canceled in order of memory used; top 2: "
             "151c6ee3-64eb-b641-43e1-fd18eda34100 3.2 GiB, 151c6e21-629c-7fb1-11fd-e1aa842cd000 800.0 MiB")
ESCALATION_FAILED = [
    "2026-11-03 10:00:02,520 [Fabric-RPC-Offload4] INFO  c.d.exec.work.foreman.AttemptManager - 151c6ee3-64eb-b641-43e1-fd18eda34100: "
    "State change requested RUNNING --> FAILED, Exception com.dremio.common.exceptions.UserRemoteException: OUT_OF_MEMORY ERROR: "
    "Query was cancelled because it exceeded the memory limits set by the administrator.",
    "MemoryArbiter detected that network reads stayed paused because direct memory was exhausted.",
]


def at(seconds, line=FAILED, job="15259175-55ba-db94-09e0-47a26c46d400"):
    """The line with its time moved to 22:38:16 + seconds and, for a job line, the job id replaced."""
    ts = datetime(2026, 10, 22, 22, 38, 16, 908000) + timedelta(seconds=seconds)
    return ts.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3] + line[23:].replace("15259175-55ba-db94-09e0-47a26c46d400", job)


def test_a_fabric_read_that_exhausted_direct_memory_is_the_fabric_oom():
    events = fabric_oom.parse([FABRIC_ERROR, "\tat io.netty...", CAUSED_BY])
    assert events["fabric_oom"] == [(datetime(2026, 10, 22, 22, 38, 16, 908000), 4194304, 6439172371, 6442450944, "other")]


def test_a_decode_copy_oom_is_not_a_socket_read_oom():
    """The decode copy OOM of the run of 2026-11-05 on the YARN cluster (MessageDecoder.decodeMessage): outside the fix."""
    decode_copy = fabric_oom.parse([FABRIC_ERROR, "\tat io.netty...", CAUSED_BY])
    socket_read = fabric_oom.parse([FABRIC_ERROR, SOCKET_READ_FRAMES[0], CAUSED_BY])
    assert decode_copy["fabric_oom"] and not fabric_oom.socket_read_ooms(decode_copy)
    assert fabric_oom.socket_read_ooms(socket_read) == socket_read["fabric_oom"]


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


def test_a_failure_without_a_named_cause_and_an_arbiter_message_elsewhere_are_not_mixed_up():
    events = fabric_oom.parse([ARBITER_FAILED[1], FAILED, SHRINK, ARBITER_FAILED[1]])
    assert events["job_failed"] == [(datetime(2026, 10, 22, 20, 14, 2, 947000), "15259175-55ba-db94-09e0-47a26c46d400", "FAILED", "")]


def test_jobs_that_failed_right_after_the_socket_read_oom_are_attributed_to_it():
    events = fabric_oom.parse([at(-5, job="aaaaaaaa-0000-0000-0000-000000000001"), FABRIC_ERROR, SOCKET_READ_FRAMES[0], CAUSED_BY,
                               at(1, job="aaaaaaaa-0000-0000-0000-000000000002"),
                               at(10, job="aaaaaaaa-0000-0000-0000-000000000003")])
    assert fabric_oom.failures_after_channel_loss(events) == ["aaaaaaaa-0000-0000-0000-000000000002"]


def test_a_job_that_failed_right_after_a_decode_copy_oom_is_not_attributed_to_the_channel_loss():
    """The run of 2026-11-05 on the YARN cluster: job 15130dc1-039b failed after an OOM of MessageDecoder.decodeMessage."""
    events = fabric_oom.parse([FABRIC_ERROR, CAUSED_BY, at(1, job="aaaaaaaa-0000-0000-0000-000000000002")])
    assert events["fabric_oom"] and not fabric_oom.failures_after_channel_loss(events)


def test_the_node_going_down_is_many_failures_in_one_second():
    events = fabric_oom.parse([at(1, job="aaaaaaaa-0000-0000-0000-000000000001"), at(1.05, job="aaaaaaaa-0000-0000-0000-000000000002"),
                               at(30, job="aaaaaaaa-0000-0000-0000-000000000003")])
    assert fabric_oom.failures_in_one_second(events) == [[("aaaaaaaa-0000-0000-0000-000000000001", ""),
                                                          ("aaaaaaaa-0000-0000-0000-000000000002", "")]]
    assert fabric_oom.failures_in_one_second(fabric_oom.parse([])) == []


def test_the_events_of_the_containers_are_merged_in_time_order():
    merged = fabric_oom.merge({"den": fabric_oom.parse([at(3)]), "home4": fabric_oom.parse([at(1), FABRIC_ERROR, CAUSED_BY])})
    assert [ts.second for ts, *_ in merged["job_failed"]] == [17, 19]
    assert len(merged["fabric_oom"]) == 1


def test_the_fabric_oom_of_27_0_is_counted_although_the_decoder_no_longer_logs_it():
    events = fabric_oom.parse([DIRECT_EXHAUSTED, TRANSPORT, OOM_STACK, "\tat io.netty...", CAUSED_BY_27, DECODER_INFO])
    assert events["fabric_oom"] == [(datetime(2026, 10, 29, 18, 33, 15, 213000), 4194304, 6442297855, 6442450944, "other")]
    assert events["transport_failure"] == [(datetime(2026, 10, 29, 18, 33, 15, 213000), "")]


def test_the_27_0_oom_is_counted_on_the_lines_the_zgrep_pattern_keeps():
    """The parser reads the zgrep output, where the transport line in between is gone."""
    events = fabric_oom.parse([DIRECT_EXHAUSTED, CAUSED_BY_27])
    assert events["fabric_oom"] == [(datetime(2026, 10, 29, 18, 33, 15, 212000), 4194304, 6442297855, 6442450944, "other")]


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
                 DIRECT_EXHAUSTED, CAUSED_BY_27, SHRINK_27, CHANNEL_CLOSED, ZK_SUSPENDED, NODE_LOST,
                 *LOST_NODE_FAILED, *SOCKET_READ_FRAMES, READ_PAUSE, GIVE_UP, TRANSPORT_CHANNEL, ESCALATION,
                 CLAW_BACK, *ESCALATION_FAILED):
        assert re.search(fabric_oom.PATTERN, line), line


def test_a_node_that_left_with_its_zookeeper_session_is_the_stand_not_the_bug():
    """The ZooKeeper loss is logged by the node that left, the unregistration by the coordinator."""
    events = fabric_oom.merge({"den": fabric_oom.parse([ZK_SUSPENDED]),
                               "dell35": fabric_oom.parse([*LOST_NODE_FAILED, NODE_LOST])})
    assert events["zk_lost"] == [(datetime(2026, 10, 30, 18, 21, 12, 365000), "suspended")]
    assert fabric_oom.node_losses(events) == [(datetime(2026, 10, 30, 18, 21, 35, 157000), "192.168.1.66:45678", "stand")]


def test_the_jobs_a_node_took_down_with_it_are_not_the_signature_of_the_bug():
    events = fabric_oom.merge({"den": fabric_oom.parse([ZK_SUSPENDED]),
                               "dell35": fabric_oom.parse([*LOST_NODE_FAILED, NODE_LOST])})
    assert len(fabric_oom.failures_in_one_second(events)[0]) == 2
    assert fabric_oom.failures_of_the_stand(events) == ["151b20b2-bb1e-d7df-67a9-d4b588918000",
                                                        "151b20b3-4cef-828e-1400-cce703ddf800"]
    assert fabric_oom.failures_in_one_second(events, fabric_oom.failures_of_the_stand(events)) == []


def test_a_node_that_left_after_a_fabric_oom_is_the_bug():
    events = fabric_oom.parse([FABRIC_ERROR, CAUSED_BY, at(5, NODE_LOST)])
    assert [cause for *_, cause in fabric_oom.node_losses(events)] == ["oom"]


def test_a_node_that_left_with_nothing_explaining_it_is_not_written_off_to_the_stand():
    assert [cause for *_, cause in fabric_oom.node_losses(fabric_oom.parse([NODE_LOST]))] == [""]


def test_a_zookeeper_loss_long_before_the_node_left_does_not_explain_it():
    events = fabric_oom.parse([ZK_SUSPENDED, at(0, NODE_LOST).replace("2026-10-22", "2026-10-30")])
    assert [cause for *_, cause in fabric_oom.node_losses(events)] == [""]


def test_a_socket_read_frame_in_the_stack_makes_the_oom_a_socket_read_one():
    """The frames of the outer exception come before the Caused by line, the frames of the cause after it."""
    for lines in ([FABRIC_ERROR, SOCKET_READ_FRAMES[0], CAUSED_BY], [FABRIC_ERROR, CAUSED_BY, SOCKET_READ_FRAMES[1]]):
        assert [kind for *_, kind in fabric_oom.parse(lines)["fabric_oom"]] == ["socket_read"], lines
    assert [kind for *_, kind in fabric_oom.parse([FABRIC_ERROR, CAUSED_BY, "\tat io.netty.handler.codec.ByteToMessageDecoder.channelRead"])["fabric_oom"]] == ["other"]


def test_a_socket_read_frame_after_another_line_does_not_change_an_earlier_oom():
    assert [kind for *_, kind in fabric_oom.parse([FABRIC_ERROR, CAUSED_BY, SHRINK, SOCKET_READ_FRAMES[0]])["fabric_oom"]] == ["other"]


def test_the_lines_of_the_read_pause_are_events_not_the_bug():
    events = fabric_oom.parse([READ_PAUSE, GIVE_UP, TRANSPORT_CHANNEL])
    assert not events["fabric_oom"]
    assert events["read_pause"] == [(datetime(2026, 11, 3, 10, 0, 0, 100000), CHANNEL, 400, 1550, 4, 7)]
    assert events["pause_gave_up"] == [(datetime(2026, 11, 3, 10, 1, 0, 200000), CHANNEL, 60012, 65)]
    assert events["transport_failure"] == [(datetime(2026, 11, 3, 10, 1, 0, 201000), CHANNEL)]


def test_a_transport_failure_that_the_read_pause_gave_up_on_is_explained():
    """F-02: the fixed build may still fail a channel, but only after the give-up of the read pause."""
    events = fabric_oom.parse([READ_PAUSE, GIVE_UP, TRANSPORT_CHANNEL])
    assert fabric_oom.unexplained_transport_failures(events) == []


def test_a_transport_failure_without_a_give_up_before_it_is_not_explained():
    """The bug: the channel fails with no give-up in front of it. The 27.0 line names the connection, not the channel,
    so a give-up of any channel would explain it; here there is none, and a give-up that only follows it explains
    nothing either."""
    assert fabric_oom.unexplained_transport_failures(fabric_oom.parse([DIRECT_EXHAUSTED, TRANSPORT, CAUSED_BY_27])) == [
        (datetime(2026, 10, 29, 18, 33, 15, 213000), "")]
    later = GIVE_UP.replace("10:01:00,200", "10:01:01,200")
    assert fabric_oom.unexplained_transport_failures(fabric_oom.parse([TRANSPORT_CHANNEL, later])) == [
        (datetime(2026, 11, 3, 10, 1, 0, 201000), CHANNEL)]


def test_a_give_up_of_another_channel_does_not_explain_the_failure():
    other = GIVE_UP.replace("0x50a8155f", "0x11111111")
    events = fabric_oom.parse([other, TRANSPORT_CHANNEL])
    assert fabric_oom.unexplained_transport_failures(events) == [(datetime(2026, 11, 3, 10, 1, 0, 201000), CHANNEL)]


def test_the_escalation_reads_the_pause_report_just_before_it():
    """F-04: the WARN names the episode of that report and follows it before the next regular check."""
    events = fabric_oom.parse([READ_PAUSE, ESCALATION_PAUSE, ESCALATION])
    assert fabric_oom.escalation_triggers(events) == [(datetime(2026, 11, 3, 10, 0, 2, 300000), 2150, 2150, 50)]


def test_an_escalation_that_does_not_follow_its_pause_report_is_visible():
    """A pause of another episode, or one 2200 ms before the WARN, is not the report that triggered it."""
    assert fabric_oom.escalation_triggers(fabric_oom.parse([READ_PAUSE, ESCALATION])) == [
        (datetime(2026, 11, 3, 10, 0, 2, 300000), 2150, 1550, 2200)]
    assert fabric_oom.escalation_triggers(fabric_oom.parse([ESCALATION])) == [
        (datetime(2026, 11, 3, 10, 0, 2, 300000), 2150, None, None)]


def test_the_escalation_names_its_victims_through_the_claw_back_line():
    events = fabric_oom.parse([ESCALATION, CLAW_BACK, *ESCALATION_FAILED])
    assert events["escalation"] == [(datetime(2026, 11, 3, 10, 0, 2, 300000), 2150)]
    assert events["claw_back"] == [(datetime(2026, 11, 3, 10, 0, 2, 310000), 1,
                                    [("151c6ee3-64eb-b641-43e1-fd18eda34100", "3.2 GiB"), ("151c6e21-629c-7fb1-11fd-e1aa842cd000", "800.0 MiB")])]
    assert fabric_oom.escalations(events) == [(datetime(2026, 11, 3, 10, 0, 2, 300000), 2150, ["151c6ee3-64eb-b641-43e1-fd18eda34100"])]
    assert events["job_failed"] == [(datetime(2026, 11, 3, 10, 0, 2, 520000), "151c6ee3-64eb-b641-43e1-fd18eda34100", "FAILED", "escalation")]


def test_an_escalation_without_a_claw_back_right_after_it_names_no_victim():
    events = fabric_oom.parse([ESCALATION, at(10, CLAW_BACK).replace("2026-10-22 22:38", "2026-11-03 10:00")])
    assert fabric_oom.escalations(events) == [(datetime(2026, 11, 3, 10, 0, 2, 300000), 2150, [])]


def test_several_victims_of_one_escalation_are_one_group_that_the_escalation_names():
    second = ESCALATION_FAILED[0].replace("151c6ee3-64eb-b641-43e1-fd18eda34100", "151c6e21-629c-7fb1-11fd-e1aa842cd000")
    events = fabric_oom.parse([*ESCALATION_FAILED, second, ESCALATION_FAILED[1]])
    assert fabric_oom.failures_in_one_second(events) == [[("151c6ee3-64eb-b641-43e1-fd18eda34100", "escalation"),
                                                          ("151c6e21-629c-7fb1-11fd-e1aa842cd000", "escalation")]]


def test_the_record_of_an_executor_is_what_the_design_asks_for():
    longer = READ_PAUSE.replace("episode 1550 ms, retry 4", "episode 2100 ms, retry 5").replace("10:00:00,100", "10:00:01,100")
    events = fabric_oom.parse([READ_PAUSE, longer, ESCALATION, CLAW_BACK, GIVE_UP, TRANSPORT_CHANNEL])
    assert fabric_oom.executor_record(events) == {
        "pauses": 2, "longest episode": "2100 ms at retry 5", "gave up": 1,
        "escalations": [("10:00:02", "paused 2150 ms", ["151c6ee3-64eb-b641-43e1-fd18eda34100"])], "transport failures": 1}
    assert fabric_oom.executor_record(fabric_oom.parse([])) == {
        "pauses": 0, "longest episode": None, "gave up": 0, "escalations": [], "transport failures": 0}


def test_the_summary_counts_the_events_the_failures_by_cause_and_the_ooms_by_allocation():
    summary = fabric_oom.summarize({"home4": fabric_oom.parse([FABRIC_ERROR, SOCKET_READ_FRAMES[0], CAUSED_BY, *ESCALATION_FAILED]),
                                    "den": fabric_oom.parse([*ARBITER_FAILED])})
    assert "'fabric_oom': 1" in summary and "'arbiter': 1" in summary and "'escalation': 1}" in summary
    assert "fabric OOMs by allocation: {'socket_read': 1}" in summary
    assert "\nhome4: {'pauses': 0" in summary and "\nden: {'pauses': 0" in summary
