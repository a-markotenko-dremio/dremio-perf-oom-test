#!/usr/bin/env bash
# OOM threshold search: for each (heap, direct) pair deploy a 4G container, run the test on growing
# row counts until it fails, then delete the container.
# Combinations already present in test_results.csv (same Dremio version, memory, rows) are skipped;
# a FAIL recorded there ends the row sweep for that pair, just like a fresh failure would.
#
#   ./cyrcle.sh                 run
#   PLAN=1 ./cyrcle.sh          only print what would run / be skipped
cd "$(dirname "$0")" || exit 1

PKG=/mnt/ubuntu-var/dremio/Downloads/dremio-enterprise-26.1.10-202607291955500295-6a7e3d8c.tar.gz
JAVA=21
CONTAINER_MB=4096
C=d26-1-10-j21-4G                       # instance names allow only alphanumerics and hyphens
SP=/mnt/ubuntu-var/dremio/$C
CSV=${REPORT_CSV:-test_results.csv}
HEAP_DIRECT=("2048 1024" "1536 1024" "1024 1024" "1024 512" "768 512")
ROWS=(10M 50M 100M 200M 500M)

CT=$(command -v incus >/dev/null && echo incus || echo lxc)
# "26.1.10-202607291955500295-6a7e3d8c": the Dremio version column of the CSV
VER=$(basename "$PKG" .tar.gz | sed -E 's/^[^0-9]*//')
RAM="$((CONTAINER_MB / 1024))G"

# Prints PASS/FAIL if the CSV already has this combination, nothing otherwise.
recorded() {  # heap direct rows
  [[ -f $CSV ]] || return 0
  python3 -I - "$CSV" "$VER" "$RAM" "$2" "$1" "$3" <<'EOF'
import csv, sys
path, ver, ram, direct, heap, rows = sys.argv[1:]
with open(path, newline="") as f:
    for r in csv.DictReader(f):
        if (r["Dremio ver"], r["Host RAM"], r["DREMIO_MAX_DIRECT_MEMORY_SIZE_MB"],
            r["DREMIO_MAX_HEAP_MEMORY_SIZE_MB"], r["Rows"]) == (ver, ram, direct, heap, rows):
            print(r["Verdict"])
            break
EOF
}

# Rows still to run for a pair: everything after the recorded ones, up to a recorded FAIL.
pending() {  # heap direct
  local rows v
  for rows in "${ROWS[@]}"; do
    v=$(recorded "$1" "$2" "$rows")
    if [[ $v == FAIL ]]; then break; fi
    [[ -n $v ]] || echo "$rows"
  done
}

for cfg in "${HEAP_DIRECT[@]}"; do
  set -- $cfg
  heap=$1 direct=$2
  todo=$(pending "$heap" "$direct")
  echo "### heap=$heap direct=$direct"
  for rows in "${ROWS[@]}"; do
    v=$(recorded "$heap" "$direct" "$rows")
    [[ -n $v ]] && echo "    $rows: already in $CSV ($v)"
    [[ $v == FAIL ]] && break
  done
  if [[ -z $todo ]]; then echo "    nothing to do, skipping"; continue; fi
  echo "    to run: $(echo $todo)"
  [[ -n ${PLAN:-} ]] && continue

  if ./deploy_dremio.sh --package "$PKG" --storage-path "$SP" --java-version "$JAVA" --name "$C" \
       --container-memory-mb "$CONTAINER_MB" --heap-memory-mb "$heap" --direct-memory-mb "$direct" \
       --accept-eula --recreate --dry-run; then
    for rows in $todo; do
      make test-container CONTAINER="$C" ROW_COUNT="$rows" || { echo "FAIL heap=$heap direct=$direct rows=$rows"; break; }
    done
  else
    echo "deploy failed: heap=$heap direct=$direct"
  fi
  $CT delete -f "$C"
done
