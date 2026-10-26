#!/usr/bin/env bash

# Runs the fabric direct-memory OOM repro test (DX-127946) on the stand of setup_fabric_oom_stand.sh. Run on the
# coordinator host.

set -euxo pipefail
REPO=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)
source "$REPO/scripts/lib/common.sh"
cd "$REPO"

NAME=$(python3 -c "import defaults; print(defaults.OOM_REPRO_COORDINATOR)")
detect_container_cli

export DREMIO_URL=http://$(container_ip):9047
OOM_RESERVE_PCT=4 DREMIO_TIMEOUT=2400 .venv/bin/python -m pytest tests/fabric_oom_repro/test_fabric_oom_repro.py -s -x
