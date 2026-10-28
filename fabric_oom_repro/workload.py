"""
The workload of the fabric OOM repro (DX-127946): the 8 aggregation and join queries of the master repro (DX-127207) on
TestCaseData / TestSuiteInfo run at the same time, optionally with one small query started next to them.
"""
import time
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor

import settings
from dremio_client import JobFailed, JobTimeout
from fabric_oom_repro.generate_oom_data import TABLES

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
INNOCENT = f"SELECT COUNT(*) AS n FROM {TEST_CASE_DATA} WHERE dir0 = '2024'"  # a small query next to the 8
INNOCENT_DELAY = 30  # seconds after the 8 queries start

Outcome = namedtuple("Outcome", "job state seconds")  # state: COMPLETED, or the first line of the error


def describe(system_options, outcomes):
    """The first lines of a run summary: what the run was tied to (data set, system options) and how the queries ended."""
    return (f"data set={settings.OOM_DATA}\nsystem options={system_options}\n"
            f"outcomes: {[f'{o.state} after {o.seconds:.0f}s' for o in outcomes]}")


def run_query(dremio, sql):
    started = time.time()
    try:
        job, state = dremio.run_sql(sql)["id"], "COMPLETED"
    except (JobFailed, JobTimeout) as e:
        job, state = str(e).split()[1], str(e).splitlines()[0]
    return Outcome(job, state, time.time() - started)


def run_workload(dremio, innocent=None):
    """Runs QUERIES at the same time and, if given, `innocent` INNOCENT_DELAY seconds later; their outcomes."""
    with ThreadPoolExecutor(len(QUERIES)) as pool:
        heavy = [pool.submit(run_query, dremio, sql) for sql in QUERIES]
        small = None
        if innocent:
            time.sleep(INNOCENT_DELAY)
            small = run_query(dremio, innocent)
    return [f.result() for f in heavy], small
