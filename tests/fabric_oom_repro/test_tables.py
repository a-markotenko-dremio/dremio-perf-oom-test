"""Offline tests of fabric_oom_repro.tables: the registration of a data set on a client that records its calls."""
from pathlib import Path

import pytest

import settings
from dremio_client import JobFailed
from fabric_oom_repro import tables, workload
from fabric_oom_repro.generate_oom_data import TABLES, YEARS
from fabric_oom_repro.workload import Outcome

SOURCE = "OOM Repro"
DATA = Path("/mnt/ubuntu-var/dremio/d25-2-0-j21-14G-4cpu/qa-oom-repro")


class FakeDremio:
    def __init__(self, repointed, promoted, years=YEARS):
        self.repointed, self.promoted, self.years, self.calls = repointed, set(promoted), years, []
        self.failures_left, self.failure = 0, None

    def fail_times(self, times, error):
        """The next `times` queries fail with `error`, as the stand does while it is still busy."""
        self.failures_left, self.failure = times, error

    def ensure_nas_source(self, source, path):
        self.calls.append(("source", source, path))
        return self.repointed

    def entity_type(self, path):
        return "dataset" if path[1] in self.promoted else "folder"

    def unpromote_table(self, path):
        self.calls.append(("unpromote", path[1]))
        self.promoted.discard(path[1])

    def promote_folder(self, path):
        self.calls.append(("promote", path[1]))
        self.promoted.add(path[1])

    def query_rows(self, sql):
        self.calls.append(("query", sql))
        if self.failures_left:
            self.failures_left -= 1
            raise self.failure
        return [{"dir0": year} for year in self.years]


def test_tables_of_a_source_already_on_the_data_set_are_only_read():
    dremio = FakeDremio(repointed=False, promoted=TABLES)
    tables.register(dremio, SOURCE, DATA)
    assert dremio.calls == [("source", SOURCE, DATA)] + [
        ("query", f'SELECT DISTINCT dir0 FROM "{SOURCE}".{name}') for name in TABLES]


def test_tables_are_promoted_again_when_the_source_moved_to_another_data_set():
    dremio = FakeDremio(repointed=True, promoted=TABLES)
    tables.register(dremio, SOURCE, DATA)
    assert [c for c in dremio.calls if c[0] != "query"] == [("source", SOURCE, DATA)] + [
        call for name in TABLES for call in (("unpromote", name), ("promote", name))]


def test_missing_tables_of_an_unchanged_source_are_promoted():
    dremio = FakeDremio(repointed=False, promoted=["TestCaseData"])
    tables.register(dremio, SOURCE, DATA)
    assert [c for c in dremio.calls if c[0] in ("unpromote", "promote")] == [("promote", "TestSuiteInfo")]


def test_registration_waits_for_an_executor_still_busy_with_the_run_before():
    """The error of 2026-10-30, 16:26: the session started while the cancelled queries of the one before still ran."""
    dremio = FakeDremio(repointed=False, promoted=TABLES)
    dremio.fail_times(2, JobFailed("Job 151ae685-a1c6-d0e5-b116-d0c925142700 FAILED: Exceeded timeout (30000) while "
                                   "waiting after sending work fragments to remote nodes. Sent 1 and only heard "
                                   "response back from 0 nodes"))
    tables.register(dremio, SOURCE, DATA, poll=0)
    assert dremio.failures_left == 0 and ("query", f'SELECT DISTINCT dir0 FROM "{SOURCE}".TestSuiteInfo') in dremio.calls


def test_registration_does_not_wait_for_an_error_of_its_own():
    dremio = FakeDremio(repointed=False, promoted=TABLES)
    dremio.fail_times(1, JobFailed("Job 151ae685-a1c6-d0e5-b116-d0c925142700 FAILED: DATA_READ ERROR: Snappy "
                                   "decompression failed on column TestName::varchar"))
    with pytest.raises(JobFailed, match="Snappy"):
        tables.register(dremio, SOURCE, DATA, poll=0)


def test_registration_gives_up_on_an_executor_that_stays_busy():
    dremio = FakeDremio(repointed=False, promoted=TABLES)
    dremio.fail_times(99, JobFailed("Job 151ae685 FAILED: Exceeded timeout (30000) while waiting after sending work "
                                    "fragments to remote nodes. Sent 1 and only heard response back from 0 nodes"))
    with pytest.raises(JobFailed, match="Exceeded timeout"):
        tables.register(dremio, SOURCE, DATA, wait=0, poll=0)


def test_a_data_set_without_all_years_is_refused():
    with pytest.raises(AssertionError, match=r"TestCaseData of .*qa-oom-repro: unexpected years \['2024'\]"):
        tables.register(FakeDremio(repointed=False, promoted=TABLES, years=["2024"]), SOURCE, DATA)


def test_the_run_summary_names_the_data_set(monkeypatch):
    monkeypatch.setattr(settings, "OOM_DATA", "qa-oom-repro.baseline-20261023")
    outcomes = [Outcome("151da457-dbeb-64fc-6796-a924ab1a5c00", "COMPLETED", 685.4)]
    assert workload.describe({"planner.width.max_per_node": 24}, outcomes) == (
        "data set=qa-oom-repro.baseline-20261023\nsystem options={'planner.width.max_per_node': 24}\n"
        "outcomes: ['COMPLETED after 685s']")
