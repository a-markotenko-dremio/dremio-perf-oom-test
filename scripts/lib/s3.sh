# The S3 server of the distributed store of the fabric OOM stand and of the runs with STORAGE=s3, in a container of its
# own. Sourced after common.sh.
# The server is the S3 gateway of SeaweedFS. MinIO, which the Dremio documentation uses as its S3-compatible
# example, was archived in 2026: dl.min.io answers 410 and the images are gone from Docker Hub.
SEAWEEDFS=4.51   # pinned: a store that changes under the stand would change what the runs measure

# launch_s3_server: recreates the container NAME with the server, so that it starts empty (uses CT, DEFAULT_IMAGE, cx).
launch_s3_server() {
    local port
    port=$(default OOM_REPRO_S3_PORT)
    $CT delete --force "$NAME" 2>/dev/null || true
    remove_orphan_volume "$NAME"
    # capped: on the stand it shares the host with the coordinator, whose container limit is already above the memory
    # free there, and a host OOM kill of that node would look like the node loss the tests hunt for
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
ExecStart=/usr/local/bin/weed server -dir=/data -s3 -s3.port=$port -s3.config=/etc/seaweedfs/s3.json
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
        systemctl daemon-reload
        systemctl enable --now seaweedfs"
}

# await_s3 IP: waits until the server answers on IP. An S3 server answers an unsigned request with 403: it is up and reachable.
await_s3() {
    local url=http://$1:$(default OOM_REPRO_S3_PORT)/
    for _ in $(seq 60); do [[ $(curl -s -o /dev/null -w "%{http_code}" "$url") == 403 ]] && return 0; sleep 1; done
    die "the store does not answer on $url"
}

# ensure_s3_server: starts the server of the STORAGE=s3 runs unless its container (TEST_S3) is running, waits for it
# and sets S3_ENDPOINT to its host:port. Its data outlives the runs: delete the container to free the space.
ensure_s3_server() {
    local NAME
    NAME=$(default TEST_S3)
    [[ -n $($CT list status=running -c n --format csv | grep -x "$NAME" || true) ]] || launch_s3_server
    await_s3 "$(container_ip)"
    S3_ENDPOINT=$(container_ip):$(default OOM_REPRO_S3_PORT)
}
