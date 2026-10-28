"""The tables of a data set of the fabric OOM repro registered in Dremio: the NAS source over the data set directory and
both folders promoted to Parquet tables (one subfolder per year, the dir0 column)."""
from fabric_oom_repro.generate_oom_data import TABLES, YEARS


def register(dremio, source, path):
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
