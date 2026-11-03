"""Offline tests of fabric_oom_repro.run_table on the pytest logs of the stand (dell35, 2026-11-02) and the older summary formats."""
from fabric_oom_repro import run_table

FAILED_RUN = """\
tests/fabric_oom_repro/test_fabric_oom_repro.py
data set=/mnt/ubuntu-var/dremio/fabric-oom-repro/scale-0.0175
system options={'planner.width.max_per_node': 24, 'exec.spillable.operators.pct_free_memory_watermark': 4.0}
outcomes: ['COMPLETED after 1455s', 'Job 1516adfb-da86-7fce-35ab-e686dc63ad00 FAILED: OUT_OF_MEMORY ERROR: Query was cancelled because it exceeded the memory limits set by the administrator. after 571s', 'COMPLETED after 2118s', 'OVER THE LIMIT: the query did not return within the time the run allows after 2400s', 'Job 1516adfb-9b6b-5cf8-a5a9-d885703d4c00 FAILED: OUT_OF_MEMORY ERROR: Query was cancelled because it exceeded the memory limits set by the administrator. after 631s', 'OVER THE LIMIT: the query did not return within the time the run allows after 2400s', 'OVER THE LIMIT: the query did not return within the time the run allows after 2400s', 'OVER THE LIMIT: the query did not return within the time the run allows after 2400s']
events: {'fabric_oom': 0, 'transport_failure': 0, 'read_pause': 0, 'pause_gave_up': 0, 'escalation': 0, 'claw_back': 0, 'shrink': 4497, 'job_failed': 2, 'node_unregistered': 0, 'zk_lost': 0}, failures by cause: {'arbiter': 2}, fabric OOMs by allocation: {}
d27-0-0-j21-14G-4cpu: {'pauses': 0, 'longest episode': None, 'gave up': 0, 'escalations': [], 'transport failures': 0}
F
=================================== FAILURES ===================================
E         AssertionError: fabric OOM not reproduced
E         outcomes: ['COMPLETED after 1455s']
E         events: {'fabric_oom': 0, 'shrink': 4497, 'job_failed': 2, 'node_unregistered': 0, 'zk_lost': 0}, failures by cause: {'arbiter': 2}, fabric OOMs by allocation: {}
FAILED tests/fabric_oom_repro/test_fabric_oom_repro.py::test_reproduce_fabric_oom
======================== 1 failed in 2409.82s (0:40:09) ========================
"""
# the summary of 2026-10-22 to 10-28, before the parser of the events
OLD_RUN = """\
outcomes: ['COMPLETED after 547s', 'Job 1 FAILED: OUT_OF_MEMORY ERROR: … after 69s']
new log lines per container: {'d25-2-0-j21-14G-4cpu': {'fabric_oom': 149, 'arbiter_cancel': 0, 'shrink_requests': 410}, 'den:d25-2-0-j21-10G-16cpu': {'fabric_oom': 0, 'arbiter_cancel': 2, 'shrink_requests': 870}}
.
============================== 1 passed in 601.20s (0:10:01) ===============================
"""


def test_a_failed_run_is_read_from_the_summary_the_test_printed(tmp_path):
    (tmp_path / "fabric-oom-repro-20261102-211607.log").write_text(FAILED_RUN)
    assert run_table.row(tmp_path / "fabric-oom-repro-20261102-211607.log") == {
        "run": "2026-11-02 21:16", "case": "repro", "took": "0:40:10", "verdict": "1 failed", "completed": 2,
        "over limit": 4, "failed": 2, "fabric OOM": 0, "arbiter": 2, "shrink": 4497}


def test_the_old_per_container_counts_are_summed(tmp_path):
    (tmp_path / "fabric-oom-repro-20261022-223816.log").write_text(OLD_RUN)
    assert run_table.row(tmp_path / "fabric-oom-repro-20261022-223816.log") == {
        "run": "2026-10-22 22:38", "case": "repro", "took": "0:10:01", "verdict": "1 passed", "completed": 1,
        "over limit": 0, "failed": 1, "fabric OOM": 149, "arbiter": 2, "shrink": 1280}


def test_a_run_without_a_result_gets_no_counts(tmp_path):
    (tmp_path / "fabric-oom-func-20261102-215623.log").write_text("collected 2 items\n\ntests/fabric_oom_repro/test_fabric_oom_func.py ")
    assert run_table.row(tmp_path / "fabric-oom-func-20261102-215623.log") == {
        "run": "2026-11-02 21:56", "case": "func", "took": "", "verdict": "no result (running or killed)"}


def test_the_table_lists_every_column_and_leaves_the_unknown_ones_empty():
    lines = run_table.table([{"run": "2026-11-02 21:56", "case": "func", "took": "", "verdict": "no result (running or killed)"}]).splitlines()
    assert lines[0].startswith("| run | case | took | verdict | fabric OOM |")
    assert lines[2] == "| 2026-11-02 21:56 | func |  | no result (running or killed) |  |  |  |  |  |  |"
