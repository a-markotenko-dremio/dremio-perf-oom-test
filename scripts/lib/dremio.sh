# Sourced by deploy_dremio.sh. Waits for Dremio, checks how it runs and runs the tests against it.

# Sets IP and DREMIO_URL and waits until Dremio answers (accepting the EULA with --accept-eula).
wait_for_dremio() {
    IP=$(cx hostname -I | awk '{print $1}')
    [[ -n $IP ]] || die "cannot determine container IP"
    DREMIO_URL="http://$IP:9047"
    log "Waiting for Dremio at $DREMIO_URL"
    for _ in $(seq 180); do
        if (( ACCEPT_EULA )); then
            curl -fsS -X POST "$DREMIO_URL/apiv2/eula/accept" >/dev/null 2>&1 || true
        elif curl -sS "$DREMIO_URL/apiv2/server_status" 2>/dev/null | grep -q "EULA has not been accepted"; then
            die "Dremio EULA has not been accepted: re-run with --accept-eula (you agree to the Dremio license terms), or accept it in the web UI at $DREMIO_URL and re-run with --recreate"
        fi
        curl -fsS "$DREMIO_URL/apiv2/server_status" 2>/dev/null | grep -q OK && break
        sleep 5
    done
    curl -fsS "$DREMIO_URL/apiv2/server_status" 2>/dev/null | grep -q OK \
        || die "Dremio did not become ready in 15 min (see: $CT exec $NAME -- journalctl -u dremio)"
}

# Logs in as DREMIO_USER, creating that first user when Dremio is new.
ensure_admin_user() {
    DREMIO_USER=${DREMIO_USER:-dremio} DREMIO_PASSWORD=${DREMIO_PASSWORD:-dremio123}
    if ! curl -fsS "$DREMIO_URL/apiv2/login" -H 'Content-Type: application/json' \
            -d "{\"userName\":\"$DREMIO_USER\",\"password\":\"$DREMIO_PASSWORD\"}" >/dev/null 2>&1; then
        log "Creating admin user $DREMIO_USER"
        curl -fsS -X PUT "$DREMIO_URL/apiv2/bootstrap/firstuser" \
            -H 'Content-Type: application/json' -H 'Authorization: _dremionull' \
            -d "{\"userName\":\"$DREMIO_USER\",\"firstName\":\"perf\",\"lastName\":\"test\",\"email\":\"perf@example.com\",\"createdAt\":$(date +%s)000,\"password\":\"$DREMIO_PASSWORD\"}" \
            >/dev/null || die "cannot create the first Dremio user"
    fi
}

# Checks the running JVM, container memory and storage access against what was asked for.
verify_configuration() {
    log "Verifying running configuration"
    args=$(cx bash -c "ps -eo args | grep '[D]remioDaemon' || true")
    [[ -n $args ]] || die "Dremio java process not found"
    grep -qE -- "-Xmx${HEAP_MB}m( |$)" <<<"$args" || die "java is not running with -Xmx${HEAP_MB}m"
    grep -qE -- "-XX:MaxDirectMemorySize=${DIRECT_MB}m( |$)" <<<"$args" || die "java is not running with MaxDirectMemorySize=${DIRECT_MB}m"
    if [[ -n $JAVA_OPTS ]]; then
        for opt in $JAVA_OPTS; do
            grep -qF -- "$opt" <<<"$args" || die "java is not running with $opt"
        done
    fi
    java_out=$(run_java -version 2>&1) || die "cannot run $JAVA_HOME_DIR/bin/java"
    if [[ -z $JAVA_IMAGE ]]; then
        grep -qE "version \"($JAVA_VERSION|1\.$JAVA_VERSION)[.\"]" <<<"$java_out" \
            || die "java $JAVA_VERSION is not the active JVM"
    fi
    [[ $(cx cat /sys/fs/cgroup/memory.max) == $((CONTAINER_MB * 1024 * 1024)) ]] \
        || die "container memory limit is not ${CONTAINER_MB}MiB"
    cx runuser -u dremio -- test -w "$STORAGE_PATH" || die "dremio user cannot write to $STORAGE_PATH"
    log "Configuration OK"
}

# Runs the pytest suite (only the smoke tests with --dry-run) against the new Dremio.
run_tests() {
    cd "$(dirname "$(readlink -f "$0")")"
    make venv
    export DREMIO_URL DREMIO_USER DREMIO_PASSWORD STORAGE_PATH
    export HEAP_MB DIRECT_MB JAVA_IMAGE
    export CONTAINER_RAM_MB=$CONTAINER_MB
    export CONTAINER_CPUS=$(cx nproc)
    JVM_VERSION=$(sed -n 's/.*Runtime Environment.*(build \(.*\))/\1/p' <<<"$java_out"); export JVM_VERSION
    [[ -n $ROWS ]] && export ROW_COUNT=$ROWS
    [[ -n $INPUT_PATH_ENV ]] && export INPUT_PATH=$INPUT_PATH_ENV
    pytest_args=(-v -rs tests)
    (( DRY_RUN )) && pytest_args+=(--dry-run)

    log "Running pytest$([[ $DRY_RUN == 1 ]] && echo ' (dry-run)') against $DREMIO_URL"
    .venv/bin/python -m pytest "${pytest_args[@]}"
}
