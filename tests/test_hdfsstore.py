"""Offline tests of hdfsstore on a fake WebHDFS: the HDFS directory of the STORAGE=hdfs runs and the table folders in it."""
import json

import pytest
import requests

import hdfsstore

TABLE = "input/STACKIT_S3/tpcds-1tb-flat/catalog_sales"
ROOT = "http://nn:9870/webhdfs/v1/perf"


class FakeWebHdfs:
    """Files by path under the root; a CREATE is answered with a redirect to a datanode, as WebHDFS does."""

    def __init__(self, files=None):
        self.files, self.dirs, self.calls = dict(files or {}), [], []

    def request(self, method, url, params, allow_redirects, timeout):
        path = url.removeprefix(ROOT + "/")
        self.calls.append((method, path, params["op"]))
        assert params["user.name"] == "dremio" and not allow_redirects
        op = params["op"]
        if op == "MKDIRS":
            self.dirs.append(path)
            return response(200)
        if op == "LISTSTATUS":
            names = {p.removeprefix(path + "/"): len(v) for p, v in self.files.items() if p.startswith(path + "/")}
            if not names:
                return response(404)
            return response(200, {"FileStatuses": {"FileStatus": [{"pathSuffix": n, "length": s} for n, s in names.items()]}})
        if op == "DELETE":
            doomed = [p for p in self.files if p == path or (params.get("recursive") and p.startswith(path + "/"))]
            for p in doomed:
                del self.files[p]
            return response(200)
        assert op == "CREATE" and params["overwrite"] == "true"
        return response(307, headers={"Location": f"http://dn:9864/{path}"})

    def put(self, location, data, timeout):
        self.files[location.removeprefix("http://dn:9864/")] = data.read()
        return response(201)


def response(status, body=None, headers=None):
    r = requests.Response()
    r.status_code, r.headers = status, headers or {}
    r._content = json.dumps(body or {}).encode()
    return r


@pytest.fixture
def webhdfs(monkeypatch):
    fake = FakeWebHdfs()
    monkeypatch.setattr(requests, "request", fake.request)
    monkeypatch.setattr(requests, "put", fake.put)
    return fake


def store():
    return hdfsstore.Store("nn", 8020, 9870, "/perf/", "dremio")


def test_the_url_is_the_one_dremio_reaches():
    assert store().url == "hdfs://nn:8020/perf"


def test_upload_makes_the_folder_hold_exactly_the_files(webhdfs, tmp_path):
    (tmp_path / "block_0_10.parquet").write_bytes(b"x" * 10)
    (tmp_path / "block_10_5.parquet").write_bytes(b"y" * 5)
    webhdfs.files = {f"{TABLE}/block_0_10.parquet": b"x" * 10, f"{TABLE}/block_20_10.parquet": b"c" * 10,
                     f"{TABLE}/block_10_5.parquet": b"old"}
    log = []
    store().upload_folder(tmp_path, TABLE, log=log.append)
    assert webhdfs.files == {f"{TABLE}/block_0_10.parquet": b"x" * 10, f"{TABLE}/block_10_5.parquet": b"y" * 5}
    assert log == [f"uploaded hdfs://nn:8020/perf/{TABLE}/block_10_5.parquet"]  # the file of the same size is kept


def test_delete_folder_leaves_the_similar_ones(webhdfs):
    webhdfs.files = {"output/t/data/1.parquet": b"x", "output/t/data/2.parquet": b"x", "output/t_other/1.parquet": b"x"}
    store().delete_folder("output/t")
    assert list(webhdfs.files) == ["output/t_other/1.parquet"]


def test_sources_are_created_over_their_directories(webhdfs):
    created = []

    class Dremio:
        def ensure_hdfs_source(self, *args):
            created.append(args)

    store().ensure_sources(Dremio(), {"perf_input": "input", "perf_output": "output"})
    assert webhdfs.dirs == ["input", "output"]
    assert created == [("perf_input", "nn", 8020, "/perf/input"), ("perf_output", "nn", 8020, "/perf/output")]


def test_a_failing_request_is_an_error(monkeypatch):
    monkeypatch.setattr(requests, "request", lambda *a, **k: response(403))
    with pytest.raises(requests.HTTPError):
        store().delete_folder("output/t")
