# Sourced by deploy_dremio.sh. Creates the container and installs Java and Dremio in it.

cx() { $CT exec "$NAME" -- "$@"; }  # run a command in the container

# Two Dremios on one STORAGE_PATH share input/ and output/: concurrent test runs collide
# (e.g. "Folder already exists" on CREATE TABLE). Use a separate --storage-path per container.
check_shared_storage() {
    if (( ! ALLOW_SHARED )); then
        while IFS=, read -r other state; do
            [[ -n $other && $other != "$NAME" && $state == RUNNING ]] || continue
            src=$($CT config device get "$other" storage source 2>/dev/null) || continue
            [[ -n $src ]] || continue
            src=$(realpath -m "$src")
            if [[ $src == "$STORAGE_PATH" || $src == "$STORAGE_PATH"/* || $STORAGE_PATH == "$src"/* ]]; then
                die "container '$other' (running) already uses storage $src, which overlaps $STORAGE_PATH: use a separate --storage-path per container (e.g. $STORAGE_PATH-$NAME), or pass --allow-shared-storage"
            fi
        done < <($CT list -c ns --format csv)
    fi
}

# Creates the container from IMAGE and mounts the storage (and the input) into it.
create_container() {
    if $CT info "$NAME" >/dev/null 2>&1; then
        (( RECREATE )) || die "container '$NAME' already exists (use --recreate)"
        log "Deleting existing container $NAME"
        $CT delete --force "$NAME"
    fi

    log "Creating container $NAME from $IMAGE (memory ${CONTAINER_MB}MiB)"
    launch_args=(-c "limits.memory=${CONTAINER_MB}MiB")
    [[ -n $CPUS ]] && launch_args+=(-c "limits.cpu=$CPUS")
    $CT launch "$IMAGE" "$NAME" "${launch_args[@]}"

    # Same path inside and outside, so the tests on the host and Dremio see the same files.
    # shift=true maps the host uid/gid, so the 'dremio' user below (host uid) can write there.
    log "Mounting storage $STORAGE_PATH"
    $CT config device add "$NAME" storage disk source="$STORAGE_PATH" path="$STORAGE_PATH" shift=true
    if [[ -n $INPUT_DIR ]]; then
        log "Mounting input $INPUT_DIR (read-only)"
        $CT config device add "$NAME" input disk source="$INPUT_DIR" path="$INPUT_DIR" readonly=true shift=true
    fi
}

# Waits until the container resolves names.
wait_for_network() {
    log "Waiting for container network"
    for _ in $(seq 60); do cx getent hosts archive.ubuntu.com >/dev/null 2>&1 && break; sleep 2; done
    cx getent hosts archive.ubuntu.com >/dev/null 2>&1 || die "container has no network/DNS"
}

# Installs OpenJDK if the image lacks it and finds JAVA_HOME_DIR.
install_java() {
    if cx bash -c "ls /usr/lib/jvm/java-${JAVA_VERSION}-openjdk-*/bin/java && command -v curl" >/dev/null 2>&1; then
        log "OpenJDK $JAVA_VERSION already in the image"
    else
        log "Installing OpenJDK $JAVA_VERSION"
        cx apt-get update -qq
        cx env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "openjdk-${JAVA_VERSION}-jdk-headless" curl ca-certificates \
            || die "cannot install openjdk-${JAVA_VERSION}-jdk-headless (not available in this image?)"
    fi
    JAVA_HOME_DIR=$(cx bash -c "dirname \$(dirname \$(readlink -f \$(ls /usr/lib/jvm/java-${JAVA_VERSION}-openjdk-*/bin/java | head -1)))")
}

# The dremio user in the container has the uid of the host user, for the storage.
create_dremio_user() {
    log "Creating user dremio ($HOST_UID:$HOST_GID)"
    cx bash -c "id ubuntu >/dev/null 2>&1 && userdel -r ubuntu 2>/dev/null; \
        getent group $HOST_GID >/dev/null || groupadd -g $HOST_GID dremio; \
        useradd -u $HOST_UID -g $HOST_GID -m -d /home/dremio -s /usr/sbin/nologin dremio"
}

# Unpacks the Dremio tarball into /opt/dremio.
install_dremio() {
    log "Installing Dremio from $(basename "$PACKAGE")"
    $CT file push "$PACKAGE" "$NAME/tmp/dremio.tar.gz"
    cx bash -c "mkdir -p /opt/dremio && tar -xzf /tmp/dremio.tar.gz -C /opt/dremio --strip-components=1 && rm /tmp/dremio.tar.gz"
    cx test -x /opt/dremio/bin/dremio || die "bin/dremio not found: unexpected tarball layout"
}

# Writes dremio-env (memory, JVM options), the systemd unit and starts Dremio.
configure_dremio() {
    log "Configuring dremio-env (heap ${HEAP_MB}MB, direct ${DIRECT_MB}MB, JAVA_HOME $JAVA_HOME_DIR${JAVA_OPTS:+, JVM options: $JAVA_OPTS})"
    cx bash -c "
        f=/opt/dremio/conf/dremio-env
        touch \$f
        sed -i -E '/^(export )?(DREMIO_MAX_HEAP_MEMORY_SIZE_MB|DREMIO_MAX_DIRECT_MEMORY_SIZE_MB|DREMIO_JAVA_SERVER_EXTRA_OPTS|JAVA_HOME)=/d' \$f
        {
            echo 'DREMIO_MAX_HEAP_MEMORY_SIZE_MB=$HEAP_MB'
            echo 'DREMIO_MAX_DIRECT_MEMORY_SIZE_MB=$DIRECT_MB'
            echo 'JAVA_HOME=$JAVA_HOME_DIR'
        } >> \$f
    "
    # Written from stdin, so that quotes and $ in the options reach dremio-env unchanged.
    if [[ -n $JAVA_OPTS ]]; then
        printf 'DREMIO_JAVA_SERVER_EXTRA_OPTS="%s"\n' "$JAVA_OPTS" | cx bash -c "cat >> /opt/dremio/conf/dremio-env"
    fi
    cx bash -c "mkdir -p /opt/dremio/log; chown -R dremio:$HOST_GID /opt/dremio"

    cx bash -c "cat > /etc/systemd/system/dremio.service" <<EOF
[Unit]
Description=Dremio
After=network-online.target

[Service]
User=dremio
Environment=JAVA_HOME=$JAVA_HOME_DIR
ExecStart=/opt/dremio/bin/dremio start-fg
LimitNOFILE=65536
Restart=on-failure
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
EOF
    cx systemctl daemon-reload
    cx systemctl enable --now dremio
}
