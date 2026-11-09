export DREMIO_URL=http://a-markotenko-0.c.dremio-1093.internal:9047
export OOM_DATA=/data/fabric-oom-repro/scale-0.0175
export OOM_CONTAINERS="dremio://a-markotenko-0.c.dremio-1093.internal,dremio://a-markotenko-1.c.dremio-1093.internal,dremio://a-markotenko-2.c.dremio-1093.internal"
export DREMIO_TIMEOUT=600
export STORAGE=hdfs 
export HDFS_HOST=a-markotenko-0.c.dremio-1093.internal
export STORAGE_PATH=/tmp/perf-blocks 
export OOM_RESERVE_PCT=4

#.venv/bin/python -m pytest -x -v -rs tests
echo pytest -v -rs tests/fabric_oom_repro/test_fabric_oom_func.py
.venv/bin/python -m pytest -v -rs tests/fabric_oom_repro/test_fabric_oom_func.py
