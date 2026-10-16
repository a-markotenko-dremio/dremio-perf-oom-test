"""Drawing toolkit of the SVG report: palette, theme CSS, the Svg builder and the shared axes."""
import textwrap
from html import escape

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


def nice_ticks(lo, hi, want=7):
    """Round values between lo and hi, about `want` of them."""
    step = next((t for t in (1, 2, 4, 5, 8, 10, 16, 20, 25, 32, 50, 64, 100, 128, 200, 256, 500, 512, 1024, 2048, 4096)
                 if (hi - lo) / t <= want), 8192)
    first = -(-int(lo) // step) * step
    return list(range(first, int(hi) + 1, step))


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

    def marker(self, i, x, y, r=5.5, filled=True, opacity=1.0):
        """Series i: circle, square, diamond (shape + colour, never colour alone)."""
        col = SERIES[i][0]
        fill = f'fill="{col}" class="f{i} ring" fill-opacity="{opacity}"' if filled else f'fill="none" class="s{i}"'
        stroke = (f'stroke="{LIGHT["surface"]}" stroke-width="2"' if filled
                  else f'stroke="{col}" stroke-width="2"')
        if i % 3 == 0:
            self.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" {fill} {stroke}/>')
        elif i % 3 == 1:
            self.add(f'<rect x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r}" height="{2 * r}" rx="1" {fill} {stroke}/>')
        else:
            self.add(f'<path d="M{x:.1f} {y - r * 1.3:.1f}L{x + r * 1.3:.1f} {y:.1f}L{x:.1f} {y + r * 1.3:.1f}'
                     f'L{x - r * 1.3:.1f} {y:.1f}Z" {fill} {stroke}/>')


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
