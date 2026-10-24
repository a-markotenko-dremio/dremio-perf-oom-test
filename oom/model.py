"""The vocabulary of the OOM search: outcomes of a run, the result of a step, a combination."""
import os
from dataclasses import dataclass

from report.runs import short_version

PASS, FAIL, ERROR = "PASS", "FAIL", "ERROR"


@dataclass
class Result:
    status: str                  # RANGE | ROUGH (a bracket wider than the precision) | ALL_PASS (no failure up to the highest
                                 # row count) | ALL_FAIL (fails at the lowest)
    pass_max: int | None = None  # millions of rows
    fail_min: int | None = None

    @property
    def done(self):
        """False while the step wants more runs to reach the precision."""
        return self.status != "ROUGH"

    @property
    def mean(self):
        if self.pass_max is not None and self.fail_min is not None:
            return (self.pass_max + self.fail_min) / 2
        return None


@dataclass(frozen=True)
class Combo:
    package: str
    image: str

    @property
    def version(self):
        return short_version(os.path.basename(self.package).removesuffix(".tar.gz"))
