"""Offline tests of the command line (oom.cli)."""
import pytest

import defaults
from oom import cli


def test_default_heap_max_is_the_container_without_direct_and_reserve(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "find_package", lambda v: f"/x/dremio-enterprise-{v}-1.tar.gz")
    a = cli.parse_args([])
    assert a.heap_max == 8192 - 4096 - 2048 and len(a.packages) == 2 and a.java_images == ["eclipse-temurin:21-jdk", "wolfi-jdk:21"]
    with pytest.raises(SystemExit, match="even"):
        cli.parse_args(["--heap-step", "63"])


def test_the_start_cleans_the_leftovers_before_the_first_run_and_a_plan_only_lists_them(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "clean_stale", lambda args: calls.append(("clean", args.plan)))
    monkeypatch.setattr(cli, "run_all", lambda *a, **k: calls.append(("run",)))
    flags = ["--packages", "/x/dremio-enterprise-26.1.8-1.tar.gz", "--ranges-csv", str(tmp_path / "r.csv"),
             "--runs-csv", str(tmp_path / "n.csv")]
    cli.main(flags + ["--plan"])
    assert calls == [("clean", True)]                                     # listed, nothing runs
    calls.clear()
    cli.main(flags)
    assert calls == [("clean", False), ("run",)]
    with pytest.raises(SystemExit):
        cli.parse_args(["--clean-stale"])                                 # the flag is gone: it is always done


def test_the_tables_of_the_search_are_in_files_unless_s3_is_asked_for():
    assert cli.parse_args(["--packages", "a.tar.gz"]).storage == "fs"
    assert cli.parse_args(["--packages", "a.tar.gz", "--storage", "s3"]).storage == "s3"
    with pytest.raises(SystemExit):
        cli.parse_args(["--packages", "a.tar.gz", "--storage", "nfs"])


def test_the_results_of_each_storage_are_kept_in_files_of_their_own():
    fs, s3 = cli.parse_args(["--packages", "a"]), cli.parse_args(["--packages", "a", "--storage", "s3"])
    assert (fs.runs_csv, fs.ranges_csv) == (str(defaults.DATA_DIR / "oom_runs.csv"), str(defaults.DATA_DIR / "oom_ranges.csv"))
    assert (s3.runs_csv, s3.ranges_csv) == (str(defaults.DATA_DIR / "oom_runs_s3.csv"), str(defaults.DATA_DIR / "oom_ranges_s3.csv"))
    assert cli.parse_args(["--packages", "a", "--storage", "s3", "--runs-csv", "x.csv"]).runs_csv == "x.csv"
    assert defaults.storage_file("oom_lines.svg", "s3") == defaults.DATA_DIR / "oom_lines_s3.svg"
