"""Smoke test of the environment: runs also with --dry-run (no data is generated)."""
import os

import pytest
import requests

from test_catalog_sales import (  # noqa: F401  (fixtures)
    DREMIO_URL, SQL_PARAMS, auth_headers, dremio_up, load_statements, run_sql, storage)

MB = 1024 * 1024
# The JVM may report a max heap slightly below -Xmx (GC dependent), so allow a small deviation.
HEAP_TOLERANCE = 0.02


@pytest.mark.dry_run_safe
def test_environment(storage, run_sql):
    """Dremio answers SQL, the NAS sources on STORAGE_PATH can be created, and the test SQL loads."""
    run_sql("SELECT 1")
    assert load_statements("run_test_body.sql", **SQL_PARAMS), "run_test_body.sql has no statements"


@pytest.mark.dry_run_safe
def test_memory_limits(run_sql, auth_headers):
    """Dremio itself reports the heap/direct memory limits the run is expected to have.

    Expected values come from HEAP_MB / DIRECT_MB (exported by deploy_dremio.sh); when they
    are not set (Dremio not deployed by the script) the check is skipped.
    """
    heap_mb, direct_mb = os.environ.get("HEAP_MB"), os.environ.get("DIRECT_MB")
    if not (heap_mb and direct_mb):
        pytest.skip("HEAP_MB / DIRECT_MB are not set: expected memory limits unknown")
    expected_heap, expected_direct = int(heap_mb) * MB, int(direct_mb) * MB

    job = run_sql("SELECT heap_max, direct_max FROM sys.memory")
    res = requests.get(f"{DREMIO_URL}/api/v3/job/{job['id']}/results",
                       headers=auth_headers, timeout=60)
    res.raise_for_status()
    rows = res.json()["rows"]
    assert rows, "sys.memory returned no rows"
    for row in rows:
        assert abs(row["heap_max"] - expected_heap) <= expected_heap * HEAP_TOLERANCE, \
            f"heap_max is {row['heap_max'] // MB} MB, expected {heap_mb} MB"
        assert row["direct_max"] == expected_direct, \
            f"direct_max is {row['direct_max'] // MB} MB, expected {direct_mb} MB"
