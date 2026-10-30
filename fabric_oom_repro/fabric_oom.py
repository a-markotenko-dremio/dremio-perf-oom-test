"""
The fabric direct-memory OOM (DX-127946) in the Dremio log, told apart from the other memory failures of a run.

The bug is one event: a fabric (RPC) read on a FABRIC-n thread fails with netty's OutOfDirectMemoryError because direct
memory is exhausted (used + requested > max), so it is counted for an ERROR line on such a thread whose cause is that
error. The logger of that line differs per version (25.2: MessageDecoder; 27.0: RpcExceptionHandler, which also logs the
memory and the allocators, and ExecTransportExceptionHandler), so it is not part of the rule. An OutOfDirectMemoryError on
another thread, or a fabric error with another cause, is not the bug.

A job failure carries its cause when the log names one: "arbiter" (the memory arbiter cancelled the greediest query; its
message is inside the exception of the failure line) or "planning" (a memory failure in execution planning), so a test
can say which mechanism failed a query. The job error of a query the bug killed is not one text: on 27.0 the same OOM
gave seven jobs an OUT_OF_MEMORY error and one a SYSTEM ERROR with a ChannelClosedException, so neither names a cause.

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
JOB = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
STATE_CHANGE = re.compile(rf"(?P<job>{JOB}): State change requested \w+ --> (?P<state>FAILED|CANCELED)")
SHRINK = re.compile(rf"Asking operator (?P<job>{JOB}):frag")
DIRECT_EXHAUSTED = "Direct memory exhausted on channel"  # 27.0: the ERROR line that carries the netty memory and the allocators
ARBITER_CANCEL = "MemoryArbiter detected no memory available"
PLANNING = "MemoryAllocationUtilities"  # the logger of a memory failure in execution planning
UNREGISTERED = re.compile(r"nodesUnregistered (?P<node>\S+)")
ZK_LOST = re.compile(r"ZK connection (?P<state>suspended|lost)")  # the stand, not the bug: the node left on its own
EVENTS = ("fabric_oom", "shrink", "job_failed", "node_unregistered", "zk_lost")
# the zgrep pattern that keeps every line parse() needs
PATTERN = "|".join(["MessageDecoder", DIRECT_EXHAUSTED, "OutOfDirectMemoryError", ARBITER_CANCEL, "Asking operator",
                    "State change requested", PLANNING, "nodesUnregistered", "ZK connection"])


def parse(lines):
    """
    The events of the lines, in log order: fabric_oom [(ts, size, used, max)], shrink [(ts, job)],
    job_failed [(ts, job, state, cause)] with cause "arbiter", "planning" or "" (not named in the log),
    node_unregistered [(ts, node)], zk_lost [(ts, state)].
    """
    events = {name: [] for name in EVENTS}
    planning_failed = set()  # jobs whose memory failure happened in execution planning
    fabric_error = failure = None  # the timestamped line whose exception text is being read
    for line in lines:
        m = LINE.match(line)
        if m:
            ts, message = datetime.strptime(m["ts"], "%Y-%m-%d %H:%M:%S,%f"), m["message"]
            fabric_error = ts if m["thread"].startswith("FABRIC-") and m["level"] == "ERROR" else None
            failure = None
            if m["level"] == "ERROR" and m["logger"].endswith(PLANNING):
                planning_failed.add(m["thread"].split(":")[0])
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
            events["fabric_oom"].append((fabric_error, int(o["size"]), int(o["used"]), int(o["max"])))
            fabric_error = None
        elif failure and ARBITER_CANCEL in line:
            events["job_failed"][-1] = failure = failure[:3] + ("arbiter",)
    return events


def merge(per_container):
    """One event list per kind over the events of all containers."""
    return {name: sorted(e for events in per_container.values() for e in events[name]) for name in EVENTS}


def failures_around(events, times, after=timedelta(seconds=2), before=timedelta()):
    """The jobs that failed from `before` ahead of any of `times` to `after` behind it."""
    return sorted({job for ts, job, _, _ in events["job_failed"] if any(-before <= ts - t <= after for t in times)})


def failures_after_fabric_oom(events, window=timedelta(seconds=2)):
    """The jobs that failed within `window` after a fabric OOM: the failures the bug caused."""
    return failures_around(events, [ts for ts, *_ in events["fabric_oom"]], window)


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


def most_failures_in_one_second(events, ignore=()):
    """A fabric OOM fails every fragment of the node, so its signature is many jobs failing in the same second."""
    return max(Counter(ts.replace(microsecond=0) for ts, job, _, _ in events["job_failed"] if job not in ignore).values(),
               default=0)


def arbiter_cancellations(events):
    """The times of the job failures the memory arbiter caused."""
    return [ts for ts, _, _, cause in events["job_failed"] if cause == "arbiter"]
