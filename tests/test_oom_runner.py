"""Offline tests of the classification of a failed run (oom.runner)."""
from types import SimpleNamespace

import pytest

from oom import runner as rn


@pytest.mark.parametrize("output, heap_oom", [
    ("java.lang.OutOfMemoryError: Java heap space", True),
    ("SYSTEM ERROR: OutOfMemoryError: GC overhead limit exceeded", True),
    ("OUT_OF_MEMORY ERROR: Query was cancelled because it exceeded the memory limits set by the administrator.\n"
     "  Heap monitor detected that the heap is almost full\n  ErrorOrigin: EXECUTOR\n"
     "(com.dremio.common.exceptions.OutOfHeapMemoryException) Heap monitor detected that the heap is almost full", True),
    ("OUT_OF_MEMORY ERROR: Query was cancelled because it exceeded the memory limits set by the administrator.\n"
     "  Unable to allocate buffer of size 4096 due to memory limit. Current allocation: 4294967296", False),
    ("Unable to allocate buffer of size 1048576 due to memory limit (direct memory)", False),
    ("OutOfMemoryError: Direct buffer memory", False),
    ("requests.exceptions.ReadTimeout", False)])
def test_only_a_heap_oom_is_a_failure(output, heap_oom):
    assert rn.classify_failure(output, "") is heap_oom
    assert rn.classify_failure("", output) is heap_oom


@pytest.mark.parametrize("storage", ["fs", "s3"])
def test_the_test_of_a_run_gets_the_storage_of_the_search(monkeypatch, storage):
    monkeypatch.setattr(rn, "container_cli", lambda: "incus")
    monkeypatch.setattr(rn, "container_name", lambda combo, args: "d26-1-8-wolfi-jdk-21-8G-4cpu")
    started = []

    class Process:
        stdout = ["PASSED\n"]
        wait = lambda self: 0

    monkeypatch.setattr(rn.subprocess, "Popen", lambda cmd, **kw: started.append(cmd) or Process())
    runner = rn.Runner(SimpleNamespace(storage=storage, storage_root="/mnt/ubuntu-var/dremio"), None)
    runner.deployed_heap = 512
    assert runner.run(512, 10) == "PASS"
    assert started == [["make", "test-container", "CONTAINER=d26-1-8-wolfi-jdk-21-8G-4cpu", "ROW_COUNT=10M", f"STORAGE={storage}"]]
