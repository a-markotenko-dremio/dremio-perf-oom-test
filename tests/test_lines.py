"""Offline tests of the line chart of oom_ranges.csv (report.lines)."""
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
    assert data[("26.1.8", "eclipse-temurin:21-jdk")] == {512: (5e8, "490M", "510M"), 576: (6e8, "590M", "610M")}
    assert data[("26.1.10", "eclipse-temurin:21-jdk")][512][0] == pytest.approx(1.42e9)


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
