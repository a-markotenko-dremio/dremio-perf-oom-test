"""Draws the OOM frontier of data/oom_ranges.csv (written by oom_ranges.py) as an SVG line chart.

    python3 -m report.lines data/oom_ranges.csv [more.csv ...] [-o oom_lines.svg] [--title TEXT]

X is the heap (MB), Y the "Mean rows" of the step: the middle of the range between the highest PASS and
the lowest FAIL row count. One line per combination of Dremio version and Java image; the version is told
apart by colour, the Java image by line style and marker shape. Steps without a mean (ALL_PASS, ALL_FAIL)
have no point, the line goes on over them. Hover a point for the PASS/FAIL range of its step.
"""
import argparse
import sys
from collections import defaultdict

import csvio
from quantities import parse_number
from .canvas import (LEFT, PW, SERIES, SERIES_DARK_CSS, Svg, document, format_tick, nice_ticks, pad_range, scale, x_axis,
                     y_axis)

PH, TOP = 460, 110
DASHES = ["", "7 4", "2 4"]          # solid, dashed, dotted: one per Java image


def load(paths):
    """{(Dremio ver, Java image): {heap_mb: (mean, pass max text, fail min text)}}, number of steps without a mean."""
    lines, no_mean = defaultdict(dict), 0
    for path in paths:
        for r in csvio.read_rows(path):
            try:
                heap = int(r["Heap MB"])
                if not (r.get("Mean rows") or "").strip():
                    no_mean += 1
                    continue
                mean = parse_number(r["Mean rows"])
            except (KeyError, ValueError):
                continue
            key = (r["Dremio ver"], r["Java image"])
            if heap in lines[key]:
                print(f"warning: {key[0]} {key[1]} heap {heap} is in more than one row, the last one is used", file=sys.stderr)
            lines[key][heap] = (mean, r.get("Pass max rows", ""), r.get("Fail min rows", ""))
    return dict(lines), no_mean


def dash_attr(s):
    """The stroke-dasharray attribute of the line style s (none for a solid line)."""
    return f' stroke-dasharray="{DASHES[s]}"' if DASHES[s] else ""


def render(lines, title):
    versions = sorted({v for v, _ in lines})
    images = sorted({i for _, i in lines})
    if len(versions) > len(SERIES):
        raise SystemExit(f"{len(versions)} Dremio versions: the palette is validated for {len(SERIES)}; pass fewer CSV files")
    if len(images) > len(DASHES):
        raise SystemExit(f"{len(images)} Java images: at most {len(DASHES)} line styles; pass fewer CSV files")

    heaps = sorted({h for pts in lines.values() for h in pts})
    ys = [p[0] for pts in lines.values() for p in pts.values()]
    xlo, xhi = pad_range(heaps)
    ylo, yhi = pad_range(ys)
    to_x, to_y = scale(xlo, xhi, LEFT, PW), scale(ylo, yhi, TOP + PH, -PH)

    svg = Svg()
    svg.text(LEFT, 30, title, "title ttl")
    lx, ly = LEFT, 56
    for key in sorted(lines):
        c, s = versions.index(key[0]), images.index(key[1])
        label = f"Dremio {key[0]} · {key[1]}"
        if lx + 60 + 7 * len(label) > LEFT + PW:             # next legend row
            lx, ly = LEFT, ly + 22
        svg.add(f'<line x1="{lx}" y1="{ly}" x2="{lx + 28}" y2="{ly}" stroke="{SERIES[c][0]}" class="s{c}" '
                f'stroke-width="2"{dash_attr(s)}/>')
        svg.marker(c, lx + 14, ly, shape=s)
        svg.text(lx + 36, ly + 4, label)
        lx += 60 + 7 * len(label)

    y_axis(svg, TOP, PH, ylo, yhi, nice_ticks(ylo, yhi, 8), format_tick, "rows (middle of the PASS/FAIL range)")
    x_axis(svg, TOP, PH, to_x, nice_ticks(xlo, xhi, 8), "{:g}".format, "heap, MB")   # MB, not K/M/G

    for key in sorted(lines):
        c, s = versions.index(key[0]), images.index(key[1])
        pts = sorted(lines[key].items())
        if len(pts) > 1:
            svg.add(f'<polyline points="{" ".join(f"{to_x(h):.1f},{to_y(p[0]):.1f}" for h, p in pts)}" fill="none" '
                    f'stroke="{SERIES[c][0]}" class="s{c}" stroke-width="2"{dash_attr(s)}/>')
    for key in sorted(lines):
        c, s = versions.index(key[0]), images.index(key[1])
        for h, (mean, lo, hi) in sorted(lines[key].items()):
            tip = f"Dremio {key[0]}, {key[1]}, heap {h} MB: mean {format_tick(mean)} rows (PASS up to {lo or '-'}, FAIL from {hi or '-'})"
            svg.marker(c, to_x(h), to_y(mean), shape=s, title=tip)

    return document(svg.parts, TOP + PH + 64, title, SERIES_DARK_CSS)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+", help="oom_ranges.csv file(s)")
    ap.add_argument("-o", "--output", default="oom_lines.svg")
    ap.add_argument("--title", default="Rows at the Java heap OOM frontier vs heap")
    args = ap.parse_args(argv)
    lines, no_mean = load(args.csv)
    if not lines:
        raise SystemExit("no steps with a mean in the given CSV files")
    with open(args.output, "w") as f:
        f.write(render(lines, args.title))
    print(f"written {args.output}: {len(lines)} lines, {sum(len(p) for p in lines.values())} points"
          + (f", {no_mean} steps without a mean skipped" if no_mean else ""))


if __name__ == "__main__":
    sys.exit(main())
