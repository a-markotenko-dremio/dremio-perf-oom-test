 DREMIO_URL=http://172.25.1.201:9047 STORAGE=hdfs HDFS_HOST=a-markotenko-0.c.dremio-1093.internal \
    STORAGE_PATH=/tmp/perf-blocks .venv/bin/python -m pytest -v -rs tests
