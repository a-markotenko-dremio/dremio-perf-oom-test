#!/usr/bin/env bash
# Runs the whole test suite against the Dremio in a container (as created by deploy_dremio.sh):
#   scripts/test_container.sh CONTAINER          (normally via `make test-container CONTAINER=...`)
#
# Reads from the container: its IP, the storage path (unless STORAGE_PATH is set), the heap/direct
# memory limits of the Dremio process, the memory and CPU limits and the JVM version. These go to the
# tests as HEAP_MB, DIRECT_MB, CONTAINER_RAM_MB, CONTAINER_CPUS and JVM_VERSION (see settings.py).
# Environment: ROW_COUNT (default 100000), STORAGE_PATH, PYTHON (default .venv/bin/python), STORAGE (fs or s3, see
# settings.py). With STORAGE=s3 the S3 server of scripts/lib/s3.sh is started unless it runs (the first time takes
# minutes), and the tables of the container go to its bucket, named like the container; STORAGE_PATH then only
# holds the generated data blocks.
set -euo pipefail
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/common.sh"
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/s3.sh"
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.."

CONTAINER=${1:-}
NAME=$CONTAINER   # cx (scripts/lib/common.sh) runs in the container NAME
[[ -n $CONTAINER ]] || { echo "usage: make test-container CONTAINER=<name> [ROW_COUNT=N] [STORAGE_PATH=DIR] [STORAGE=fs|s3]" >&2; exit 2; }
PYTHON=${PYTHON:-.venv/bin/python}
ROW_COUNT=${ROW_COUNT:-100000}
detect_container_cli

IP=$(container_ip || true)
[[ -n $IP ]] || die "cannot get the IP of container $CONTAINER (is it running?)"

STORAGE_PATH=${STORAGE_PATH:-$($CT config device get "$CONTAINER" storage source || true)}
[[ -n $STORAGE_PATH ]] || die "cannot get the storage path of $CONTAINER; pass STORAGE_PATH=DIR"

# The Dremio process: its -Xmx / -XX:MaxDirectMemorySize and the java binary it runs with.
ARGS=$(cx sh -c "ps -eo args | grep '[D]remioDaemon'" || true)
HEAP_MB=$(sed -n 's/.*-Xmx\([0-9]*\)m.*/\1/p' <<<"$ARGS")
DIRECT_MB=$(sed -n 's/.*-XX:MaxDirectMemorySize=\([0-9]*\)m.*/\1/p' <<<"$ARGS")
# The java of the process: in the container, or (Dremio runs in Docker) inside the image of its container.
JAVA_BIN=$(awk '{print $1}' <<<"$ARGS")
if cx test -x "$JAVA_BIN" 2>/dev/null; then
    JAVA_IMAGE=""
    JAVA_OUT=$(cx "$JAVA_BIN" -version 2>&1 || true)
else
    JAVA_IMAGE=$(cx docker inspect --format '{{.Config.Image}}' dremio 2>/dev/null || true)
    JAVA_OUT=$(cx_docker_run --rm --entrypoint "$JAVA_BIN" "$JAVA_IMAGE" -version 2>&1 || true)
fi
JVM_VERSION=$(sed -n 's/.*Runtime Environment.*(build \(.*\))/\1/p' <<<"$JAVA_OUT")

# The container limits ("max" or unreadable: unknown).
LIMIT=$(cx cat /sys/fs/cgroup/memory.max 2>/dev/null || true)
CONTAINER_RAM_MB=""
[[ $LIMIT =~ ^[0-9]+$ ]] && CONTAINER_RAM_MB=$((LIMIT / 1048576))
CONTAINER_CPUS=$(cx nproc 2>/dev/null || true)

if [[ ${STORAGE:-} == s3 ]]; then
    ensure_s3_server
    S3_BUCKET=$CONTAINER
fi

ROWS_LABEL=$("$PYTHON" -c 'import sys, results_report as r; print(r.format_rows(r.parse_rows(sys.argv[1])))' "$ROW_COUNT")
echo "==> $CONTAINER: http://$IP:9047 (storage $STORAGE_PATH${S3_ENDPOINT:+, s3://$S3_ENDPOINT/$S3_BUCKET}, container ${CONTAINER_RAM_MB:-?} MB, cpus ${CONTAINER_CPUS:-?}, heap ${HEAP_MB:-?} MB, direct ${DIRECT_MB:-?} MB, rows $ROWS_LABEL)"

export DREMIO_URL=http://$IP:9047 STORAGE STORAGE_PATH S3_ENDPOINT S3_BUCKET ROW_COUNT HEAP_MB DIRECT_MB JVM_VERSION JAVA_IMAGE CONTAINER_RAM_MB CONTAINER_CPUS
exec "$PYTHON" -m pytest -v -rs tests
