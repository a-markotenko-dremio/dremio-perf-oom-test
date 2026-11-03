"""
Fabric direct-memory OOM reproduction (DX-127946): the workload of fabric_oom_repro.workload on the two-host stand of
scripts/fabric_oom_repro/setup_fabric_oom_stand.sh. The run passes when the bug reproduced: the baseline of an unfixed
build (F-01), and the configurations of the fixed build where the bug must still reproduce, both changes off (F-10),
escalation on without the read pause (F-22), and the `factor` measurement (F-16). The test cases are in test-cases/
of the QA repository; options: OOM_* in settings.py.

Run: scripts/fabric_oom_repro/run_fabric_oom_repro.sh
"""
from collections import namedtuple

import pytest

from fabric_oom_repro import fabric_oom
from fabric_oom_repro.logs import events_added_by
from fabric_oom_repro.workload import describe, run_workload

Run = namedtuple("Run", "events summary")


@pytest.fixture(scope="module")
def run(dremio, tables, system_options, containers):
    """The workload, with the events it added to the logs of all containers merged in time order."""
    (outcomes, _), per_container = events_added_by(containers, lambda: run_workload(dremio))
    summary = f"{describe(system_options, outcomes)}\n{fabric_oom.summarize(per_container)}"
    print("\n" + summary)
    return Run(fabric_oom.merge(per_container), summary)


def test_reproduce_fabric_oom(run):
    """F-01: The bug reproduces on the unfixed build. The same run is F-10, F-16 and F-22 by its configuration."""
    assert run.events["fabric_oom"], f"fabric OOM not reproduced\n{run.summary}"


def test_no_read_pause_and_no_escalation(run):
    """F-10, F-22: without the read pause nothing pauses and nothing escalates (the escalation acts only on the
    pause's reports), so these runs look like the unfixed build in the log too."""
    assert not run.events["read_pause"] and not run.events["escalation"], (
        f"the read pause or the escalation acted in a run where it was off\n{run.summary}")
