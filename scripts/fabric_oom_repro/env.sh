# Sourced by the run scripts: the repository root as the working directory, DREMIO_URL of the coordinator container
# and STORAGE_PATH of the stand.
REPO=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)
source "$REPO/scripts/lib/common.sh"
cd "$REPO"
NAME=$(default OOM_REPRO_COORDINATOR)
detect_container_cli
export DREMIO_URL=http://$(container_ip):9047 STORAGE_PATH=$(default OOM_REPRO_STORAGE)
