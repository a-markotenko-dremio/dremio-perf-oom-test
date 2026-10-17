VENV := .venv
PYTHON := $(VENV)/bin/python

.PHONY: test test-container create-container venv clean data report scatter

test: $(VENV)/.installed
	$(PYTHON) -m pytest -v -rs tests

venv: $(VENV)/.installed

$(VENV)/.installed: requirements.txt
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install -r requirements.txt
	touch $@

clean:
	rm -rf $(VENV) .pytest_cache __pycache__

# Pre-generate the Parquet data blocks (reused by `make test`), e.g.:
#   make data ROW_COUNT=1440000000   (or ROW_COUNT=1.44G; K/M/G suffixes work everywhere)
STORAGE_PATH ?= $(shell python3 -c "import defaults; print(defaults.STORAGE_ROOT)")
ROW_COUNT ?= 100000
data: $(VENV)/.installed
	$(PYTHON) generate_data.py --rows $(ROW_COUNT) --storage $(STORAGE_PATH)

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
# STORAGE_PATH defaults to the one used by `make data`; the EULA is accepted (--accept-eula).
create-container:
	@test -n "$(PACKAGE)" || { echo "usage: make create-container PACKAGE=<dremio-*.tar.gz> [STORAGE_PATH=DIR] [JAVA=N] [HEAP_MB=N] [DIRECT_MB=N] [CONTAINER_MB=N] [CPUS=N] [NAME=NAME] [INPUT=PATH|URL] [JAVA_IMAGE=IMAGE] [DOCKER_CONFIG=FILE] [JAVA_OPTS=OPTS] [GC_LOG=1] [RECREATE=1] [OVERCOMMIT=1]" >&2; exit 2; }
	./deploy_dremio.sh --package "$(PACKAGE)" --storage-path "$(STORAGE_PATH)" $(if $(JAVA_IMAGE),--java-image "$(JAVA_IMAGE)",$(if $(JAVA),--java-version "$(JAVA)")) \
		$(if $(HEAP_MB),--heap-memory-mb "$(HEAP_MB)") $(if $(DIRECT_MB),--direct-memory-mb "$(DIRECT_MB)") --accept-eula \
		$(if $(CONTAINER_MB),--container-memory-mb "$(CONTAINER_MB)") $(if $(CPUS),--cpus "$(CPUS)") \
		$(if $(NAME),--name "$(NAME)") $(if $(INPUT),--input "$(INPUT)") $(if $(IMAGE),--image "$(IMAGE)") \
		$(if $(JAVA_OPTS),--java-opts "$(JAVA_OPTS)") $(if $(GC_LOG),--gc-log) $(if $(DOCKER_CONFIG),--docker-config "$(DOCKER_CONFIG)") \
		$(if $(RECREATE),--recreate) $(if $(OVERCOMMIT),--allow-memory-overcommit) $(if $(DRY_RUN),--dry-run)

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
