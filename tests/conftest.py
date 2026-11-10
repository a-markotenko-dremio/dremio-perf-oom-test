"""Pytest options and the fixtures shared by the test modules."""
import os

import pytest
import requests

import settings
import generate_data
import hdfsstore
import s3store
from dremio_client import DremioClient


def pytest_addoption(parser):
    parser.addoption("--dry-run", action="store_true",
                     help="collect all tests and run only those marked dry_run_safe")


def pytest_configure(config):
    config.addinivalue_line("markers", "dry_run_safe: test runs even with --dry-run")
    config.addinivalue_line("markers", "bdd: test checks a case of test-cases/ of the QA repository on the stand")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--dry-run"):
        return
    skip = pytest.mark.skip(reason="dry-run: environment is verified, test not executed")
    for item in items:
        if "dry_run_safe" not in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def dremio():
    """A logged-in client; every test is skipped when Dremio is not reachable."""
    client = DremioClient(settings.DREMIO_URL, settings.TIMEOUT)
    try:
        client.is_up()
    except requests.RequestException as e:
        pytest.skip(f"Dremio is not reachable at {settings.DREMIO_URL}: {e}")
    client.login()
    return client


@pytest.fixture(scope="session")
def storage_path():
    """STORAGE_PATH, which the tests that use Dremio need (the offline tests run without it)."""
    if settings.STORAGE_PATH is None:
        pytest.fail("STORAGE_PATH is not set: the storage of the container, see defaults.storage_path")
    return settings.STORAGE_PATH


def require(*names):
    for name in names:
        if getattr(settings, name) is None:
            pytest.fail(f"{name} is not set, STORAGE={settings.STORAGE} needs it")


@pytest.fixture(scope="session")
def remote_store():
    """The store that keeps both tables with STORAGE=s3 (a bucket) or hdfs (a directory), None with STORAGE=fs."""
    if settings.STORAGE == "s3":
        require("S3_ENDPOINT", "S3_BUCKET")  # make test-container sets them, and starts the server
        return s3store.Store(settings.S3_ENDPOINT, settings.S3_BUCKET, settings.S3_KEY, settings.S3_SECRET)
    if settings.STORAGE == "hdfs":
        require("HDFS_HOST")
        return hdfsstore.Store(settings.HDFS_HOST, settings.HDFS_PORT, settings.HDFS_WEB_PORT, settings.HDFS_ROOT,
                               settings.HDFS_USER)


@pytest.fixture(scope="session")
def storage(dremio, storage_path, remote_store):
    """Creates the Dremio sources that keep both tables: NAS sources on STORAGE_PATH, or the sources of the remote store."""
    path = storage_path
    if not os.access(path.parent if not path.exists() else path, os.W_OK):
        pytest.fail(f"STORAGE_PATH {path} is not writable by user "
                    f"{os.environ.get('USER', '?')}; create it and grant write access")
    sources = {settings.INPUT_SOURCE: "input", settings.OUTPUT_SOURCE: "output"}
    if remote_store:
        remote_store.ensure_sources(dremio, sources)
    else:
        for source, subdir in sources.items():
            (path / subdir).mkdir(parents=True, exist_ok=True)
            dremio.ensure_nas_source(source, path / subdir)


@pytest.fixture(scope="session")
def prepared_data(dremio, storage, storage_path, remote_store):
    """The generated input table, registered in Dremio."""
    assert 0 < settings.ROW_COUNT <= settings.MAX_ROW_COUNT, \
        f"ROW_COUNT must be in 1..{settings.MAX_ROW_COUNT}, got {settings.ROW_COUNT}"
    dremio.unpromote_table(settings.INPUT_TABLE_PATH)
    log = lambda m: print(m, flush=True)
    table_dir = generate_data.generate(settings.ROW_COUNT, storage_path, log=log)
    if remote_store:
        remote_store.upload_folder(table_dir, generate_data.TABLE_SUBDIR.as_posix(), log=log)
    dremio.promote_folder(settings.INPUT_TABLE_PATH)
