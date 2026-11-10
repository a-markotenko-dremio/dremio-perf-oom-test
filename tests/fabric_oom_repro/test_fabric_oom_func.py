"""
Verification of the fabric direct-memory OOM fix (read pause DX-128233 and MemoryArbiter escalation DX-127978; the test
cases are in test-cases/ of the QA repository, the plan is test-plan-fabric-direct-memory-oom.md): the workload of the
reproduction runs once per module and every test checks one case on the events the run added to the logs. On an
unfixed build F-02 and both scenarios of F-03 fail (27.0.0, runs of 2026-10-30; the F-07 query outlived an OOM that
failed the eight). F-06 is the same module run with the default reserve (no OOM_RESERVE_PCT); F-07 needs its own run with
OOM_INNOCENT=1: with the small query the fabric OOM did not reproduce, so the other cases are checked without it.
F-12 (read pause alone) is the same module with OOM_ESCALATION=0.

The time limit of a query is the run's own rule (the plan: every query of these runs is cancelled after
OOM_MAX_QUERY_SECONDS): a query the fix saved from the OOM is of no use to the user if it answers after half an hour,
and a query that reaches the limit is cancelled and the run fails on the limit, not on the product. P-05 needs
OOM_MAX_QUERY_SECONDS=0: with no limit the queries run to their end and the run says whether every query of the
workload is served, at the price of an hour (scripts/fabric_oom_repro/run_fabric_oom_feature.sh).

F-03 and F-05 see the same picture when it is the stand that broke and not the product: an executor that lost its
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

pytestmark = pytest.mark.bdd  # a case of test-cases/ of the QA repository, checked on the stand: `pytest -m bdd` runs them all

Run = namedtuple("Run", "outcomes innocent events per_container unrelated cut summary")


@pytest.fixture(scope="module")
def run(dremio, tables, stand_ready, system_options, containers, stand):
    """The workload, with the events it added to the logs of all containers, per container and merged in time order."""
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
    return Run(outcomes, innocent, events, per_container, unrelated, cut, summary)


def test_run_put_memory_under_pressure(run):
    """F-02, run precondition: the workload puts memory under pressure. Without shrink requests the other tests prove
    nothing, so such a run is an error, not a verdict."""
    assert run.events["shrink"], f"no memory pressure\n{run.summary}"


def test_the_stand_held_through_the_run(run):
    """F-02, run precondition (the other half): a node that left on a lost ZooKeeper session and a failure that is not
    about memory give the picture of F-03 and F-05 without the product doing anything wrong, so such a run proves
    nothing."""
    stand = [loss for loss in fabric_oom.node_losses(run.events) if loss[2] == "stand"]
    assert not stand and not run.unrelated, (f"the stand broke during the run, repeat it: nodes that left with their "
                                             f"ZooKeeper session {stand}, jobs failed for another reason "
                                             f"{run.unrelated}\n{run.summary}")


def test_every_transport_failure_follows_a_give_up(run):
    """F-02: every transport-level failure of the run follows a `still can't allocate` give-up of the read pause, which
    is the one way the fixed build may still fail a channel. The decode-copy OOMs the fix leaves as they are are
    counted apart (the summary), they do not fail the case; the channels are a node's own, so every node is read on
    its own events."""
    unexplained = {container: fabric_oom.unexplained_transport_failures(events)
                   for container, events in run.per_container.items()}
    assert not any(unexplained.values()), (
        f"the channel failed without the read pause giving up first: {unexplained}\n{run.summary}")


def test_no_query_failed_because_of_a_transport_failure(run):
    """F-03: no job fails within 2 s after a transport-level failure or a socket-read OOM. Whether every other failed
    job carries the escalation or a per-query OOM is read from the summary: a failure the log does not name has no
    cause the test can check."""
    caused = [job for job in fabric_oom.failures_after_channel_loss(run.events) if job not in run.cut]
    assert not caused, f"jobs failed right after the channel was lost: {caused}\n{run.summary}"


def test_jobs_that_failed_in_one_second_have_a_named_cause(run):
    """F-03: jobs failing in the same second all have a named cause. The bug fails every fragment of a node at once, so
    its signature is a group of jobs failing in the same second with nothing in the log naming a cause; the arbiter
    cancel and the escalation may each cancel several queries at once, and then every job of the group carries one of
    them. The jobs the stand took down and the ones the run cancelled on its time limit (they too end in one second,
    all at the limit) are counted out here and reported by their own test."""
    ignore = set(run.unrelated) | set(run.cut) | set(fabric_oom.failures_of_the_stand(run.events))
    groups = [g for g in fabric_oom.failures_in_one_second(run.events, ignore)
              if any(cause not in ("arbiter", "escalation") for _, cause in g)]
    assert not groups, f"jobs failed in the same second with no cause named in the log: {groups}\n{run.summary}"


def test_escalation_fires_only_after_a_long_enough_pause(run):
    """F-04: every escalation shows a pause of at least `millis`, reads the pause report just before it and follows it
    at once, and the run reaches no give-up. A run without an escalation does not exercise it (F-13 does)."""
    early, late = [], []
    for container, events in run.per_container.items():
        for ts, paused, episode, gap in fabric_oom.escalation_triggers(events):
            if paused < settings.OOM_ESCALATION_MILLIS:
                early.append((container, ts, paused))
            if episode != paused or gap >= fabric_oom.REGULAR_CHECK_MS:
                late.append((container, ts, f"paused {paused} ms, pause line: episode {episode} ms, {gap} ms before"))
    assert not early and not late and not run.events["pause_gave_up"], (
        f"escalations before {settings.OOM_ESCALATION_MILLIS} ms of pause: {early}; escalations that do not follow "
        f"their pause report at once: {late}; pauses that gave up: {run.events['pause_gave_up']}\n{run.summary}")


def test_executors_stay_in_the_cluster(run):
    """F-05: Executors stay registered during the run. A node that left after a fabric OOM, or with nothing in the
    logs explaining it, is the product; one that left with its ZooKeeper session is the stand and belongs to
    test_the_stand_held_through_the_run."""
    gone = [loss for loss in fabric_oom.node_losses(run.events) if loss[2] != "stand"]
    assert not gone, f"nodes left the cluster during the run: {gone}\n{run.summary}"


@pytest.mark.skipif(not settings.OOM_INNOCENT, reason="the small query runs only with OOM_INNOCENT=1")
def test_innocent_query_completes(run):
    """F-07: A small query next to the heavy ones survives."""
    assert run.innocent.state == "COMPLETED", f"the small query failed: {run.innocent.state}\n{run.summary}"


@pytest.mark.skipif(not settings.OOM_MAX_QUERY_SECONDS, reason="this run has no time limit (OOM_MAX_QUERY_SECONDS=0)")
def test_no_query_takes_longer_than_the_run_allows(run):
    """Run rule of the plan, not a case: every query of a verification run is cancelled after OOM_MAX_QUERY_SECONDS.
    Spilling instead of failing is the fix working, but only while the answer still arrives in time. A failure here is
    a failure on the limit: the queries it names were cancelled, not failed by the product, and whether they would ever
    have answered is what the run without a limit measures (P-05)."""
    assert not run.cut, (f"the run was cut off by its time limit: {len(run.cut)} queries did not answer within "
                         f"{settings.OOM_MAX_QUERY_SECONDS}s {run.cut}\n{run.summary}")


@pytest.mark.skipif(bool(settings.OOM_MAX_QUERY_SECONDS), reason="the queries are cut off by the time limit of the run")
def test_every_query_of_the_workload_is_served(run):
    """P-05: Every query is served when given the time. The fix works when a query under memory pressure
    spills and answers instead of being lost. This is the one criterion that needs the whole run, however long it
    takes, so it runs without a time limit and on its own."""
    lost = sorted(o.job for o in run.outcomes if o.state != "COMPLETED")
    assert not lost, f"{len(lost)} queries of the workload were never served: {lost}\n{run.summary}"
