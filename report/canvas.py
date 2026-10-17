"""Drawing toolkit of the SVG report: palette, theme CSS, the Svg builder and the shared axes."""
import math
import textwrap
from html import escape

import quantities

# Categorical slots 1-3 of the reference palette: the only ones validated for all-pairs forms.
SERIES = [("#2a78d6", "#3987e5"), ("#eb6834", "#d95926"), ("#1baf7a", "#199e70")]

# Light colours go into the element attributes (every SVG renderer understands them, CSS variables
# are not supported by many viewers); the dark theme only overrides them through classes.
LIGHT = {"surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "grid": "#e4e3df"}
DARK = {"surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "grid": "#33332f"}

CSS = """
text { font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; font-size: 12px }
.title { font-size: 18px; font-weight: 600 }
.section { font-size: 15px; font-weight: 600 }
.panel-title { font-size: 13px; font-weight: 600 }
.small { font-size: 10px }
@media (prefers-color-scheme: dark) {
  .bg { fill: %(surface)s } .t { fill: %(ink2)s } .ttl { fill: %(ink)s }
  .grid { stroke: %(grid)s } .axis, .ink2s { stroke: %(ink2)s } .ink2f { fill: %(ink2)s } .ring { stroke: %(surface)s }
%(series)s}
"""

W, LEFT, RIGHT = 1100, 80, 30
PW = W - LEFT - RIGHT


def fmt_mb(mb):
    return f"{mb / 1024:g}G" if mb % 256 == 0 and mb >= 1024 else f"{mb}M"


MB_STEPS = (1, 2, 4, 5, 8, 10, 16, 20, 25, 32, 50, 64, 100, 128, 200, 256, 500, 512, 1024, 2048, 4096)


def nice_ticks(lo, hi, want=7, steps=None):
    """Round values between lo and hi, about `want` of them. `steps` are the allowed distances between two ticks (default:
    1, 2 or 5 times a power of ten); the smallest one that gives at most `want` ticks is used. Integer steps give integers."""
    raw = (hi - lo) / want
    if steps is None:
        mag = 10 ** math.floor(math.log10(raw))
        steps = [m * mag for m in (1, 2, 5, 10)]
    step = next((t for t in steps if t >= raw), steps[-1] * 2)
    first = math.ceil(lo / step - 1e-9) * step
    ticks, i = [], 0
    while first + i * step <= hi + step * 1e-9:
        ticks.append(round(first + i * step, 10))
        i += 1
    return ticks


def pad_range(values):
    """The range of the values with 6% of room on both sides (10% of the value, or 1, when they are all the same)."""
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.06 or (abs(hi) * 0.1 or 1)
    return lo - pad, hi + pad


def format_tick(v):
    """A label of an axis in the K/M/G notation of the CSV files, never a rounded number."""
    return quantities.format_quantity(v, exact=True)


def scale(lo, hi, origin, length):
    """The function that maps a value of lo..hi to origin..origin+length (a negative length turns the axis over)."""
    return lambda v: origin + (v - lo) / (hi - lo) * length


class Svg:
    def __init__(self):
        self.parts = []

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, cls="t", anchor="start", extra=""):
        fill = f' fill="{LIGHT["ink"]}"' if "ttl" in cls else ""
        self.add(f'<text class="{cls}"{fill} x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}"{extra}>{escape(str(s))}</text>')

    def line(self, x1, y1, x2, y2, cls, color, width=1, dash=""):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<line class="{cls}" stroke="{color}" stroke-width="{width}"{d} '
                 f'x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')

    def shape(self, kind, x, y, r, attrs, title=""):
        """A circle (kind 0), a square (1) or a diamond (2) of radius r; `attrs` are its other SVG attributes, `title` the hover text."""
        if kind % 3 == 0:
            tag, geometry = "circle", f'cx="{x:.1f}" cy="{y:.1f}" r="{r}"'
        elif kind % 3 == 1:
            tag, geometry = "rect", f'x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r}" height="{2 * r}" rx="1"'
        else:
            tag = "path"
            geometry = (f'd="M{x:.1f} {y - r * 1.3:.1f}L{x + r * 1.3:.1f} {y:.1f}L{x:.1f} {y + r * 1.3:.1f}'
                        f'L{x - r * 1.3:.1f} {y:.1f}Z"')
        if title:
            self.add(f'<{tag} {geometry} {attrs}><title>{escape(title)}</title></{tag}>')
        else:
            self.add(f'<{tag} {geometry} {attrs}/>')

    def marker(self, i, x, y, r=5.5, filled=True, opacity=1.0, shape=None, title=""):
        """A mark in the colour of series i; the shape is told apart too (colour is never the only code): by default
        circle, square, diamond by series, or the given `shape`."""
        col = SERIES[i][0]
        fill = f'fill="{col}" class="f{i} ring" fill-opacity="{opacity}"' if filled else f'fill="none" class="s{i}"'
        stroke = (f'stroke="{LIGHT["surface"]}" stroke-width="2"' if filled
                  else f'stroke="{col}" stroke-width="2"')
        self.shape(i if shape is None else shape, x, y, r, f"{fill} {stroke}", title)


def section_header(svg, y, title, caption):
    svg.text(LEFT, y, title, "section ttl")
    lines = textwrap.wrap(caption, 140)
    for k, line in enumerate(lines):
        svg.text(LEFT, y + 18 + 15 * k, line, "t")
    return y + 22 + 15 * len(lines)


def y_axis(svg, top, ph, lo, hi, ticks, fmt, label):
    for v in ticks:
        y = top + ph - (v - lo) / (hi - lo) * ph
        svg.line(LEFT, y, LEFT + PW, y, "grid", LIGHT["grid"])
        svg.text(LEFT - 8, y + 4, fmt(v), anchor="end")
    svg.line(LEFT, top + ph, LEFT + PW, top + ph, "axis", LIGHT["ink2"])
    svg.text(16, top + ph / 2, label, anchor="middle", extra=f' transform="rotate(-90 16 {top + ph / 2:.0f})"')


def x_axis(svg, top, ph, to_x, ticks, fmt, label):
    """The ticks of a horizontal axis below the plot (grid lines through it) and its label."""
    for t in ticks:
        svg.line(to_x(t), top, to_x(t), top + ph, "grid", LIGHT["grid"])
        svg.text(to_x(t), top + ph + 20, fmt(t), anchor="middle")
    svg.text(LEFT + PW / 2, top + ph + 44, label, anchor="middle")


SERIES_DARK_CSS = "".join(f"  .f{i} {{ fill: {c[1]} }} .s{i} {{ stroke: {c[1]} }}\n" for i, c in enumerate(SERIES))


def document(parts, height, label, series_css):
    """The finished SVG text: header, theme CSS (`series_css` are the dark-theme rules of the marks), background, `parts`."""
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height:.0f}" width="{W}" height="{height:.0f}" '
            f'role="img" fill="{LIGHT["ink2"]}" aria-label="{escape(label)}">')
    style = "<style>" + CSS % {**DARK, "series": series_css} + "</style>"
    bg = f'<rect width="{W}" height="{height:.0f}" fill="{LIGHT["surface"]}" class="bg"/>'
    return "\n".join([head, style, bg, *parts, "</svg>"])
