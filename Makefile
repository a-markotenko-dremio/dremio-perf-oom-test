VENV := .venv
PYTHON := $(VENV)/bin/python

.PHONY: test test-container create-container venv clean data report scatter fabric-oom fabric-oom-stand fabric-oom-repro fabric-oom-func

test: $(VENV)/.installed
	$(PYTHON) -m pytest -v -rs tests

venv: $(VENV)/.installed

$(VENV)/.installed: requirements.txt
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install -r requirements.txt
	touch $@

clean:
	rm -rf $(VENV) .pytest_cache __pycache__

# Pre-generate the Parquet data blocks (reused by `make test`) in the storage of a container, e.g.:
#   make data CONTAINER=d26-1-8-j21-16G-4cpu ROW_COUNT=1440000000   (or ROW_COUNT=1.44G; K/M/G suffixes work everywhere)
# The storage is STORAGE_PATH when given, else <STORAGE_ROOT of defaults.py>/<CONTAINER>.
ROW_COUNT ?= 100000
data: $(VENV)/.installed
	@test -n "$(STORAGE_PATH)$(CONTAINER)" || { echo "usage: make data CONTAINER=NAME|STORAGE_PATH=DIR [ROW_COUNT=N]" >&2; exit 2; }
	$(PYTHON) generate_data.py --rows $(ROW_COUNT) --storage $(or $(STORAGE_PATH),$(shell python3 -c "import defaults; print(defaults.storage_path('$(CONTAINER)'))"))

# PRE_SQL="ALTER SYSTEM SET ...; ..." runs these statements before the test body (see settings.py).
# Run all tests against the Dremio in a container (as created by deploy_dremio.sh), e.g.:
#   make test-container CONTAINER=dremio-j17-d27 ROW_COUNT=10000000
# The container IP, its storage path (unless STORAGE_PATH is given) and the expected heap/direct
# memory limits are read from the container. Give each container its own --storage-path when
# deploying: containers on one path overwrite each other's input/output data.
test-container: $(VENV)/.installed
	@PYTHON=$(PYTHON) ROW_COUNT=$(ROW_COUNT) scripts/test_container.sh "$(CONTAINER)"

# Create (deploy) a Dremio container with deploy_dremio.sh, e.g.:
#   make create-container PACKAGE=~/dremio-community-26.0.0.tar.gz JAVA=21 HEAP_MB=8192 DIRECT_MB=16384 CPUS=4
# Optional: NAME, CONTAINER_MB, INPUT, IMAGE, RECREATE=1 (delete an existing container first),
#   JAVA_OPTS="-XX:..." (extra JVM options of Dremio), GC_LOG=1 (GC log in /opt/dremio/log/gc.log),
#   HEAP_MB, DIRECT_MB, JAVA=N (OpenJDK major version): the defaults are those of deploy_dremio.sh,
#   JAVA_IMAGE=cgr.dev/chainguard/jdk:latest-dev (run Dremio in Docker with the Java of this image instead of JAVA),
#     or JAVA_IMAGE=wolfi-jdk:21 (built in the container on cgr.dev/chainguard/wolfi-base with OpenJDK 21),
#   DOCKER_CONFIG=~/.docker/config.json (registry credentials for such an image),
#   OVERCOMMIT=1 (allow a container memory limit above the memory of the host).
# STORAGE_PATH defaults to <STORAGE_ROOT of defaults.py>/<container name>; the EULA is accepted (--accept-eula).
create-container:
	@test -n "$(PACKAGE)" || { echo "usage: make create-container PACKAGE=<dremio-*.tar.gz> [STORAGE_PATH=DIR] [JAVA=N] [HEAP_MB=N] [DIRECT_MB=N] [CONTAINER_MB=N] [CPUS=N] [NAME=NAME] [INPUT=PATH|URL] [JAVA_IMAGE=IMAGE] [DOCKER_CONFIG=FILE] [JAVA_OPTS=OPTS] [GC_LOG=1] [RECREATE=1] [OVERCOMMIT=1]" >&2; exit 2; }
	./deploy_dremio.sh --package "$(PACKAGE)" $(if $(STORAGE_PATH),--storage-path "$(STORAGE_PATH)") $(if $(JAVA_IMAGE),--java-image "$(JAVA_IMAGE)",$(if $(JAVA),--java-version "$(JAVA)")) \
		$(if $(HEAP_MB),--heap-memory-mb "$(HEAP_MB)") $(if $(DIRECT_MB),--direct-memory-mb "$(DIRECT_MB)") --accept-eula \
		$(if $(CONTAINER_MB),--container-memory-mb "$(CONTAINER_MB)") $(if $(CPUS),--cpus "$(CPUS)") \
		$(if $(NAME),--name "$(NAME)") $(if $(INPUT),--input "$(INPUT)") $(if $(IMAGE),--image "$(IMAGE)") \
		$(if $(JAVA_OPTS),--java-opts "$(JAVA_OPTS)") $(if $(GC_LOG),--gc-log) $(if $(DOCKER_CONFIG),--docker-config "$(DOCKER_CONFIG)") \
		$(if $(RECREATE),--recreate) $(if $(OVERCOMMIT),--allow-memory-overcommit) $(if $(DRY_RUN),--dry-run)

# The two-host stand of the fabric direct-memory OOM repro (DX-127946) from a Dremio tarball, and its runs (run on the
# coordinator host; the pytest output of every run goes to data/fabric-oom-<case>-<time>.log), e.g.:
#   make fabric-oom TARBALL=/mnt/ubuntu-var/nfs/shared/Downloads/dremio-enterprise-25.2.0-202410241428100111-a963b970.tar.gz
#   make fabric-oom-func RUNS=3                      (fix verification on the stand that is up)
#   make fabric-oom-repro OOM_DATA=/mnt/.../other    (the repro on another data set)
# A run that fails (the repro test fails when the bug does not reproduce) does not stop the next; the exit status is the last failure.
RUNS ?= 3
fabric-oom: fabric-oom-stand fabric-oom-repro

fabric-oom-stand: $(VENV)/.installed
	@test -n "$(TARBALL)" || { echo "usage: make fabric-oom-stand TARBALL=<dremio-*.tar.gz>" >&2; exit 2; }
	scripts/fabric_oom_repro/setup_fabric_oom_stand.sh "$(TARBALL)"

fabric-oom-repro fabric-oom-func: fabric-oom-%: $(VENV)/.installed
	@rc=0; for i in $$(seq $(RUNS)); do \
	    bash -o pipefail -c 'scripts/fabric_oom_repro/run_fabric_oom_$*.sh 2>&1 | tee "data/fabric-oom-$*-$$(date +%Y%m%d-%H%M%S).log"' || rc=$$?; \
	done; exit $$rc

# SVG report of the results, e.g.: make report CSV="data/test_results_den.csv data/test_results_home4.csv"
CSV ?= data/test_results.csv
report: $(VENV)/.installed
	$(PYTHON) -m report.lines data/oom_ranges.csv -o data/oom_lines.svg ; feh data/oom_lines.svg


# PASS/FAIL scatter of three CSV columns (X, Y, verdict: header names), e.g.:
#   make scatter CSV=data/test_results.csv X=Rows Y=DREMIO_MAX_HEAP_MEMORY_SIZE_MB V=Verdict
# K/M/G suffixes in the values are understood and used on the axes.
scatter: $(VENV)/.installed
	@test -n "$(X)" -a -n "$(Y)" -a -n "$(V)" || { echo "usage: make scatter CSV=file.csv X=<col> Y=<col> V=<verdict col> [OUT=scatter.svg]" >&2; exit 2; }
	$(PYTHON) -m report.scatter "$(CSV)" "$(X)" "$(Y)" "$(V)" -o "$(or $(OUT),scatter.svg)"
