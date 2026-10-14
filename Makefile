VENV := .venv
PYTHON := $(VENV)/bin/python

.PHONY: test venv clean data

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
