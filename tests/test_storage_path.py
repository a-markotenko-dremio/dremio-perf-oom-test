"""Offline tests of the container storages: <STORAGE_ROOT>/<container name>, and the root itself is never mounted."""
import os
import subprocess
from pathlib import Path

import pytest

import defaults

LIB = defaults.ROOT_DIR / "scripts" / "lib"
ROOT = str(defaults.STORAGE_ROOT)


def container_sh(script, tmp_path=None, **env):
    """Runs the script after sourcing common.sh and container.sh; with tmp_path, a fake incus from there is first in PATH."""
    path = f"{tmp_path}:{os.environ['PATH']}" if tmp_path else os.environ["PATH"]
    return subprocess.run(["bash", "-euc", f"source {LIB}/common.sh; source {LIB}/container.sh; {script}"],
                           capture_output=True, text=True, env={**os.environ, "PATH": path, **env})


def test_the_storage_of_a_container_is_its_name_under_the_root():
    assert defaults.storage_path("v27") == defaults.STORAGE_ROOT / "v27"
    assert defaults.storage_path("v27", "/tmp/root") == Path("/tmp/root/v27")
    assert container_sh("storage_path v27").stdout.strip() == f"{ROOT}/v27"


def test_the_data_set_of_the_fabric_oom_stand_is_named_by_its_scale_outside_any_container_storage():
    assert defaults.OOM_REPRO_DATA == defaults.STORAGE_ROOT / "fabric-oom-repro" / "scale-0.0175"


@pytest.mark.parametrize("path", [ROOT, ROOT + "/", str(defaults.STORAGE_ROOT.parent), "/"])
def test_the_root_and_the_directories_above_it_are_refused(path):
    r = container_sh("check_storage_root", STORAGE_PATH=path, NAME="v27")
    assert r.returncode == 1
    assert f"would mount the storage root {ROOT} of all containers" in r.stderr
    assert f"e.g. {ROOT}/v27 (the default)" in r.stderr


@pytest.mark.parametrize("path", [ROOT + "/v27", ROOT + "-v27", "/tmp/storage"])
def test_a_directory_under_the_root_or_beside_it_is_accepted(path):
    assert container_sh("check_storage_root", STORAGE_PATH=path, NAME="v27").returncode == 0


def test_the_shared_storage_error_suggests_the_storage_of_the_new_container(tmp_path):
    # the case on home4: the stand coordinator mounts the whole root, a new container v27 asks for <root>/27
    incus = tmp_path / "incus"
    incus.write_text(f'#!/bin/bash\ncase "$1" in list) echo "d25-2-0-j21-14G-4cpu,RUNNING" ;; config) echo "{ROOT}" ;; esac\n')
    incus.chmod(0o755)
    r = container_sh("CT=incus; ALLOW_SHARED=0; check_shared_storage", tmp_path, STORAGE_PATH=ROOT + "/27", NAME="v27")
    assert r.returncode == 1
    assert f"already uses storage {ROOT}, which overlaps {ROOT}/27" in r.stderr
    assert f"(by default {ROOT}/v27)" in r.stderr
