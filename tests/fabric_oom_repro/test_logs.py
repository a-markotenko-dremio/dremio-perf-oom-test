"""Offline tests of the log reading of fabric_oom_repro.logs on log lines of the real repro (DX-127207, the customer's profile)."""
import gzip
import os
import stat

import pytest

from fabric_oom_repro import fabric_oom
from fabric_oom_repro import logs as repro

FABRIC_OOM = [
    "ExecTransportExceptionHandler - Transport-level exception detected on connection null <--> null (fabric client). Failing all active fragments.",
    "CopyRpcExceptionHandler - Transport-level exception detected on channel [...]. Failing all fragments on this executor.",
    "io.netty.util.internal.OutOfDirectMemoryError: failed to allocate 4194304 byte(s) of direct memory (used: 111664955678, max: 111669149696)",
]
ARBITER_CANCEL = "MemoryArbiter detected no memory available"


@pytest.fixture
def container_logs(tmp_path, monkeypatch):
    """`incus exec NAME -- CMD...` runs CMD here; the log paths point into tmp_path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    incus = bin_dir / "incus"
    incus.write_text('#!/bin/bash\nshift 3\nexec "$@"\n')
    incus.chmod(incus.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setattr(repro, "LOGS", repro.LOGS.replace("/opt/dremio/log", str(tmp_path)))
    return tmp_path


def test_lines_of_the_current_log_and_of_the_archive_are_read(container_logs):
    (container_logs / "server.log").write_text("\n".join(FABRIC_OOM[:2] + [ARBITER_CANCEL, "INFO started"]) + "\n")
    (container_logs / "archive").mkdir()
    with gzip.open(container_logs / "archive" / "server.2026-10-22.1.log.gz", "wt") as f:
        f.write(FABRIC_OOM[2] + "\n")
    assert repro.log_lines("any", fabric_oom.PATTERN) == [FABRIC_OOM[2], *FABRIC_OOM[:2], ARBITER_CANCEL]


def test_the_archive_comes_before_the_current_log(container_logs):
    """A roll at midnight moves lines to the archive: only this order keeps the lines a run already counted in place."""
    (container_logs / "server.log").write_text(FABRIC_OOM[0] + "\n")
    (container_logs / "archive").mkdir()
    with gzip.open(container_logs / "archive" / "server.2026-10-22.1.log.gz", "wt") as f:
        f.write(FABRIC_OOM[2] + "\n")
    assert repro.log_lines("any", fabric_oom.PATTERN) == [FABRIC_OOM[2], FABRIC_OOM[0]]


def test_a_log_without_matches_and_without_archive_has_no_lines(container_logs):
    (container_logs / "server.log").write_text("INFO started\n")
    assert repro.log_lines("any", fabric_oom.PATTERN) == []


def test_an_unreadable_log_is_an_error_not_a_zero(container_logs):
    with pytest.raises(AssertionError, match="reading the log of any failed"):
        repro.log_lines("any", fabric_oom.PATTERN)


def test_only_the_events_the_action_added_are_returned(container_logs):
    (container_logs / "server.log").write_text(FABRIC_OOM[0] + "\n")

    def action():
        with open(container_logs / "server.log", "a") as f:
            f.write("2026-10-22 20:33:43,022 [MA-memory-monitor-thread-1] INFO  c.d.sabot.memory.MemoryArbiterImpl - Asking operator "
                    "15258cdc-ced8-89fe-7b9c-c91519dc5c00:frag:4:2:3(shrinkable memory: 0) to shrink memory.\n")
        return "done"

    result, per_container = repro.events_added_by(["any"], action)
    assert result == "done"
    assert {name: len(e) for name, e in per_container["any"].items() if e} == {"shrink": 1}
