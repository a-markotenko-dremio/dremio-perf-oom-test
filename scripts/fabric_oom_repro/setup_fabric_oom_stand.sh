#!/usr/bin/env bash
# Brings up the two-host stand of the fabric direct-memory OOM repro (DX-127946) from a Dremio tarball: coordinator +
# executor on this host, the second executor on the executor host of defaults.py, and the data set of the stand.
#   scripts/fabric_oom_repro/setup_fabric_oom_stand.sh TARBALL      (or: make fabric-oom-stand TARBALL=...)
# Run on the coordinator host. The containers are named after the tarball (default_container_name of common.sh), so
# the tests find them by the data device, not by name. The executor host runs its part from its own clone of this
# repository (git pull first, so push before running).
set -euxo pipefail
REPO=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)
source "$REPO/scripts/lib/common.sh"
source "$REPO/scripts/lib/cluster.sh"
cd "$REPO"

[[ $# -eq 1 && -f $1 ]] || { echo "usage: $0 TARBALL (a dremio-*.tar.gz)" >&2; exit 2; }
TARBALL=$(readlink -f "$1")
JAVA=21
COORDINATOR_CPUS=4 COORDINATOR_HEAP_MB=4096 COORDINATOR_DIRECT_MB=6144 COORDINATOR_MB=14336
EXECUTOR_CPUS=16 EXECUTOR_HEAP_MB=2048 EXECUTOR_DIRECT_MB=6144 EXECUTOR_MB=10240
COORDINATOR=$(default_container_name "$TARBALL" $JAVA $COORDINATOR_MB $COORDINATOR_CPUS)
EXECUTOR=$(default_container_name "$TARBALL" $JAVA $EXECUTOR_MB $EXECUTOR_CPUS)
EXECUTOR_HOST=$(default OOM_REPRO_EXECUTOR_HOST)
EXECUTOR_REPO=$(default OOM_REPRO_EXECUTOR_REPO)
DATA=$(default OOM_REPRO_DATA)

# stop everything on both hosts, create the containers
incus stop --all
ssh -n "$EXECUTOR_HOST" "incus stop --all"
ssh -n "$EXECUTOR_HOST" "cd $EXECUTOR_REPO && git pull --ff-only"
./deploy_dremio.sh --package "$TARBALL" --name "$COORDINATOR" --java-version $JAVA --cpus $COORDINATOR_CPUS \
    --heap-memory-mb $COORDINATOR_HEAP_MB --direct-memory-mb $COORDINATOR_DIRECT_MB --container-memory-mb $COORDINATOR_MB \
    --recreate --accept-eula --dry-run
ssh -n "$EXECUTOR_HOST" "cd $EXECUTOR_REPO && ./deploy_dremio.sh --package $TARBALL --name $EXECUTOR --java-version $JAVA \
    --cpus $EXECUTOR_CPUS --heap-memory-mb $EXECUTOR_HEAP_MB --direct-memory-mb $EXECUTOR_DIRECT_MB \
    --container-memory-mb $EXECUTOR_MB --recreate --accept-eula --dry-run"

# cluster config (mounts the data directory into both nodes), then wait for the executor and the UI
scripts/fabric_oom_repro/configure_cluster_node.sh "$COORDINATOR" "$EXECUTOR_HOST" coordinator
ssh -n "$EXECUTOR_HOST" "cd $EXECUTOR_REPO && scripts/fabric_oom_repro/configure_cluster_node.sh $EXECUTOR $(hostname) executor"
NAME=$COORDINATOR
detect_container_cli
registered() { cx grep -q "nodesRegistered $(host_address "$EXECUTOR_HOST")" /opt/dremio/log/server.log; }
for _ in $(seq 60); do registered && break; sleep 5; done
registered
DREMIO_URL=http://$(container_ip):9047
curl -fsS --retry 30 --retry-delay 2 --retry-connrefused -o /dev/null -w "UI $DREMIO_URL: HTTP %{http_code}\n" "$DREMIO_URL"

# the data set on both hosts
[[ -d $DATA/TestCaseData ]] || .venv/bin/python -m fabric_oom_repro.generate_oom_data "$DATA" --scale "$(default OOM_REPRO_SCALE)"
ssh -n "$EXECUTOR_HOST" "mkdir -p $DATA" && rsync -a "$DATA/" "$EXECUTOR_HOST:$DATA/"
echo "stand up: $COORDINATOR on $(hostname), $EXECUTOR on $EXECUTOR_HOST, data set $DATA"
