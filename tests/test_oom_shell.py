"""Offline tests of the shell helpers the OOM search relies on (scripts/lib/common.sh through oom.runner.common_sh)."""
import argparse
import os
import shutil
import stat

import pytest

from oom import model as m
from oom import runner as rn

BASH = shutil.which("bash")


def path_with(tmp_path, *commands):
    """A directory that holds bash and the given fake commands only, so that `command -v` finds just those."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    os.symlink(BASH, bin_dir / "bash")
    for name in commands:
        script = bin_dir / name
        script.write_text('#!/bin/sh\necho "$0 $@"\n')
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(bin_dir)


def test_the_container_cli_is_incus_when_there_is_one_else_lxc(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", path_with(tmp_path, "incus", "lxc"))
    assert rn.container_cli() == "incus"
    shutil.rmtree(tmp_path / "bin")
    monkeypatch.setenv("PATH", path_with(tmp_path, "lxc"))
    assert rn.container_cli() == "lxc"


def test_without_a_container_cli_the_error_of_the_script_is_shown(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", path_with(tmp_path))
    with pytest.raises(SystemExit, match="neither incus nor lxc found in PATH"):
        rn.container_cli()


def test_cx_docker_run_starts_docker_in_the_container_without_the_apparmor_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", path_with(tmp_path, "incus"))
    out = rn.common_sh('detect_container_cli; NAME=box; cx_docker_run --rm --entrypoint bash img -c "echo 1"')
    assert out.endswith("incus exec box -- docker run --security-opt apparmor=unconfined --rm --entrypoint bash img -c echo 1")


def test_the_container_name_is_the_one_deploy_dremio_builds():
    combo = m.Combo("/x/dremio-enterprise-26.1.8-202605070149260956-31448f13.tar.gz", "wolfi-jdk:21")
    assert rn.container_name(combo, argparse.Namespace(container_mb=8192, cpus=4)) == "d26-1-8-wolfi-jdk-21-8G-4cpu"
    plain = m.Combo("/x/dremio-enterprise-26.1.10-1.tar.gz", "eclipse-temurin:21-jdk")
    assert rn.container_name(plain, argparse.Namespace(container_mb=14336, cpus=16)) == "d26-1-10-eclipse-temurin-21-jdk-14G-16cpu"
