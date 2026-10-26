"""Counts the lines of the Dremio logs of the repro containers (the current log and its archives)."""
import shlex
import subprocess

import settings

# the log is rolled to the archive at midnight UTC, so a run can span both
LOGS = "/opt/dremio/log/server.log /opt/dremio/log/archive/server.*.log.gz"
PATTERNS = {
    "fabric_oom": "Transport-level exception|Direct memory exhausted|MessageDecoder - |OutOfDirectMemoryError",  # the bug
    "arbiter_cancel": "no memory available",  # the memory arbiter cancelled the greediest query: not the bug
    "shrink_requests": "Asking operator",     # the arbiter asked an operator to spill: the pressure the repro needs
}


def log_count(container, pattern):
    """Number of lines matching the extended regular expression in the Dremio log and its archives."""
    host, _, name = container.rpartition(":")
    command = ["incus", "exec", name, "--", "bash", "-c", f"shopt -s nullglob; zgrep -hE {shlex.quote(pattern)} {LOGS}"]
    # ssh joins its arguments into one remote command line, so they must be quoted for it
    out = subprocess.run(["ssh", "-o", "BatchMode=yes", host, shlex.join(command)] if host else command,
                         capture_output=True, text=True)
    assert out.returncode in (0, 1), f"counting in {container} failed: {out.stderr}"  # 1: nothing matches
    return len(out.stdout.splitlines())


def log_counts():
    return {c: {name: log_count(c, pattern) for name, pattern in PATTERNS.items()} for c in settings.OOM_CONTAINERS}
