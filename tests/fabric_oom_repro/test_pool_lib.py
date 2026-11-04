"""Offline tests of the storage pool helpers of scripts/lib/common.sh on a fake incus.

The case they come from: a stand was deleted while the volume under the pool was not mounted, so incus dropped the
instances but their directories came back with the volume, and the next run died on

    Error: Failed creating instance from image: Volume path
    "/var/lib/incus/storage-pools/default/containers/d27-0-0-j21-14G-4cpu" already exists
"""
import os
import subprocess

import defaults
from test_cluster_lib import fake_command

LIB = defaults.ROOT_DIR / "scripts" / "lib"
ORPHAN = "d27-0-0-j21-14G-4cpu"


def common_sh(tmp_path, script, instances="", state="CREATED"):
    """Runs the script after sourcing common.sh; the fake incus knows `instances` and reports the pool in `state`."""
    pool = tmp_path / "pool"
    (pool / "containers").mkdir(parents=True, exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake_command(bin_dir, "sudo", 'exec "$@"')
    fake_command(bin_dir, "incus", f'''case "$1 $2" in
        "info "*) printf "%s\\n" {instances or '""'} | grep -qx "$2";;
        "profile device") echo default;;
        "storage get") echo {pool};;
        "storage list") echo "default,{state}";;
    esac''')
    out = subprocess.run(["bash", "-euc", f'source {LIB}/common.sh; detect_container_cli; {script}'],
                         capture_output=True, text=True, env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"})
    return out, pool / "containers" / ORPHAN


def test_the_volume_of_a_container_incus_does_not_know_is_removed(tmp_path):
    _, volume = common_sh(tmp_path, "true")
    volume.mkdir()
    out, volume = common_sh(tmp_path, f"remove_orphan_volume {ORPHAN}")
    assert out.returncode == 0, out.stderr
    assert not volume.exists()


def test_the_volume_of_an_existing_container_is_kept(tmp_path):
    _, volume = common_sh(tmp_path, "true")
    volume.mkdir()
    out, volume = common_sh(tmp_path, f"remove_orphan_volume {ORPHAN}", instances=ORPHAN)
    assert out.returncode == 0, out.stderr
    assert volume.is_dir()


def test_nothing_happens_without_a_volume(tmp_path):
    out, volume = common_sh(tmp_path, f"remove_orphan_volume {ORPHAN}")
    assert out.returncode == 0, out.stderr
    assert not volume.exists()


def test_a_pool_whose_volume_is_not_mounted_is_not_available(tmp_path):
    assert common_sh(tmp_path, "pool_is_available")[0].returncode == 0
    assert common_sh(tmp_path, "pool_is_available", state="UNAVAILABLE")[0].returncode != 0
