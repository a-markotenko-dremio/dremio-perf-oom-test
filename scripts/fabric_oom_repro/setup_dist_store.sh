#!/usr/bin/env bash
# Brings up the S3 server that holds the distributed store (paths.dist) of the stand, in its own container on this
# host, and publishes it on PEER_HOST's route of this host so that the node on the other host reaches it too.
#   scripts/fabric_oom_repro/setup_dist_store.sh PEER_HOST
# Prints the endpoint as host:port, the form core-site.xml wants (no scheme). Safe to run again: the container is
# recreated, so every stand starts from an empty store.
# The server is the S3 gateway of SeaweedFS. MinIO, which the Dremio documentation uses as its S3-compatible
# example, was archived in 2026: dl.min.io answers 410 and the images are gone from Docker Hub.
set -euo pipefail
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../lib/common.sh"
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../lib/cluster.sh"

[[ $# -eq 1 ]] || { echo "usage: $0 PEER_HOST" >&2; exit 2; }
detect_container_cli
NAME=$(default OOM_REPRO_S3)
PORT=$(default OOM_REPRO_S3_PORT)
BUCKET=$(default OOM_REPRO_DIST_BUCKET)
SEAWEEDFS=4.51   # pinned: a store that changes under the stand would change what the runs measure
HOST_IP=$(own_address "$1")

$CT delete --force "$NAME" 2>/dev/null || true
# capped: it shares the host with the coordinator, whose container limit is already above the memory free there,
# and a host OOM kill of that node would look like the node loss the tests hunt for
$CT launch "$DEFAULT_IMAGE" "$NAME" -c limits.cpu=1 -c limits.memory=1GiB >/dev/null
for _ in $(seq 60); do cx getent hosts github.com >/dev/null 2>&1 && break; sleep 1; done
cx bash -euc "
    SEAWEEDFS=$SEAWEEDFS
    curl -fsSL https://github.com/seaweedfs/seaweedfs/releases/download/\$SEAWEEDFS/linux_amd64.tar.gz \
        | tar -xz -C /usr/local/bin weed
    mkdir -p /data /etc/seaweedfs
    cat > /etc/seaweedfs/s3.json <<JSON
{\"identities\": [{\"name\": \"dremio\",
  \"credentials\": [{\"accessKey\": \"$(default OOM_REPRO_S3_KEY)\", \"secretKey\": \"$(default OOM_REPRO_S3_SECRET)\"}],
  \"actions\": [\"Admin\", \"Read\", \"Write\", \"List\", \"Tagging\"]}]}
JSON
    cat > /etc/systemd/system/seaweedfs.service <<UNIT
[Unit]
Description=SeaweedFS with the S3 gateway
After=network-online.target

[Service]
ExecStart=/usr/local/bin/weed server -dir=/data -s3 -s3.port=$PORT -s3.config=/etc/seaweedfs/s3.json
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload
    systemctl enable --now seaweedfs"

# the bucket must exist before Dremio writes into it
cx bash -euc "
    for _ in \$(seq 60); do weed shell -master=localhost:9333 <<<'s3.bucket.list' >/dev/null 2>&1 && break; sleep 1; done
    weed shell -master=localhost:9333 <<<'s3.bucket.create -name $BUCKET' >/dev/null"

forward_ports "$HOST_IP" "$(container_ip)" "$PORT"
add_loopback_alias "$HOST_IP"
curl -fsS --retry 30 --retry-delay 1 --retry-connrefused -o /dev/null -w "" "http://$HOST_IP:$PORT/" || true
echo "$HOST_IP:$PORT"
