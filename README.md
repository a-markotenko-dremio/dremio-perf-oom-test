# perf-dremio

Performance tests of Dremio: the OOM frontier search, deployment into Incus/LXD containers, reports.
Settings of the tests are environment variables, described in `settings.py`; shared locations and defaults are in `defaults.py`.

Offline tests (no Dremio needed): `make test` runs the whole suite, which skips the tests that need Dremio when it is
not reachable; or `.venv/bin/python -m pytest tests`.

## Storage: files, S3 or HDFS

The tables of a test run (`input/` and `output/`) live in files, in a bucket of an S3 server or in a directory of an HDFS:

| `STORAGE` | where the tables are | Dremio sources |
|-----------|----------------------|----------------|
| `fs` (default) | files under `STORAGE_PATH` | NAS |
| `s3` | a bucket of an S3 server, named like the container | S3 |
| `hdfs` | the directory `HDFS_ROOT` of an existing HDFS | HDFS |

With `s3` and `hdfs`, `STORAGE_PATH` only holds the generated data blocks, from which the input table is uploaded into the bucket or the directory.
The S3 server is the S3 gateway of SeaweedFS in a container of its own (`TEST_S3` of `defaults.py`, code in
`scripts/lib/s3.sh`). `make test-container` starts it when it is not running (the first start takes minutes). Its data
outlives the runs and is not deleted by them; `make fabric-oom-clean` deletes it together with every other container.

`hdfs` is for a Dremio cluster that already runs (nothing is deployed): run pytest directly, from any host that reaches
the coordinator and the namenode (the data goes by WebHDFS, Dremio reads it by RPC). `make test-container` and `make oom` do not serve it.
For the cluster `a-markotenko-0..2` (the coordinator is `a-markotenko-0`, which is also the namenode):

```
DREMIO_URL=http://172.25.1.201:9047 STORAGE=hdfs HDFS_HOST=a-markotenko-0.c.dremio-1093.internal \
    STORAGE_PATH=/tmp/perf-blocks .venv/bin/python -m pytest -v -rs tests
```

`make test STORAGE=s3` works too, but then `S3_ENDPOINT` (host:port) and `S3_BUCKET` must be set, see `settings.py`.

## Make targets

| Command | What it does |
|---------|--------------|
| `make test` | the whole test suite |
| `make venv` | creates `.venv` |
| `make clean` | removes `.venv` and the caches |
| `make data CONTAINER=NAME ROW_COUNT=1.44G` | generates the Parquet data blocks in the storage of a container (or `STORAGE_PATH=DIR`); `make test` reuses them. K/M/G suffixes work everywhere |
| `make create-container PACKAGE=<dremio-*.tar.gz>` | deploys a Dremio container with `deploy_dremio.sh` |
| `make test-container CONTAINER=NAME [ROW_COUNT=N] [STORAGE=fs\|s3]` | runs the tests against the Dremio in a container |
| `make oom [STORAGE=fs\|s3] [OOM_ARGS="..."]` | the OOM frontier search, `OOM_ARGS` are the options of `oom_ranges.py` (`--help`; `PLAN=1` or `--plan` only prints the plan) |
| `make report` | the OOM chart of every storage that has results |
| `make report-fs`, `make report-s3` | the chart of one storage |
| `make scatter CSV=file.csv X=<col> Y=<col> V=<verdict col> [OUT=scatter.svg]` | PASS/FAIL scatter of three CSV columns |

### create-container

```
make create-container PACKAGE=~/dremio-community-26.0.0.tar.gz JAVA=21 HEAP_MB=8192 DIRECT_MB=16384 CPUS=4
```

Optional variables: `NAME`, `CONTAINER_MB`, `INPUT`, `IMAGE`, `STORAGE_PATH`, `HEAP_MB`, `DIRECT_MB`, `CPUS`
(the defaults are those of `deploy_dremio.sh`; `STORAGE_PATH` defaults to `<STORAGE_ROOT>/<container name>`, the EULA is accepted).

- `JAVA=N`: OpenJDK major version.
- `JAVA_IMAGE=cgr.dev/chainguard/jdk:latest-dev`: run Dremio in Docker with the Java of this image instead of `JAVA`;
  `JAVA_IMAGE=wolfi-jdk:21` is built in the container on `cgr.dev/chainguard/wolfi-base` with OpenJDK 21.
- `DOCKER_CONFIG=~/.docker/config.json`: registry credentials for such an image.
- `JAVA_OPTS="-XX:..."`: extra JVM options of Dremio. `GC_LOG=1`: GC log in `/opt/dremio/log/gc.log`.
- `RECREATE=1`: delete an existing container first. `OVERCOMMIT=1`: allow a container memory limit above the memory of the host.
- `DRY_RUN=1`: only the smoke tests.

Give each container its own storage path: containers on one path overwrite each other's input and output data.

### test-container

```
make test-container CONTAINER=dremio-j17-d27 ROW_COUNT=10000000
make test-container CONTAINER=dremio-j17-d27 STORAGE=s3
```

The container IP, its storage path (unless `STORAGE_PATH` is given) and the expected heap and direct memory limits are
read from the container. `PRE_SQL="ALTER SYSTEM SET ...; ..."` runs these statements before the test body.

## OOM search

```
make oom
make oom STORAGE=s3 OOM_ARGS="--heap-start 1024 --plan"
make report
```

The results of each storage are kept apart, because they are not comparable:

| | runs (primary data) | ranges (for the chart) | chart |
|-|---------------------|------------------------|-------|
| `fs` | `data/oom_runs.csv` | `data/oom_ranges.csv` | `data/oom_lines.svg` |
| `s3` | `data/oom_runs_s3.csv` | `data/oom_ranges_s3.csv` | `data/oom_lines_s3.svg` |

The ranges are derived from the runs and never read. The runs take hours: the search resumes from the recorded runs.
After changing code that `oom_ranges.py` runs, restart it: a running process keeps the old code.

## Fabric direct-memory OOM repro (DX-127946)

The two-host stand from a Dremio tarball and its runs. Run on the coordinator host; the pytest output of every run goes
to `data/fabric-oom-<case>-<time>.log`. A run that fails (the repro test fails when the bug does not reproduce) does
not stop the next; the exit status is the last failure. `RUNS` (default 3) is the number of runs.

```
make fabric-oom TARBALL=/mnt/ubuntu-var/nfs/shared/Downloads/dremio-enterprise-25.2.0-202410241428100111-a963b970.tar.gz
OOM_JAVA_OPTS=-Ddremio.rpc.pause_reads_on_direct_oom=true make fabric-oom-stand TARBALL=...
OOM_MEMORY_PCT=50 make fabric-oom-stand TARBALL=...
OOM_ESCALATION=1 make fabric-oom-func RUNS=3
make fabric-oom-feature RUNS=1
make fabric-oom-repro OOM_DATA=/mnt/.../other
make fabric-oom-report
make fabric-oom-clean
```

- `fabric-oom`: the stand and the repro.
- The data set (`OOM_DATA`) is made by the tests: the `oom_data` fixture generates it (scale `OOM_SCALE`) at the same path on every host of `OOM_CONTAINERS` where the directory does not exist, nothing is copied between hosts. A remote host gets a venv with the `duckdb` of `requirements.txt` in `~/.cache/fabric-oom` (the first run installs it with `uv`, which fetches Python 3.12).
- Nodes that are not incus containers (an existing cluster): `OOM_CONTAINERS=dremio://HOST,yarn://HOST,...` (`dremio://` the coordinator, `yarn://` an executor that YARN runs); their logs are read over ssh, their build is the `dremio_pkg_url` of the VM metadata.
  Run pytest directly, with `DREMIO_URL` and an `OOM_DATA` on a disk with room for the data set (about 12.6 GB at the default scale) on every node. On `a-markotenko-0..2`: `OOM_DATA=/data/fabric-oom-repro/scale-0.0175` (the directory `/data/fabric-oom-repro` is made once on each VM: `sudo install -d -o dremio -g dremio /data/fabric-oom-repro`).
- `OOM_JAVA_OPTS=...` on the stand: a build with the fix, read pause on.
- `OOM_MEMORY_PCT=50` on the stand: both nodes with half the heap, direct memory and container RAM.
- `fabric-oom-func`: the fix verification on the stand that is up; `OOM_ESCALATION=1` escalation on, `0` the read pause alone.
- `fabric-oom-feature`: the same workload with no time limit: does the fix serve every query.
- `fabric-oom-repro OOM_DATA=...`: the repro on another data set; on a fixed build with both changes off the bug must still reproduce.
- `fabric-oom-report`: a table with a row for every pytest session of every run from the logs in `data/` (`func` has three sessions per run), with how to read it.
- `fabric-oom-clean`: removes the stand from both hosts (every container, also the S3 servers with their buckets), keeps the generated data.
