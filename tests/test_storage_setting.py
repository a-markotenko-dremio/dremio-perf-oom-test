"""Offline test of the STORAGE setting: read once from the environment, at import of settings."""
import importlib

import pytest

import defaults
import settings


def test_the_storage_is_fs_unless_s3_is_asked_for(monkeypatch):
    try:
        assert settings.STORAGE == defaults.STORAGE == "fs"
        monkeypatch.setenv("STORAGE", "s3")
        assert importlib.reload(settings).STORAGE == "s3"
        monkeypatch.setenv("STORAGE", "nfs")
        with pytest.raises(ValueError, match="STORAGE must be one of fs, s3, got 'nfs'"):
            importlib.reload(settings)
    finally:
        monkeypatch.undo()
        importlib.reload(settings)
