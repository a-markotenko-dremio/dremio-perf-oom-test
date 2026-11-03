"""Offline tests of scripts/lib/s3.sh on a fake incus and curl: the S3 server of the STORAGE=s3 runs is started only when it is not running."""
import os
import subprocess

import defaults
from test_cluster_lib import fake_command

LIB = defaults.ROOT_DIR / "scripts" / "lib"


def ensure_s3_server(tmp_path, running):
    """Runs ensure_s3_server; the fake incus lists `running` as the running containers and logs its calls. Returns (output, log lines)."""
    log = tmp_path / "log"
    fake_command(tmp_path, "incus", f'echo "$@" >> {log}\n'
                 f'case "$1" in list) printf "%s\\n" {running};; exec) echo "1.1.1.1 via 10.97.177.1 dev eth0 src 10.97.177.20";; esac')
    fake_command(tmp_path, "curl", "echo 403")
    out = subprocess.run(["bash", "-euc", f'source {LIB}/common.sh; source {LIB}/s3.sh; detect_container_cli; ensure_s3_server; echo "$S3_ENDPOINT"'],
                         capture_output=True, text=True, env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"})
    return out, log.read_text().splitlines()


def test_a_running_server_is_used_as_it_is(tmp_path):
    out, log = ensure_s3_server(tmp_path, f"other {defaults.TEST_S3}")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == f"10.97.177.20:{defaults.OOM_REPRO_S3_PORT}"
    assert not [line for line in log if line.startswith(("launch", "delete"))]


def test_a_missing_server_is_launched_with_a_capped_container_of_its_own(tmp_path):
    out, log = ensure_s3_server(tmp_path, f"{defaults.TEST_S3}-not other")  # a name that only starts like it is not it
    assert out.returncode == 0, out.stderr
    assert any(line.startswith("launch") and f" {defaults.TEST_S3} " in line and "limits.memory=1GiB" in line for line in log), log
    assert f"delete --force {defaults.TEST_S3}" in log

