"""
Verification of the fabric direct-memory OOM fixes (DX-127978, DX-127979; test plan fabric-oom-test-plan.md): the
workload of the repro runs once per module, with a small query next to it, and every test checks one criterion of the
plan on the events the run added to the logs. On an unfixed build the tests of TC-02, TC-04 and TC-05 fail.

TC-02 no fabric OOM, no query failed because of one; TC-04 the small query completes; TC-05 one failure does not take
the node down; TC-06 the arbiter acts before memory runs out; TC-10 no executor left the cluster. TC-03 is the same
module run with the default reserve (no OOM_RESERVE_PCT). TC-04 needs its own run with OOM_INNOCENT=1: with the small
query the fabric OOM did not reproduce, so the other criteria are checked without it.

Run: scripts/fabric_oom_repro/run_fabric_oom_func.sh
"""
from collections import Counter, namedtuple

import pytest

import settings
from fabric_oom_repro import fabric_oom
from fabric_oom_repro.logs import log_lines
from fabric_oom_repro.workload import INNOCENT, describe, run_workload

Run = namedtuple("Run", "outcomes innocent events summary")


@pytest.fixture(scope="module")
def run(dremio, tables, system_options, containers):
    """The workload, with the events it added to the logs of all containers merged in time order."""
    before = {c: len(log_lines(c, fabric_oom.PATTERN)) for c in containers}
    outcomes, innocent = run_workload(dremio, INNOCENT if settings.OOM_INNOCENT else None)
    events = fabric_oom.merge({c: fabric_oom.parse(log_lines(c, fabric_oom.PATTERN)[n:]) for c, n in before.items()})
    summary = (f"{describe(system_options, outcomes)}\n"
               f"innocent query: {f'{innocent.state} after {innocent.seconds:.0f}s' if innocent else 'not run'}\n"
               f"events: {({name: len(e) for name, e in events.items()})}, failures by cause: "
               f"{dict(Counter(cause or 'not named' for *_, cause in events['job_failed']))}")
    print("\n" + summary)
    return Run(outcomes, innocent, events, summary)


def test_run_put_memory_under_pressure(run):
    """Without shrink requests the run did not stress the node and the other tests prove nothing."""
    assert run.events["shrink"], f"no memory pressure\n{run.summary}"


def test_no_fabric_oom(run):
    assert not run.events["fabric_oom"], f"fabric OOM happened: {run.events['fabric_oom']}\n{run.summary}"


def test_no_query_failed_because_of_a_fabric_oom(run):
    caused = fabric_oom.failures_after_fabric_oom(run.events)
    assert not caused, f"jobs failed right after a fabric OOM: {caused}\n{run.summary}"


@pytest.mark.skipif(not settings.OOM_INNOCENT, reason="the small query runs only with OOM_INNOCENT=1")
def test_innocent_query_completes(run):
    assert run.innocent.state == "COMPLETED", f"the small query failed: {run.innocent.state}\n{run.summary}"


def test_one_failure_does_not_take_the_node_down(run):
    most = fabric_oom.most_failures_in_one_second(run.events)
    assert most <= 1, f"{most} jobs failed in the same second (the node went down)\n{run.summary}"


def test_arbiter_acts_before_memory_runs_out(run):
    """If memory ran out, an arbiter cancellation came first: the escalation of DX-127978."""
    oom, cancel = run.events["fabric_oom"], fabric_oom.arbiter_cancellations(run.events)
    assert not oom or (cancel and cancel[0] < oom[0][0]), f"fabric OOM before any arbiter cancellation\n{run.summary}"


def test_executors_stay_in_the_cluster(run):
    gone = run.events["node_unregistered"]
    assert not gone, f"nodes left the cluster during the run: {gone}\n{run.summary}"
