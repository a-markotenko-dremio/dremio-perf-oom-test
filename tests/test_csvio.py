"""Offline tests of the CSV helpers (csvio.py)."""
import pytest

import csvio


def test_append_row_creates_the_directory_and_writes_the_header_once(tmp_path):
    path = tmp_path / "new" / "dir" / "r.csv"
    csvio.append_row(path, ["a", "b"], {"a": 1, "b": "x"})
    csvio.append_row(path, ["a", "b"], {"a": 2, "b": "y"})
    assert path.read_text().splitlines() == ["a,b", "1,x", "2,y"]
    assert csvio.read_rows(path) == [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}]


def test_append_row_to_an_empty_file_writes_the_header(tmp_path):
    path = tmp_path / "r.csv"
    path.write_text("")
    csvio.append_row(path, ["a"], {"a": 1})
    assert path.read_text().splitlines() == ["a", "1"]


def test_a_missing_file_is_an_error_unless_it_is_allowed(tmp_path):
    with pytest.raises(FileNotFoundError):
        csvio.read_rows(tmp_path / "none.csv")
    assert csvio.read_rows(tmp_path / "none.csv", missing_ok=True) == []


def test_read_table_keeps_columns_with_the_same_name_apart(tmp_path):
    path = tmp_path / "r.csv"
    path.write_text("a,a,c\n1,2,3\n")
    assert csvio.read_table(path) == (["a", "a", "c"], [["1", "2", "3"]])
    path.write_text("")
    assert csvio.read_table(path) == ([], [])


def test_write_rows_replaces_the_file_and_leaves_no_temporary_file(tmp_path):
    path = tmp_path / "sub" / "t.csv"
    csvio.write_rows(path, ["a", "b"], [{"a": 1, "b": "x,y"}])
    csvio.write_rows(path, ["a", "b"], [{"a": 2, "b": "z"}])
    assert csvio.read_rows(path) == [{"a": "2", "b": "z"}]
    assert [p.name for p in path.parent.iterdir()] == ["t.csv"]
