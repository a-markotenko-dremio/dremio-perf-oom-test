"""Fixtures of the fabric OOM tests: the system options of a run, the data set and its tables, the containers and what
they run."""
import pytest

import settings
from dremio_client import sql_value
from fabric_oom_repro.generate_oom_data import TABLES
from fabric_oom_repro.stand import stand_of
from fabric_oom_repro.tables import register
from fabric_oom_repro.workload import wait_until_ready


@pytest.fixture(scope="module")
def system_options(dremio):
    """System options of the run (every job is its own session, so ALTER SESSION would not reach the query)."""
    # The result cache is left as the stand has it: switching it off stopped the bug from reproducing (7 of 7 runs
    # with it on 2026-10-30, 0 of 4 with it off). The queries are not answered from it either, because every run sends
    # them with its own marker (fabric_oom_repro.workload.marked).
    options = {"planner.width.max_per_node": settings.OOM_WIDTH}
    if settings.OOM_RESERVE_PCT is not None:
        options["exec.spillable.operators.pct_free_memory_watermark"] = float(settings.OOM_RESERVE_PCT)
    if settings.OOM_ESCALATION is not None:  # the options of PR #30766; an unfixed build rejects them
        options["exec.spillable.operators.direct_escalation.enabled"] = settings.OOM_ESCALATION
        options["exec.spillable.operators.direct_escalation.millis"] = settings.OOM_ESCALATION_MILLIS
    for name, value in options.items():
        dremio.run_sql(f'ALTER SYSTEM SET "{name}" = {sql_value(value)}')
    yield options
    for name in options:
        dremio.run_sql(f'ALTER SYSTEM RESET "{name}"')


@pytest.fixture(scope="session")
def oom_data():
    """The directory of the data set (OOM_DATA): the input every run of the repro is tied to."""
    if settings.OOM_DATA is None:
        pytest.fail("OOM_DATA is not set: the directory of the data set (TestCaseData and TestSuiteInfo of "
                    "fabric_oom_repro.generate_oom_data); on the stand scripts/fabric_oom_repro/env.sh sets it")
    if not all((settings.OOM_DATA / name).is_dir() for name in TABLES):
        pytest.fail(f"OOM_DATA {settings.OOM_DATA} has no {' and '.join(TABLES)}: generate it with fabric_oom_repro.generate_oom_data")
    return settings.OOM_DATA


@pytest.fixture(scope="session")
def containers():
    """The containers whose logs the run is read from (OOM_CONTAINERS)."""
    if settings.OOM_CONTAINERS is None:
        pytest.fail("OOM_CONTAINERS is not set: the containers of the stand, host:container for the other host; "
                    "on the stand scripts/fabric_oom_repro/env.sh finds them")
    return settings.OOM_CONTAINERS


@pytest.fixture(scope="session")
def stand(containers):
    """What the run is on: the package of every container and the commit of the tests, for the run summary."""
    return stand_of(containers)


@pytest.fixture(scope="module")
def tables(dremio, oom_data):
    """The tables of the data set registered in Dremio."""
    register(dremio, settings.OOM_SOURCE, oom_data)


@pytest.fixture(scope="module")
def stand_ready(dremio, tables):
    """The stand answers the probe query before the workload starts (F-02): a stand that does not makes the run an
    error, not a verdict on the product."""
    probes = wait_until_ready(dremio)
    print(f"\nprobes before the run: {[f'{p.state} after {p.seconds:.0f}s' for p in probes]}")
