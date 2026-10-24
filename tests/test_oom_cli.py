"""Offline tests of the command line (oom.cli)."""
import pytest

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
