"""Offline tests of dremio_client: the catalog calls on the responses of the stand (the source "OOM Repro" of the repro)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

import dremio_client

SOURCE = "OOM Repro"
STAND = Path("/mnt/ubuntu-var/dremio/d25-2-0-j21-14G-4cpu/qa-oom-repro")
SOURCE_ID = "4f3ea3c9-6d6b-4b1a-9c0e-2f0e8c8a4b11"


def response(ok=True, status=200, **body):
    return SimpleNamespace(ok=ok, status_code=status, text=str(body), json=lambda: body, raise_for_status=lambda: None)


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    """A client whose catalog holds the source at STAND; records the PUT and POST calls."""
    calls = []
    monkeypatch.setattr(dremio_client.requests, "get", lambda url, **kw: (
        response(data=[{"path": [SOURCE], "id": SOURCE_ID, "tag": "7"}]) if url.endswith("/api/v3/catalog")
        else response(id=SOURCE_ID, type="NAS", config={"path": str(STAND)})))
    monkeypatch.setattr(dremio_client.requests, "put", lambda url, **kw: calls.append(("put", url, kw["json"])) or response())
    monkeypatch.setattr(dremio_client.requests, "post", lambda url, **kw: calls.append(("post", url, kw["json"])) or response())
    return dremio_client.DremioClient("http://192.168.1.75:9047", 60), calls


def test_a_source_already_on_the_path_is_left_alone(catalog):
    client, calls = catalog
    assert client.ensure_nas_source(SOURCE, STAND) is False
    assert calls == []


def test_a_source_on_another_path_is_repointed(catalog):
    client, calls = catalog
    other = STAND.with_name("qa-oom-repro.baseline-20261023")
    assert client.ensure_nas_source(SOURCE, other) is True
    assert calls == [("put", f"http://192.168.1.75:9047/api/v3/catalog/{SOURCE_ID}",
                      {"entityType": "source", "id": SOURCE_ID, "tag": "7", "name": SOURCE, "type": "NAS",
                       "config": {"path": str(other)}})]


def test_a_missing_source_is_created(catalog, monkeypatch):
    client, calls = catalog
    monkeypatch.setattr(dremio_client.requests, "get", lambda url, **kw: response(data=[]))
    assert client.ensure_nas_source(SOURCE, STAND) is True
    assert [(kind, body["config"]) for kind, _, body in calls] == [("post", {"path": str(STAND)})]


def test_a_job_that_passes_its_own_time_limit_is_cancelled(monkeypatch):
    """The time limit of a fabric OOM run (OOM_MAX_QUERY_SECONDS) bounds one job, not the client: the job is
    cancelled when it reaches the limit and the error names it, so the run does not wait out DREMIO_TIMEOUT."""
    clock, calls = [0.0], []
    monkeypatch.setattr(dremio_client.time, "time", lambda: clock[0])
    monkeypatch.setattr(dremio_client.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(dremio_client.requests, "post", lambda url, **kw: calls.append(url) or response(id="job1"))
    monkeypatch.setattr(dremio_client.requests, "get", lambda url, **kw: response(jobState="RUNNING"))
    client = dremio_client.DremioClient("http://192.168.1.75:9047", 7200)
    with pytest.raises(dremio_client.JobTimeout, match="did not finish within 600s"):
        client.run_sql("SELECT 1", timeout=600)
    assert calls[-1] == "http://192.168.1.75:9047/api/v3/job/job1/cancel"


def test_a_bool_option_is_written_as_an_sql_keyword():
    """ALTER SYSTEM SET "dremio.results_cache_rest_enabled" = False is a syntax error; false is not."""
    assert dremio_client.sql_value(False) == "false"
    assert dremio_client.sql_value(24) == 24 and dremio_client.sql_value(4.0) == 4.0


S3_ARGS = ("perf_input", "10.97.177.20:9000", "dremio", "dremio123", "/d26-1-8-wolfi-jdk-21-8G-4cpu/input")
S3_PROPERTIES = [{"name": "fs.s3a.endpoint", "value": "10.97.177.20:9000"}, {"name": "fs.s3a.path.style.access", "value": "true"}]


@pytest.fixture
def s3_catalog(monkeypatch):
    """A client whose catalog holds the S3 source over S3_ARGS; records the PUT and POST calls."""
    calls = []
    existing = {"rootPath": S3_ARGS[4], "propertyList": S3_PROPERTIES}
    monkeypatch.setattr(dremio_client.requests, "get", lambda url, **kw: (
        response(data=[{"path": ["perf_input"], "id": SOURCE_ID, "tag": "7"}]) if url.endswith("/api/v3/catalog")
        else response(id=SOURCE_ID, type="S3", config=existing)))
    monkeypatch.setattr(dremio_client.requests, "put", lambda url, **kw: calls.append(("put", kw["json"])) or response())
    monkeypatch.setattr(dremio_client.requests, "post", lambda url, **kw: calls.append(("post", kw["json"])) or response())
    return dremio_client.DremioClient("http://10.97.177.9:9047", 60), calls, existing


def test_an_s3_source_on_the_bucket_is_left_alone(s3_catalog):
    client, calls, _ = s3_catalog
    assert client.ensure_s3_source(*S3_ARGS) is False
    assert calls == []


def test_an_s3_source_on_another_bucket_is_repointed(s3_catalog):
    client, calls, existing = s3_catalog
    existing["rootPath"] = "/d26-1-10-wolfi-jdk-21-8G-4cpu/input"
    assert client.ensure_s3_source(*S3_ARGS) is True
    [(kind, body)] = calls
    assert (kind, body["type"], body["config"]["rootPath"], body["config"]["propertyList"]) == ("put", "S3", S3_ARGS[4], S3_PROPERTIES)


def test_a_missing_s3_source_is_created_with_the_endpoint_of_the_server(s3_catalog, monkeypatch):
    client, calls, _ = s3_catalog
    monkeypatch.setattr(dremio_client.requests, "get", lambda url, **kw: response(data=[]))
    assert client.ensure_s3_source(*S3_ARGS) is True
    [(kind, body)] = calls
    assert (kind, body["type"], body["config"]["accessKey"], body["config"]["propertyList"]) == ("post", "S3", "dremio", S3_PROPERTIES)


def test_a_nas_source_is_not_turned_into_an_s3_source(catalog):
    client, calls = catalog
    with pytest.raises(AssertionError, match="is a NAS source, not S3"):
        client.ensure_s3_source(SOURCE, *S3_ARGS[1:])
    assert calls == []
