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
from html import escape

import csvio
from .canvas import CSS, DARK, LEFT, LIGHT, PW, SERIES, W, Svg, y_axis
from .scatter import format_value, nice_ticks, pad_range, parse_value

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
                mean = parse_value(r["Mean rows"])
            except (KeyError, ValueError):
                continue
            key = (r["Dremio ver"], r["Java image"])
            if heap in lines[key]:
                print(f"warning: {key[0]} {key[1]} heap {heap} is in more than one row, the last one is used", file=sys.stderr)
            lines[key][heap] = (mean, r.get("Pass max rows", ""), r.get("Fail min rows", ""))
    return dict(lines), no_mean


def marker(svg, shape, color, x, y, r=5.5, title=""):
    """Circle, square or diamond in series colour `color`; the hover text goes into a <title>."""
    col = SERIES[color][0]
    attrs = f'fill="{col}" class="f{color}" stroke="{LIGHT["surface"]}" stroke-width="2"'
    tip = f"<title>{escape(title)}</title>" if title else ""
    if shape == 0:
        svg.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" {attrs}>{tip}</circle>')
    elif shape == 1:
        svg.add(f'<rect x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r}" height="{2 * r}" rx="1" {attrs}>{tip}</rect>')
    else:
        d = r * 1.3
        svg.add(f'<path d="M{x:.1f} {y - d:.1f}L{x + d:.1f} {y:.1f}L{x:.1f} {y + d:.1f}L{x - d:.1f} {y:.1f}Z" {attrs}>{tip}</path>')


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
    px = lambda x: LEFT + (x - xlo) / (xhi - xlo) * PW
    py = lambda y: TOP + PH - (y - ylo) / (yhi - ylo) * PH

    svg = Svg()
    svg.text(LEFT, 30, title, "title ttl")
    lx, ly = LEFT, 56
    for key in sorted(lines):
        c, s = versions.index(key[0]), images.index(key[1])
        label = f"Dremio {key[0]} · {key[1]}"
        if lx + 60 + 7 * len(label) > LEFT + PW:             # next legend row
            lx, ly = LEFT, ly + 22
        dash = f' stroke-dasharray="{DASHES[s]}"' if DASHES[s] else ""
        svg.add(f'<line x1="{lx}" y1="{ly}" x2="{lx + 28}" y2="{ly}" stroke="{SERIES[c][0]}" class="s{c}" '
                f'stroke-width="2"{dash}/>')
        marker(svg, s, c, lx + 14, ly)
        svg.text(lx + 36, ly + 4, label)
        lx += 60 + 7 * len(label)

    y_axis(svg, TOP, PH, ylo, yhi, nice_ticks(ylo, yhi), format_value, "rows (middle of the PASS/FAIL range)")
    for t in nice_ticks(xlo, xhi):
        svg.line(px(t), TOP, px(t), TOP + PH, "grid", LIGHT["grid"])
        svg.text(px(t), TOP + PH + 20, f"{t:g}", anchor="middle")
    svg.text(LEFT + PW / 2, TOP + PH + 44, "heap, MB", anchor="middle")

    for key in sorted(lines):
        c, s = versions.index(key[0]), images.index(key[1])
        pts = sorted(lines[key].items())
        if len(pts) > 1:
            dash = f' stroke-dasharray="{DASHES[s]}"' if DASHES[s] else ""
            svg.add(f'<polyline points="{" ".join(f"{px(h):.1f},{py(p[0]):.1f}" for h, p in pts)}" fill="none" '
                    f'stroke="{SERIES[c][0]}" class="s{c}" stroke-width="2"{dash}/>')
    for key in sorted(lines):
        c, s = versions.index(key[0]), images.index(key[1])
        for h, (mean, lo, hi) in sorted(lines[key].items()):
            tip = f"Dremio {key[0]}, {key[1]}, heap {h} MB: mean {format_value(mean)} rows (PASS up to {lo or '-'}, FAIL from {hi or '-'})"
            marker(svg, s, c, px(h), py(mean), title=tip)

    H = TOP + PH + 64
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
            f'role="img" fill="{LIGHT["ink2"]}" aria-label="{escape(title)}">')
    dark = "".join(f"  .f{i} {{ fill: {c[1]} }} .s{i} {{ stroke: {c[1]} }}\n" for i, c in enumerate(SERIES))
    style = "<style>" + CSS % {**DARK, "series": dark} + "</style>"
    bg = f'<rect width="{W}" height="{H}" fill="{LIGHT["surface"]}" class="bg"/>'
    return "\n".join([head, style, bg, *svg.parts, "</svg>"])


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
