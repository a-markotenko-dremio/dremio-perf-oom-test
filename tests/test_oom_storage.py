"""Offline tests of the cleaning of the container storages (oom.runner): what is deleted and what never is."""
import argparse
import os
import subprocess

import pytest

from oom import cli
from oom import model as m
from oom import runner as rn

NAME = "d26-1-8-wolfi-jdk-21-8G-4cpu"


def make_storage(root, name=NAME):
    """A storage as the tests leave it: a link to the shared blocks, the input table (hard links to the blocks) and a
    half-written output table of a failed run."""
    shared = root / "blocks"
    shared.mkdir(exist_ok=True)
    (shared / "block_0.parquet").write_text("data")
    storage = root / name
    (storage / "input").mkdir(parents=True)
    os.symlink(shared, storage / "blocks")
    os.link(shared / "block_0.parquet", storage / "input" / "block_0.parquet")
    (storage / "output" / "tpcds-1tb" / "catalog_sales").mkdir(parents=True)
    (storage / "output" / "tpcds-1tb" / "catalog_sales" / "half.parquet").write_text("x" * 1000)
    return storage


def test_the_storage_is_deleted_with_its_leftovers_and_the_shared_blocks_stay(tmp_path):
    storage = make_storage(tmp_path)
    rn.remove_storage(tmp_path, NAME, keep=tmp_path / "blocks")
    assert not storage.exists()
    assert (tmp_path / "blocks" / "block_0.parquet").read_text() == "data"           # neither the link nor the hard link took it


def test_a_missing_storage_is_not_an_error(tmp_path):
    rn.remove_storage(tmp_path, NAME)


@pytest.mark.parametrize("name", ["", "..", "a/b", "../x", "/etc"])
def test_only_a_directory_directly_under_the_root_is_deleted(tmp_path, name):
    with pytest.raises(ValueError, match="not a directory directly under"):
        rn.remove_storage(tmp_path, name)


def test_the_directory_that_has_to_survive_is_never_deleted_with_its_parent(tmp_path):
    storage = make_storage(tmp_path)
    with pytest.raises(ValueError, match="refusing"):
        rn.remove_storage(tmp_path, NAME, keep=storage / "blocks_inside")
    assert storage.exists()


def test_a_symlink_is_removed_without_touching_its_target(tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "f").write_text("keep")
    os.symlink(target, tmp_path / NAME)
    rn.remove_storage(tmp_path, NAME)
    assert not (tmp_path / NAME).exists() and (target / "f").read_text() == "keep"


def test_stale_storages_are_the_container_named_directories_without_a_container(tmp_path):
    for name in (NAME, "d26-1-10-eclipse-temurin-21-jdk-14G-16cpu", "d26-1-8-j21-4G-4cpu", "Downloads", "blocks", "notes", "d26-1-8"):
        (tmp_path / name).mkdir()
    (tmp_path / "d27-0-0-wolfi-jdk-21-8G-4cpu").write_text("a file")
    os.symlink(tmp_path / "blocks", tmp_path / "d26-1-9-link-8G-4cpu")
    stale = rn.stale_storage_dirs(tmp_path, existing={"d26-1-10-eclipse-temurin-21-jdk-14G-16cpu"})
    assert stale == ["d26-1-8-j21-4G-4cpu", NAME]
    assert rn.stale_storage_dirs(tmp_path / "none", set()) == []


def fake_runner(tmp_path, monkeypatch, calls):
    monkeypatch.setattr(rn, "container_cli", lambda: "incus")
    monkeypatch.setattr(rn, "container_name", lambda combo, args: NAME)

    def fake_run(cmd, **kwargs):
        calls.append((cmd[:2], (tmp_path / NAME).exists()))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(rn.subprocess, "run", fake_run)
    args = argparse.Namespace(storage_root=str(tmp_path), container_mb=8192, cpus=4, direct_mb=4096)
    return rn.Runner(args, m.Combo("/x/dremio-enterprise-26.1.8-1.tar.gz", "wolfi-jdk:21"))


def test_a_deployment_starts_by_deleting_the_container_and_the_leftovers_of_the_previous_one(tmp_path, monkeypatch):
    make_storage(tmp_path)
    calls = []
    runner = fake_runner(tmp_path, monkeypatch, calls)
    assert runner.deploy(1024)
    assert calls[0][0] == ["incus", "delete"] and calls[1][0][0].endswith("deploy_dremio.sh")
    assert calls[1][1] is False                                     # the storage was gone when the deployment began
    assert (tmp_path / "blocks" / "block_0.parquet").exists()


def test_a_finished_step_deletes_the_container_and_the_storage(tmp_path, monkeypatch):
    make_storage(tmp_path)
    runner = fake_runner(tmp_path, monkeypatch, [])
    runner.deployed_heap = 1024
    runner.delete()
    assert not (tmp_path / NAME).exists() and runner.deployed_heap is None and (tmp_path / "blocks").is_dir()


def test_the_blocks_directory_inside_a_storage_stops_the_deletion(tmp_path, monkeypatch):
    make_storage(tmp_path)
    monkeypatch.setenv("BLOCKS_DIR", str(tmp_path / NAME / "blocks_real"))
    runner = fake_runner(tmp_path, monkeypatch, [])
    with pytest.raises(ValueError, match="refusing"):
        runner.delete()
    assert (tmp_path / NAME).exists()


def test_clean_stale_lists_with_plan_and_deletes_without(tmp_path, monkeypatch, capsys):
    make_storage(tmp_path, "d26-1-8-j21-4G-4cpu")
    make_storage(tmp_path, "d26-1-10-j21-4G-4cpu")
    monkeypatch.setattr(cli, "container_cli", lambda: "incus")
    monkeypatch.setattr(cli, "list_containers", lambda cli_name: {"d26-1-10-j21-4G-4cpu"})
    args = argparse.Namespace(storage_root=str(tmp_path), plan=True)
    cli.clean_stale(args)
    assert "would delete the storage" in capsys.readouterr().out and (tmp_path / "d26-1-8-j21-4G-4cpu").exists()
    args.plan = False
    cli.clean_stale(args)
    assert not (tmp_path / "d26-1-8-j21-4G-4cpu").exists() and (tmp_path / "d26-1-10-j21-4G-4cpu").exists()
    assert (tmp_path / "blocks" / "block_0.parquet").exists()
    cli.clean_stale(args)
    assert "no stale storages" in capsys.readouterr().out
