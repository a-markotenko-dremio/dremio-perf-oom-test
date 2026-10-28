#!/usr/bin/env bash
# Brings up the two-host stand of the fabric direct-memory OOM repro (DX-127946): coordinator + executor on this host,
# the second executor on the executor host of defaults.py, and the data of the repro. Run on the coordinator host.
# The executor host runs its part from its own clone of this repository (git pull first, so push before running).
set -euxo pipefail
REPO=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)
source "$REPO/scripts/lib/common.sh"
source "$REPO/scripts/lib/cluster.sh"
cd "$REPO"

COORDINATOR=$(default OOM_REPRO_COORDINATOR)
EXECUTOR=$(default OOM_REPRO_EXECUTOR)
EXECUTOR_HOST=$(default OOM_REPRO_EXECUTOR_HOST)
EXECUTOR_REPO=$(default OOM_REPRO_EXECUTOR_REPO)
STORAGE=$(default OOM_REPRO_STORAGE)
DATA=$STORAGE/$(default OOM_REPRO_SUBDIR)
TARBALL=/mnt/ubuntu-var/nfs/shared/Downloads/dremio-enterprise-25.2.0-202410241428100111-a963b970.tar.gz

# stop everything on both hosts, create the containers
incus stop --all
ssh -n "$EXECUTOR_HOST" "incus stop --all"
ssh -n "$EXECUTOR_HOST" "cd $EXECUTOR_REPO && git pull --ff-only"
./deploy_dremio.sh --package "$TARBALL" --storage-path "$STORAGE" --name "$COORDINATOR" --cpus 4 \
    --heap-memory-mb 4096 --direct-memory-mb 6144 --container-memory-mb 14336 --recreate --accept-eula --dry-run
ssh -n "$EXECUTOR_HOST" "cd $EXECUTOR_REPO && ./deploy_dremio.sh --package $TARBALL --storage-path $STORAGE \
    --name $EXECUTOR --cpus 16 --heap-memory-mb 2048 --direct-memory-mb 6144 --container-memory-mb 10240 \
    --recreate --accept-eula --dry-run"

# cluster config, then wait for the executor and the UI
scripts/fabric_oom_repro/configure_cluster_node.sh "$COORDINATOR" "$EXECUTOR_HOST" coordinator
ssh -n "$EXECUTOR_HOST" "cd $EXECUTOR_REPO && scripts/fabric_oom_repro/configure_cluster_node.sh $EXECUTOR $(hostname) executor"
NAME=$COORDINATOR
detect_container_cli
registered() { cx grep -q "nodesRegistered $(host_address "$EXECUTOR_HOST")" /opt/dremio/log/server.log; }
for _ in $(seq 60); do registered && break; sleep 5; done
registered
DREMIO_URL=http://$(container_ip):9047
curl -fsS --retry 30 --retry-delay 2 --retry-connrefused -o /dev/null -w "UI $DREMIO_URL: HTTP %{http_code}\n" "$DREMIO_URL"

# data (scale 1/57) on both hosts
[[ -d $DATA/TestCaseData ]] || .venv/bin/python -m fabric_oom_repro.generate_oom_data "$DATA" --scale 0.0175
ssh -n "$EXECUTOR_HOST" "mkdir -p $DATA" && rsync -a "$DATA/" "$EXECUTOR_HOST:$DATA/"
