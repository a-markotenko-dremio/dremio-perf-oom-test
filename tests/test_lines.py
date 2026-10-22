"""Offline tests of the line chart of oom_ranges.csv (report.lines)."""
import re

import pytest

from report import lines

HEADER = "Dremio ver,Java image,Heap MB,Pass max rows,Fail min rows,Mean rows,Status\n"


def write(tmp_path, *rows):
    path = tmp_path / "ranges.csv"
    path.write_text(HEADER + "".join(rows))
    return path


def test_one_line_per_version_and_java_image(tmp_path):
    path = write(tmp_path,
                 "26.1.8,eclipse-temurin:21-jdk,512,490M,510M,500M,RANGE\n",
                 "26.1.8,eclipse-temurin:21-jdk,576,590M,610M,600M,RANGE\n",
                 "26.1.8,wolfi-jdk:21,512,390M,410M,400M,RANGE\n",
                 "26.1.10,eclipse-temurin:21-jdk,512,1.4G,1.44G,1.42G,RANGE\n",
                 "26.1.10,wolfi-jdk:21,512,10M,,,ALL_FAIL\n")
    data, no_mean = lines.load([path])
    assert sorted(data) == [("26.1.10", "eclipse-temurin:21-jdk"), ("26.1.8", "eclipse-temurin:21-jdk"),
                            ("26.1.8", "wolfi-jdk:21")] and no_mean == 1
    assert data[("26.1.8", "eclipse-temurin:21-jdk")] == {512: [(5e8, "490M", "510M")], 576: [(6e8, "590M", "610M")]}
    assert data[("26.1.10", "eclipse-temurin:21-jdk")][512][0][0] == pytest.approx(1.42e9)


def test_chart_has_a_polyline_per_combination_and_a_point_per_step(tmp_path):
    path = write(tmp_path,
                 "26.1.8,a,512,1M,3M,2M,RANGE\n", "26.1.8,a,576,2M,4M,3M,RANGE\n",
                 "26.1.8,b,512,1M,3M,2M,RANGE\n", "26.1.8,b,576,2M,4M,3M,RANGE\n")
    out = tmp_path / "o.svg"
    lines.main([str(path), "-o", str(out)])
    svg = out.read_text()
    assert svg.count("<polyline") == 2 and svg.count("<title>") == 4
    assert "Dremio 26.1.8 · a" in svg and "PASS up to 1M, FAIL from 3M" in svg


def test_too_many_versions_are_refused(tmp_path):
    rows = [f"26.1.{v},a,512,1M,3M,2M,RANGE\n" for v in range(4)]
    with pytest.raises(SystemExit, match="Dremio versions"):
        lines.render(lines.load([write(tmp_path, *rows)])[0], "t")


def test_file_without_means_is_refused(tmp_path):
    with pytest.raises(SystemExit, match="no steps with a mean"):
        lines.main([str(write(tmp_path, "26.1.8,a,512,1.44G,,,ALL_PASS\n")), "-o", str(tmp_path / "o.svg")])


# The five repeated searches of 26.1.10 / wolfi-jdk:21 at heap 640 (data/repeats/oom_rep_10W_640_*.ranges.csv) and the
# search of the main sweep at the neighbouring heap sizes.
REPEATS_10W = ["26.1.10,wolfi-jdk:21,640,912M,917M,914.5M,RANGE\n", "26.1.10,wolfi-jdk:21,640,873M,879M,876M,RANGE\n",
               "26.1.10,wolfi-jdk:21,640,808M,814M,811M,RANGE\n", "26.1.10,wolfi-jdk:21,640,770M,775M,772.5M,RANGE\n",
               "26.1.10,wolfi-jdk:21,640,644M,650M,647M,RANGE\n"]
NEIGHBOURS_10W = ["26.1.10,wolfi-jdk:21,608,687M,693M,690M,RANGE\n", "26.1.10,wolfi-jdk:21,672,794M,800M,797M,RANGE\n"]


def test_repeated_searches_of_a_heap_size_are_kept_and_not_warned_about(tmp_path, capsys):
    data, _ = lines.load([write(tmp_path, *NEIGHBOURS_10W, *REPEATS_10W)])
    rows = data[("26.1.10", "wolfi-jdk:21")]
    assert [m for m, _, _ in rows[640]] == [914.5e6, 876e6, 811e6, 772.5e6, 647e6] and len(rows[608]) == 1
    assert capsys.readouterr().err == ""


def test_a_repeated_heap_size_is_drawn_at_the_mean_with_a_bar_over_the_spread(tmp_path):
    out = tmp_path / "o.svg"
    lines.main([str(write(tmp_path, *NEIGHBOURS_10W, *REPEATS_10W)), "-o", str(out)])
    svg = out.read_text()
    assert svg.count("<polyline") == 1 and svg.count("<circle") + svg.count("<rect") + svg.count("<path d=") >= 3
    assert svg.count('<line class="s0"') == 1                          # one bar: only heap 640 has several searches
    assert "mean 804.2M rows of 5 searches (from 647M to 914.5M)" in svg


def test_the_axis_reaches_the_ends_of_the_bar(tmp_path):
    rows = ["26.1.8,a,512,1M,3M,2M,RANGE\n", "26.1.8,a,512,8M,10M,9M,RANGE\n", "26.1.8,a,576,4M,6M,5M,RANGE\n"]
    out = tmp_path / "o.svg"
    lines.main([str(write(tmp_path, *rows)), "-o", str(out)])
    svg = out.read_text()
    y1, y2 = [float(v) for v in re.search(r'<line class="s0"[^>]* y1="([\d.]+)"[^>]* y2="([\d.]+)"', svg).groups()]
    assert 110 <= min(y1, y2) and max(y1, y2) <= 110 + 460 and abs(y1 - y2) > 100      # inside the plot, and long


RUNS_HEADER = "Timestamp,Dremio ver,Java image,Heap MB,Rows,Outcome\n"


def write_runs(tmp_path, *rows):
    path = tmp_path / "runs.csv"
    path.write_text(RUNS_HEADER + "".join(f"t,{r}\n" for r in rows))
    return path


def test_the_run_summary_counts_the_outcomes_and_the_row_counts(tmp_path):
    path = write_runs(tmp_path, "26.1.8,a,512,32,PASS", "26.1.8,a,512,43,FAIL", "26.1.8,a,512,1440,PASS", "26.1.8,a,512,700,ERROR")
    assert lines.run_summary([path]) == {"PASS": 2, "FAIL": 1, "other": 1, "rows": (32, 1440)}
    with pytest.raises(SystemExit, match="no runs"):
        lines.run_summary([write_runs(tmp_path)])


def test_the_description_names_the_point_the_limits_and_the_runs(tmp_path):
    data, _ = lines.load([write(tmp_path, *NEIGHBOURS_10W, *REPEATS_10W)])
    text = lines.describe(data, {"PASS": 244, "FAIL": 201, "other": 0, "rows": (32, 1440)}, "container 8 GB, 16 CPUs")
    assert "highest PASS and the lowest FAIL" in text[0] and "the 5 searches of one combination" in text[0]
    assert text[1] == "Limits: container 8 GB, 16 CPUs. Heap 608 to 672 MB."
    assert text[2] == "Runs: 445 test runs (244 PASS, 201 FAIL) of 32M to 1.44G rows, in 7 searches with a result."
    assert lines.describe(data)[1:] == ["Heap 608 to 672 MB."]             # without --limits and --runs only what the data says


def test_the_description_is_drawn_below_the_axis_and_the_chart_grows(tmp_path):
    ranges = write(tmp_path, *NEIGHBOURS_10W, *REPEATS_10W)
    plain, noted = tmp_path / "plain.svg", tmp_path / "noted.svg"
    lines.main([str(ranges), "-o", str(plain)])
    lines.main([str(ranges), "-o", str(noted), "--runs", str(write_runs(tmp_path, "26.1.10,a,640,700,PASS", "26.1.10,a,640,800,FAIL")),
                "--limits", "container 8 GB"])
    height = lambda path: float(re.search(r'viewBox="0 0 \d+ ([\d.]+)"', path.read_text()).group(1))
    assert "Limits: container 8 GB. Heap 608 to 672 MB." in noted.read_text()
    assert "Runs: 2 test runs (1 PASS, 1 FAIL) of 700M to 800M rows" in noted.read_text()
    assert height(noted) > height(plain) > 560
