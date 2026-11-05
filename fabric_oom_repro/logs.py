"""Lines of the Dremio logs of the nodes of the repro (the archives and the current log, in log order). A node of
OOM_CONTAINERS is a container of the stand (`[host:]container`, read through incus), the coordinator of a Dremio
installed on a host (`dremio://host`) or an executor that YARN runs on a host (`yarn://host`); the last two are read over ssh."""
import shlex

from fabric_oom_repro import fabric_oom
from fabric_oom_repro.stand import node, run_on, split_scheme


def server_logs(directory):
    """The log files of a Dremio log directory, the archives first: the log is rolled to the archive at midnight UTC,
    so a roll during a run keeps the order."""
    return f"{directory}/archive/server.*.log.gz {directory}/server.log"


LOGS = server_logs("/opt/dremio/log")                # in the containers of the stand
DREMIO_LOGS = server_logs("/var/log/dremio")         # of a Dremio installed on a host
YARN_LOGS = "/data/yarn/logs"                        # the log directories of the YARN containers: readable for the yarn user only
EXECUTOR_MARK = "YarnDaemon.run"                     # a line of the stdout of the container that runs Dremio, the others do not have it
# per stdout file: its pattern lines when it is the one of the executor; the sh gets MARK, PATTERN and the file as $1, $2, $3
YARN_GREP = 'grep -qF "$1" "$3" && grep -hE "$2" "$3"'


def read_command(entry, pattern):
    """The host (empty for this one) and the command that prints the lines of the node's logs matching the pattern."""
    scheme, host = split_scheme(entry)
    zgrep = f"shopt -s nullglob; zgrep -hE {shlex.quote(pattern)}"
    if scheme == "dremio":
        return host, ["bash", "-c", f"{zgrep} {DREMIO_LOGS}"]
    if scheme == "yarn":
        # the listing comes first: a directory that cannot be read is an error, not a log without lines
        find = (f"sudo -n ls {YARN_LOGS} >/dev/null && sudo -n find {YARN_LOGS} -name stdout "
                f"-exec sh -c {shlex.quote(YARN_GREP)} _ {EXECUTOR_MARK} {shlex.quote(pattern)} {{}} \\;")
        return host, ["bash", "-c", find]
    host, name = node(entry)
    return host, ["incus", "exec", name, "--", "bash", "-c", f"{zgrep} {LOGS}"]


def log_lines(container, pattern):
    """The lines matching the extended regular expression in the Dremio log and its archives."""
    out = run_on(*read_command(container, pattern))
    assert out.returncode in (0, 1), f"reading the log of {container} failed: {out.stderr}"  # 1: nothing matches
    return out.stdout.splitlines()


def events_added_by(containers, action):
    """Runs `action` and returns its result with the events (fabric_oom.parse) it added to the log of every container."""
    before = {c: len(log_lines(c, fabric_oom.PATTERN)) for c in containers}
    result = action()
    return result, {c: fabric_oom.parse(log_lines(c, fabric_oom.PATTERN)[n:]) for c, n in before.items()}
