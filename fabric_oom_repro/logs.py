"""Lines of the Dremio logs of the repro containers (the archives and the current log, in log order)."""
import shlex

from fabric_oom_repro import fabric_oom
from fabric_oom_repro.stand import node, run_on

# the log is rolled to the archive at midnight UTC: the archives come first so a roll during a run keeps the order
LOGS = "/opt/dremio/log/archive/server.*.log.gz /opt/dremio/log/server.log"


def log_lines(container, pattern):
    """The lines matching the extended regular expression in the Dremio log and its archives."""
    host, name = node(container)
    out = run_on(host, ["incus", "exec", name, "--", "bash", "-c", f"shopt -s nullglob; zgrep -hE {shlex.quote(pattern)} {LOGS}"])
    assert out.returncode in (0, 1), f"reading the log of {container} failed: {out.stderr}"  # 1: nothing matches
    return out.stdout.splitlines()


def events_added_by(containers, action):
    """Runs `action` and returns its result with the events (fabric_oom.parse) it added to the log of every container."""
    before = {c: len(log_lines(c, fabric_oom.PATTERN)) for c in containers}
    result = action()
    return result, {c: fabric_oom.parse(log_lines(c, fabric_oom.PATTERN)[n:]) for c, n in before.items()}
