"""Fast generator of catalog_sales test data (Parquet blocks) using DuckDB.

Data is generated in reusable blocks of BLOCK_ROWS rows:
    <storage>/blocks/block_<first id>_<rows>.parquet
A block is generated once and then reused by every later run. The table folder
    <storage>/input/STACKIT_S3/tpcds-1tb-flat/catalog_sales
is assembled from the blocks needed for the requested row count (hard links, so no extra
disk space; falls back to copying when links are not possible).

Usage: python generate_data.py --rows 1440000000 [--storage /mnt/ubuntu-var/dremio]
"""
import argparse
import os
import shutil
from pathlib import Path

import duckdb

BLOCK_ROWS = 10_000_000
TABLE_SUBDIR = Path("input/STACKIT_S3/tpcds-1tb-flat/catalog_sales")

INT_COLS = ["cs_sold_date_sk", "cs_sold_time_sk", "cs_ship_date_sk", "cs_bill_customer_sk",
            "cs_bill_cdemo_sk", "cs_bill_hdemo_sk", "cs_bill_addr_sk", "cs_ship_customer_sk",
            "cs_ship_cdemo_sk", "cs_ship_hdemo_sk", "cs_ship_addr_sk", "cs_call_center_sk",
            "cs_catalog_page_sk", "cs_ship_mode_sk", "cs_warehouse_sk", "cs_item_sk",
            "cs_promo_sk"]
DECIMAL_COLS = {"cs_wholesale_cost": 10, "cs_list_price": 15, "cs_sales_price": 12,
                "cs_ext_discount_amt": 0, "cs_ext_sales_price": 12,
                "cs_ext_wholesale_cost": 10, "cs_ext_list_price": 15, "cs_ext_tax": 1,
                "cs_coupon_amt": 2, "cs_ext_ship_cost": 0, "cs_net_paid": 2,
                "cs_net_paid_inc_tax": 2, "cs_net_paid_inc_ship": 2,
                "cs_net_paid_inc_ship_tax": 2, "cs_net_profit": 0}


def block_query(first, rows):
    cols = [f"CAST(i AS INTEGER) AS {c}" for c in INT_COLS]
    cols.append("CAST(i AS BIGINT) AS cs_order_number")
    cols.append("CAST(1 AS INTEGER) AS cs_quantity")
    cols += [f"CAST({v}.0 AS DECIMAL(7,2)) AS {c}" for c, v in DECIMAL_COLS.items()]
    return f"SELECT {', '.join(cols)} FROM range({first}, {first + rows}) t(i)"


def block_plan(total_rows, block_rows=BLOCK_ROWS):
    """Returns [(first_id, rows)] covering total_rows."""
    return [(first, min(block_rows, total_rows - first))
            for first in range(0, total_rows, block_rows)]


def generate(total_rows, storage, block_rows=BLOCK_ROWS, log=print):
    """Ensures the blocks exist and assembles the table folder. Returns the folder."""
    storage = Path(storage)
    blocks_dir = storage / "blocks"
    table_dir = storage / TABLE_SUBDIR
    blocks_dir.mkdir(parents=True, exist_ok=True)
    plan = block_plan(total_rows, block_rows)

    con = duckdb.connect()
    wanted = {}
    for n, (first, rows) in enumerate(plan, 1):
        path = blocks_dir / f"block_{first:010d}_{rows}.parquet"
        wanted[path.name] = path
        if path.exists():
            continue
        tmp = path.with_suffix(".tmp")
        con.execute(f"COPY ({block_query(first, rows)}) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)")
        tmp.rename(path)
        log(f"generated block {n}/{len(plan)}: {path.name}")

    # Assemble the table folder from exactly the wanted blocks.
    table_dir.mkdir(parents=True, exist_ok=True)
    for f in table_dir.iterdir():
        if f.name not in wanted:
            shutil.rmtree(f) if f.is_dir() else f.unlink()
    for name, src in wanted.items():
        dst = table_dir / name
        if dst.exists():
            continue
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
    return table_dir


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, required=True)
    ap.add_argument("--storage", default=os.environ.get("STORAGE_PATH", "/mnt/ubuntu-var/dremio"))
    a = ap.parse_args()
    print(generate(a.rows, a.storage))
