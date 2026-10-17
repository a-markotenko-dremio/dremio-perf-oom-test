# perf-dremio: project rules

Project: performance tests of Dremio (OOM frontier search, deployment into Incus/LXD containers, reports).

Run the tests (offline, no Dremio needed): `.venv/bin/python -m pytest tests`

## Language

- Everything that is stored is English only: code, identifiers, comments, docstrings, `--help` texts, log and error messages, documentation, test names, commit messages, CLAUDE.md. No exceptions, no mixed-language files.
- Only the interactive conversation with the user may be in any language. Keep it short: the concrete answer first (a number, a command), explanations after, and only if needed.

## DRY: one source of truth

- Before writing code, search the repository for what already exists: `scripts/lib/*.sh`, `results_report.py`, `settings.py`, `report/canvas.py`, `quantities.py`, `csvio.py`, `defaults.py`, `oom/`. If it exists, use it. If something similar exists, generalize it and use it in both places instead of copying.
- Logic is not duplicated between bash and Python, between scripts and modules, or between tests and code. Shared logic goes to `scripts/lib/` (shell) or a module of a package (Python).
- Parsing and formatting of quantities (K/M/G, rows, MB), rounding, the container name and IP, paths (`/mnt/ubuntu-var/dremio`) and defaults (heap, direct memory, CPUs) are defined in exactly one place. A new copy of such logic is a defect.
- A new default, flag or CSV column is added in one place, and `--help`, the docstring, the `Makefile` and the tests are updated in the same change.
- Leave no dead code: functions, arguments, flags and tests that became unused are removed in the same change.

## SDLC: how to work

1. **Requirements.** Clarify an ambiguous task before implementing it (one short question with a proposed default). If the user said they will give the command to implement after the discussion, write nothing before that command.
2. **Scope.** Change only what was asked. No changes of file or CSV formats, no new columns, flags or refactoring "on the way". If something useful comes up, propose it, do not do it. If the user says a change was not requested, revert it.
3. **Tests with the change.** Every behaviour change comes with unit tests. A test must reproduce the real case from the user's logs (with their data), not only an idealized one. A test that can never fail does not count. Do not commit until the whole suite passes.
4. **Verification.** Do not claim that something works before running it. Say explicitly what was not verified (a real Dremio run, another machine). The runs happen on other hosts: draw conclusions about them from the data the user provides, not from local files in `data/`.
5. **Review before commit.** Read your own diff: duplicates, dead code, unrelated changes, outdated comments, `--help`, `Makefile`. Only then commit.
6. **Commit.** Only when asked. Small, coherent commits, English messages that explain why. Generated data (`data/*.csv`, `*.svg`, `*.log`) is not committed. No push and no merge unless asked.
7. **Expensive runs.** Runs take hours. Do not start real deployments, and do not delete containers, disks or user data, without being asked. After changing code that runs on another machine, remind that a running process still uses the old version and must be restarted.
8. **Resources.** When designing a search, minimize the number of runs (idle runs cost hours). Use the already recorded results (`data/oom_runs.csv`) before making new runs.
