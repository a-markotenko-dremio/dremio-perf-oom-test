"""Draws the OOM frontier of data/oom_ranges.csv (written by oom_ranges.py) as an SVG line chart.

    python3 -m report.lines data/oom_ranges.csv [more.csv ...] [-o oom_lines.svg] [--title TEXT]
        [--runs oom_runs.csv ...] [--limits TEXT]

X is the heap (MB), Y the "Mean rows" of the step: the middle of the range between the highest PASS and
the lowest FAIL row count. One line per combination of Dremio version and Java image; the version is told
apart by colour, the Java image by line style and marker shape. Steps without a mean (ALL_PASS, ALL_FAIL)
have no point, the line goes on over them. Hover a point for the PASS/FAIL range of its step.

A heap size with several rows (repeated searches, e.g. from data/repeats/*.ranges.csv) is drawn at the average of their
means, with a vertical bar from the lowest to the highest mean: the bar is the spread of the result between searches.

Below the chart a description says what a point is, the limits of the test (--limits, free text) and how many runs the
chart rests on (--runs: the oom_runs.csv files the ranges come from).
"""
import argparse
import sys
import textwrap
from collections import defaultdict
from statistics import mean as average

import csvio
from quantities import parse_number
from .canvas import (LEFT, PW, SERIES, SERIES_DARK_CSS, Svg, document, format_tick, nice_ticks, pad_range, scale, x_axis,
                     y_axis)

PH, TOP = 460, 110
DASHES = ["", "7 4", "2 4"]          # solid, dashed, dotted: one per Java image


def load(paths):
    """{(Dremio ver, Java image): {heap_mb: [(mean, pass max text, fail min text), ...]}} (one tuple per row of the heap size),
    number of steps without a mean."""
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
            lines[key].setdefault(heap, []).append((mean, r.get("Pass max rows", ""), r.get("Fail min rows", "")))
    return dict(lines), no_mean


def run_summary(paths):
    """{"PASS": n, "FAIL": n, "other": n, "rows": (lowest, highest row count in millions)} of the oom_runs.csv files."""
    runs = [r for path in paths for r in csvio.read_rows(path)]
    if not runs:
        raise SystemExit("no runs in the --runs files")
    outcomes = [r["Outcome"] for r in runs]
    rows = [int(r["Rows"]) for r in runs]
    return {"PASS": outcomes.count("PASS"), "FAIL": outcomes.count("FAIL"),
            "other": len(outcomes) - outcomes.count("PASS") - outcomes.count("FAIL"), "rows": (min(rows), max(rows))}


def describe(lines, runs=None, limits=None):
    """The paragraphs below the chart: what a point is, the limits of the test, the runs behind the chart."""
    searches = sum(len(rows) for pts in lines.values() for rows in pts.values())
    most = max(len(rows) for pts in lines.values() for rows in pts.values())
    heaps = sorted({h for pts in lines.values() for h in pts})
    text = ["Each point is one finished search for one Dremio version and Java image at one heap size. Its height is the number of "
            "rows at which the test starts to fail with a Java heap OOM: the middle between the highest PASS and the lowest FAIL "
            "(hover shows both)."
            + (f" A bar shows the lowest to highest result of the {most} searches of one combination at a heap size." if most > 1 else "")]
    text.append((f"Limits: {limits}. " if limits else "") + f"Heap {heaps[0]} to {heaps[-1]} MB.")
    if runs:
        other = f", {runs['other']} other" if runs["other"] else ""
        text.append(f"Runs: {runs['PASS'] + runs['FAIL'] + runs['other']} test runs ({runs['PASS']} PASS, {runs['FAIL']} FAIL{other}) of "
                    f"{format_tick(runs['rows'][0] * 10**6)} to {format_tick(runs['rows'][1] * 10**6)} rows, in {searches} searches with a result.")
    return text


def dash_attr(s):
    """The stroke-dasharray attribute of the line style s (none for a solid line)."""
    return f' stroke-dasharray="{DASHES[s]}"' if DASHES[s] else ""


def render(lines, title, notes=()):
    versions = sorted({v for v, _ in lines})
    images = sorted({i for _, i in lines})
    if len(versions) > len(SERIES):
        raise SystemExit(f"{len(versions)} Dremio versions: the palette is validated for {len(SERIES)}; pass fewer CSV files")
    if len(images) > len(DASHES):
        raise SystemExit(f"{len(images)} Java images: at most {len(DASHES)} line styles; pass fewer CSV files")

    heaps = sorted({h for pts in lines.values() for h in pts})
    ys = [p[0] for pts in lines.values() for rows in pts.values() for p in rows]
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
        pts = [(h, average(p[0] for p in rows)) for h, rows in sorted(lines[key].items())]
        if len(pts) > 1:
            svg.add(f'<polyline points="{" ".join(f"{to_x(h):.1f},{to_y(y):.1f}" for h, y in pts)}" fill="none" '
                    f'stroke="{SERIES[c][0]}" class="s{c}" stroke-width="2"{dash_attr(s)}/>')
    for key in sorted(lines):
        c, s = versions.index(key[0]), images.index(key[1])
        for h, rows in sorted(lines[key].items()):
            means = [p[0] for p in rows]
            if len(rows) > 1:
                svg.line(to_x(h), to_y(min(means)), to_x(h), to_y(max(means)), f"s{c}", SERIES[c][0], 2)
                tip = (f"Dremio {key[0]}, {key[1]}, heap {h} MB: mean {format_tick(average(means))} rows of {len(rows)} searches "
                       f"(from {format_tick(min(means))} to {format_tick(max(means))})")
            else:
                _, lo, hi = rows[0]
                tip = f"Dremio {key[0]}, {key[1]}, heap {h} MB: mean {format_tick(means[0])} rows (PASS up to {lo or '-'}, FAIL from {hi or '-'})"
            svg.marker(c, to_x(h), to_y(average(means)), shape=s, title=tip)
    y = TOP + PH + 72
    for note in notes:
        for line in textwrap.wrap(note, 150):
            svg.text(LEFT, y, line, "t")
            y += 16
        y += 6
    return document(svg.parts, y + 10, title, SERIES_DARK_CSS)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+", help="oom_ranges.csv file(s)")
    ap.add_argument("-o", "--output", default="oom_lines.svg")
    ap.add_argument("--title", default="Rows at the Java heap OOM frontier vs heap")
    ap.add_argument("--runs", nargs="+", metavar="CSV", help="oom_runs.csv file(s) the ranges come from: adds the number of runs to the description")
    ap.add_argument("--limits", metavar="TEXT", help='limits of the test for the description, e.g. "container 8 GB, direct memory 4096 MB, 16 CPUs"')
    args = ap.parse_args(argv)
    lines, no_mean = load(args.csv)
    if not lines:
        raise SystemExit("no steps with a mean in the given CSV files")
    with open(args.output, "w") as f:
        f.write(render(lines, args.title, describe(lines, run_summary(args.runs) if args.runs else None, args.limits)))
    print(f"written {args.output}: {len(lines)} lines, {sum(len(p) for p in lines.values())} points"
          + (f", {no_mean} steps without a mean skipped" if no_mean else ""))


if __name__ == "__main__":
    sys.exit(main())
