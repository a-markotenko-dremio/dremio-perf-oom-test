# perf-dremio: project rules

Project: performance tests of Dremio (OOM frontier search, deployment into Incus/LXD containers, reports).

Run the tests (offline, no Dremio needed): `.venv/bin/python -m pytest tests`

## Where the shared code is

- Before writing code, search what exists: `scripts/lib/*.sh`, `results_report.py`, `settings.py`, `report/canvas.py`, `quantities.py`, `csvio.py`, `defaults.py`, `oom/`.
- Shared shell logic goes to `scripts/lib/`, shared Python logic to a module of a package.
- Parsing and formatting of quantities (K/M/G, rows, MB), rounding, the container name and IP, paths (`/mnt/ubuntu-var/dremio`) and defaults (heap, direct memory, CPUs) are defined in exactly one place (`quantities.py`, `defaults.py`, `scripts/lib/common.sh`, `deploy_dremio.sh`).

## Data

- `data/oom_runs.csv` is the primary record of the OOM search. `data/oom_ranges.csv` is derived from it for the chart and never read.
- Generated data (`data/*.csv`, `*.svg`, `*.log`) is not committed.

## Runs

- The runs happen on other hosts (`den`, `home4`): draw conclusions about them from the data the user provides, not from local files in `data/`. Say explicitly that a real Dremio run was not verified.
- Do not start real deployments and do not delete containers or the storage under `/mnt/ubuntu-var/dremio` without being asked.
- Runs take hours: before making a new run use the recorded results (`data/oom_runs.csv`). Idle runs cost time.
- After changing code that `oom_ranges.py` runs, remind that the running process keeps the old code and must be restarted.
