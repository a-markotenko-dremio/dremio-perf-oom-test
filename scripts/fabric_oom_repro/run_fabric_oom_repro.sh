#!/usr/bin/env bash
# Runs the fabric direct-memory OOM repro test (DX-127946) on the stand of setup_fabric_oom_stand.sh. Run on the
# coordinator host.
set -euxo pipefail
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/env.sh"
OOM_RESERVE_PCT=4 DREMIO_TIMEOUT=2400 .venv/bin/python -m pytest tests/fabric_oom_repro/test_fabric_oom_repro.py -s -x
