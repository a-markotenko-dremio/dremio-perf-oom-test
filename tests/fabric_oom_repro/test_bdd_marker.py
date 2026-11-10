"""The `bdd` marker: `pytest -m bdd` must select every test that checks a case of the QA repository on the stand, and
nothing else, so a new module of cases that forgets the marker is caught here and not by a run that skips it."""
import subprocess
import sys

from fabric_oom_repro.stand import REPO

ON_THE_STAND = {"tests/fabric_oom_repro/test_fabric_oom_func.py", "tests/fabric_oom_repro/test_fabric_oom_repro.py"}


def test_the_marker_selects_the_cases_of_the_stand_and_nothing_else():
    collected = subprocess.run([sys.executable, "-m", "pytest", "-m", "bdd", "--collect-only", "-q", "tests"],
                               cwd=REPO, capture_output=True, text=True, check=True).stdout
    assert {line.split("::")[0] for line in collected.splitlines() if "::" in line} == ON_THE_STAND
