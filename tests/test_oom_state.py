"""Offline tests of the recorded state and the model (oom.state, oom.model)."""
from oom import model as m
from oom import search as se
from oom_helpers import OWN, SIB, combo, history_rows, make_args, make_state, package_combo, read, sibling_state


def test_combo_version_is_short():
    assert combo().version == "26.1.10"


def test_ranges_are_written_from_the_runs_with_the_row_suffix(tmp_path):
    state = make_state(tmp_path)
    state.add_run(combo(), 512, 50, m.PASS)
    assert read(tmp_path / "ranges.csv") == []                       # one PASS does not finish the step
    state.add_run(combo(), 512, 60, m.FAIL)
    state.add_run(combo(), 512, 55, m.PASS)
    row = read(tmp_path / "ranges.csv")[0]
    assert (row["Pass max rows"], row["Fail min rows"], row["Mean rows"], row["Status"]) == ("55M", "60M", "57.5M", "RANGE")
    assert row["Dremio ver"] == "26.1.10" and row["Java image"] == "wolfi-jdk:21" and row["Heap MB"] == "512"


def test_ranges_follow_the_runs_file_of_the_real_history(tmp_path):
    """The recorded runs of the user's log: own 108 PASS / 128 FAIL at 448 MB, 368 / 388 at 512 MB; the sibling 178 / 198 and 438 / 458."""
    args = make_args(tmp_path, precision=20)
    sibling_state(tmp_path, history_rows([]), args).write_ranges()
    rows = read(tmp_path / "ranges.csv")
    assert [(r["Dremio ver"], r["Java image"], r["Heap MB"], r["Mean rows"]) for r in rows] == [
        (*OWN, "448", "118M"), (*OWN, "512", "378M"), (*SIB, "448", "188M"), (*SIB, "512", "448M")]


def test_the_ranges_file_is_never_read_and_is_replaced(tmp_path):
    (tmp_path / "ranges.csv").write_text("Dremio ver,Java image,Heap MB,Pass max rows,Fail min rows,Mean rows,Status\n"
                                         "26.1.10,wolfi-jdk:21,512,1M,2M,1500K,RANGE\n")
    state = make_state(tmp_path)
    assert state.step(combo(), 512) is None                          # the old row says nothing
    state.write_ranges()
    assert read(tmp_path / "ranges.csv") == []                       # the file is the image of the runs, here none
    assert not list(tmp_path.glob("*.tmp"))


def test_a_deleted_ranges_file_is_regenerated_and_an_edited_runs_file_changes_it(tmp_path):
    args = make_args(tmp_path, precision=20)
    sibling_state(tmp_path, history_rows([]), args).write_ranges()
    before = (tmp_path / "ranges.csv").read_text()
    (tmp_path / "ranges.csv").unlink()
    make_state(tmp_path, args).write_ranges()
    assert (tmp_path / "ranges.csv").read_text() == before
    lines = (tmp_path / "runs.csv").read_text().splitlines()
    (tmp_path / "runs.csv").write_text("\n".join(l for l in lines if ",448,128," not in l and ",448,198," not in l) + "\n")
    make_state(tmp_path, args).write_ranges()
    assert [(r["Dremio ver"], r["Heap MB"]) for r in read(tmp_path / "ranges.csv")] == [
        ("26.1.10", "512"), ("26.1.8", "512")]                       # the steps of 448 MB lost their FAIL


def test_a_step_is_finished_by_the_precision_of_the_search(tmp_path):
    own, runs = package_combo(*OWN), [(*OWN, 512, 100, "PASS"), (*OWN, 512, 130, "FAIL")]
    assert sibling_state(tmp_path, runs, make_args(tmp_path, precision=20)).step(own, 512) is None
    assert sibling_state(tmp_path, runs, make_args(tmp_path, precision=30)).step(own, 512).mean == 115


def test_step_result_of_the_runs():
    rows = lambda *pairs: dict(pairs)
    assert se.step_result(rows((100, m.PASS), (110, m.FAIL)), 10, 10, 1440) == m.Result("RANGE", 100, 110)
    assert se.step_result(rows((100, m.PASS), (130, m.FAIL)), 10, 10, 1440) is None
    assert se.step_result(rows((1440, m.PASS), (700, m.PASS)), 10, 10, 1440) == m.Result("ALL_PASS", pass_max=1440)
    assert se.step_result(rows((700, m.PASS)), 10, 10, 1440) is None
    assert se.step_result(rows((10, m.FAIL), (50, m.FAIL)), 10, 10, 1440) == m.Result("ALL_FAIL", fail_min=10)
    assert se.step_result(rows((50, m.FAIL)), 10, 10, 1440) is None
    assert se.step_result(rows((100, m.PASS), (120, m.FAIL), (150, m.PASS)), 10, 10, 1440) is None   # a PASS above the FAIL is ignored
