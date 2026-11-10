"""
The fabric direct-memory OOM (DX-127946) in the Dremio log, told apart from the other memory failures of a run, and the
lines of the two changes that fix it: the read pause (DX-128233, PR #30964) and the MemoryArbiter escalation
(DX-127978, PR #30766). The test cases are in test-cases/ of the QA repository (the test plan
test-plan-fabric-direct-memory-oom.md).

The bug is one event: a fabric (RPC) read on a FABRIC-n thread fails with netty's OutOfDirectMemoryError because direct
memory is exhausted (used + requested > max), so it is counted for an ERROR line on such a thread whose cause is that
error. The logger of that line differs per version (25.2: MessageDecoder; 27.0: RpcExceptionHandler, which also logs the
memory and the allocators, and ExecTransportExceptionHandler), so it is not part of the rule. An OutOfDirectMemoryError on
another thread, or a fabric error with another cause, is not the bug. The event carries the kind of allocation that
failed, by the frames of its stack: "socket_read" (ioBuffer or RecvByteBufAllocator$MaxMessageHandle, the rule of the
read pause) or "other" (a decode copy, which the fix leaves as it is). The channel failing is its own event: the
"Transport-level exception" line that fails every fragment on the executor.

With the read pause on, a socket read that cannot allocate is a WARN ("Socket read could not allocate ... paused reads
for N ms (episode N ms, retry N, node total pauses N)") and the channel stays up; after 60 s of failing reads the
ERROR "still can't allocate ... failing it" precedes the transport failure. The escalation is the WARN "MemoryArbiter
escalating direct memory pressure: socket reads paused for Nms", followed by the claw-back INFO that lists the top
queries by memory in cancel order ("Canceling N queries ... top 5: <id> <memory>, ..."): the first N of them are the
victims. Their texts are taken from the PR diffs; no log of a build with the changes has been read yet.

A job failure carries its cause when the log names one: "arbiter" (the memory arbiter cancelled the greediest query
because nothing shrinkable was left), "escalation" (it cancelled the query because reads stayed paused; both messages
are inside the exception of the failure line) or "planning" (a memory failure in execution planning), so a test can say
which mechanism failed a query. The job error of a query the bug killed is not one text: on 27.0 the same OOM gave
seven jobs an OUT_OF_MEMORY error and one a SYSTEM ERROR with a ChannelClosedException, so neither names a cause.

A node can leave the cluster without the bug: on this stand the executor runs on the other host and loses its
ZooKeeper session ("ZK connection suspended"), the coordinator unregisters it and fails every query it was running.
In the log that is the same picture as the bug taking the node down, so the ZooKeeper losses are events too and a
node loss carries what preceded it: a fabric OOM (the bug) or a lost session (the stand).
"""
import re
from collections import Counter
from datetime import datetime, timedelta

LINE = re.compile(r"(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) \[(?P<thread>[^\]]*)\] +(?P<level>\w+) +(?P<logger>\S+) - (?P<message>.*)")
OOM = re.compile(r"OutOfDirectMemoryError: failed to allocate (?P<size>\d+) byte\(s\) of direct memory \(used: (?P<used>\d+), max: (?P<max>\d+)\)")
SOCKET_READ_FRAME = re.compile(r"\.ioBuffer\(|RecvByteBufAllocator\$MaxMessageHandle")  # the frames of a socket read allocation
JOB = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
STATE_CHANGE = re.compile(rf"(?P<job>{JOB}): State change requested \w+ --> (?P<state>FAILED|CANCELED)")
SHRINK = re.compile(rf"Asking operator (?P<job>{JOB}):frag")
DIRECT_EXHAUSTED = "Direct memory exhausted on channel"  # 27.0: the ERROR line that carries the netty memory and the allocators
TRANSPORT = "Transport-level exception detected"  # the channel failed: every fragment on the executor fails
# the channel of the transport failure, when the line names one: the build with the read pause does, 27.0 names the connection
TRANSPORT_LINE = re.compile(rf"{TRANSPORT}(?: on channel (?P<channel>\[[^\]]*\]))?")
ARBITER_CANCEL = "MemoryArbiter detected no memory available"
ESCALATION_CANCEL = "MemoryArbiter detected that network reads stayed paused because direct memory was exhausted"
PLANNING = "MemoryAllocationUtilities"  # the logger of a memory failure in execution planning
UNREGISTERED = re.compile(r"nodesUnregistered (?P<node>\S+)")
ZK_LOST = re.compile(r"ZK connection (?P<state>suspended|lost)")  # the stand, not the bug: the node left on its own
READ_PAUSE = re.compile(r"Socket read could not allocate direct memory on channel (?P<channel>\[[^\]]*\]); paused reads "
                        r"for (?P<delay>\d+) ms \(episode (?P<episode>\d+) ms, retry (?P<retry>\d+), node total pauses (?P<total>\d+)\)")
GIVE_UP = re.compile(r"Channel (?P<channel>\[[^\]]*\]) still can't allocate after pausing reads for (?P<episode>\d+) ms "
                     r"\((?P<retries>\d+) retries\); failing it")
REGULAR_CHECK_MS = 500  # how often the arbiter checks by itself; a pause report of >= `millis` queues a check at once
ESCALATION = re.compile(r"MemoryArbiter escalating direct memory pressure: socket reads paused for (?P<paused>\d+) ?ms")
CLAW_BACK = re.compile(r"Canceling (?P<count>\d+) queries that together consume .* top \d+: (?P<top>.*)")
TOP_QUERY = re.compile(rf"(?P<job>{JOB}) (?P<memory>[^,]+)")
EVENTS = ("fabric_oom", "transport_failure", "read_pause", "pause_gave_up", "escalation", "claw_back", "shrink",
          "job_failed", "node_unregistered", "zk_lost")
# the zgrep pattern that keeps every line parse() needs
PATTERN = "|".join(["MessageDecoder", DIRECT_EXHAUSTED, "OutOfDirectMemoryError", "ioBuffer", "MaxMessageHandle", TRANSPORT,
                    "Socket read could not allocate", "still can't allocate", "MemoryArbiter escalating",
                    "Queries are canceled in order", ARBITER_CANCEL, ESCALATION_CANCEL, "Asking operator",
                    "State change requested", PLANNING, "nodesUnregistered", "ZK connection"])


def parse(lines):
    """
    The events of the lines, in log order: fabric_oom [(ts, size, used, max, kind)] with kind "socket_read" or "other",
    transport_failure [(ts, channel)] with the channel "" when the line names the connection instead (27.0),
    read_pause [(ts, channel, delay_ms, episode_ms, retry, node_total)],
    pause_gave_up [(ts, channel, episode_ms, retries)], escalation [(ts, paused_ms)],
    claw_back [(ts, count, [(job, memory)])] with the top queries in cancel order, shrink [(ts, job)],
    job_failed [(ts, job, state, cause)] with cause "arbiter", "escalation", "planning" or "" (not named in the log),
    node_unregistered [(ts, node)], zk_lost [(ts, state)].
    """
    events = {name: [] for name in EVENTS}
    planning_failed = set()  # jobs whose memory failure happened in execution planning
    fabric_error = failure = None  # the timestamped line whose exception text is being read
    block_oom = None  # the index of the fabric OOM whose stack is being read, for the kind of its allocation
    socket_read = False  # a socket read frame was seen in the stack being read
    for line in lines:
        m = LINE.match(line)
        if m:
            ts, message = datetime.strptime(m["ts"], "%Y-%m-%d %H:%M:%S,%f"), m["message"]
            fabric_error = ts if m["thread"].startswith("FABRIC-") and m["level"] == "ERROR" else None
            failure = block_oom = None
            socket_read = False
            if m["level"] == "ERROR" and m["logger"].endswith(PLANNING):
                planning_failed.add(m["thread"].split(":")[0])
            elif s := TRANSPORT_LINE.search(message):
                events["transport_failure"].append((ts, s["channel"] or ""))
            elif s := READ_PAUSE.search(message):
                events["read_pause"].append((ts, s["channel"], int(s["delay"]), int(s["episode"]), int(s["retry"]), int(s["total"])))
            elif s := GIVE_UP.search(message):
                events["pause_gave_up"].append((ts, s["channel"], int(s["episode"]), int(s["retries"])))
            elif s := ESCALATION.search(message):
                events["escalation"].append((ts, int(s["paused"])))
            elif s := CLAW_BACK.search(message):
                events["claw_back"].append((ts, int(s["count"]), [(t["job"], t["memory"]) for t in TOP_QUERY.finditer(s["top"])]))
            elif s := SHRINK.search(message):
                events["shrink"].append((ts, s["job"]))
            elif s := STATE_CHANGE.search(message):
                failure = (ts, s["job"], s["state"], "planning" if s["job"] in planning_failed else "")
                events["job_failed"].append(failure)
            elif s := UNREGISTERED.search(message):
                events["node_unregistered"].append((ts, s["node"]))
            elif s := ZK_LOST.search(message):
                events["zk_lost"].append((ts, s["state"]))
        elif fabric_error and (o := OOM.search(line)) and int(o["used"]) + int(o["size"]) > int(o["max"]):
            events["fabric_oom"].append((fabric_error, int(o["size"]), int(o["used"]), int(o["max"]),
                                         "socket_read" if socket_read else "other"))
            block_oom, fabric_error = len(events["fabric_oom"]) - 1, None
        elif (fabric_error or block_oom is not None) and SOCKET_READ_FRAME.search(line):
            socket_read = True
            if block_oom is not None:
                events["fabric_oom"][block_oom] = events["fabric_oom"][block_oom][:4] + ("socket_read",)
        elif failure and ARBITER_CANCEL in line:
            events["job_failed"][-1] = failure = failure[:3] + ("arbiter",)
        elif failure and ESCALATION_CANCEL in line:
            events["job_failed"][-1] = failure = failure[:3] + ("escalation",)
    return events


def socket_read_ooms(events):
    """The fabric OOMs of a failed socket read, the ones the fix handles; the decode copy ones ("other") are outside it."""
    return [oom for oom in events["fabric_oom"] if oom[4] == "socket_read"]


def merge(per_container):
    """One event list per kind over the events of all containers."""
    return {name: sorted(e for events in per_container.values() for e in events[name]) for name in EVENTS}


def failures_around(events, times, after=timedelta(seconds=2), before=timedelta()):
    """The jobs that failed from `before` ahead of any of `times` to `after` behind it."""
    return sorted({job for ts, job, _, _ in events["job_failed"] if any(-before <= ts - t <= after for t in times)})


def failures_after_channel_loss(events, window=timedelta(seconds=2)):
    """The jobs that failed within `window` after a socket-read OOM or a transport failure: the failures the bug caused."""
    return failures_around(events, [ts for ts, *_ in socket_read_ooms(events)]
                           + [ts for ts, _ in events["transport_failure"]], window)


def unexplained_transport_failures(events):
    """The transport failures of one node that the read pause does not explain: the ones no `still can't allocate`
    give-up precedes (F-02). A give-up of the same channel explains the failure; when either line names no channel
    (27.0 names the connection instead), any give-up before it does."""
    def explained(ts, channel):
        return any(gave_up <= ts and (channel in ("", its_channel) or its_channel == "")
                   for gave_up, its_channel, *_ in events["pause_gave_up"])

    return [failure for failure in events["transport_failure"] if not explained(*failure)]


def node_losses(events, window=timedelta(seconds=120)):
    """
    The nodes that left the cluster, each with what preceded it within `window`: "oom" when a fabric OOM did (the bug
    took the node down), "stand" when the node lost its ZooKeeper session and no OOM did, "" when nothing explains it.
    """
    return [(ts, node, "oom" if any(timedelta() <= ts - oom[0] <= window for oom in events["fabric_oom"])
             else "stand" if any(timedelta() <= ts - zk[0] <= window for zk in events["zk_lost"]) else "")
            for ts, node in events["node_unregistered"]]


def failures_of_the_stand(events, window=timedelta(seconds=2)):
    """
    The jobs the stand failed: the ones that went down with a node that left on a lost ZooKeeper session. The
    coordinator fails them a few milliseconds before it logs the node, so the window reaches both ways.
    """
    return failures_around(events, [ts for ts, _, cause in node_losses(events) if cause == "stand"], window, window)


def failures_in_one_second(events, ignore=()):
    """
    The groups of two or more jobs that failed in the same second, each job with its cause. A fabric OOM fails every
    fragment of the node, so its signature is such a group; an escalation that cancels several queries at once is one
    too, but every job of it carries the escalation.
    """
    by_second = {}
    for ts, job, _, cause in events["job_failed"]:
        if job not in ignore:
            by_second.setdefault(ts.replace(microsecond=0), []).append((job, cause))
    return [group for group in by_second.values() if len(group) > 1]


def escalations(events, window=timedelta(seconds=2)):
    """Every escalation with how long reads were paused and the queries it cancelled: the first `count` of the top
    queries of the claw-back that follows it within `window` (the claw-back line is the one that names them)."""
    return [(ts, paused, next(([job for job, _ in top[:count]] for cb, count, top in events["claw_back"]
                               if timedelta() <= cb - ts <= window), []))
            for ts, paused in events["escalation"]]


def escalation_triggers(events):
    """Every escalation of one node with the pause report just before it: (ts, paused_ms, episode_ms, gap_ms), the last
    two None when no pause line precedes it. The escalation reads the pause of that report and the report queues its
    own check instead of waiting for the next regular one (design change 2), so paused_ms is the episode of that line
    and gap_ms stays under REGULAR_CHECK_MS."""
    triggers = []
    for ts, paused in events["escalation"]:
        pause = max((p for p in events["read_pause"] if p[0] <= ts), key=lambda p: p[0], default=None)
        triggers.append((ts, paused, pause[3] if pause else None,
                         round((ts - pause[0]) / timedelta(milliseconds=1)) if pause else None))
    return triggers


def executor_record(events):
    """What the design document asks to record per executor for every run: the pause count, the longest pause
    episode with its retry number, the escalations with the queries they cancelled, and the transport failures."""
    longest = max(events["read_pause"], key=lambda p: p[3], default=None)
    return {"pauses": len(events["read_pause"]),
            "longest episode": f"{longest[3]} ms at retry {longest[4]}" if longest else None,
            "gave up": len(events["pause_gave_up"]),
            "escalations": [(ts.strftime("%H:%M:%S"), f"paused {paused} ms", cancelled) for ts, paused, cancelled in escalations(events)],
            "transport failures": len(events["transport_failure"])}


def summarize(per_container):
    """The lines of a run summary about the logs: the events of all containers, the failures by cause, the fabric OOMs
    by the kind of allocation that failed, and the record of every executor."""
    events = merge(per_container)
    return (f"events: {({name: len(e) for name, e in events.items()})}, failures by cause: "
            f"{dict(Counter(cause or 'not named' for *_, cause in events['job_failed']))}, "
            f"fabric OOMs by allocation: {dict(Counter(kind for *_, kind in events['fabric_oom']))}\n"
            + "\n".join(f"{container}: {executor_record(e)}" for container, e in per_container.items()))
