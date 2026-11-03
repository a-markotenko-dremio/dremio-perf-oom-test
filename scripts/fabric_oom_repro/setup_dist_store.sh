#!/usr/bin/env bash
# Brings up the S3 server that holds the distributed store (paths.dist) of the stand, in its own container on this
# host, and publishes it on PEER_HOST's route of this host so that the node on the other host reaches it too.
#   scripts/fabric_oom_repro/setup_dist_store.sh PEER_HOST
# Prints two endpoints as "LOCAL REMOTE", in the host:port form core-site.xml wants (no scheme): the address of the
# store's container for the node on this host, and the published address of this host for the node on PEER_HOST.
# They differ because a node reaches its own host's address through a loopback alias (configure_cluster_node.sh adds
# it so that the node can reach its own published ports), and that alias also hides every other service published on
# that address - the store among them. Safe to run again: the container is recreated, so every stand starts empty.
# The server is launched by scripts/lib/s3.sh.
set -euo pipefail
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../lib/common.sh"
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../lib/cluster.sh"
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../lib/s3.sh"

[[ $# -eq 1 ]] || { echo "usage: $0 PEER_HOST" >&2; exit 2; }
detect_container_cli
NAME=$(default OOM_REPRO_S3)
PORT=$(default OOM_REPRO_S3_PORT)
BUCKET=$(default OOM_REPRO_DIST_BUCKET)
HOST_IP=$(own_address "$1")

launch_s3_server

# the bucket must exist before Dremio writes into it
cx bash -euc "
    for _ in \$(seq 60); do weed shell -master=localhost:9333 <<<'s3.bucket.list' >/dev/null 2>&1 && break; sleep 1; done
    weed shell -master=localhost:9333 <<<'s3.bucket.create -name $BUCKET' >/dev/null"

STORE_IP=$(container_ip)
forward_ports "$HOST_IP" "$STORE_IP" "$PORT"
await_s3 "$STORE_IP"
echo "$STORE_IP:$PORT $HOST_IP:$PORT"
