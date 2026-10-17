"""Offline tests of the PASS/FAIL scatter chart (report.scatter)."""
import pytest

from report import scatter


@pytest.mark.parametrize("text, value", [("100K", 1e5), ("1.44G", 1.44e9), ("10m", 1e7), ("2.5", 2.5), (" 4096 ", 4096)])
def test_parse_value(text, value):
    assert scatter.parse_value(text) == pytest.approx(value)


@pytest.mark.parametrize("text", ["", "abc", "42 + CTAS", "10T"])
def test_parse_value_rejects(text):
    with pytest.raises(ValueError):
        scatter.parse_value(text)


@pytest.mark.parametrize("value, text", [(1.44e9, "1.44G"), (100000, "100K"), (10**7, "10M"), (4096, "4096"), (7.5, "7.5")])
def test_format_value(value, text):
    assert scatter.format_value(value) == text


def test_nice_ticks_are_round_and_inside_the_range():
    ticks = scatter.nice_ticks(0, 1_440_000_000)
    assert 5 <= len(ticks) <= 12 and ticks[0] == 0 and ticks[-1] <= 1_440_000_000
    assert len({round(b - a) for a, b in zip(ticks, ticks[1:])}) == 1


def test_chart_colours_points_by_verdict(tmp_path):
    csv_path = tmp_path / "r.csv"
    csv_path.write_text("rows,heap,verdict\n10M,1024,PASS\n1.44G,512,fail\n5M,x,PASS\n1M,64,UNFINISHED\n")
    out = tmp_path / "o.svg"
    scatter.main([str(csv_path), "rows", "heap", "Verdict", "-o", str(out)])
    svg = out.read_text()
    assert svg.count('class="pPASS" fill-opacity') == 1 and svg.count('class="pFAIL" fill-opacity') == 1
    assert "1.44G" in svg and "PASS (1)" in svg and "FAIL (1)" in svg


def test_unknown_column_lists_the_columns(tmp_path):
    csv_path = tmp_path / "r.csv"
    csv_path.write_text("a,b,c\n1,2,PASS\n")
    with pytest.raises(SystemExit, match="no column named 'x'.*'a', 'b', 'c'"):
        scatter.main([str(csv_path), "a", "b", "x"])


def test_index_is_not_a_column(tmp_path):
    csv_path = tmp_path / "r.csv"
    csv_path.write_text("a,b,c\n1,2,PASS\n")
    with pytest.raises(SystemExit, match="no column named '0'"):
        scatter.main([str(csv_path), "0", "b", "c"])


def test_ambiguous_name(tmp_path):
    csv_path = tmp_path / "r.csv"
    csv_path.write_text("a,a,c\n1,2,PASS\n")
    with pytest.raises(SystemExit, match="ambiguous"):
        scatter.main([str(csv_path), "a", "a", "c"])
