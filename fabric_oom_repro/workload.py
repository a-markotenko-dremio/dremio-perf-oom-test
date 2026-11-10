"""
The workload of the fabric OOM repro (DX-127946): the 8 aggregation and join queries of the master repro (DX-127207) on
TestCaseData / TestSuiteInfo run at the same time, optionally with one small query started next to them.
"""
import re
import time
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor

import settings
from dremio_client import JobFailed, JobTimeout
from fabric_oom_repro.generate_oom_data import TABLES
from fabric_oom_repro.progress import progress

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
# The probe before a run: the stand must answer INNOCENT within PROBE_LIMIT, retried every PROBE_RETRY seconds for up to
# READY_WAIT. An executor still cancelling the queries of the session before answers no fragment start for minutes
# (`Exceeded timeout (30000) while waiting after sending work fragments to remote nodes`: three sessions of 2026-11-04
# lost every query to that, not to memory). Next to the 8 queries INNOCENT answered in 53-79 s, alone it takes seconds.
PROBE_LIMIT = 120
PROBE_RETRY = 30
READY_WAIT = 600
HEARTBEAT = 60  # seconds between the progress lines of a run that is still waiting for its queries

Outcome = namedtuple("Outcome", "job state seconds")  # state: COMPLETED, or the first line of the error
# The errors a memory failure of the run gives a query: the OOM of the arbiter or of an operator, and the
# ChannelClosedException and the lost executor of a node that went down. Another class (a broken input file, a
# planning error) or a timeout is not about memory and says nothing about the bug.
MEMORY_FAILURE = re.compile("OUT_OF_MEMORY ERROR|SYSTEM ERROR: ChannelClosedException|compute nodes became unavailable")
# The state of a query the run itself cut off after OOM_MAX_QUERY_SECONDS: the product did not fail it, the run ran out
# of patience, so it is neither a memory failure nor a dirty run (the test of the time limit reports them, the
# other tests ignore them).
OVER_THE_LIMIT = "OVER THE LIMIT: the query did not return within the time the run allows"


def describe(stand, system_options, outcomes):
    """The first lines of a run summary: what the run was on (the commit of the tests, the package of every container,
    the data set, the system options) and how the queries ended."""
    return (f"commit={stand.commit}\nbuild={stand.packages}\ndata set={settings.OOM_DATA}\nsystem options={system_options}\n"
            f"outcomes: {[f'{o.state} after {o.seconds:.0f}s' for o in outcomes]}")


def slowest_completed(outcomes):
    """The query that took longest and still returned its result: what surviving the pressure costs."""
    return max((o for o in outcomes if o.state == "COMPLETED"), key=lambda o: o.seconds, default=None)


def unrelated_failures(outcomes):
    """The jobs of the run that failed for a reason that is not a memory failure: the run is dirty, they prove nothing."""
    return sorted(o.job for o in outcomes
                  if o.state not in ("COMPLETED", OVER_THE_LIMIT) and not MEMORY_FAILURE.search(o.state))


def over_the_limit(outcomes):
    """The jobs the run cut off before they could answer."""
    return sorted(o.job for o in outcomes if o.state == OVER_THE_LIMIT)


def marked(sql, marker):
    """The query with the marker of its run in front of its result: the same text is then never sent twice, so the
    result cache cannot answer a run from the run before. The cache stays on because it is part of what reproduces the
    bug: with it the fabric OOM happened in 7 of 7 runs of 2026-10-30, without it in 0 of 4 (the same workload then
    spilled and every query was served, see the Risks of test-plan-fabric-direct-memory-oom.md in the QA repository). Every query of the run returns one row, so the
    wrapper costs nothing."""
    return f"SELECT '{marker}' AS run, * FROM ({sql}) m"


def run_query(dremio, sql, limit=None, name="query"):
    """Runs the query and reports how it ended as soon as it does: the outcomes of the others are printed only when
    the whole run is over."""
    started = time.time()
    try:
        job, state = dremio.run_sql(sql, timeout=limit)["id"], "COMPLETED"
    except JobTimeout as e:
        job, state = str(e).split()[1], OVER_THE_LIMIT
    except JobFailed as e:
        job, state = str(e).split()[1], str(e).splitlines()[0]
    outcome = Outcome(job, state, time.time() - started)
    progress(f"{name} {job}: {state[:120]} after {outcome.seconds:.0f}s")
    return outcome


def new_marker():
    """What makes the queries of one run unique (marked)."""
    return time.strftime("%Y%m%d-%H%M%S")


class StandNotReady(Exception):
    """The stand did not answer the probe query: the run cannot start, so it ends in an error, not a verdict."""


def wait_until_ready(dremio, now=time.time, sleep=time.sleep):
    """The probe queries sent until one completes within PROBE_LIMIT seconds; raises StandNotReady when READY_WAIT
    seconds pass first. Every probe carries its own marker, so the result cache answers none of them."""
    deadline, marker, probes = now() + READY_WAIT, new_marker(), []
    while True:
        probes.append(run_query(dremio, marked(INNOCENT, f"{marker}-probe-{len(probes)}"), PROBE_LIMIT,
                                f"probe {len(probes) + 1}"))
        if probes[-1].state == "COMPLETED":
            return probes
        if now() > deadline:
            raise StandNotReady(f"the stand did not answer the probe query within {READY_WAIT}s, the run cannot start: "
                                f"{[f'{p.state} after {p.seconds:.0f}s' for p in probes]}")
        sleep(PROBE_RETRY)


def wait_for(queries, sleep=time.sleep, now=time.time):
    """Waits for the queries, telling every HEARTBEAT seconds how many are still running: without it a run of an hour
    prints nothing between its first and its last query."""
    started = now()
    while not all(q.done() for q in queries):
        sleep(HEARTBEAT)
        progress(f"{sum(q.done() for q in queries)} of {len(queries)} queries finished, "
                 f"{(now() - started) / 60:.0f} min gone")


def run_workload(dremio, innocent=False, limit=None):
    """Runs QUERIES at the same time and, with `innocent`, INNOCENT INNOCENT_DELAY seconds later; their outcomes. The
    queries carry the marker of this run, so none of them is answered from the result cache. A query that takes longer
    than `limit` seconds is cancelled and ends OVER_THE_LIMIT; without a limit it runs to its end."""
    marker = new_marker()
    progress(f"sending {len(QUERIES)} queries, limit of a query {f'{limit}s' if limit else 'none'}")
    with ThreadPoolExecutor(len(QUERIES)) as pool:
        heavy = [pool.submit(run_query, dremio, marked(sql, marker), limit, f"query {i + 1}/{len(QUERIES)}")
                 for i, sql in enumerate(QUERIES)]
        small = None
        if innocent:
            time.sleep(INNOCENT_DELAY)
            small = run_query(dremio, marked(INNOCENT, marker), limit, "small query")
        wait_for(heavy)
    return [f.result() for f in heavy], small
