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
        else response(id=SOURCE_ID, config={"path": str(STAND)})))
    monkeypatch.setattr(dremio_client.requests, "put", lambda url, **kw: calls.append(("put", url, kw["json"])) or response())
    monkeypatch.setattr(dremio_client.requests, "post", lambda url, **kw: calls.append(("post", url, kw["json"])) or response())
    monkeypatch.setattr(Path, "mkdir", lambda *a, **kw: None)
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
