# Sourced by the run scripts: the repository root as the working directory, DREMIO_URL of the coordinator container,
# STORAGE_PATH of the stand and OOM_DATA, the data set of the run: the one setup_fabric_oom_stand.sh generates unless
# another directory of the storage is given (OOM_DATA=qa-oom-repro.other scripts/fabric_oom_repro/run_fabric_oom_repro.sh).
REPO=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)
source "$REPO/scripts/lib/common.sh"
cd "$REPO"
NAME=$(default OOM_REPRO_COORDINATOR)
detect_container_cli
export DREMIO_URL=http://$(container_ip):9047 STORAGE_PATH=$(default OOM_REPRO_STORAGE) OOM_DATA=${OOM_DATA:-$(default OOM_REPRO_SUBDIR)}
