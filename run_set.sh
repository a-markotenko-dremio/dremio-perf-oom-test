#!/bin/sh
memsize=$1
rows=$2
export REPORT_CSV=test_results.csv 
P1=/mnt/ubuntu-var/dremio/Downloads/dremio-enterprise-26.1.8-202605070149260956-31448f13.tar.gz
P2=/mnt/ubuntu-var/dremio/Downloads/dremio-enterprise-26.1.10-202607291955500295-6a7e3d8c.tar.gz

run_set(){
	sz=$1
	rws=$2
	PKG=$P1 CONTAINER_MB=16384 PAIRS="$sz 8192" ROWS="$rws" bash cyrcle.sh 
	PKG=$P2 CONTAINER_MB=16384 PAIRS="$sz 8192" ROWS="$rws" bash cyrcle.sh 
}

# Runs both packages with `heap` and `rows` (say 350M), then reads the last two runs of the CSV (one per
# package) and prints PASS if both passed, else FAIL: one failed run is enough to call the size failing.
# Stops with an error when the last two runs are not these two (a deploy failed, or cyrcle.sh skipped them
# because they are already recorded and an older run sits at the end of the file).
check_rows() {
	heap=$1
	rows=$2
	run_set "$heap" "$rows" >&2
	[ -f "$REPORT_CSV" ] || { echo "$REPORT_CSV does not exist: no run was recorded" >&2; return 1; }
	runs=$(python3 -I scripts/last_runs.py "$REPORT_CSV" 2) || return 1
	[ "$(echo "$runs" | wc -l)" -eq 2 ] || { echo "less than two runs in $REPORT_CSV" >&2; return 1; }
	verdict=PASS
	for run in $runs; do
		r=$(echo "$run" | cut -d, -f1); h=$(echo "$run" | cut -d, -f2); v=$(echo "$run" | cut -d, -f4)
		if [ "$r" != "$rows" ] || [ "$h" != "$heap" ]; then
			echo "the last run in $REPORT_CSV is rows=$r heap=$h, expected rows=$rows heap=$heap: not run, or skipped as already recorded" >&2
			return 1
		fi
		[ "$v" = PASS ] || verdict=FAIL
	done
	echo "$verdict"
}

# Binary search of the row count (in millions) where the tests start to fail, with a fixed heap:
#   search_rows HEAP [LOW [HIGH [PRECISION]]]      (default 300 500 10: the answer is within 10M rows)
# The next row count is the middle of [LOW, HIGH]: PASS moves LOW up to it, FAIL moves HIGH down to it.
# If nothing failed, HIGH itself is run at the end; if nothing passed, LOW is run.
search_rows() {
	heap=$1
	lo=${2:-300}
	hi=${3:-500}
	precision=${4:-10}
	seen_pass=0
	seen_fail=0
	while [ $((hi - lo)) -gt "$precision" ]; do
		mid=$(( (lo + hi) / 2 ))
		echo "== heap=$heap: range ${lo}M..${hi}M, running ${mid}M"
		verdict=$(check_rows "$heap" "${mid}M") || { echo "search stopped" >&2; return 1; }
		echo "== ${mid}M: $verdict"
		if [ "$verdict" = PASS ]; then lo=$mid; seen_pass=1; else hi=$mid; seen_fail=1; fi
	done
	if [ $seen_fail -eq 0 ]; then
		echo "== nothing failed so far, checking the upper end ${hi}M"
		verdict=$(check_rows "$heap" "${hi}M") || return 1
		[ "$verdict" = PASS ] && { echo "RESULT heap=$heap: no failure up to ${hi}M"; return 0; }
	elif [ $seen_pass -eq 0 ]; then
		echo "== nothing passed so far, checking the lower end ${lo}M"
		verdict=$(check_rows "$heap" "${lo}M") || return 1
		[ "$verdict" = FAIL ] && { echo "RESULT heap=$heap: fails already at ${lo}M"; return 0; }
	fi
	echo "RESULT heap=$heap: passes at ${lo}M, fails at ${hi}M (within ${precision}M rows)"
}

#run_set $memsize $rows
search_rows "${memsize:-512}" "${LOW:-300}" "${HIGH:-500}" "${PRECISION:-10}"
