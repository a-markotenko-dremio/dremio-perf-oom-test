#!/usr/bin/env bash
# Deploys Dremio into an Incus (or LXC) container and runs the pytest suite against it.
#
# Example:
#   ./deploy_dremio.sh --package ~/dremio-community-26.0.0.tar.gz --java-version 21 \
#       --heap-memory-mb 8192 --direct-memory-mb 16384 --container-memory-mb 28672 \
#       --input s3://minio-host:9000/bucket --storage-path /mnt/ubuntu-var/dremio --dry-run
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
for lib in common image container dremio; do source "$SCRIPT_DIR/scripts/lib/$lib.sh"; done

usage() {
    cat <<EOF
Usage: $0 --package FILE --storage-path DIR [options]

Required:
  --package FILE             Dremio tarball (dremio-*.tar.gz)
  --storage-path DIR         local directory where the test tables are stored; mounted into
                             the container at the same path (STORAGE_PATH for the tests)

Options:
  --java-version N           OpenJDK major version installed in the container (default: 17)
  --heap-memory-mb N         DREMIO_MAX_HEAP_MEMORY_SIZE_MB, an even number (default: 4096)
  --direct-memory-mb N       DREMIO_MAX_DIRECT_MEMORY_SIZE_MB (default: 8192)
  --container-memory-mb N    memory limit of the whole container (default: heap + direct + 2048)
  --input PATH|URL           input data: a local directory (mounted read-only at the same
                             path) or a MinIO/S3 endpoint over TCP (http[s]://host:port[/bucket]
                             or s3://host:port[/bucket]); exported to the tests as INPUT_PATH
  --name NAME                container name (default: d<dremio version>-j<java>-<memory>-<cpus>cpu, e.g. d26-1-8-j21-16G-4cpu)
  --cpus N                   CPU limit of the container (default: unlimited)
  --image IMAGE              base image, used as is (default: a local cached image perf-java<N> with
                             OpenJDK and curl preinstalled, built from images:ubuntu/22.04 for incus
                             or ubuntu:22.04 for lxc on the first run)
  --rebuild-image            rebuild the cached perf-java<N> image (e.g. to pick up JDK updates)
  --java-opts "OPTS"         extra JVM options for the Dremio server (DREMIO_JAVA_SERVER_EXTRA_OPTS in
                             dremio-env), e.g. "-XX:InitiatingHeapOccupancyPercent=90 -XX:+UseParallelGC"
  --gc-log                   write the GC log to /opt/dremio/log/gc.log in the container (-Xlog:gc*, Java 9+)
  --recreate                 delete the container first if it already exists
  --accept-eula              accept the Dremio EULA via POST /apiv2/eula/accept (you confirm
                             that you have read and agree to the license terms)
  --rows N                   number of rows of the generated input table, e.g. 10000000, 10M,
                             1.44G; 1..2147483647 (exported
                             as ROW_COUNT; default: the ROW_COUNT environment variable, else 100000).
                             Data is generated in reusable 10M-row blocks under STORAGE_PATH/blocks
  --allow-shared-storage     do not stop if another running container already mounts the same
                             --storage-path (runs on a shared path overwrite each other's data)
  --dry-run                  deploy and verify the environment, then run pytest in dry-run
                             mode: tests are collected and the environment smoke test runs,
                             but the real test (data generation, queries) is skipped
  -h, --help                 show this help
EOF
}

PACKAGE="" STORAGE_PATH="" INPUT="" IMAGE=""
JAVA_VERSION=17 HEAP_MB=4096 DIRECT_MB=8192 CONTAINER_MB="" CPUS="" NAME=""
JAVA_OPTS="" GC_LOG=0
RECREATE=0 DRY_RUN=0 ACCEPT_EULA=0 REBUILD_IMAGE=0 ROWS="" ALLOW_SHARED=0

# Reads the command line into the variables above.
parse_args() {
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
            --java-opts) JAVA_OPTS=$2; shift 2 ;;
            --gc-log) GC_LOG=1; shift ;;
            --recreate) RECREATE=1; shift ;;
            --rebuild-image) REBUILD_IMAGE=1; shift ;;
            --accept-eula) ACCEPT_EULA=1; shift ;;
            --rows) ROWS=$2; shift 2 ;;
            --allow-shared-storage) ALLOW_SHARED=1; shift ;;
            --dry-run) DRY_RUN=1; shift ;;
            -h|--help) usage; exit 0 ;;
            *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
        esac
    done
}

# Checks the settings and fills in the defaults that depend on each other (rows, JVM options, memory, name).
validate_settings() {
    [[ -n $PACKAGE ]] || { usage >&2; die "--package is required"; }
    [[ -n $STORAGE_PATH ]] || { usage >&2; die "--storage-path is required"; }
    [[ -f $PACKAGE ]] || die "package not found: $PACKAGE"
    [[ $PACKAGE == *.tar.gz || $PACKAGE == *.tgz ]] || die "only tarball packages (.tar.gz) are supported"
    ROWS=${ROWS:-${ROW_COUNT:-}}
    if [[ -n $ROWS ]]; then
        # number with an optional K/M/G suffix (decimal): 10M -> 10000000, 1.44G -> 1440000000
        [[ $ROWS =~ ^([0-9]+(\.[0-9]+)?)([KkMmGg]?)$ ]] \
            || die "--rows must be a number with an optional K/M/G suffix (e.g. 10M, 1.44G), got '$ROWS'"
        case ${BASH_REMATCH[3]} in [Kk]) mult=1000 ;; [Mm]) mult=1000000 ;; [Gg]) mult=1000000000 ;; *) mult=1 ;; esac
        ROWS=$(awk -v v="${BASH_REMATCH[1]}" -v m="$mult" 'BEGIN { printf "%.0f", v * m }')
        (( ROWS >= 1 && ROWS <= 2147483647 )) || die "--rows must be in 1..2147483647 rows, got $ROWS"
    fi
    (( GC_LOG )) && JAVA_OPTS="${JAVA_OPTS:+$JAVA_OPTS }-Xlog:gc*:file=/opt/dremio/log/gc.log:time,uptime:filecount=5,filesize=50m"
    for v in JAVA_VERSION HEAP_MB DIRECT_MB; do
        [[ ${!v} =~ ^[0-9]+$ ]] || die "$v must be a positive integer"
    done
    # The JVM rounds the maximum heap up to a multiple of 2 MB (-Xmx445m runs with 446 MB), so an odd value
    # would silently be the same configuration as the next even one.
    (( HEAP_MB % 2 == 0 )) || die "--heap-memory-mb must be even (got $HEAP_MB): the JVM rounds odd values up to the next even MB"
    CONTAINER_MB=${CONTAINER_MB:-$((HEAP_MB + DIRECT_MB + 2048))}
    [[ $CONTAINER_MB =~ ^[0-9]+$ ]] || die "--container-memory-mb must be an integer"
    (( HEAP_MB + DIRECT_MB < CONTAINER_MB )) \
        || die "heap ($HEAP_MB) + direct ($DIRECT_MB) MB must be less than container memory ($CONTAINER_MB MB)"
    [[ -n $NAME ]] || NAME=$(default_container_name "$PACKAGE" "$JAVA_VERSION" "$CONTAINER_MB" "$CPUS")
}

# --input: local directory -> mounted into the container; URL -> checked over TCP.
resolve_input() {
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
}

parse_args "$@"
validate_settings
detect_container_cli
USE_CACHED_IMAGE=0
if [[ -z $IMAGE ]]; then USE_CACHED_IMAGE=1; IMAGE=perf-java${JAVA_VERSION}; fi
$CT list >/dev/null 2>&1 || die "'$CT list' failed: no access to the daemon (add your user to the incus-admin/lxd group)"

mkdir -p "$STORAGE_PATH"
STORAGE_PATH=$(realpath "$STORAGE_PATH")

resolve_input

HOST_UID=$(id -u) HOST_GID=$(id -g)
(( HOST_UID != 0 )) || die "run as a regular user: Dremio in the container uses your uid for storage access"

# ---------------------------------------------------------------- deployment
ensure_image
check_shared_storage
create_container
wait_for_network
install_java
create_dremio_user
install_dremio
configure_dremio
wait_for_dremio
ensure_admin_user
verify_configuration
run_tests
