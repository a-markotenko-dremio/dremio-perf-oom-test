"""Offline tests of the PASS/FAIL scatter chart (report.scatter)."""
import pytest

from report import scatter


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
