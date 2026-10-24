"""Offline tests of generate_oom_data.py: the tables of the fabric OOM repro at a tiny scale."""
import duckdb
import pytest

from fabric_oom_repro import generate_oom_data as g

# one build per year: FULL_SCALE_ROWS * scale / 3 years / (SUITES * TESTS) = 1
ONE_BUILD_SCALE = 3 * g.SUITES * g.TESTS / g.FULL_SCALE_ROWS


def rows(path):
    return duckdb.connect().execute(f"SELECT count(*) FROM read_parquet('{path}/*.parquet')").fetchone()[0]


def test_each_table_has_a_folder_per_year_with_the_rows_of_its_builds(tmp_path):
    counts = g.generate(tmp_path, ONE_BUILD_SCALE, log=lambda *_: None)
    assert counts == {f"{table}/{year}": expected
                      for table, expected in (("TestCaseData", g.SUITES * g.TESTS), ("TestSuiteInfo", g.SUITES))
                      for year in g.YEARS}
    for year in g.YEARS:
        assert rows(tmp_path / "TestCaseData" / year) == g.SUITES * g.TESTS


def test_the_queries_columns_exist_and_builds_are_named_per_year(tmp_path):
    g.generate(tmp_path, ONE_BUILD_SCALE, log=lambda *_: None)
    con = duckdb.connect()
    columns = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{tmp_path}/TestCaseData/2025/*.parquet')").fetchall()}
    assert columns == {"BuildUniqueId", "TestName", "ClassName", "FullName", "Duration", "Status", "ErrorDetails",
                       "ProjectName", "SuiteName"}
    build = con.execute(f"SELECT DISTINCT BuildUniqueId FROM read_parquet('{tmp_path}/TestSuiteInfo/2025/*.parquet')").fetchall()
    assert build == [("build-2025-0000000",)]


def test_an_existing_table_directory_is_not_overwritten(tmp_path):
    (tmp_path / "TestCaseData" / "2024").mkdir(parents=True)
    with pytest.raises(SystemExit, match="already exists"):
        g.generate(tmp_path, ONE_BUILD_SCALE, log=lambda *_: None)


def test_a_scale_without_builds_is_refused(tmp_path):
    with pytest.raises(SystemExit, match="gives no builds"):
        g.generate(tmp_path, 1e-9, log=lambda *_: None)
