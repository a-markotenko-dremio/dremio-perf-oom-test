VENV := .venv
PYTHON := $(VENV)/bin/python

.PHONY: test test-container venv clean data

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
#   make data ROW_COUNT=1440000000
STORAGE_PATH ?= /mnt/ubuntu-var/dremio
ROW_COUNT ?= 100000
data: $(VENV)/.installed
	$(PYTHON) generate_data.py --rows $(ROW_COUNT) --storage $(STORAGE_PATH)

# Run all tests against the Dremio in a container (as created by deploy_dremio.sh), e.g.:
#   make test-container CONTAINER=dremio-j17-d27 ROW_COUNT=10000000
# The container IP and the expected heap/direct memory limits are read from the container.
CT := $(shell command -v incus >/dev/null 2>&1 && echo incus || echo lxc)
test-container: $(VENV)/.installed
	@test -n "$(CONTAINER)" || { echo "usage: make test-container CONTAINER=<name> [ROW_COUNT=N] [STORAGE_PATH=DIR]" >&2; exit 2; }
	@IP=$$($(CT) exec $(CONTAINER) -- hostname -I | awk '{print $$1}'); \
	test -n "$$IP" || { echo "cannot get the IP of container $(CONTAINER) (is it running?)" >&2; exit 1; }; \
	ARGS=$$($(CT) exec $(CONTAINER) -- sh -c "ps -eo args | grep '[D]remioDaemon'"); \
	HEAP=$$(echo "$$ARGS" | sed -n 's/.*-Xmx\([0-9]*\)m.*/\1/p'); \
	DIRECT=$$(echo "$$ARGS" | sed -n 's/.*-XX:MaxDirectMemorySize=\([0-9]*\)m.*/\1/p'); \
	echo "==> $(CONTAINER): http://$$IP:9047 (heap $${HEAP:-?} MB, direct $${DIRECT:-?} MB, rows $(ROW_COUNT))"; \
	DREMIO_URL=http://$$IP:9047 STORAGE_PATH=$(STORAGE_PATH) ROW_COUNT=$(ROW_COUNT) \
	HEAP_MB=$$HEAP DIRECT_MB=$$DIRECT \
	$(PYTHON) -m pytest -v -rs test_environment.py test_catalog_sales.py
