"""
Verification of the fabric direct-memory OOM fixes (DX-127978, DX-127979; test plan fabric-oom-test-plan.md): the
workload of the repro runs once per module, with a small query next to it, and every test checks one criterion of the
plan on the events the run added to the logs. On an unfixed build the tests of TC-02 and TC-05 fail (27.0.0, runs of
2026-10-30; TC-04 passed there: the small query outlived an OOM that failed the eight).

TC-02 no fabric OOM, no query failed because of one; TC-04 the small query completes; TC-05 one failure does not take
the node down; TC-06 the arbiter acts before memory runs out; TC-10 no executor left the cluster. TC-03 is the same
module run with the default reserve (no OOM_RESERVE_PCT). TC-04 needs its own run with OOM_INNOCENT=1: with the small
query the fabric OOM did not reproduce, so the other criteria are checked without it.

TC-11 is the cost of surviving: a query the arbiter saved from the OOM is of no use to the user if it answers after
half an hour, so OOM_MAX_QUERY_SECONDS is the time a query of the run may take. It is also what keeps a run short: a
query that reaches the limit is cancelled, and TC-11 fails the run on the limit, not on the product. TC-12 is the other
half of it and needs OOM_MAX_QUERY_SECONDS=0: with no limit the queries run to their end and the run says whether the
fix works at all (every query of the workload is served), at the price of an hour
(scripts/fabric_oom_repro/run_fabric_oom_feature.sh).

TC-05 and TC-10 see the same picture when it is the stand that broke and not the product: an executor that lost its
ZooKeeper session leaves the cluster and takes its queries down with it. They judge the product only, and
test_the_stand_held_through_the_run reports the rest; a run it fails gives no verdict on those two and is repeated.

Run: scripts/fabric_oom_repro/run_fabric_oom_func.sh
"""
from collections import Counter, namedtuple

import pytest

import settings
from fabric_oom_repro import fabric_oom
from fabric_oom_repro.logs import log_lines
from fabric_oom_repro.workload import (INNOCENT, describe, over_the_limit, run_workload, slowest_completed,
                                       unrelated_failures)

Run = namedtuple("Run", "outcomes innocent events unrelated cut summary")


@pytest.fixture(scope="module")
def run(dremio, tables, system_options, containers):
    """The workload, with the events it added to the logs of all containers merged in time order."""
    before = {c: len(log_lines(c, fabric_oom.PATTERN)) for c in containers}
    outcomes, innocent = run_workload(dremio, INNOCENT if settings.OOM_INNOCENT else None,
                                      settings.OOM_MAX_QUERY_SECONDS or None)
    events = fabric_oom.merge({c: fabric_oom.parse(log_lines(c, fabric_oom.PATTERN)[n:]) for c, n in before.items()})
    unrelated, cut = unrelated_failures(outcomes), over_the_limit(outcomes)
    summary = (f"{describe(system_options, outcomes)}\n"
               f"innocent query: {f'{innocent.state} after {innocent.seconds:.0f}s' if innocent else 'not run'}\n"
               f"events: {({name: len(e) for name, e in events.items()})}, failures by cause: "
               f"{dict(Counter(cause or 'not named' for *_, cause in events['job_failed']))}\n"
               f"node losses: {fabric_oom.node_losses(events)}, jobs failed for another reason: {unrelated}\n"
               f"time limit of a query: {f'{settings.OOM_MAX_QUERY_SECONDS}s' if settings.OOM_MAX_QUERY_SECONDS else 'none'}, "
               f"queries it cut off: {cut}\n"
               f"slowest query that was served: {f'{slowest.seconds:.0f}s' if (slowest := slowest_completed(outcomes)) else 'none'}")
    print("\n" + summary)
    return Run(outcomes, innocent, events, unrelated, cut, summary)


def test_run_put_memory_under_pressure(run):
    """Without shrink requests the run did not stress the node and the other tests prove nothing."""
    assert run.events["shrink"], f"no memory pressure\n{run.summary}"


def test_no_fabric_oom(run):
    assert not run.events["fabric_oom"], f"fabric OOM happened: {run.events['fabric_oom']}\n{run.summary}"


def test_no_query_failed_because_of_a_fabric_oom(run):
    caused = [job for job in fabric_oom.failures_after_fabric_oom(run.events) if job not in run.cut]
    assert not caused, f"jobs failed right after a fabric OOM: {caused}\n{run.summary}"


@pytest.mark.skipif(not settings.OOM_INNOCENT, reason="the small query runs only with OOM_INNOCENT=1")
def test_innocent_query_completes(run):
    assert run.innocent.state == "COMPLETED", f"the small query failed: {run.innocent.state}\n{run.summary}"


def test_the_stand_held_through_the_run(run):
    """Without this the run proves nothing either way: a node that left on a lost ZooKeeper session and a failure that
    is not about memory give the picture of TC-05 and TC-10 without the product doing anything wrong."""
    stand = [loss for loss in fabric_oom.node_losses(run.events) if loss[2] == "stand"]
    assert not stand and not run.unrelated, (f"the stand broke during the run, repeat it: nodes that left with their "
                                             f"ZooKeeper session {stand}, jobs failed for another reason "
                                             f"{run.unrelated}\n{run.summary}")


def test_one_failure_does_not_take_the_node_down(run):
    """The bug fails every fragment of a node at once, so its signature is many jobs failing in the same second. The
    jobs the stand took down are not that signature, and neither are the ones the run cancelled on its time limit
    (they too end in one second, all at the limit): both are counted out here and reported by their own test."""
    ignore = set(run.unrelated) | set(run.cut) | set(fabric_oom.failures_of_the_stand(run.events))
    most = fabric_oom.most_failures_in_one_second(run.events, ignore)
    assert most <= 1, f"{most} jobs failed in the same second (the node went down)\n{run.summary}"


@pytest.mark.skipif(not settings.OOM_MAX_QUERY_SECONDS, reason="this run has no time limit (OOM_MAX_QUERY_SECONDS=0)")
def test_no_query_takes_longer_than_the_run_allows(run):
    """TC-11: spilling instead of failing is the fix working, but only while the answer still arrives in time. A
    failure here is a failure on the time limit: the queries it names were cancelled, not failed by the product, and
    whether they would ever have answered is what the run without a limit (TC-12) measures."""
    assert not run.cut, (f"the run was cut off by its time limit: {len(run.cut)} queries did not answer within "
                         f"{settings.OOM_MAX_QUERY_SECONDS}s {run.cut}\n{run.summary}")


@pytest.mark.skipif(bool(settings.OOM_MAX_QUERY_SECONDS), reason="the queries are cut off by the time limit of the run")
def test_every_query_of_the_workload_is_served(run):
    """TC-12: the fix works when a query under memory pressure spills and answers instead of being lost. This is the
    one criterion that needs the whole run, however long it takes, so it runs without a time limit and on its own."""
    lost = sorted(o.job for o in run.outcomes if o.state != "COMPLETED")
    assert not lost, f"{len(lost)} queries of the workload were never served: {lost}\n{run.summary}"


def test_arbiter_acts_before_memory_runs_out(run):
    """If memory ran out, an arbiter cancellation came first: the escalation of DX-127978."""
    oom, cancel = run.events["fabric_oom"], fabric_oom.arbiter_cancellations(run.events)
    assert not oom or (cancel and cancel[0] < oom[0][0]), f"fabric OOM before any arbiter cancellation\n{run.summary}"


def test_executors_stay_in_the_cluster(run):
    """A node that left after a fabric OOM, or with nothing in the logs explaining it, is the product; one that left
    with its ZooKeeper session is the stand and belongs to the test above."""
    gone = [loss for loss in fabric_oom.node_losses(run.events) if loss[2] != "stand"]
    assert not gone, f"nodes left the cluster during the run: {gone}\n{run.summary}"
