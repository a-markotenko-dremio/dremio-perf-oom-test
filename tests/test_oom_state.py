"""Offline tests of the recorded state and the model (oom.state, oom.model)."""
from oom import model as m
from oom import state as st
from oom_helpers import combo, read


def test_combo_version_is_short():
    assert combo().version == "26.1.10"


def test_mean_is_written_with_the_row_suffix(tmp_path):
    state = st.State(tmp_path / "ranges.csv", tmp_path / "runs.csv")
    state.add_step(combo(), 512, m.Result("RANGE", 50, 200))
    row = read(tmp_path / "ranges.csv")[0]
    assert (row["Pass max rows"], row["Fail min rows"], row["Mean rows"]) == ("50M", "200M", "125M")
    assert row["Dremio ver"] == "26.1.10" and row["Java image"] == "wolfi-jdk:21"
