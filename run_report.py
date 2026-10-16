"""What one test run leaves behind: a row in the report CSV and, on failure, a traceback file."""
import os
import traceback

import settings
import results_report


def configured_mb(env_name, reported_bytes):
    """The memory limit as configured (HEAP_MB / DIRECT_MB, set by deploy_dremio.sh and
    scripts/test_container.sh), so that the report shows 446 for -Xmx446m instead of what the JVM
    reports after rounding. Without the variable the value reported by Dremio is used."""
    value = os.environ.get(env_name, "").strip()
    return int(value) if value.isdigit() else reported_bytes // (1024 * 1024)


def write_report(dremio, minutes, verdict, started_at):
    """Adds this run to REPORT_CSV. The Dremio version is queried from Dremio; the memory limits are
    the configured ones."""
    version = dremio.query_rows("SELECT version FROM sys.nodes")[0]["version"]
    mem = dremio.query_rows("SELECT heap_max, direct_max FROM sys.memory")[0]
    host = results_report.host_name()
    results_report.append_row(settings.REPORT_CSV, {
        "Timestamp": results_report.timestamp(started_at),
        "Host src": host, "Data src": "dir/Parquet",
        "Host dst": host, "Data dst": "dir/Iceberg",
        "Dremio ver": version,
        "JVM ver": os.environ.get("JVM_VERSION", ""),
        "Host RAM": results_report.host_ram(),
        "CPUs": results_report.cpus(),
        "DREMIO_MAX_DIRECT_MEMORY_SIZE_MB": configured_mb("DIRECT_MB", mem["direct_max"]),
        "DREMIO_MAX_HEAP_MEMORY_SIZE_MB": configured_mb("HEAP_MB", mem["heap_max"]),
        "Rows": results_report.format_rows(settings.ROW_COUNT),
        "Duration (minutes)": f"{minutes:.1f}",
        "Verdict": verdict,
        "Run by": results_report.run_by(),
    })
    print(f"report row added to {settings.REPORT_CSV}", flush=True)


def write_traceback(started_at):
    """Saves the traceback of the exception being handled to test_result_<timestamp>.log next to the CSV."""
    path = settings.REPORT_CSV.parent / f"test_result_{results_report.timestamp(started_at)}.log"
    path.write_text(traceback.format_exc())
    print(f"traceback saved to {path}", flush=True)
