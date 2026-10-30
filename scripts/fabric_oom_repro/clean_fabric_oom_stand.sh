#!/usr/bin/env bash
# Removes the stand of the fabric direct-memory OOM repro (DX-127946) from both hosts: every container, the storage of
# each, the port forwarding of the host and the distributed directories of the stands. Containers of earlier stands
# are named after their Dremio version, so setup_fabric_oom_stand.sh never replaces them; this is what removes them.
#   scripts/fabric_oom_repro/clean_fabric_oom_stand.sh           (or: make fabric-oom-clean)
# Run on the coordinator host; it cleans the executor host from its own clone of this repository.
# --local PEER_HOST cleans only the host it runs on, whose address is the one that leads to PEER_HOST.
# The generated data is kept, it costs hours to make again: the data sets under OOM_REPRO_DIR, the blocks of
# generate_data.py and the Dremio tarballs under Downloads.
set -euxo pipefail
REPO=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)
source "$REPO/scripts/lib/common.sh"
source "$REPO/scripts/lib/cluster.sh"
cd "$REPO"

EXECUTOR_HOST=$(default OOM_REPRO_EXECUTOR_HOST)
case "${1:-}" in
    --local) [[ $# -eq 2 ]] || { echo "usage: $0 [--local PEER_HOST]" >&2; exit 2; }; PEER=$2 ;;
    "") PEER=$EXECUTOR_HOST ;;
    *) echo "usage: $0 [--local PEER_HOST]" >&2; exit 2 ;;
esac
detect_container_cli

mapfile -t names < <($CT list -c n --format csv)
(( ${#names[@]} == 0 )) || $CT delete --force "${names[@]}"
# by name, not per container: the storages of stands whose containers are already gone are left behind too
mapfile -t storages < <(container_storages)
(( ${#storages[@]} == 0 )) || rm -rf "${storages[@]}"
nat_rules "$(own_address "$PEER")" | drop_nat_rules

if [[ ${1:-} != --local ]]; then
    ssh -n "$EXECUTOR_HOST" "cd $(default OOM_REPRO_EXECUTOR_REPO) \
        && scripts/fabric_oom_repro/clean_fabric_oom_stand.sh --local $(hostname)"
fi
echo "stand removed: containers, their storages and the port forwarding; data sets, blocks and packages kept"
