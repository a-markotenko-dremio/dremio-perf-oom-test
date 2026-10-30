"""Fixtures of the fabric OOM tests: the system options of a run, the data set and its tables, the containers."""
import pytest

import settings
from dremio_client import sql_value
from fabric_oom_repro.generate_oom_data import TABLES
from fabric_oom_repro.tables import register


@pytest.fixture(scope="module")
def system_options(dremio):
    """System options of the run (every job is its own session, so ALTER SESSION would not reach the query)."""
    # The result cache answers a repeat of the same query from the run before in a second (TTL 24 h, seen on
    # 2026-10-30: three sessions measured nothing), so the queries of the workload are executed every time.
    options = {"planner.width.max_per_node": settings.OOM_WIDTH, "dremio.results_cache_rest_enabled": False}
    if settings.OOM_RESERVE_PCT is not None:
        options["exec.spillable.operators.pct_free_memory_watermark"] = float(settings.OOM_RESERVE_PCT)
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


@pytest.fixture(scope="module")
def tables(dremio, oom_data):
    """The tables of the data set registered in Dremio."""
    register(dremio, settings.OOM_SOURCE, oom_data)
