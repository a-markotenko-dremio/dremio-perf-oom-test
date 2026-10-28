"""Fixtures of the fabric OOM tests: the system options of a run, the data set and its tables."""
import pytest

import settings
from fabric_oom_repro.generate_oom_data import TABLES
from fabric_oom_repro.tables import register


@pytest.fixture(scope="module")
def system_options(dremio):
    """System options of the run (every job is its own session, so ALTER SESSION would not reach the query)."""
    options = {"planner.width.max_per_node": settings.OOM_WIDTH}
    if settings.OOM_RESERVE_PCT is not None:
        options["exec.spillable.operators.pct_free_memory_watermark"] = float(settings.OOM_RESERVE_PCT)
    for name, value in options.items():
        dremio.run_sql(f'ALTER SYSTEM SET "{name}" = {value}')
    yield options
    for name in options:
        dremio.run_sql(f'ALTER SYSTEM RESET "{name}"')


@pytest.fixture(scope="session")
def oom_data(storage_path):
    """The directory of the data set (OOM_DATA under STORAGE_PATH): the input every run of the repro is tied to."""
    if settings.OOM_DATA is None:
        pytest.fail("OOM_DATA is not set: the data set of the repro, a directory of STORAGE_PATH with TestCaseData and "
                    "TestSuiteInfo (setup_fabric_oom_stand.sh generates the one of the stand)")
    path = storage_path / settings.OOM_DATA
    if not all((path / name).is_dir() for name in TABLES):
        pytest.fail(f"OOM_DATA {path} has no {' and '.join(TABLES)}: generate it with fabric_oom_repro.generate_oom_data")
    return path


@pytest.fixture(scope="module")
def tables(dremio, oom_data):
    """The tables of the data set registered in Dremio."""
    register(dremio, settings.OOM_SOURCE, oom_data)
