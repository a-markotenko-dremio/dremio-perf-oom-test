"""
Verification of the fabric direct-memory OOM fix (read pause DX-128233 and MemoryArbiter escalation DX-127978; the test
cases are in test-cases/ of the QA repository, the plan is test-plan-fabric-direct-memory-oom.md): the workload of the
reproduction runs once per module and every test checks one case on the events the run added to the logs. On an
unfixed build F-03, F-04 and F-05 fail (27.0.0, runs of 2026-10-30; the F-09 query outlived an OOM that failed the
eight). F-08 is the same module run with the default reserve (no OOM_RESERVE_PCT); F-09 needs its own run with
OOM_INNOCENT=1: with the small query the fabric OOM did not reproduce, so the other cases are checked without it.
F-17 (read pause alone) is the same module with OOM_ESCALATION=0.

P-06 is the cost of surviving: a query the fix saved from the OOM is of no use to the user if it answers after half an
hour, so OOM_MAX_QUERY_SECONDS is the time a query of the run may take; a query that reaches the limit is cancelled and
the run fails on the limit, not on the product. P-07 needs OOM_MAX_QUERY_SECONDS=0: with no limit
the queries run to their end and the run says whether every query of the workload is served, at the price of an hour
(scripts/fabric_oom_repro/run_fabric_oom_feature.sh).

F-05 and F-07 see the same picture when it is the stand that broke and not the product: an executor that lost its
ZooKeeper session leaves the cluster and takes its queries down with it. They judge the product only, and
test_the_stand_held_through_the_run reports the rest; a run it fails gives no verdict on those two and is repeated.
A run starts only when the stand answers a probe query (stand_ready, F-02): on 2026-11-04 three sessions lost every
query within 30 s because the executor was still cancelling the queries of the session before, and such a run is an
error of the setup, not a verdict.

Run: scripts/fabric_oom_repro/run_fabric_oom_func.sh
"""
from collections import namedtuple

import pytest

import settings
from fabric_oom_repro import fabric_oom
from fabric_oom_repro.logs import events_added_by
from fabric_oom_repro.workload import (describe, over_the_limit, run_workload, slowest_completed,
                                       unrelated_failures)

Run = namedtuple("Run", "outcomes innocent events unrelated cut summary")


@pytest.fixture(scope="module")
def run(dremio, tables, stand_ready, system_options, containers, stand):
    """The workload, with the events it added to the logs of all containers merged in time order."""
    (outcomes, innocent), per_container = events_added_by(
        containers, lambda: run_workload(dremio, settings.OOM_INNOCENT, settings.OOM_MAX_QUERY_SECONDS or None))
    events = fabric_oom.merge(per_container)
    unrelated, cut = unrelated_failures(outcomes), over_the_limit(outcomes)
    summary = (f"{describe(stand, system_options, outcomes)}\n"
               f"innocent query: {f'{innocent.state} after {innocent.seconds:.0f}s' if innocent else 'not run'}\n"
               f"{fabric_oom.summarize(per_container)}\n"
               f"node losses: {fabric_oom.node_losses(events)}, jobs failed for another reason: {unrelated}\n"
               f"time limit of a query: {f'{settings.OOM_MAX_QUERY_SECONDS}s' if settings.OOM_MAX_QUERY_SECONDS else 'none'}, "
               f"queries it cut off: {cut}\n"
               f"slowest query that was served: {f'{slowest.seconds:.0f}s' if (slowest := slowest_completed(outcomes)) else 'none'}")
    print("\n" + summary)
    return Run(outcomes, innocent, events, unrelated, cut, summary)


def test_run_put_memory_under_pressure(run):
    """F-02: The workload puts memory under pressure. Without shrink requests the other tests prove nothing."""
    assert run.events["shrink"], f"no memory pressure\n{run.summary}"


def test_the_stand_held_through_the_run(run):
    """F-02 (run guard, the other half): a node that left on a lost ZooKeeper session and a failure that is not about
    memory give the picture of F-05 and F-07 without the product doing anything wrong, so such a run proves nothing."""
    stand = [loss for loss in fabric_oom.node_losses(run.events) if loss[2] == "stand"]
    assert not stand and not run.unrelated, (f"the stand broke during the run, repeat it: nodes that left with their "
                                             f"ZooKeeper session {stand}, jobs failed for another reason "
                                             f"{run.unrelated}\n{run.summary}")


def test_no_transport_level_failure(run):
    """F-03: No transport-level failure under the baseline workload and no socket-read OOM that fails a channel. A fabric
    OOM event is an ERROR of a failed read on a FABRIC thread, which with the read pause on is a WARN instead. The decode
    copy OOMs the fix leaves as they are are counted apart (the summary), they do not fail the case."""
    socket_reads = fabric_oom.socket_read_ooms(run.events)
    assert not run.events["transport_failure"] and not socket_reads, (
        f"the channel failed: transport failures {run.events['transport_failure']}, socket-read OOMs {socket_reads}\n{run.summary}")


def test_no_query_failed_because_of_a_transport_failure(run):
    """F-04: No query fails because of a transport-level failure (the jobs that failed within 2 s after one, or after
    a socket-read OOM). Whether every other failed job carries the escalation or a per-query OOM is read from the
    summary: a failure the log does not name has no cause the test can check."""
    caused = [job for job in fabric_oom.failures_after_channel_loss(run.events) if job not in run.cut]
    assert not caused, f"jobs failed right after the channel was lost: {caused}\n{run.summary}"


def test_one_failure_does_not_take_the_node_down(run):
    """F-05: One failure does not take the node down. The bug fails every fragment of a node at once, so its signature
    is many jobs failing in the same second; an escalation that cancels several queries at once is allowed, and every
    job of such a group carries it. The jobs the stand took down and the ones the run cancelled on its time limit
    (they too end in one second, all at the limit) are counted out here and reported by their own test."""
    ignore = set(run.unrelated) | set(run.cut) | set(fabric_oom.failures_of_the_stand(run.events))
    groups = [g for g in fabric_oom.failures_in_one_second(run.events, ignore) if any(cause != "escalation" for _, cause in g)]
    assert not groups, f"jobs failed in the same second without the escalation naming them (the node went down): {groups}\n{run.summary}"


def test_escalation_fires_only_after_a_long_enough_pause(run):
    """F-06: Escalation fires only after a pause of at least `millis` and before the give-up. A run without an
    escalation does not exercise it (F-18 does)."""
    early = [e for e in run.events["escalation"] if e[1] < settings.OOM_ESCALATION_MILLIS]
    assert not early and not run.events["pause_gave_up"], (
        f"escalations before {settings.OOM_ESCALATION_MILLIS} ms of pause: {early}; pauses that gave up: "
        f"{run.events['pause_gave_up']}\n{run.summary}")


def test_executors_stay_in_the_cluster(run):
    """F-07: Executors stay registered during the run. A node that left after a fabric OOM, or with nothing in the
    logs explaining it, is the product; one that left with its ZooKeeper session is the stand and belongs to
    test_the_stand_held_through_the_run."""
    gone = [loss for loss in fabric_oom.node_losses(run.events) if loss[2] != "stand"]
    assert not gone, f"nodes left the cluster during the run: {gone}\n{run.summary}"


@pytest.mark.skipif(not settings.OOM_INNOCENT, reason="the small query runs only with OOM_INNOCENT=1")
def test_innocent_query_completes(run):
    """F-09: A small query next to the heavy ones survives."""
    assert run.innocent.state == "COMPLETED", f"the small query failed: {run.innocent.state}\n{run.summary}"


@pytest.mark.skipif(not settings.OOM_MAX_QUERY_SECONDS, reason="this run has no time limit (OOM_MAX_QUERY_SECONDS=0)")
def test_no_query_takes_longer_than_the_run_allows(run):
    """P-06: A query is served within the time the run allows. Spilling instead of failing is the fix working, but only
    while the answer still arrives in time. A failure here is a failure on the time limit: the queries it names were
    cancelled, not failed by the product, and whether they would ever have answered is what the run without a limit
    measures."""
    assert not run.cut, (f"the run was cut off by its time limit: {len(run.cut)} queries did not answer within "
                         f"{settings.OOM_MAX_QUERY_SECONDS}s {run.cut}\n{run.summary}")


@pytest.mark.skipif(bool(settings.OOM_MAX_QUERY_SECONDS), reason="the queries are cut off by the time limit of the run")
def test_every_query_of_the_workload_is_served(run):
    """P-07: Every query is served when given the time. The fix works when a query under memory pressure
    spills and answers instead of being lost. This is the one criterion that needs the whole run, however long it
    takes, so it runs without a time limit and on its own."""
    lost = sorted(o.job for o in run.outcomes if o.state != "COMPLETED")
    assert not lost, f"{len(lost)} queries of the workload were never served: {lost}\n{run.summary}"
