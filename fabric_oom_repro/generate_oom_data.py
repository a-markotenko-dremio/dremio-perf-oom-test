"""Generates the Parquet tables of the master fabric OOM repro of DX-127207, scaled down.

The repro runs 8 queries at once on TestCaseData (9.4 B rows, one folder per year: dir0 = 2024, 2025, 2026) and
TestSuiteInfo of the dremio-release data. The customer-like data is not available, so the two tables are generated
with the columns the 8 queries use:
    TestCaseData   BuildUniqueId, TestName, ClassName, FullName, Duration, Status, ErrorDetails, ProjectName, SuiteName
    TestSuiteInfo  BuildUniqueId, SuiteName, ProjectName, ProjectFullName, Duration, TestCaseCount
Both are written to <output_dir>/<table>/<year>/*.parquet, so that the folder name is the dir0 column.

--scale is the fraction of the 9.4 B rows (the memory of the repro was 7 x 96 GB; the scale of 1/57 matches 2 x 6 GB).
The rows per build are fixed: SUITES suites per build and TESTS tests per suite, so --scale changes the number of
builds. The GROUP BY BuildUniqueId, TestName of the queries then has about one group per TestCaseData row.

Usage: python -m fabric_oom_repro.generate_oom_data OUTPUT_DIR --scale 0.0175
"""
import argparse
import os
import sys

import duckdb

FULL_SCALE_ROWS = 9_400_000_000
YEARS = ("2024", "2025", "2026")
SUITES = 20
TESTS = 50
PROJECTS = 8
CLASSES = 40
FAILED_PERCENT = 5

# {builds} is filled in; every row is derived from the build number b, the suite number s and the test number t.
TEST_CASE_DATA = """
    SELECT BuildUniqueId, TestName, ClassName, ClassName || '.' || TestName AS FullName, Duration, Status,
           CASE WHEN Status = 'FAILED' THEN repeat('at com.dremio.Test.run(Test.java:42) ', 8) || TestName END AS ErrorDetails,
           ProjectName, SuiteName
    FROM (
        SELECT 'build-{year}-' || lpad(b::VARCHAR, 7, '0') AS BuildUniqueId,
               'test_' || md5(b::VARCHAR || '-' || s::VARCHAR || '-' || t::VARCHAR) AS TestName,
               'com.dremio.suite' || s::VARCHAR || '.Class' || (hash(b, s, t) % {classes})::VARCHAR AS ClassName,
               (hash(t, s, b) % 600000) / 1000.0 AS Duration,
               CASE WHEN hash(s, b, t) % 100 < {failed} THEN 'FAILED' ELSE 'PASSED' END AS Status,
               'project_' || (hash(b) % {projects})::VARCHAR AS ProjectName,
               'suite_' || lpad(s::VARCHAR, 3, '0') AS SuiteName
        FROM range({builds}) a(b), range({suites}) c(s), range({tests}) d(t))"""

TEST_SUITE_INFO = """
    SELECT 'build-{year}-' || lpad(b::VARCHAR, 7, '0') AS BuildUniqueId,
           'suite_' || lpad(s::VARCHAR, 3, '0') AS SuiteName,
           'project_' || (hash(b) % {projects})::VARCHAR AS ProjectName,
           'org/project_' || (hash(b) % {projects})::VARCHAR AS ProjectFullName,
           (hash(s, b) % 3600000) / 1000.0 AS Duration,
           {tests} AS TestCaseCount
    FROM range({builds}) a(b), range({suites}) c(s)"""


TABLES = {"TestCaseData": TEST_CASE_DATA, "TestSuiteInfo": TEST_SUITE_INFO}


def generate(output_dir, scale, log=print):
    """Writes both tables under output_dir; returns {"<table>/<year>": rows}."""
    builds = round(FULL_SCALE_ROWS * scale / len(YEARS) / (SUITES * TESTS))
    if builds < 1:
        sys.exit(f"--scale {scale} gives no builds")
    connection = duckdb.connect()
    counts = {}
    for table, query in TABLES.items():
        for year in YEARS:
            target = os.path.join(output_dir, table, year)
            if os.path.exists(target):
                sys.exit(f"{target} already exists, remove it first")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            sql = query.format(year=year, builds=builds, suites=SUITES, tests=TESTS, projects=PROJECTS,
                               classes=CLASSES, failed=FAILED_PERCENT)
            connection.execute(f"COPY ({sql}) TO '{target}' (FORMAT parquet, FILE_SIZE_BYTES '256MB', ROW_GROUP_SIZE 1000000)")
            counts[f"{table}/{year}"] = connection.execute(
                f"SELECT count(*) FROM read_parquet('{target}/*.parquet')").fetchone()[0]
            log(f"{table}/{year}: {counts[f'{table}/{year}']} rows")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output_dir")
    parser.add_argument("--scale", type=float, required=True, help="fraction of the 9.4 B rows, e.g. 0.0175")
    args = parser.parse_args()
    generate(args.output_dir, args.scale)


if __name__ == "__main__":
    main()
