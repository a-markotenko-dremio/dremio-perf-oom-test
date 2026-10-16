"""The SVG report: three sections drawn with canvas from the runs of runs.

  1. Heap needed vs rows: per row count the "safe heap" (the lowest tested heap above the highest
     failed one, so every larger heap passed); the bar below it reaches down to the highest failed
     heap, i.e. the real limit lies inside the bar. All versions in one chart.
  2. Pass rate by heap: for the row counts that have both outcomes, the share of passed runs at each
     heap. Shows how wide the unstable transition zone is and whether results contradict each other.
  3. Heap x direct: for every tested combination the largest row count that passed (cell shade and
     the "pass" number) and the smallest one that failed ("fail"). Shows which of the two limits.
The Dremio versions are told apart by colour AND marker shape.
"""
from collections import defaultdict
from html import escape

import results_report
from .runs import by_heap, frontier
from .canvas import (CSS, DARK, LEFT, LIGHT, PW, SERIES, W, Svg, fmt_mb, nice_ticks,
                     section_header, y_axis)


# ------------------------------------------------------------------ 1. heap needed vs rows
def section_frontier(svg, y, data, versions):
    y = section_header(svg, y, "1. Heap needed vs rows",
                       "Marker: safe heap (the lowest tested heap above the highest FAIL; all larger heaps passed). "
                       "Bar down to the highest FAIL: the real limit is inside it. Dashed stem: no FAIL seen, the limit may be lower.")
    all_rows = sorted({r for d in data.values() for r in d})
    pts = {}
    for ver in versions:
        for rows in all_rows:
            if rows in data[ver]:
                pts[ver, rows] = frontier(data[ver][rows])
    vals = [h for pair in pts.values() for h in pair if h is not None]
    span = max(max(vals) - min(vals), 128)
    lo, hi = max(min(vals) - span * 0.15, 0), max(vals) + span * 0.15
    ph = 300
    top = y + 6
    step = PW / len(all_rows)
    px = lambda rows: LEFT + (all_rows.index(rows) + 0.5) * step
    py = lambda h: top + ph - (h - lo) / (hi - lo) * ph
    y_axis(svg, top, ph, lo, hi, nice_ticks(lo, hi), fmt_mb, "heap, MB")
    for rows in all_rows:
        svg.text(px(rows), top + ph + 20, results_report.format_rows(rows), anchor="middle")
    svg.text(LEFT + PW / 2, top + ph + 42, "rows processed", anchor="middle")

    n = len(versions)
    for i, ver in enumerate(versions):
        col = SERIES[i][0]
        dx = (i - (n - 1) / 2) * 16
        line = [(px(rows) + dx, py(pts[ver, rows][1])) for rows in all_rows
                if (ver, rows) in pts and pts[ver, rows][1] is not None]
        if len(line) > 1:
            svg.add(f'<polyline points="{" ".join(f"{x:.1f},{y_:.1f}" for x, y_ in line)}" fill="none" '
                    f'stroke="{col}" class="s{i}" stroke-width="1.5" stroke-opacity="0.6"/>')
        for rows in all_rows:
            if (ver, rows) not in pts:
                continue
            bad, safe = pts[ver, rows]
            x = px(rows) + dx
            tip = (f"Dremio {ver}, {results_report.format_rows(rows)} rows: highest FAIL heap "
                   f"{bad if bad is not None else '-'} MB, safe heap "
                   f"{safe if safe is not None else 'none (every tested heap failed)'} MB")
            svg.add(f'<g><title>{escape(tip)}</title>')
            if safe is not None and bad is not None:
                svg.add(f'<rect x="{x - 4:.1f}" y="{py(safe):.1f}" width="8" height="{max(py(bad) - py(safe), 1):.1f}" rx="3" '
                        f'fill="{col}" class="f{i}" fill-opacity="0.3"/>')
            if safe is not None and bad is None:
                svg.line(x, py(safe), x, top + ph, f"s{i}", col, 1.5, "3 3")
            if safe is not None:
                svg.marker(i, x, py(safe))
            else:  # even the largest tested heap failed: more is needed
                svg.marker(i, x, py(bad), filled=False)
                svg.text(x, py(bad) - 12, "more", "small", "middle")
            svg.add("</g>")
    return top + ph + 66


# ------------------------------------------------------------------ 2. pass rate by heap
def section_pass_rate(svg, y, data, versions):
    y = section_header(svg, y, "2. Pass rate by heap",
                       "Share of passed runs at each heap, for the row counts where some version both passed and failed. "
                       "Marker size grows with the number of runs; a rate between 0% and 100% means unstable results.")
    mixed = []
    for rows in sorted({r for d in data.values() for r in d}):
        outcomes = [0, 0]
        for ver in versions:
            for p, f in by_heap(data[ver].get(rows, {})).values():
                outcomes[0] += p
                outcomes[1] += f
        if all(outcomes):
            mixed.append(rows)
    mixed = mixed[-3:]
    if not mixed:
        svg.text(LEFT, y + 10, "No row count has both PASS and FAIL runs: the transition zone was not reached.")
        return y + 40
    ph = 150
    for rows in mixed:
        heaps = sorted({h for v in versions for h in by_heap(data[v].get(rows, {}))})
        pad = max((heaps[-1] - heaps[0]) * 0.06, 8)
        x0, x1 = heaps[0] - pad, heaps[-1] + pad
        top = y + 22
        svg.text(LEFT, y + 12, f"{results_report.format_rows(rows)} rows", "panel-title ttl")
        px = lambda h: LEFT + (h - x0) / (x1 - x0) * PW
        py = lambda r: top + ph - r * ph
        y_axis(svg, top, ph, 0, 1, [0, 0.5, 1], lambda v: f"{v:.0%}", "pass rate")
        for h in nice_ticks(x0, x1, 12):
            svg.text(px(h), top + ph + 18, fmt_mb(h), anchor="middle")
        svg.text(LEFT + PW / 2, top + ph + 38, "heap, MB", anchor="middle")
        n = len(versions)
        for i, ver in enumerate(versions):
            col = SERIES[i][0]
            dy = (i - (n - 1) / 2) * 5
            pts = [(px(h), py(p / (p + f)) + dy, h, p, f)
                   for h, (p, f) in sorted(by_heap(data[ver].get(rows, {})).items())]
            if len(pts) > 1:
                svg.add(f'<polyline points="{" ".join(f"{x:.1f},{y_:.1f}" for x, y_, *_ in pts)}" fill="none" '
                        f'stroke="{col}" class="s{i}" stroke-width="1.5" stroke-opacity="0.5"/>')
            for x, y_, h, p, f in pts:
                tip = f"Dremio {ver}, {results_report.format_rows(rows)} rows, heap {h} MB: {p} PASS, {f} FAIL"
                svg.add(f'<g><title>{escape(tip)}</title>')
                svg.marker(i, x, y_, r=min(4 + (p + f - 1) * 1.2, 8))
                svg.add("</g>")
        y = top + ph + 62
    return y


# ------------------------------------------------------------------ 3. heap x direct
def section_heatmap(svg, y, data, versions):
    y = section_header(svg, y, "3. Heap x direct memory",
                       "Per combination: pass = largest row count that passed (darker = more), fail = smallest that failed. "
                       "Dashed cell: it failed at a row count that another run passed. Empty cell: not tested.")
    all_rows = sorted({r for d in data.values() for r in d})
    rank = {r: k for k, r in enumerate(all_rows)}
    for i, ver in enumerate(versions):
        col = SERIES[i][0]
        cells = defaultdict(lambda: {"pass": [], "fail": []})
        for rows, runs in data[ver].items():
            for (h, d), (p, f) in runs.items():
                if p:
                    cells[h, d]["pass"].append(rows)
                if f:
                    cells[h, d]["fail"].append(rows)
        heaps = sorted({h for h, _ in cells})
        directs = sorted({d for _, d in cells}, reverse=True)
        cw = min(PW / len(heaps), 96)
        ch = 46
        top = y + 24
        svg.marker(i, LEFT + 6, y + 8, r=4)
        svg.text(LEFT + 18, y + 12, f"Dremio {ver}", "panel-title ttl")
        for ci, h in enumerate(heaps):
            svg.text(LEFT + ci * cw + cw / 2, top + len(directs) * ch + 16, fmt_mb(h), anchor="middle")
        svg.text(LEFT + len(heaps) * cw / 2, top + len(directs) * ch + 36, "heap, MB", anchor="middle")
        for ri, d in enumerate(directs):
            svg.text(LEFT - 8, top + ri * ch + ch / 2 + 4, f"direct {fmt_mb(d)}", anchor="end")
            for ci, h in enumerate(heaps):
                x, y_ = LEFT + ci * cw, top + ri * ch
                c = cells.get((h, d))
                if not c:
                    svg.add(f'<rect x="{x + 1:.1f}" y="{y_ + 1:.1f}" width="{cw - 2:.1f}" height="{ch - 2}" rx="4" '
                            f'fill="none" stroke="{LIGHT["grid"]}" class="grid"/>')
                    continue
                best = max(c["pass"], default=None)
                worst = min(c["fail"], default=None)
                conflict = best is not None and worst is not None and worst <= best
                level = 0.12 + 0.43 * (rank[best] + 1) / len(all_rows) if best is not None else 0
                tip = (f"Dremio {ver}, heap {h} MB, direct {d} MB: "
                       f"passed up to {results_report.format_rows(best) if best else '-'} rows, "
                       f"failed from {results_report.format_rows(worst) if worst else '-'} rows")
                svg.add(f'<g><title>{escape(tip)}</title>')
                dash = ' stroke-dasharray="3 2"' if conflict else ""
                fill = f'fill="{col}" fill-opacity="{level:.2f}"' if best is not None else 'fill="none"'
                cls = f"f{i} s{i}" if best is not None else f"s{i}"
                svg.add(f'<rect x="{x + 1:.1f}" y="{y_ + 1:.1f}" width="{cw - 2:.1f}" height="{ch - 2}" rx="4" {fill} '
                        f'stroke="{col}" class="{cls}" stroke-width="1.5"{dash}/>')
                if best is not None:
                    svg.text(x + cw / 2, y_ + 19, f"pass {results_report.format_rows(best)}", "small ttl", "middle")
                if worst is not None:
                    svg.text(x + cw / 2, y_ + 35, f"fail {results_report.format_rows(worst)}", "small ttl", "middle")
                svg.add("</g>")
        y = top + len(directs) * ch + 54
    return y


def render(data, rams):
    versions = sorted(data)
    if len(versions) > len(SERIES):
        raise SystemExit(f"{len(versions)} Dremio versions: the palette is validated for {len(SERIES)}; "
                         "pass fewer CSV files or filter the versions")
    svg = Svg()
    svg.text(LEFT, 30, "Dremio memory vs rows: where PASS turns into FAIL", "title ttl")
    svg.text(LEFT, 50, f"Container RAM: {', '.join(sorted(rams)) or '?'}. Runs are pooled over CPUs and RAM; "
                       f"hover a mark for the numbers.")
    lx = LEFT
    for i, ver in enumerate(versions):
        svg.marker(i, lx + 6, 72, r=5)
        svg.text(lx + 18, 76, f"Dremio {ver}")
        lx += 40 + 8 * len(ver) + 40
    y = 100
    y = section_frontier(svg, y, data, versions)
    y = section_pass_rate(svg, y, data, versions)
    y = section_heatmap(svg, y, data, versions)
    H = y + 10
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H:.0f}" width="{W}" height="{H:.0f}" '
            f'role="img" fill="{LIGHT["ink2"]}" aria-label="PASS/FAIL analysis of the Dremio memory tests">')
    dark = [s[1] for s in SERIES]
    series_dark = "".join(f"  .f{i} {{ fill: {c} }} .s{i} {{ stroke: {c} }}\n" for i, c in enumerate(dark))
    style = "<style>" + CSS % {**DARK, "series": series_dark} + "</style>"
    bg = f'<rect width="{W}" height="{H:.0f}" fill="{LIGHT["surface"]}" class="bg"/>'
    return "\n".join([head, style, bg, *svg.parts, "</svg>"])
