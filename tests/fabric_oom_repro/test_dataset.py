"""Offline tests of fabric_oom_repro.dataset: the data set is generated on every host of the nodes, never copied between them."""
import os
import stat

import pytest

from fabric_oom_repro import dataset, generate_oom_data

SCALE = 0.0001


@pytest.fixture
def hosts(tmp_path, monkeypatch):
    """Fake ssh (runs the command here, recording the host) and rsync (records its arguments); every call is a line of `calls`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, script in (("ssh", f'echo "ssh $3" >> "{tmp_path}/calls"\nshift 3\nexec bash -c "$1"'),
                         ("rsync", f'echo "rsync $@" >> "{tmp_path}/calls"')):
        tool = bin_dir / name
        tool.write_text(f"#!/bin/bash\n{script}\n")
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # the fake hosts share this one: REMOTE_DIR lands in it
    (tmp_path / "home").mkdir()
    return lambda: (tmp_path / "calls").read_text().splitlines() if (tmp_path / "calls").exists() else []


def test_a_missing_data_set_is_generated_here_for_a_local_container_and_on_every_other_host(tmp_path, hosts, monkeypatch):
    monkeypatch.setattr(dataset, "run_checked", lambda host, command: f"generated on {host}")  # the remote generator needs a venv
    path = tmp_path / "data" / "scale-0.0001"
    log = []
    dataset.prepare(path, SCALE, ["d27", "den:d27", "yarn://a-1", "yarn://a-2"], log=log.append)
    assert all((path / name).is_dir() for name in generate_oom_data.TABLES)
    assert sorted(m for m in log if m.startswith("generated on")) == [f"generated on {h}" for h in ("a-1", "a-2", "den")]
    assert sorted(c for c in hosts() if c.startswith("rsync")) == sorted(
        f"rsync -a {dataset.GENERATOR} {h}:{dataset.REMOTE_DIR}/" for h in ("den", "a-1", "a-2"))


def test_nothing_is_generated_here_when_every_node_is_on_another_host(tmp_path, hosts, monkeypatch):
    monkeypatch.setattr(dataset, "run_checked", lambda host, command: "")
    dataset.prepare(tmp_path / "data", SCALE, ["yarn://a-1"], log=lambda m: None)
    assert not (tmp_path / "data").exists()


def test_the_generator_runs_in_a_venv_with_the_duckdb_of_the_requirements(hosts, tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(dataset, "run_checked", lambda host, command: commands.append((host, command)) or "")
    dataset.generate_remote("a-1", "/data/fabric-oom-repro/scale-0.0175", 0.0175, lambda m: None)
    assert dataset.duckdb_requirement() == "duckdb==1.5.6"
    (_, setup), (host, run) = commands
    assert dataset.duckdb_requirement() in setup[-1] and "uv pip install" in setup[-1] and dataset.REMOTE_PYTHON in setup[-1]
    assert (host, run) == ("a-1", [f"{dataset.REMOTE_DIR}/venv/bin/python", f"{dataset.REMOTE_DIR}/generate_oom_data.py",
                                   "/data/fabric-oom-repro/scale-0.0175", "--scale", "0.0175"])


def test_a_failing_remote_command_is_an_error_with_its_output(hosts):
    with pytest.raises(AssertionError, match="false on a-1 failed"):
        dataset.run_checked("a-1", ["false"])


def test_ensure_keeps_a_data_set_generates_in_an_empty_directory_and_refuses_any_other(tmp_path):
    path = tmp_path / "empty"
    path.mkdir()
    generate_oom_data.ensure(path, SCALE, log=lambda m: None)
    stamp = (path / "TestSuiteInfo").stat().st_mtime_ns
    generate_oom_data.ensure(path, SCALE, log=lambda m: None)
    assert (path / "TestSuiteInfo").stat().st_mtime_ns == stamp
    (tmp_path / "other" / "TestCaseData").mkdir(parents=True)
    with pytest.raises(SystemExit, match="not a data set"):
        generate_oom_data.ensure(tmp_path / "other", SCALE, log=lambda m: None)
