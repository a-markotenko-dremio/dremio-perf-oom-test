#!/usr/bin/env bash
# Deploys Dremio into an Incus (or LXC) container and runs the pytest suite against it.
#
# Example:
#   ./deploy_dremio.sh --package ~/dremio-community-26.0.0.tar.gz --java-version 21 \
#       --heap-memory-mb 8192 --direct-memory-mb 16384 --container-memory-mb 28672 \
#       --input s3://minio-host:9000/bucket --storage-path /mnt/ubuntu-var/dremio --dry-run
set -euo pipefail

usage() {
    cat <<EOF
Usage: $0 --package FILE --storage-path DIR [options]

Required:
  --package FILE             Dremio tarball (dremio-*.tar.gz)
  --storage-path DIR         local directory where the test tables are stored; mounted into
                             the container at the same path (STORAGE_PATH for the tests)

Options:
  --java-version N           OpenJDK major version installed in the container (default: 17)
  --heap-memory-mb N         DREMIO_MAX_HEAP_MEMORY_SIZE_MB   (default: 4096)
  --direct-memory-mb N       DREMIO_MAX_DIRECT_MEMORY_SIZE_MB (default: 8192)
  --container-memory-mb N    memory limit of the whole container (default: heap + direct + 2048)
  --input PATH|URL           input data: a local directory (mounted read-only at the same
                             path) or a MinIO/S3 endpoint over TCP (http[s]://host:port[/bucket]
                             or s3://host:port[/bucket]); exported to the tests as INPUT_PATH
  --name NAME                container name (default: dremio-j<java>-d<dremio major>, e.g. dremio-j17-d27)
  --cpus N                   CPU limit of the container (default: unlimited)
  --image IMAGE              base image, used as is (default: a local cached image perf-java<N> with
                             OpenJDK and curl preinstalled, built from images:ubuntu/22.04 for incus
                             or ubuntu:22.04 for lxc on the first run)
  --rebuild-image            rebuild the cached perf-java<N> image (e.g. to pick up JDK updates)
  --recreate                 delete the container first if it already exists
  --accept-eula              accept the Dremio EULA via POST /apiv2/eula/accept (you confirm
                             that you have read and agree to the license terms)
  --dry-run                  deploy and verify the environment, then run pytest in dry-run
                             mode: tests are collected and the environment smoke test runs,
                             but the real test (data generation, queries) is skipped
  -h, --help                 show this help
EOF
}

PACKAGE="" STORAGE_PATH="" INPUT="" IMAGE=""
JAVA_VERSION=17 HEAP_MB=4096 DIRECT_MB=8192 CONTAINER_MB="" CPUS="" NAME=""
RECREATE=0 DRY_RUN=0 ACCEPT_EULA=0 REBUILD_IMAGE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --package) PACKAGE=$2; shift 2 ;;
        --storage-path) STORAGE_PATH=$2; shift 2 ;;
        --java-version) JAVA_VERSION=$2; shift 2 ;;
        --heap-memory-mb) HEAP_MB=$2; shift 2 ;;
        --direct-memory-mb) DIRECT_MB=$2; shift 2 ;;
        --container-memory-mb) CONTAINER_MB=$2; shift 2 ;;
        --input) INPUT=$2; shift 2 ;;
        --name) NAME=$2; shift 2 ;;
        --cpus) CPUS=$2; shift 2 ;;
        --image) IMAGE=$2; shift 2 ;;
        --recreate) RECREATE=1; shift ;;
        --rebuild-image) REBUILD_IMAGE=1; shift ;;
        --accept-eula) ACCEPT_EULA=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

log() { echo "==> $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

[[ -n $PACKAGE ]] || { usage >&2; die "--package is required"; }
[[ -n $STORAGE_PATH ]] || { usage >&2; die "--storage-path is required"; }
[[ -f $PACKAGE ]] || die "package not found: $PACKAGE"
[[ $PACKAGE == *.tar.gz || $PACKAGE == *.tgz ]] || die "only tarball packages (.tar.gz) are supported"
for v in JAVA_VERSION HEAP_MB DIRECT_MB; do
    [[ ${!v} =~ ^[0-9]+$ ]] || die "$v must be a positive integer"
done
# Default container name: dremio-j<java>-d<dremio major version from the package file name>
if [[ -z $NAME ]]; then
    NAME=dremio-j${JAVA_VERSION}
    [[ $(basename "$PACKAGE") =~ -([0-9]+)\.[0-9]+\.[0-9]+ ]] && NAME+=-d${BASH_REMATCH[1]}
fi
CONTAINER_MB=${CONTAINER_MB:-$((HEAP_MB + DIRECT_MB + 2048))}
[[ $CONTAINER_MB =~ ^[0-9]+$ ]] || die "--container-memory-mb must be an integer"
(( HEAP_MB + DIRECT_MB < CONTAINER_MB )) \
    || die "heap ($HEAP_MB) + direct ($DIRECT_MB) MB must be less than container memory ($CONTAINER_MB MB)"

if command -v incus >/dev/null; then CT=incus; DEFAULT_IMAGE=images:ubuntu/22.04
elif command -v lxc >/dev/null; then CT=lxc; DEFAULT_IMAGE=ubuntu:22.04
else die "neither incus nor lxc found in PATH"; fi
USE_CACHED_IMAGE=0
if [[ -z $IMAGE ]]; then USE_CACHED_IMAGE=1; IMAGE=perf-java${JAVA_VERSION}; fi
$CT list >/dev/null 2>&1 || die "'$CT list' failed: no access to the daemon (add your user to the incus-admin/lxd group)"

mkdir -p "$STORAGE_PATH"
STORAGE_PATH=$(realpath "$STORAGE_PATH")

# --input: local directory -> mounted into the container; URL -> checked over TCP.
INPUT_DIR="" INPUT_PATH_ENV=""
if [[ -n $INPUT ]]; then
    if [[ $INPUT =~ ^(https?|s3)://([^/:]+)(:([0-9]+))?(/.*)?$ ]]; then
        host=${BASH_REMATCH[2]}
        port=${BASH_REMATCH[4]:-$([[ ${BASH_REMATCH[1]} == https ]] && echo 443 || echo 9000)}
        timeout 5 bash -c "exec 3<>/dev/tcp/$host/$port" 2>/dev/null \
            || die "MinIO endpoint $host:$port is not reachable over TCP"
        INPUT_PATH_ENV=$INPUT
    else
        [[ -d $INPUT ]] || die "input directory not found: $INPUT"
        INPUT_DIR=$(realpath "$INPUT")
        INPUT_PATH_ENV=$INPUT_DIR
    fi
fi

HOST_UID=$(id -u) HOST_GID=$(id -g)
(( HOST_UID != 0 )) || die "run as a regular user: Dremio in the container uses your uid for storage access"

# ---------------------------------------------------------------- cached base image
# Ubuntu + OpenJDK + curl, built once and reused, so that every deployment skips the apt install.
if (( USE_CACHED_IMAGE )); then
    if (( REBUILD_IMAGE )) && $CT image info "$IMAGE" >/dev/null 2>&1; then
        log "Deleting cached image $IMAGE"
        $CT image delete "$IMAGE"
    fi
    if ! $CT image info "$IMAGE" >/dev/null 2>&1; then
        BUILD="${IMAGE}-build"
        $CT info "$BUILD" >/dev/null 2>&1 && $CT delete --force "$BUILD"
        log "Building image $IMAGE from $DEFAULT_IMAGE (one-time)"
        build_image() {
            $CT launch "$DEFAULT_IMAGE" "$BUILD" || return 1
            local bx=("$CT" exec "$BUILD" --)
            for _ in $(seq 60); do "${bx[@]}" getent hosts archive.ubuntu.com >/dev/null 2>&1 && break; sleep 2; done
            "${bx[@]}" getent hosts archive.ubuntu.com >/dev/null 2>&1 || return 1
            "${bx[@]}" apt-get update -qq || return 1
            "${bx[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
                "openjdk-${JAVA_VERSION}-jdk-headless" curl ca-certificates || return 1
            "${bx[@]}" apt-get clean || return 1
            $CT stop "$BUILD" || return 1
            $CT publish "$BUILD" --alias "$IMAGE" || return 1
        }
        if ! build_image; then
            $CT delete --force "$BUILD" >/dev/null 2>&1 || true
            die "cannot build image $IMAGE (is openjdk-${JAVA_VERSION}-jdk-headless available?)"
        fi
        $CT delete --force "$BUILD"
    fi
fi

# ---------------------------------------------------------------- container
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

cx() { $CT exec "$NAME" -- "$@"; }

log "Waiting for container network"
for _ in $(seq 60); do cx getent hosts archive.ubuntu.com >/dev/null 2>&1 && break; sleep 2; done
cx getent hosts archive.ubuntu.com >/dev/null 2>&1 || die "container has no network/DNS"

# ---------------------------------------------------------------- Java + Dremio
if cx bash -c "ls /usr/lib/jvm/java-${JAVA_VERSION}-openjdk-*/bin/java && command -v curl" >/dev/null 2>&1; then
    log "OpenJDK $JAVA_VERSION already in the image"
else
    log "Installing OpenJDK $JAVA_VERSION"
    cx apt-get update -qq
    cx env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "openjdk-${JAVA_VERSION}-jdk-headless" curl ca-certificates \
        || die "cannot install openjdk-${JAVA_VERSION}-jdk-headless (not available in this image?)"
fi
JAVA_HOME_DIR=$(cx bash -c "dirname \$(dirname \$(readlink -f \$(ls /usr/lib/jvm/java-${JAVA_VERSION}-openjdk-*/bin/java | head -1)))")

log "Creating user dremio ($HOST_UID:$HOST_GID)"
cx bash -c "id ubuntu >/dev/null 2>&1 && userdel -r ubuntu 2>/dev/null; \
    getent group $HOST_GID >/dev/null || groupadd -g $HOST_GID dremio; \
    useradd -u $HOST_UID -g $HOST_GID -m -d /home/dremio -s /usr/sbin/nologin dremio"

log "Installing Dremio from $(basename "$PACKAGE")"
$CT file push "$PACKAGE" "$NAME/tmp/dremio.tar.gz"
cx bash -c "mkdir -p /opt/dremio && tar -xzf /tmp/dremio.tar.gz -C /opt/dremio --strip-components=1 && rm /tmp/dremio.tar.gz"
cx test -x /opt/dremio/bin/dremio || die "bin/dremio not found: unexpected tarball layout"

log "Configuring dremio-env (heap ${HEAP_MB}MB, direct ${DIRECT_MB}MB, JAVA_HOME $JAVA_HOME_DIR)"
cx bash -c "
    f=/opt/dremio/conf/dremio-env
    touch \$f
    sed -i -E '/^(export )?(DREMIO_MAX_HEAP_MEMORY_SIZE_MB|DREMIO_MAX_DIRECT_MEMORY_SIZE_MB|JAVA_HOME)=/d' \$f
    {
        echo 'DREMIO_MAX_HEAP_MEMORY_SIZE_MB=$HEAP_MB'
        echo 'DREMIO_MAX_DIRECT_MEMORY_SIZE_MB=$DIRECT_MB'
        echo 'JAVA_HOME=$JAVA_HOME_DIR'
    } >> \$f
    chown -R dremio:$HOST_GID /opt/dremio
"

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

# ---------------------------------------------------------------- wait + verify
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

DREMIO_USER=${DREMIO_USER:-dremio} DREMIO_PASSWORD=${DREMIO_PASSWORD:-dremio123}
if ! curl -fsS "$DREMIO_URL/apiv2/login" -H 'Content-Type: application/json' \
        -d "{\"userName\":\"$DREMIO_USER\",\"password\":\"$DREMIO_PASSWORD\"}" >/dev/null 2>&1; then
    log "Creating admin user $DREMIO_USER"
    curl -fsS -X PUT "$DREMIO_URL/apiv2/bootstrap/firstuser" \
        -H 'Content-Type: application/json' -H 'Authorization: _dremionull' \
        -d "{\"userName\":\"$DREMIO_USER\",\"firstName\":\"perf\",\"lastName\":\"test\",\"email\":\"perf@example.com\",\"createdAt\":$(date +%s)000,\"password\":\"$DREMIO_PASSWORD\"}" \
        >/dev/null || die "cannot create the first Dremio user"
fi

log "Verifying running configuration"
args=$(cx bash -c "ps -eo args | grep '[D]remioDaemon' || true")
[[ -n $args ]] || die "Dremio java process not found"
grep -qE -- "-Xmx${HEAP_MB}m( |$)" <<<"$args" || die "java is not running with -Xmx${HEAP_MB}m"
grep -qE -- "-XX:MaxDirectMemorySize=${DIRECT_MB}m( |$)" <<<"$args" || die "java is not running with MaxDirectMemorySize=${DIRECT_MB}m"
java_out=$(cx "$JAVA_HOME_DIR/bin/java" -version 2>&1) || die "cannot run $JAVA_HOME_DIR/bin/java"
grep -qE "version \"($JAVA_VERSION|1\.$JAVA_VERSION)[.\"]" <<<"$java_out" \
    || die "java $JAVA_VERSION is not the active JVM"
[[ $(cx cat /sys/fs/cgroup/memory.max) == $((CONTAINER_MB * 1024 * 1024)) ]] \
    || die "container memory limit is not ${CONTAINER_MB}MiB"
cx runuser -u dremio -- test -w "$STORAGE_PATH" || die "dremio user cannot write to $STORAGE_PATH"
log "Configuration OK"

# ---------------------------------------------------------------- tests
cd "$(dirname "$(readlink -f "$0")")"
make venv
export DREMIO_URL DREMIO_USER DREMIO_PASSWORD STORAGE_PATH
export HEAP_MB DIRECT_MB
[[ -n $INPUT_PATH_ENV ]] && export INPUT_PATH=$INPUT_PATH_ENV
pytest_args=(-v -rs test_environment.py test_catalog_sales.py)
(( DRY_RUN )) && pytest_args+=(--dry-run)

log "Running pytest$([[ $DRY_RUN == 1 ]] && echo ' (dry-run)') against $DREMIO_URL"
.venv/bin/python -m pytest "${pytest_args[@]}"
