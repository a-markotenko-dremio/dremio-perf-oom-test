#!/usr/bin/env bash
# Runs the fix verification of the fabric direct-memory OOM (fabric-oom-test-plan.md) on the stand of
# setup_fabric_oom_stand.sh: with the 4 % arbiter reserve of the repro, with the default reserve (TC-03), and with the
# small query next to the 8 (TC-04). Run on the coordinator host (make fabric-oom-func).
set -euxo pipefail
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/env.sh"
rc=0
OOM_RESERVE_PCT=4 DREMIO_TIMEOUT=2400 .venv/bin/python -m pytest tests/fabric_oom_repro/test_fabric_oom_func.py -s || rc=$?
DREMIO_TIMEOUT=2400 .venv/bin/python -m pytest tests/fabric_oom_repro/test_fabric_oom_func.py -s || rc=$?
OOM_INNOCENT=1 OOM_RESERVE_PCT=4 DREMIO_TIMEOUT=2400 .venv/bin/python -m pytest tests/fabric_oom_repro/test_fabric_oom_func.py -s || rc=$?
exit $rc
