"""Reading, appending and writing CSV files: the only place of the project that touches the csv module."""
import csv
import os
from pathlib import Path


def read_table(path):
    """(header, rows) of a CSV file as lists, so that columns with the same name stay apart. Raises when the file is missing."""
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    return (rows[0], rows[1:]) if rows else ([], [])


def read_rows(path, missing_ok=False):
    """The rows of a CSV file as dicts keyed by the header; `missing_ok` gives [] for a file that does not exist."""
    path = Path(path)
    if missing_ok and not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def append_row(path, columns, row):
    """Appends `row` (a dict keyed by `columns`), creating the directory and writing the header when the file is new."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        if new:
            w.writeheader()
        w.writerow(row)


def write_rows(path, columns, rows):
    """Replaces the file with the header and `rows` (dicts keyed by `columns`). The new file is complete before it
    takes the place of the old one, so a reader never sees half of it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)
