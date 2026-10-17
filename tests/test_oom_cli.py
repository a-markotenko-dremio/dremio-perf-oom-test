"""Offline tests of the command line (oom.cli)."""
import pytest

from oom import cli


def test_default_heap_max_is_the_container_without_direct_and_reserve(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "find_package", lambda v: f"/x/dremio-enterprise-{v}-1.tar.gz")
    a = cli.parse_args([])
    assert a.heap_max == 8192 - 4096 - 2048 and len(a.packages) == 2 and a.java_images == ["eclipse-temurin:21-jdk", "wolfi-jdk:21"]
    with pytest.raises(SystemExit, match="even"):
        cli.parse_args(["--heap-step", "63"])
