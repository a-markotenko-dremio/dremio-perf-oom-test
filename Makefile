VENV := .venv
PYTHON := $(VENV)/bin/python

.PHONY: test test-container create-container venv clean data oom report report-fs report-s3 scatter fabric-oom fabric-oom-stand fabric-oom-repro fabric-oom-func fabric-oom-feature fabric-oom-clean fabric-oom-report

test: $(VENV)/.installed
	$(PYTHON) -m pytest -v -rs tests

venv: $(VENV)/.installed

$(VENV)/.installed: requirements.txt
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install -r requirements.txt
	touch $@

clean:
	rm -rf $(VENV) .pytest_cache __pycache__

ROW_COUNT ?= 100000
data: $(VENV)/.installed
	@test -n "$(STORAGE_PATH)$(CONTAINER)" || { echo "usage: make data CONTAINER=NAME|STORAGE_PATH=DIR [ROW_COUNT=N]" >&2; exit 2; }
	$(PYTHON) generate_data.py --rows $(ROW_COUNT) --storage $(or $(STORAGE_PATH),$(shell python3 -c "import defaults; print(defaults.storage_path('$(CONTAINER)'))"))

test-container: $(VENV)/.installed
	@PYTHON=$(PYTHON) ROW_COUNT=$(ROW_COUNT) scripts/test_container.sh "$(CONTAINER)"

create-container:
	@test -n "$(PACKAGE)" || { echo "usage: make create-container PACKAGE=<dremio-*.tar.gz> [STORAGE_PATH=DIR] [JAVA=N] [HEAP_MB=N] [DIRECT_MB=N] [CONTAINER_MB=N] [CPUS=N] [NAME=NAME] [INPUT=PATH|URL] [JAVA_IMAGE=IMAGE] [DOCKER_CONFIG=FILE] [JAVA_OPTS=OPTS] [GC_LOG=1] [RECREATE=1] [OVERCOMMIT=1]" >&2; exit 2; }
	./deploy_dremio.sh --package "$(PACKAGE)" $(if $(STORAGE_PATH),--storage-path "$(STORAGE_PATH)") $(if $(JAVA_IMAGE),--java-image "$(JAVA_IMAGE)",$(if $(JAVA),--java-version "$(JAVA)")) \
		$(if $(HEAP_MB),--heap-memory-mb "$(HEAP_MB)") $(if $(DIRECT_MB),--direct-memory-mb "$(DIRECT_MB)") --accept-eula \
		$(if $(CONTAINER_MB),--container-memory-mb "$(CONTAINER_MB)") $(if $(CPUS),--cpus "$(CPUS)") \
		$(if $(NAME),--name "$(NAME)") $(if $(INPUT),--input "$(INPUT)") $(if $(IMAGE),--image "$(IMAGE)") \
		$(if $(JAVA_OPTS),--java-opts "$(JAVA_OPTS)") $(if $(GC_LOG),--gc-log) $(if $(DOCKER_CONFIG),--docker-config "$(DOCKER_CONFIG)") \
		$(if $(RECREATE),--recreate) $(if $(OVERCOMMIT),--allow-memory-overcommit) $(if $(DRY_RUN),--dry-run)

RUNS ?= 3
fabric-oom: fabric-oom-stand fabric-oom-repro

fabric-oom-stand: $(VENV)/.installed
	@test -n "$(TARBALL)" || { echo "usage: make fabric-oom-stand TARBALL=<dremio-*.tar.gz>" >&2; exit 2; }
	scripts/fabric_oom_repro/setup_fabric_oom_stand.sh "$(TARBALL)"

fabric-oom-repro fabric-oom-func fabric-oom-feature: fabric-oom-%: $(VENV)/.installed
	@rc=0; for i in $$(seq $(RUNS)); do \
	    bash -o pipefail -c 'scripts/fabric_oom_repro/run_fabric_oom_$*.sh 2>&1 | tee "data/fabric-oom-$*-$$(date +%Y%m%d-%H%M%S).log"' || rc=$$?; \
	done; exit $$rc

fabric-oom-clean:
	scripts/fabric_oom_repro/clean_fabric_oom_stand.sh

fabric-oom-report: $(VENV)/.installed
	$(PYTHON) -m fabric_oom_repro.run_table data


CSV ?= data/test_results.csv
storage_file = $(shell python3 -c "import defaults; print(defaults.storage_file('$(1)', '$(2)'))")
oom: $(VENV)/.installed
	$(PYTHON) oom_ranges.py $(if $(STORAGE),--storage $(STORAGE)) $(OOM_ARGS)

report: $(foreach s,fs s3,$(if $(wildcard $(call storage_file,oom_ranges.csv,$(s))),report-$(s)))

report-fs report-s3: report-%: $(VENV)/.installed
	$(PYTHON) -m report.lines $(call storage_file,oom_ranges.csv,$*) -o $(call storage_file,oom_lines.svg,$*) ; feh $(call storage_file,oom_lines.svg,$*)

scatter: $(VENV)/.installed
	@test -n "$(X)" -a -n "$(Y)" -a -n "$(V)" || { echo "usage: make scatter CSV=file.csv X=<col> Y=<col> V=<verdict col> [OUT=scatter.svg]" >&2; exit 2; }
	$(PYTHON) -m report.scatter "$(CSV)" "$(X)" "$(Y)" "$(V)" -o "$(or $(OUT),scatter.svg)"
