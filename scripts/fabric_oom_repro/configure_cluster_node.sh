#!/usr/bin/env bash
# Makes a Dremio container a node of the two-host stand: mounts the data sets of the stand, forwards its ports from the
# address of this host, sets the cluster keys of dremio.conf and restarts Dremio. Run on the host of the container.
#   scripts/fabric_oom_repro/configure_cluster_node.sh CONTAINER PEER_HOST coordinator|executor
# PEER_HOST is the other host of the cluster as named in /etc/hosts; the address of this host is the one that leads
# to it. For an executor it is the host of the coordinator (ZooKeeper runs there).
# Safe to run again. Heap, direct memory and the container limit are set by deploy_dremio.sh, not here.
set -euo pipefail
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../lib/common.sh"
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../lib/cluster.sh"

[[ $# -eq 3 ]] || { echo "usage: $0 CONTAINER PEER_HOST coordinator|executor" >&2; exit 2; }
NAME=$1
PEER=$2
detect_container_cli
mount_stand_data "$(default OOM_REPRO_DIR)"
HOST_IP=$(own_address "$PEER")
# The conduit (gRPC between the nodes: catalog settings, metadata jobs) listens on a random port unless fixed; the
# peers reach it through the published host address, so it is fixed and forwarded like fabric.
CONDUIT_PORT=45679
case $3 in
    coordinator)
        configure_cluster_node "$HOST_IP" "2181 9047 31010 45678 $CONDUIT_PORT" "registration.publish-host: \"$HOST_IP\"" \
            "services.conduit.port: $CONDUIT_PORT" ;;
    executor)
        configure_cluster_node "$HOST_IP" "45678 $CONDUIT_PORT" \
            "services.coordinator.enabled: false" "services.coordinator.master.enabled: false" \
            "services.executor.enabled: true" "zookeeper: \"$(host_address "$PEER"):2181\"" \
            "registration.publish-host: \"$HOST_IP\"" "services.conduit.port: $CONDUIT_PORT" ;;
    *) echo "role must be coordinator or executor, not $3" >&2; exit 2 ;;
esac
echo "done: $NAME advertises $HOST_IP as $3"
