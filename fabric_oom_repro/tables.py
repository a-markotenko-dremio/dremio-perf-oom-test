"""The tables of a data set of the fabric OOM repro registered in Dremio: the NAS source over the data set directory and
both folders promoted to Parquet tables (one subfolder per year, the dir0 column)."""
import time

from dremio_client import JobFailed
from fabric_oom_repro.generate_oom_data import TABLES, YEARS

# A run that reached its time limit leaves the executor working: the coordinator cancels the queries and calls them
# CANCELED at once, while their fragments go on spilling (2026-10-30: cancelled at 22:25:56, still spilling at
# 22:27:56). Every query sent meanwhile fails with this error, so the next run waits for the node instead of failing.
BUSY = "while waiting after sending work fragments to remote nodes"
BUSY_WAIT_SECONDS = 600
BUSY_POLL_SECONDS = 30


def register(dremio, source, path, wait=BUSY_WAIT_SECONDS, poll=BUSY_POLL_SECONDS):
    """`register_tables`, waiting up to `wait` seconds for an executor still busy with the run before."""
    deadline = time.time() + wait
    while True:
        try:
            return register_tables(dremio, source, path)
        except JobFailed as e:
            if BUSY not in str(e) or time.time() > deadline:
                raise
            time.sleep(poll)


def register_tables(dremio, source, path):
    """
    Points `source` at the data set `path` and promotes its tables. When the source pointed at another directory, the
    tables are promoted again: their cached metadata (file sizes, footer offsets) describes the other files and reading
    with it fails ("Cannot seek after EOF"). Every table is then read to check that all years are there on every node.
    """
    repointed = dremio.ensure_nas_source(source, path)
    for name in TABLES:
        if repointed:
            dremio.unpromote_table([source, name])
        if dremio.entity_type([source, name]) != "dataset":
            dremio.promote_folder([source, name])
        years = {row["dir0"] for row in dremio.query_rows(f'SELECT DISTINCT dir0 FROM "{source}".{name}')}
        assert years == set(YEARS), f"{name} of {path}: unexpected years {sorted(years)}"
