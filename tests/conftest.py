from __future__ import annotations

import pytest

from osrs_cli import api


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Redirect the on-disk cache + rate-limit state to a tmp dir per test."""
    cache = tmp_path / "cache"
    monkeypatch.setattr(api, "CACHE_DIR", cache)
    monkeypatch.setattr(api, "RATE_STATE_FILE", cache / "_rate.json")
    yield cache
