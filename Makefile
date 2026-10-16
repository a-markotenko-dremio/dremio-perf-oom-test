VENV := .venv
PYTHON := $(VENV)/bin/python

.PHONY: test test-container create-container venv clean data

test: $(VENV)/.installed
	$(PYTHON) -m pytest -v -rs test_catalog_sales.py

venv: $(VENV)/.installed

$(VENV)/.installed: requirements.txt
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install -r requirements.txt
	touch $@

clean:
	rm -rf $(VENV) .pytest_cache __pycache__

# Pre-generate the Parquet data blocks (reused by `make test`), e.g.:
#   make data ROW_COUNT=1440000000   (or ROW_COUNT=1.44G; K/M/G suffixes work everywhere)
STORAGE_PATH ?= /mnt/ubuntu-var/dremio
ROW_COUNT ?= 100000
data: $(VENV)/.installed
	$(PYTHON) generate_data.py --rows $(ROW_COUNT) --storage $(STORAGE_PATH)

# PRE_SQL="ALTER SYSTEM SET ...; ..." runs these statements before the test body (see test_catalog_sales.py).
# Run all tests against the Dremio in a container (as created by deploy_dremio.sh), e.g.:
#   make test-container CONTAINER=dremio-j17-d27 ROW_COUNT=10000000
# The container IP, its storage path (unless STORAGE_PATH is given) and the expected heap/direct
# memory limits are read from the container. Give each container its own --storage-path when
# deploying: containers on one path overwrite each other's input/output data.
CT := $(shell command -v incus >/dev/null 2>&1 && echo incus || echo lxc)
test-container: $(VENV)/.installed
	@test -n "$(CONTAINER)" || { echo "usage: make test-container CONTAINER=<name> [ROW_COUNT=N] [STORAGE_PATH=DIR]" >&2; exit 2; }
	@IP=$$($(CT) exec $(CONTAINER) -- hostname -I | awk '{print $$1}'); \
	test -n "$$IP" || { echo "cannot get the IP of container $(CONTAINER) (is it running?)" >&2; exit 1; }; \
	SP="$(if $(filter command line environment,$(origin STORAGE_PATH)),$(STORAGE_PATH),)"; \
	[ -n "$$SP" ] || SP=$$($(CT) config device get $(CONTAINER) storage source); \
	test -n "$$SP" || { echo "cannot get the storage path of $(CONTAINER); pass STORAGE_PATH=DIR" >&2; exit 1; }; \
	ARGS=$$($(CT) exec $(CONTAINER) -- sh -c "ps -eo args | grep '[D]remioDaemon'"); \
	HEAP=$$(echo "$$ARGS" | sed -n 's/.*-Xmx\([0-9]*\)m.*/\1/p'); \
	DIRECT=$$(echo "$$ARGS" | sed -n 's/.*-XX:MaxDirectMemorySize=\([0-9]*\)m.*/\1/p'); \
	LIMIT=$$($(CT) exec $(CONTAINER) -- cat /sys/fs/cgroup/memory.max 2>/dev/null); \
	RAM_MB=""; case "$$LIMIT" in ''|max|*[!0-9]*) ;; *) RAM_MB=$$((LIMIT / 1048576));; esac; \
	CPUS=$$($(CT) exec $(CONTAINER) -- nproc 2>/dev/null); \
	JVM=$$($(CT) exec $(CONTAINER) -- $$(echo "$$ARGS" | awk '{print $$1}') -version 2>&1 | sed -n 's/.*Runtime Environment.*(build \(.*\))/\1/p'); \
	echo "==> $(CONTAINER): http://$$IP:9047 (storage $$SP, container $${RAM_MB:-?} MB, cpus $${CPUS:-?}, heap $${HEAP:-?} MB, direct $${DIRECT:-?} MB, rows $$($(PYTHON) -c 'import results_report as r; print(r.format_rows(r.parse_rows("$(ROW_COUNT)")))'))"; \
	DREMIO_URL=http://$$IP:9047 STORAGE_PATH=$$SP ROW_COUNT=$(ROW_COUNT) \
	HEAP_MB=$$HEAP DIRECT_MB=$$DIRECT JVM_VERSION="$$JVM" CONTAINER_RAM_MB="$$RAM_MB" CONTAINER_CPUS="$$CPUS" \
	$(PYTHON) -m pytest -v -rs test_environment.py test_catalog_sales.py

# Create (deploy) a Dremio container with deploy_dremio.sh, e.g.:
#   make create-container PACKAGE=~/dremio-community-26.0.0.tar.gz JAVA=21 HEAP_MB=8192 DIRECT_MB=16384 CPUS=4
# Optional: NAME, CONTAINER_MB, INPUT, IMAGE, RECREATE=1 (delete an existing container first),
#   JAVA_OPTS="-XX:..." (extra JVM options of Dremio), GC_LOG=1 (GC log in /opt/dremio/log/gc.log).
# STORAGE_PATH defaults to the one used by `make data`; the EULA is accepted (--accept-eula).
JAVA ?= 17
HEAP_MB ?= 4096
DIRECT_MB ?= 8192
create-container:
	@test -n "$(PACKAGE)" || { echo "usage: make create-container PACKAGE=<dremio-*.tar.gz> [STORAGE_PATH=DIR] [JAVA=17] [HEAP_MB=N] [DIRECT_MB=N] [CONTAINER_MB=N] [CPUS=N] [NAME=NAME] [INPUT=PATH|URL] [JAVA_OPTS=OPTS] [GC_LOG=1] [RECREATE=1]" >&2; exit 2; }
	./deploy_dremio.sh --package "$(PACKAGE)" --storage-path "$(STORAGE_PATH)" --java-version "$(JAVA)" \
		--heap-memory-mb "$(HEAP_MB)" --direct-memory-mb "$(DIRECT_MB)" --accept-eula \
		$(if $(CONTAINER_MB),--container-memory-mb "$(CONTAINER_MB)") $(if $(CPUS),--cpus "$(CPUS)") \
		$(if $(NAME),--name "$(NAME)") $(if $(INPUT),--input "$(INPUT)") $(if $(IMAGE),--image "$(IMAGE)") \
		$(if $(JAVA_OPTS),--java-opts "$(JAVA_OPTS)") $(if $(GC_LOG),--gc-log) \
		$(if $(RECREATE),--recreate) $(if $(DRY_RUN),--dry-run)

report: $(VENV)/.installed
	$(VENV)/bin/python3 make_report_svg.py test_results.csv -o report.svg
