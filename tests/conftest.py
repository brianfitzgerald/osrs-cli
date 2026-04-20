from __future__ import annotations

import pytest

from osrs_cli.api import OsrsApiClient


@pytest.fixture
def client(tmp_path) -> OsrsApiClient:
    """Fresh client with cache + rate-limit state isolated to a tmp dir."""
    cache = tmp_path / "cache"
    return OsrsApiClient(cache_dir=cache)
