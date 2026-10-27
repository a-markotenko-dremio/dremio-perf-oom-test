# Sourced by the run scripts: the repository root as the working directory and DREMIO_URL of the coordinator container.
REPO=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)
source "$REPO/scripts/lib/common.sh"
cd "$REPO"
NAME=$(python3 -c "import defaults; print(defaults.OOM_REPRO_COORDINATOR)")
detect_container_cli
export DREMIO_URL=http://$(container_ip):9047
