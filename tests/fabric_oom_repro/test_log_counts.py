"""Offline tests of the log counting of test_fabric_oom_repro.py on log lines of the real repro (DX-127207, the customer's profile)."""
import gzip
import os
import re
import stat

import pytest

from fabric_oom_repro import logs as repro

FABRIC_OOM = [
    "ExecTransportExceptionHandler - Transport-level exception detected on connection null <--> null (fabric client). Failing all active fragments.",
    "CopyRpcExceptionHandler - Transport-level exception detected on channel [...]. Failing all fragments on this executor.",
    "io.netty.util.internal.OutOfDirectMemoryError: failed to allocate 4194304 byte(s) of direct memory (used: 111664955678, max: 111669149696)",
]
ARBITER_CANCEL = "MemoryArbiter detected no memory available"


@pytest.mark.parametrize("line", FABRIC_OOM)
def test_a_fabric_oom_line_is_counted_as_fabric_oom(line):
    assert re.search(repro.PATTERNS["fabric_oom"], line)


def test_an_arbiter_cancel_is_not_a_fabric_oom():
    assert not re.search(repro.PATTERNS["fabric_oom"], ARBITER_CANCEL)
    assert re.search(repro.PATTERNS["arbiter_cancel"], ARBITER_CANCEL)


@pytest.fixture
def container_logs(tmp_path, monkeypatch):
    """`incus exec NAME -- CMD...` runs CMD here; the log paths point into tmp_path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    incus = bin_dir / "incus"
    incus.write_text('#!/bin/bash\nshift 3\nexec "$@"\n')
    incus.chmod(incus.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setattr(repro, "LOGS", f"{tmp_path}/server.log {tmp_path}/archive/server.*.log.gz")
    return tmp_path


def test_lines_of_the_current_log_and_of_the_archive_are_counted(container_logs):
    (container_logs / "server.log").write_text("\n".join(FABRIC_OOM[:2] + [ARBITER_CANCEL]) + "\n")
    (container_logs / "archive").mkdir()
    with gzip.open(container_logs / "archive" / "server.2026-10-22.1.log.gz", "wt") as f:
        f.write(FABRIC_OOM[2] + "\n")
    assert repro.log_count("any", repro.PATTERNS["fabric_oom"]) == 3
    assert repro.log_count("any", repro.PATTERNS["arbiter_cancel"]) == 1


def test_a_log_without_matches_and_without_archive_counts_zero(container_logs):
    (container_logs / "server.log").write_text("INFO started\n")
    assert repro.log_count("any", repro.PATTERNS["fabric_oom"]) == 0


def test_an_unreadable_log_is_an_error_not_a_zero(container_logs):
    with pytest.raises(AssertionError, match="counting in any failed"):
        repro.log_count("any", repro.PATTERNS["fabric_oom"])
