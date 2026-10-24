"""Offline tests of the drawing toolkit shared by the charts (report.canvas)."""
import pytest

from report import canvas


def test_nice_ticks_are_round_and_inside_the_range():
    ticks = canvas.nice_ticks(0, 1_440_000_000, 8)
    assert 5 <= len(ticks) <= 12 and ticks[0] == 0 and ticks[-1] <= 1_440_000_000
    assert len({round(b - a) for a, b in zip(ticks, ticks[1:])}) == 1


@pytest.mark.parametrize("lo, hi", [(2994.74, 3002.4), (0.3, 7.9), (-5.5, 5.5), (300.0, 1500.0)])
def test_no_tick_is_outside_the_range(lo, hi):
    for steps in (None, canvas.MB_STEPS):
        ticks = canvas.nice_ticks(lo, hi, 7, steps)
        assert ticks and all(lo <= t <= hi for t in ticks)


def test_the_steps_decide_the_distance_between_ticks_and_integer_steps_give_integers():
    assert canvas.nice_ticks(0, 1000, 8) == [0, 200, 400, 600, 800, 1000]                     # 1, 2 or 5 times a power of ten
    ticks = canvas.nice_ticks(300, 1500, 7, canvas.MB_STEPS)
    assert ticks == [400, 600, 800, 1000, 1200, 1400] and all(isinstance(t, int) for t in ticks)
    assert canvas.nice_ticks(0, 1000, 6, canvas.MB_STEPS) == [0, 200, 400, 600, 800, 1000]    # from the list of steps (200)
    assert canvas.nice_ticks(0, 1000, 7, canvas.MB_STEPS) == [0, 200, 400, 600, 800, 1000]
    assert canvas.nice_ticks(0, 100, 7, canvas.MB_STEPS) == [0, 16, 32, 48, 64, 80, 96]       # 16 is in the list, 20 would give 6 ticks


def test_pad_range_leaves_room_on_both_sides_and_copes_with_one_value():
    assert canvas.pad_range([10, 20]) == pytest.approx((9.4, 20.6))
    lo, hi = canvas.pad_range([50])
    assert lo < 50 < hi


def test_scale_maps_a_range_onto_a_length_and_a_negative_length_turns_it_over():
    to_x = canvas.scale(0, 10, 100, 500)
    assert (to_x(0), to_x(10), to_x(5)) == (100, 600, 350)
    to_y = canvas.scale(0, 10, 400, -300)
    assert (to_y(0), to_y(10)) == (400, 100)


def test_tick_labels_use_the_csv_notation_and_never_round():
    assert [canvas.format_tick(v) for v in (1.44e9, 100000.0, 4096.0, 1234567.0)] == ["1.44G", "100K", "4096", "1.23457e+06"]


def test_a_shape_with_a_title_has_a_hover_text_and_without_one_is_self_closing():
    svg = canvas.Svg()
    svg.shape(0, 10, 20, 5, 'fill="red"', "a < b")
    svg.shape(1, 10, 20, 5, 'fill="red"')
    svg.shape(2, 10, 20, 5, 'fill="red"')
    circle, square, diamond = svg.parts
    assert circle.startswith("<circle ") and circle.endswith("<title>a &lt; b</title></circle>")
    assert square.startswith("<rect ") and square.endswith("/>") and diamond.startswith("<path ") and diamond.endswith("/>")


def test_a_marker_takes_the_colour_of_its_series_and_the_shape_apart_from_it():
    svg = canvas.Svg()
    svg.marker(1, 10, 20, shape=0, title="tip")
    assert f'fill="{canvas.SERIES[1][0]}"' in svg.parts[0] and "<circle " in svg.parts[0] and 'class="f1 ring"' in svg.parts[0]


def test_a_document_carries_the_theme_the_parts_and_the_size():
    text = canvas.document(["<g/>"], 321.4, 'a "chart"', "  .p { fill: red }\n")
    assert text.startswith("<svg ") and text.endswith("</svg>") and "<g/>" in text
    assert 'viewBox="0 0 1100 321"' in text and "&quot;chart&quot;" in text and ".p { fill: red }" in text
    assert "prefers-color-scheme: dark" in text
