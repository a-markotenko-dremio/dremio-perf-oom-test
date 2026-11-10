"""
A table of every pytest session of the fabric OOM stand from the logs of `make fabric-oom-*` (data/fabric-oom-<case>-<time>.log):
when the run started, how long the session took and how it ended, read from the summary the test prints and from pytest's
last line. A log holds one session (repro, feature) or three (func). A session without that line is still going or was
killed, and gets no counts.

  .venv/bin/python -m fabric_oom_repro.run_table [DIR]      (default: data/; make fabric-oom-report)
"""
import ast
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

NAME = re.compile(r"fabric-oom-(?P<case>\w+)-(?P<when>\d{8}-\d{6})\.log$")
VERDICT = re.compile(r"^=+ (?P<counts>\d+ (?:passed|failed).*?) in (?P<seconds>[\d.]+)s", re.M)
COMMIT = re.compile(r"^commit=(?P<commit>\S+)$", re.M)
BUILD = re.compile(r"^build=(?P<packages>\{.*\})$", re.M)  # container -> "tarball sha256", or the package URL of a node that is no container
SYSTEM_OPTIONS = re.compile(r"^system options=(?P<options>\{.*\})$", re.M)
RESERVE_OPTION = "exec.spillable.operators.pct_free_memory_watermark"
INNOCENT_QUERY = re.compile(r"^innocent query: (?P<state>.*)$", re.M)
OUTCOMES = re.compile(r"^(?:E +)?outcomes: (?P<list>\[.*\])$", re.M)
EVENTS = re.compile(r"^(?:E +)?events: (?P<events>\{.*?\}), failures by cause: (?P<causes>\{.*?\})", re.M)
LINE_COUNTS = re.compile(r"^(?:E +)?new log lines per container: (?P<counts>\{.*\})$", re.M)  # the summary before 2026-10-29
SESSION_START = re.compile(r"^=+ test session starts =+$", re.M)
COLUMNS = ("run", "case", "session", "commit", "build", "reserve %", "small query", "took", "verdict", "fabric OOM", "arbiter", "completed", "over limit", "failed", "shrink")
LEGEND = """\
How to read the table:
- run: the start of the run in the host's local time (from the log name); session: the pytest session of the run, func has
  three (the 4 % arbiter reserve, the default reserve, the small query next to the 8 with the 4 % reserve), repro and feature one;
  commit: the commit of this repository the run was executed from (-dirty: with uncommitted changes); build: the Dremio tarball the
  containers were installed from and the first 12 hex digits of its sha256 (the log has the whole; one entry per different
  package when the nodes differ); both empty in logs from before they were printed;
  reserve %: the arbiter reserve of the session (exec.spillable.operators.pct_free_memory_watermark; "default" is Dremio's own 20),
  small query: whether the small query ran next to the 8 (OOM_INNOCENT) - what tells the three sessions of func apart (empty in logs
  that do not print them);
  case: repro = the reproduction (F-01), func = the
  fix verification (F-02..F-07), feature = the run without a time limit (P-05); took: the time pytest reported.
- verdict: pytest's count. For repro "passed" means the bug reproduced (F-01 passes when it does), for func and feature
  "passed" means the fix criteria held. "no result" is a log without pytest's last line: the run is still going or was killed.
- fabric OOM: the fabric direct-memory OOM events of both nodes, the bug; arbiter: the queries the memory arbiter cancelled,
  expected under pressure; shrink: the shrink requests, 0 means the run did not stress the node and proves nothing (F-02).
- completed / over limit / failed: how the 8 queries ended: served, cut off by the run's own time limit (2400 s for repro,
  OOM_MAX_QUERY_SECONDS = 600 s for func, none for feature), or failed with an error."""


def rows(path):
    """One row per pytest session of a log (a log without the header line of pytest is one session)."""
    name = NAME.search(path.name)
    parts = SESSION_START.split(path.read_text())
    return [row(name, number, text) for number, text in enumerate(parts[1:] or parts, 1)]


def row(name, number, text):
    """The counts of the summary the test printed in a session, or only the name when the session has no result yet."""
    verdict = VERDICT.search(text)
    r = {"run": datetime.strptime(name["when"], "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M"), "case": name["case"], "session": number,
         "took": str(timedelta(seconds=round(float(verdict["seconds"])))) if verdict else "",
         "verdict": verdict["counts"].split(",")[0] if verdict else "no result (running or killed)"}
    if commit := COMMIT.search(text):
        r["commit"] = commit["commit"]
    if build := BUILD.search(text):
        r["build"] = "; ".join(sorted({" ".join([name, *(sha[:12] for sha in shas)]) for name, *shas in map(str.split, ast.literal_eval(build["packages"]).values())}))
    if options := SYSTEM_OPTIONS.search(text):
        r["reserve %"] = ast.literal_eval(options["options"]).get(RESERVE_OPTION, "default")  # not set: Dremio's own (20)
    if small := INNOCENT_QUERY.search(text):
        r["small query"] = "no" if small["state"] == "not run" else "yes"
    if outcomes := OUTCOMES.search(text):
        states = ast.literal_eval(outcomes["list"])
        r |= {key: sum(s.startswith(start) for s in states)
              for key, start in (("completed", "COMPLETED"), ("over limit", "OVER THE LIMIT"), ("failed", "Job "))}
    if events := EVENTS.search(text):
        counts, causes = ast.literal_eval(events["events"]), ast.literal_eval(events["causes"])
        r |= {"fabric OOM": counts["fabric_oom"], "arbiter": causes.get("arbiter", 0), "shrink": counts["shrink"]}
    elif counts := LINE_COUNTS.search(text):
        per_container = ast.literal_eval(counts["counts"]).values()
        r |= {key: sum(c[name] for c in per_container)
              for key, name in (("fabric OOM", "fabric_oom"), ("arbiter", "arbiter_cancel"), ("shrink", "shrink_requests"))}
    return r


def table(rows):
    """The rows as a Markdown table, in the order given."""
    lines = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    return "\n".join(lines + ["| " + " | ".join(str(r.get(c, "")) for c in COLUMNS) + " |" for r in rows])


def main(directory):
    print(table(sorted((r for p in Path(directory).glob("fabric-oom-*.log") for r in rows(p)), key=lambda r: (r["run"], r["session"]))))
    print("\n" + LEGEND)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data")
