"""Offline tests of fabric_oom_repro.stand: the package of a container as install_dremio records it, and the commit of the tests."""
import os
import stat

import pytest

from fabric_oom_repro import stand

PACKAGE = "dremio-enterprise-27.0.0-PR-31026-3.tar.gz"
SHA256 = "6eed9b2ae971f8c44dd17cb1935d32436339b914828f554e329c25d7e670c60d"


@pytest.fixture
def fake_incus(tmp_path, monkeypatch):
    """`incus config get NAME KEY` answers from the file KEY in tmp_path (empty when there is none, as incus does)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    incus = bin_dir / "incus"
    incus.write_text(f'#!/bin/bash\n[[ $1 == config && $2 == get ]] || exit 2\ncat "{tmp_path}/$4" 2>/dev/null; exit 0\n')
    incus.chmod(incus.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    return tmp_path


def test_the_package_is_the_tarball_and_its_sha256(fake_incus):
    (fake_incus / "user.dremio.package").write_text(PACKAGE + "\n")
    (fake_incus / "user.dremio.package-sha256").write_text(SHA256 + "\n")
    assert stand.package("d27-0-0-j21-14G-4cpu") == f"{PACKAGE} {SHA256}"


def test_a_container_deployed_before_the_package_was_recorded_is_an_error(fake_incus):
    (fake_incus / "user.dremio.package").write_text(PACKAGE + "\n")
    with pytest.raises(AssertionError, match="d27-0-0-j21-14G-4cpu has no .* deployed before install_dremio recorded"):
        stand.package("d27-0-0-j21-14G-4cpu")


def test_the_host_of_a_container_is_split_off_its_name():
    assert stand.node("den:d27-0-0-j21-10G-16cpu") == ("den", "d27-0-0-j21-10G-16cpu")
    assert stand.node("d27-0-0-j21-14G-4cpu") == ("", "d27-0-0-j21-14G-4cpu")


def test_the_commit_is_the_one_of_this_repository():
    assert len(stand.commit().split("-")[0]) >= 7  # the abbreviated hash, maybe with -dirty


def test_a_node_that_is_no_container_has_its_scheme_and_host_split_off():
    assert stand.split_scheme("yarn://a-markotenko-1.c.dremio-1093.internal") == ("yarn", "a-markotenko-1.c.dremio-1093.internal")
    assert stand.split_scheme("den:d27-0-0-j21-10G-16cpu") == stand.split_scheme("d27-0-0-j21-14G-4cpu") == ("", "")


def test_the_other_hosts_of_the_nodes_are_listed_once(tmp_path):
    assert stand.hosts(["d27-0-0-j21-14G-4cpu", "den:d27-0-0-j21-10G-16cpu", "dremio://a-0", "yarn://a-1", "yarn://a-2", "den:other"]) \
        == ["den", "a-0", "a-1", "a-2"]


@pytest.fixture
def fake_vm(tmp_path, monkeypatch):
    """`ssh HOST CMD` runs CMD here and `curl` answers with the URL it is asked for (the metadata server answers only with the header)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, script in (("ssh", 'shift 3\nexec bash -c "$1"'),
                         ("curl", '[[ " $* " == *" Metadata-Flavor: Google "* ]] || exit 22\necho "gs://builds/${@: -1}"')):
        tool = bin_dir / name
        tool.write_text(f"#!/bin/bash\n{script}\n")
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")


def test_the_package_of_a_vm_is_its_package_url(fake_vm):
    assert stand.package("yarn://a-1") == f"gs://builds/{stand.METADATA_PACKAGE_URL}"
