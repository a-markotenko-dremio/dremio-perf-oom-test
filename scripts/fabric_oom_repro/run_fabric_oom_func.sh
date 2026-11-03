#!/usr/bin/env bash
# Runs the fix verification of the fabric direct-memory OOM (test-plan-fabric-direct-memory-oom.md, test-cases/ of the
# QA repository) on the stand of setup_fabric_oom_stand.sh: with the 4 % arbiter reserve of the reproduction
# (F-03..F-07), with the default reserve (F-08), and with the small query next to the 8 (F-09). The configuration of
# the build under test comes from the environment: OOM_ESCALATION=1 turns the escalation on (0 off: F-17, read pause
# alone), the read pause is OOM_JAVA_OPTS of the stand setup. Every query is cut off after OOM_MAX_QUERY_SECONDS, so a
# session ends in minutes and a query that needs longer fails the run on the limit (P-06); run_fabric_oom_feature.sh
# is the run without one. Run on the coordinator host (make fabric-oom-func).
set -euxo pipefail
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/env.sh"
rc=0
OOM_RESERVE_PCT=4 DREMIO_TIMEOUT=2400 .venv/bin/python -m pytest tests/fabric_oom_repro/test_fabric_oom_func.py -s || rc=$?
DREMIO_TIMEOUT=2400 .venv/bin/python -m pytest tests/fabric_oom_repro/test_fabric_oom_func.py -s || rc=$?
OOM_INNOCENT=1 OOM_RESERVE_PCT=4 DREMIO_TIMEOUT=2400 .venv/bin/python -m pytest tests/fabric_oom_repro/test_fabric_oom_func.py -s || rc=$?
exit $rc
