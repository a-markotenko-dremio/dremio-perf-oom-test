"""Draws a PASS/FAIL scatter chart of any three columns of a CSV file as SVG.

    python3 -m report.scatter FILE.csv X Y VERDICT [-o scatter.svg]

X, Y and VERDICT are column names from the header row of the file. Every row is a point at
(X, Y); the VERDICT column colours it: PASS green, FAIL red. The X and Y values may carry a K (kilo),
M (mega) or G (giga) suffix ("100K", "1.44G", decimal units) and the axes are labelled the same way.
Rows whose X or Y is not a number, or whose verdict is neither PASS nor FAIL, are skipped.

    python3 -m report.scatter data/test_results.csv Rows DREMIO_MAX_HEAP_MEMORY_SIZE_MB Verdict
"""
import argparse
import sys

import csvio
from quantities import parse_number
from .canvas import LEFT, LIGHT, PW, Svg, document, format_tick, nice_ticks, pad_range, scale, x_axis, y_axis

COLORS = {"PASS": ("#1a9850", "#3dbb6f"), "FAIL": ("#d73027", "#f06b5f")}  # light, dark theme
PH, TOP = 460, 90


def column_index(header, name):
    """The index of the column with this header name (exact match, else ignoring case and surrounding spaces)."""
    names = [h.strip() for h in header]
    for matches in (lambda h: h == name.strip(), lambda h: h.lower() == name.strip().lower()):
        found = [i for i, h in enumerate(names) if matches(h)]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise SystemExit(f"column name {name!r} is ambiguous: it is the header of columns {found}")
    raise SystemExit(f"no column named {name!r}; the columns are: " + ", ".join(repr(h) for h in names))


def load(path, x_spec, y_spec, v_spec):
    """([(x, y, 'PASS'|'FAIL', line number)], skipped row count, (x name, y name, verdict name))."""
    header, rows = csvio.read_table(path)
    if not header:
        raise SystemExit(f"{path} is empty")
    xi, yi, vi = (column_index(header, s) for s in (x_spec, y_spec, v_spec))
    points, skipped = [], 0
    for n, r in enumerate(rows, start=2):
        try:
            verdict = r[vi].strip().upper()
            if verdict not in COLORS:
                raise ValueError(verdict)
            points.append((parse_number(r[xi]), parse_number(r[yi]), verdict, n))
        except (ValueError, IndexError):
            skipped += 1
    return points, skipped, tuple(header[i].strip() for i in (xi, yi, vi))


def render(points, names, title):
    xlo, xhi = pad_range([p[0] for p in points])
    ylo, yhi = pad_range([p[1] for p in points])
    to_x, to_y = scale(xlo, xhi, LEFT, PW), scale(ylo, yhi, TOP + PH, -PH)

    svg = Svg()
    svg.text(LEFT, 30, title, "title ttl")
    counts = {v: sum(1 for p in points if p[2] == v) for v in COLORS}
    lx = LEFT
    for v in COLORS:
        svg.shape(0, lx + 6, 52, 5.5, f'fill="{COLORS[v][0]}" class="p{v}"')
        svg.text(lx + 18, 56, f"{v} ({counts[v]})")
        lx += 110
    y_axis(svg, TOP, PH, ylo, yhi, nice_ticks(ylo, yhi, 8), format_tick, names[1])
    x_axis(svg, TOP, PH, to_x, nice_ticks(xlo, xhi, 8), format_tick, names[0])
    # FAIL last: a failure must not be hidden under a pass at the same spot; both stay visible (opacity)
    for verdict in ("PASS", "FAIL"):
        for x, y, v, n in points:
            if v == verdict:
                svg.shape(0, to_x(x), to_y(y), 6, f'fill="{COLORS[v][0]}" class="p{v}" fill-opacity="0.8" '
                          f'stroke="{LIGHT["surface"]}" stroke-width="1.5"',
                          f"{names[0]} {format_tick(x)}, {names[1]} {format_tick(y)}: {v} (line {n})")
    dark_points = "".join(f"  .p{v} {{ fill: {c[1]} }}\n" for v, c in COLORS.items())
    return document(svg.parts, TOP + PH + 64, title, dark_points)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="CSV file with a header row")
    ap.add_argument("x", help="X column: header name")
    ap.add_argument("y", help="Y column: header name")
    ap.add_argument("verdict", help="PASS/FAIL column: header name")
    ap.add_argument("-o", "--output", default="scatter.svg")
    ap.add_argument("--title", help="chart title (default: 'Y vs X')")
    args = ap.parse_args(argv)
    points, skipped, names = load(args.csv, args.x, args.y, args.verdict)
    if not points:
        raise SystemExit(f"no usable rows in {args.csv}: X and Y must be numbers (optional K/M/G suffix), "
                         f"the verdict PASS or FAIL")
    with open(args.output, "w") as f:
        f.write(render(points, names, args.title or f"{names[1]} vs {names[0]}"))
    print(f"written {args.output}: {len(points)} points" + (f", {skipped} rows skipped" if skipped else ""))


if __name__ == "__main__":
    sys.exit(main())
