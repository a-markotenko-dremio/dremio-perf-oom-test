#!/usr/bin/env bash
# Runs the workload of the fabric OOM fix verification (fabric-oom-test-plan.md, TC-12) with no time limit on a query:
# under the 4 % arbiter reserve of the repro the queries spill, and the run tells whether every one of them is served
# in the end. That takes the time it takes (37 min on the 14G/10G stand on 2026-10-30), which is why the run with the
# limit (run_fabric_oom_func.sh) is the one to repeat. Run on the coordinator host (make fabric-oom-feature).
set -euxo pipefail
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/env.sh"
OOM_MAX_QUERY_SECONDS=0 OOM_INNOCENT=1 OOM_RESERVE_PCT=4 DREMIO_TIMEOUT=7200 \
    .venv/bin/python -m pytest tests/fabric_oom_repro/test_fabric_oom_func.py -s
