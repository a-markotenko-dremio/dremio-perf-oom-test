import pytest


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
