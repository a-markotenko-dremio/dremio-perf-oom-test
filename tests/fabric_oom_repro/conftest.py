"""Fixtures of the fabric OOM tests: the system options of a run and the tables of the repro."""
import pytest

import defaults
import settings
from fabric_oom_repro.generate_oom_data import TABLES, YEARS


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


@pytest.fixture(scope="module")
def tables(dremio):
    """The NAS source over the generated tables, with both folders promoted to Parquet tables (one folder per year)."""
    dremio.ensure_nas_source(settings.OOM_SOURCE, settings.STORAGE_PATH / defaults.OOM_REPRO_SUBDIR)
    for name in TABLES:
        if dremio.entity_type([settings.OOM_SOURCE, name]) != "dataset":
            dremio.promote_folder([settings.OOM_SOURCE, name])
        years = {row["dir0"] for row in dremio.query_rows(f'SELECT DISTINCT dir0 FROM "{settings.OOM_SOURCE}".{name}')}
        assert years == set(YEARS), f"{name}: unexpected years {sorted(years)}"
