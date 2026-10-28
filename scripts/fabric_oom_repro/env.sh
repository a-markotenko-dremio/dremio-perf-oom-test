# Sourced by the run scripts (make fabric-oom-repro / fabric-oom-func): the repository root as the working directory and
# the environment of the tests: DREMIO_URL of the coordinator, OOM_CONTAINERS (both nodes of the stand, found by their
# data device) and OOM_DATA, the data set of the run (the one of the stand unless OOM_DATA names another directory).
REPO=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)
source "$REPO/scripts/lib/common.sh"
source "$REPO/scripts/lib/cluster.sh"
cd "$REPO"
detect_container_cli
NAME=$(stand_node)
EXECUTOR_HOST=$(default OOM_REPRO_EXECUTOR_HOST)
export DREMIO_URL=http://$(container_ip):9047 OOM_CONTAINERS=$NAME,$EXECUTOR_HOST:$(stand_node "$EXECUTOR_HOST") \
    OOM_DATA=${OOM_DATA:-$(default OOM_REPRO_DATA)}
