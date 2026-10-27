"""
Fabric direct-memory OOM repro (DX-127946): the workload of fabric_oom_repro.workload on the two-host stand of
scripts/fabric_oom_repro/setup_fabric_oom_stand.sh. The test passes when a Dremio log got a fabric OOM line (TC-01 of
the test plan, the baseline of an unfixed build); options: OOM_* in settings.py.

Run: scripts/fabric_oom_repro/run_fabric_oom_repro.sh
"""
from fabric_oom_repro.logs import log_counts
from fabric_oom_repro.workload import run_workload


def test_reproduce_fabric_oom(dremio, tables, system_options):
    before = log_counts()
    outcomes, _ = run_workload(dremio)
    delta = {c: {k: n - before[c][k] for k, n in counts.items()} for c, counts in log_counts().items()}
    summary = (f"system options={system_options}\noutcomes: {[f'{o.state} after {o.seconds:.0f}s' for o in outcomes]}\n"
               f"new log lines per container: {delta}")
    print("\n" + summary)
    assert sum(d["fabric_oom"] for d in delta.values()) > 0, f"fabric OOM not reproduced\n{summary}"
