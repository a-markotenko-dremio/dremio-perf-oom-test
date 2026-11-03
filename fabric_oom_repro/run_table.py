"""
A table of every run of the fabric OOM stand from the pytest logs of `make fabric-oom-*` (data/fabric-oom-<case>-<time>.log):
when it ran, how long it took and how it ended, read from the summary the test prints and from pytest's last line.
A log without that line is a run still going or killed, and gets no counts.

  .venv/bin/python -m fabric_oom_repro.run_table [DIR]      (default: data/; make fabric-oom-report)
"""
import ast
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

NAME = re.compile(r"fabric-oom-(?P<case>\w+)-(?P<when>\d{8}-\d{6})\.log$")
VERDICT = re.compile(r"^=+ (?P<counts>\d+ (?:passed|failed).*?) in (?P<seconds>[\d.]+)s", re.M)
OUTCOMES = re.compile(r"^(?:E +)?outcomes: (?P<list>\[.*\])$", re.M)
EVENTS = re.compile(r"^(?:E +)?events: (?P<events>\{.*?\}), failures by cause: (?P<causes>\{.*?\})", re.M)
LINE_COUNTS = re.compile(r"^(?:E +)?new log lines per container: (?P<counts>\{.*\})$", re.M)  # the summary before 2026-10-29
COLUMNS = ("run", "case", "took", "verdict", "fabric OOM", "arbiter", "completed", "over limit", "failed", "shrink")
LEGEND = """\
How to read the table:
- run: the start of the run in the host's local time (from the log name); case: repro = the reproduction (F-01), func = the
  fix verification (F-03..F-09, P-06), feature = the run without a time limit (P-07); took: the time pytest reported.
- verdict: pytest's count. For repro "passed" means the bug reproduced (F-01 passes when it does), for func and feature
  "passed" means the fix criteria held. "no result" is a log without pytest's last line: the run is still going or was killed.
- fabric OOM: the fabric direct-memory OOM events of both nodes, the bug; arbiter: the queries the memory arbiter cancelled,
  expected under pressure; shrink: the shrink requests, 0 means the run did not stress the node and proves nothing (F-02).
- completed / over limit / failed: how the 8 queries ended: served, cut off by the run's own time limit (2400 s for repro,
  OOM_MAX_QUERY_SECONDS = 600 s for func, none for feature), or failed with an error."""


def row(path):
    """One row per log: the counts of the summary the test printed, or only the name when the run has no result yet."""
    name = NAME.search(path.name)
    text = path.read_text()
    verdict = VERDICT.search(text)
    r = {"run": datetime.strptime(name["when"], "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M"), "case": name["case"],
         "took": str(timedelta(seconds=round(float(verdict["seconds"])))) if verdict else "",
         "verdict": verdict["counts"].split(",")[0] if verdict else "no result (running or killed)"}
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
    print(table(sorted((row(p) for p in Path(directory).glob("fabric-oom-*.log")), key=lambda r: r["run"])))
    print("\n" + LEGEND)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data")
