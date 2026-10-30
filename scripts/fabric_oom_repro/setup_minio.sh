#!/usr/bin/env bash
# Brings up the MinIO that holds the distributed store (paths.dist) of the stand, in its own container on this host,
# and publishes it on PEER_HOST's route of this host so that the node on the other host reaches it too.
#   scripts/fabric_oom_repro/setup_minio.sh PEER_HOST
# Prints the endpoint as host:port, the form core-site.xml wants (no scheme). Safe to run again: the container is
# recreated, so every stand starts from an empty store.
set -euo pipefail
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../lib/common.sh"
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../lib/cluster.sh"

[[ $# -eq 1 ]] || { echo "usage: $0 PEER_HOST" >&2; exit 2; }
detect_container_cli
NAME=$(default OOM_REPRO_MINIO)
PORT=$(default OOM_REPRO_MINIO_PORT)
BUCKET=$(default OOM_REPRO_DIST_BUCKET)
HOST_IP=$(own_address "$1")

$CT delete --force "$NAME" 2>/dev/null || true
$CT launch "$DEFAULT_IMAGE" "$NAME" >/dev/null
for _ in $(seq 60); do cx getent hosts dl.min.io >/dev/null 2>&1 && break; sleep 1; done
cx bash -euc "
    curl -fsSL -o /usr/local/bin/minio https://dl.min.io/server/minio/release/linux-amd64/minio
    chmod +x /usr/local/bin/minio
    mkdir -p /data/$BUCKET   # the bucket must exist before Dremio uses it; with the filesystem backend it is a directory
    cat > /etc/systemd/system/minio.service <<UNIT
[Unit]
Description=MinIO
After=network-online.target

[Service]
Environment=MINIO_ROOT_USER=$(default OOM_REPRO_MINIO_KEY)
Environment=MINIO_ROOT_PASSWORD=$(default OOM_REPRO_MINIO_SECRET)
ExecStart=/usr/local/bin/minio server /data --address :$PORT
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload
    systemctl enable --now minio"

forward_ports "$HOST_IP" "$(container_ip)" "$PORT"
add_loopback_alias "$HOST_IP"
curl -fsS --retry 30 --retry-delay 1 --retry-connrefused -o /dev/null "http://$HOST_IP:$PORT/minio/health/live"
echo "$HOST_IP:$PORT"
