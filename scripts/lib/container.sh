# Sourced by deploy_dremio.sh. Creates the container and installs Java (or Docker and the Java image) and Dremio in it.

cx() { $CT exec "$NAME" -- "$@"; }  # run a command in the container

# Runs the java Dremio runs with: from the Java image with --java-image, else the one in the container.
run_java() {
    if [[ -n $JAVA_IMAGE ]]; then cx docker run --rm --security-opt apparmor=unconfined --entrypoint "$JAVA_HOME_DIR/bin/java" "$JAVA_IMAGE" "$@"
    else cx "$JAVA_HOME_DIR/bin/java" "$@"; fi
}

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
    if [[ -n $JAVA_IMAGE ]]; then read -r -a docker_args <<<"$(docker_launch_args)"; launch_args+=("${docker_args[@]}"); fi
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

# Prepares the Java: OpenJDK in the container, or with --java-image the image in Docker. Sets JAVA_HOME_DIR
# (the Java home inside the image in the second case).
install_java() {
    if [[ -n $JAVA_IMAGE ]]; then install_java_image; else install_java_apt; fi
}

# Builds wolfi-jdk:<N> in the Docker of the container: the public cgr.dev/chainguard/wolfi-base with bash, libstdc++
# (RocksDB JNI) and OpenJDK N from the Wolfi packages (the versioned tags of cgr.dev/chainguard/jdk are not public).
# It is a run + commit, not a Dockerfile: the RUN steps of `docker build` fail on the AppArmor check inside the
# container. The built image is cached on the host ($PERF_CACHE_DIR, default ~/.cache/perf-dremio) and loaded from
# there into the next containers; --rebuild-image builds it again.
build_wolfi_jdk_image() {
    local n=$1 cache=${PERF_CACHE_DIR:-$HOME/.cache/perf-dremio}/wolfi-jdk-$1.tar.gz
    if cx docker image inspect "wolfi-jdk:$n" >/dev/null 2>&1; then log "Image wolfi-jdk:$n already built"; return; fi
    if [[ -s $cache ]] && (( ! REBUILD_IMAGE )); then
        log "Loading wolfi-jdk:$n from the host cache $cache"
        if cx docker load <"$cache" >/dev/null; then return; fi
        echo "WARNING: cannot load $cache, building the image" >&2
    fi
    log "Building wolfi-jdk:$n (OpenJDK $n on cgr.dev/chainguard/wolfi-base)"
    cx docker rm -f wolfi-jdk-build >/dev/null 2>&1 || true
    cx docker run --name wolfi-jdk-build --security-opt apparmor=unconfined --entrypoint sh cgr.dev/chainguard/wolfi-base \
        -c "apk add --no-cache bash libstdc++ openjdk-$n >/dev/null && ln -s /usr/lib/jvm/java-$n-openjdk/bin/java /usr/bin/java" \
        && cx docker commit wolfi-jdk-build "wolfi-jdk:$n" >/dev/null \
        || { cx docker rm -f wolfi-jdk-build >/dev/null 2>&1 || true; die "cannot build wolfi-jdk:$n (is there a Wolfi package openjdk-$n?)"; }
    cx docker rm wolfi-jdk-build >/dev/null
    log "Caching wolfi-jdk:$n on the host: $cache"
    mkdir -p "$(dirname "$cache")" \
        && cx docker save "wolfi-jdk:$n" | gzip >"$cache.tmp" && [[ -s $cache.tmp ]] && mv "$cache.tmp" "$cache" \
        || { rm -f "$cache.tmp"; echo "WARNING: cannot cache wolfi-jdk:$n on the host" >&2; }
}

# Pulls the Java image into the Docker of the container and finds JAVA_HOME_DIR in it.
install_java_image() {
    log "Waiting for Docker in the container"
    for _ in $(seq 30); do cx docker info >/dev/null 2>&1 && break; sleep 2; done
    cx docker info >/dev/null 2>&1 || die "Docker does not run in the container (see: $CT exec $NAME -- journalctl -u docker)"
    if [[ -n $DOCKER_CONFIG_FILE ]]; then
        cx mkdir -p /root/.docker
        $CT file push "$DOCKER_CONFIG_FILE" "$NAME/root/.docker/config.json"
    fi
    if [[ $JAVA_IMAGE =~ ^wolfi-jdk:([0-9]+)$ ]]; then
        build_wolfi_jdk_image "${BASH_REMATCH[1]}"
    else
        log "Pulling $JAVA_IMAGE"
        cx docker pull "$JAVA_IMAGE" >/dev/null \
            || die "cannot pull $JAVA_IMAGE (a tag that needs a login? pass --docker-config ~/.docker/config.json)"
    fi
    local probe
    probe=$(cx docker run --rm --security-opt apparmor=unconfined --entrypoint bash "$JAVA_IMAGE" -c "command -v java" 2>&1) \
        || die "cannot run $JAVA_IMAGE with bash and java (Dremio's bin/dremio needs both, use a -dev image): $probe"
    JAVA_HOME_DIR=$(cx docker run --rm --security-opt apparmor=unconfined --entrypoint bash "$JAVA_IMAGE" -c 'dirname $(dirname $(readlink -f $(command -v java)))')
}

# Installs OpenJDK if the container lacks it and finds JAVA_HOME_DIR.
install_java_apt() {
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

    write_service_unit
    cx systemctl daemon-reload
    cx systemctl enable --now dremio
}

# The systemd unit: Dremio runs directly, or with --java-image inside a Docker container of that image
# (host network, the Dremio directory and the storage mounted at the same paths, the uid of the host user).
write_service_unit() {
    local input_mount=""
    [[ -n $INPUT_DIR ]] && input_mount="-v $INPUT_DIR:$INPUT_DIR:ro"
    if [[ -n $JAVA_IMAGE ]]; then
        cx bash -c "cat > /etc/systemd/system/dremio.service" <<EOF
[Unit]
Description=Dremio
After=network-online.target docker.service
Requires=docker.service

[Service]
ExecStartPre=-/usr/bin/docker rm -f dremio
ExecStart=/usr/bin/docker run --rm --security-opt apparmor=unconfined --name dremio --network host --user $HOST_UID:$HOST_GID --ulimit nofile=65536:65536 -e HOME=/tmp -v /etc/passwd:/etc/passwd:ro -v /etc/group:/etc/group:ro -v /opt/dremio:/opt/dremio -v $STORAGE_PATH:$STORAGE_PATH $input_mount --entrypoint bash $JAVA_IMAGE -c 'exec /opt/dremio/bin/dremio start-fg'
ExecStop=/usr/bin/docker stop dremio
Restart=on-failure
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
EOF
    else
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
    fi
}
