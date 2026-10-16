"""Draws an SVG analysis of the test runs (PASS/FAIL against heap, direct memory and rows).

    python3 -m report data/test_results_home4.csv [more.csv ...] [-o report.svg]

What the three sections show is described in svg.py.
"""
import argparse

from .runs import load, summary
from .svg import render


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+", help="result CSV file(s)")
    ap.add_argument("-o", "--output", default="report.svg")
    args = ap.parse_args()
    data, rams = load(args.csv)
    if not data:
        raise SystemExit("no PASS/FAIL rows found in the given CSV files")
    with open(args.output, "w") as f:
        f.write(render(data, rams))
    summary(data)
    print(f"written {args.output}")


if __name__ == "__main__":
    main()
