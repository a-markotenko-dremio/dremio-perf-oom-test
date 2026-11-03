#!/usr/bin/env bash
# Runs the fabric direct-memory OOM reproduction (DX-127946, F-01 of test-cases/ in the QA repository) on the stand of
# setup_fabric_oom_stand.sh. On a build with the fix the same run is F-10 (both changes off), F-22 (OOM_ESCALATION=1
# without the read pause) or F-16 (`factor` 2 -> 1). Run on the coordinator host (make fabric-oom-repro).
set -euxo pipefail
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/env.sh"
OOM_RESERVE_PCT=4 DREMIO_TIMEOUT=2400 .venv/bin/python -m pytest tests/fabric_oom_repro/test_fabric_oom_repro.py -s -x
