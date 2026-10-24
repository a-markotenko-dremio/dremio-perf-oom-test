"""
Fabric direct-memory OOM repro (DX-127946): the 8 aggregation and join queries of the master repro (DX-127207) run at
the same time on TestCaseData / TestSuiteInfo, scaled down to the two-host stand. The test passes when a Dremio log got
a fabric OOM line. Needs the stand of scripts/fabric_oom_repro/setup_fabric_oom_stand.sh; options: OOM_* in settings.py.

Run: scripts/fabric_oom_repro/run_fabric_oom_repro.sh

"""
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import defaults
import settings
from dremio_client import JobFailed, JobTimeout
from fabric_oom_repro.generate_oom_data import TABLES, YEARS
from fabric_oom_repro.logs import PATTERNS, log_counts

TEST_CASE_DATA, TEST_SUITE_INFO = (f'"{settings.OOM_SOURCE}".{name}' for name in TABLES)


def outer(year, inner, extra=""):
    return f"SELECT '{year}' AS yr, COUNT(*) AS grp, SUM(c) AS n{extra} FROM ({inner}) t"


def joined(year):
    return f"""
  FROM {TEST_CASE_DATA} tc
  JOIN {TEST_SUITE_INFO} ts ON tc.BuildUniqueId = ts.BuildUniqueId AND tc.SuiteName = ts.SuiteName AND ts.dir0 = '{year}'"""


def agg(year):
    return outer(year, f"""
  SELECT BuildUniqueId, TestName, COUNT(*) c, SUM(Duration) d, MAX(Status) s, MIN(ClassName) k, MAX(FullName) f
  FROM {TEST_CASE_DATA} WHERE dir0 = '{year}'
  GROUP BY BuildUniqueId, TestName""", ", SUM(d) AS dur")


def agg2(year):
    return outer(year, f"""
  SELECT BuildUniqueId, ClassName, TestName, COUNT(*) c, SUM(Duration) d, MAX(ErrorDetails) e, MAX(Status) s
  FROM {TEST_CASE_DATA} WHERE dir0 = '{year}'
  GROUP BY BuildUniqueId, ClassName, TestName""")


def join(year):
    return outer(year, f"""
  SELECT tc.BuildUniqueId, tc.ClassName, p.ProjectFullName, COUNT(*) c, SUM(tc.Duration + ts.Duration) d, MAX(tc.Status) s{joined(year)}
  JOIN (SELECT DISTINCT ProjectName, ProjectFullName FROM {TEST_SUITE_INFO} WHERE dir0 = '2025') p ON tc.ProjectName = p.ProjectName
  WHERE tc.dir0 = '{year}'
  GROUP BY tc.BuildUniqueId, tc.ClassName, p.ProjectFullName""")


def join2(year):
    return outer(year, f"""
  SELECT tc.BuildUniqueId, tc.TestName, COUNT(*) c, SUM(tc.Duration + ts.Duration) d, MAX(ts.TestCaseCount) m{joined(year)}
  WHERE tc.dir0 = '{year}'
  GROUP BY tc.BuildUniqueId, tc.TestName""")


QUERIES = [agg("2024"), agg("2025"), join("2024"), join("2025"),
           agg2("2026"), join2("2026"), agg2("2024"), join2("2025")]


def run_query(dremio, sql):
    """The outcome of one query: COMPLETED, or the first line of the error, with the time it took."""
    started = time.time()
    try:
        dremio.run_sql(sql)
        outcome = "COMPLETED"
    except (JobFailed, JobTimeout) as e:
        outcome = str(e).splitlines()[0]
    return f"{outcome} after {time.time() - started:.0f}s"


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


def test_reproduce_fabric_oom(dremio, tables, system_options):
    before = log_counts()
    with ThreadPoolExecutor(max_workers=len(QUERIES)) as pool:
        outcomes = list(pool.map(lambda sql: run_query(dremio, sql), QUERIES))
    delta = {c: {k: n - before[c][k] for k, n in counts.items()} for c, counts in log_counts().items()}
    summary = f"system options={system_options}\noutcomes: {outcomes}\nnew log lines per container: {delta}"
    print("\n" + summary)
    assert sum(d["fabric_oom"] for d in delta.values()) > 0, f"fabric OOM not reproduced\n{summary}"
