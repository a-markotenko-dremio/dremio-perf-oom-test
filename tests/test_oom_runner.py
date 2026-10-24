"""Offline tests of the classification of a failed run (oom.runner)."""
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
