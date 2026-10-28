"""Pytest options and the fixtures shared by the test modules."""
import os

import pytest
import requests

import settings
import generate_data
from dremio_client import DremioClient


def pytest_addoption(parser):
    parser.addoption("--dry-run", action="store_true",
                     help="collect all tests and run only those marked dry_run_safe")


def pytest_configure(config):
    config.addinivalue_line("markers", "dry_run_safe: test runs even with --dry-run")


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


@pytest.fixture(scope="session")
def storage(dremio, storage_path):
    """Creates the Dremio NAS sources that keep both tables on STORAGE_PATH."""
    path = storage_path
    if not os.access(path.parent if not path.exists() else path, os.W_OK):
        pytest.fail(f"STORAGE_PATH {path} is not writable by user "
                    f"{os.environ.get('USER', '?')}; create it and grant write access")
    dremio.ensure_nas_source(settings.INPUT_SOURCE, path / "input")
    dremio.ensure_nas_source(settings.OUTPUT_SOURCE, path / "output")


@pytest.fixture(scope="session")
def prepared_data(dremio, storage, storage_path):
    """The generated input table, registered in Dremio."""
    assert 0 < settings.ROW_COUNT <= settings.MAX_ROW_COUNT, \
        f"ROW_COUNT must be in 1..{settings.MAX_ROW_COUNT}, got {settings.ROW_COUNT}"
    dremio.unpromote_table(settings.INPUT_TABLE_PATH)
    generate_data.generate(settings.ROW_COUNT, storage_path, log=lambda m: print(m, flush=True))
    dremio.promote_folder(settings.INPUT_TABLE_PATH)
