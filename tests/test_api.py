from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
import requests

from osrs_cli import api


def _resp(status: int, payload: dict | None = None) -> MagicMock:
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.json.return_value = payload or {}
    r.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}") if status >= 400 else None
    return r


def test_cache_respects_ttl(isolated_cache):
    api._write_cache("k", {"x": 1})
    assert api._read_cache("k", ttl=60) == {"x": 1}
    path = api._cache_path("k")
    os.utime(path, (0, 0))
    assert api._read_cache("k", ttl=60) is None


def test_rate_limit_blocks_after_max(isolated_cache, monkeypatch):
    monkeypatch.setattr(api, "RATE_LIMIT_MAX", 2)
    api._check_rate_limit()
    api._check_rate_limit()
    with pytest.raises(api.RateLimitError):
        api._check_rate_limit()


def test_get_player_caches_and_force_bypasses(isolated_cache, mocker):
    get = mocker.patch("osrs_cli.api.requests.get", return_value=_resp(200, {"username": "foo"}))
    api.get_player("foo")
    assert api.get_player("foo")["_cached"] is True
    api.get_player("foo", force=True)
    assert get.call_count == 2


def test_get_player_404_raises_value_error(isolated_cache, mocker):
    mocker.patch("osrs_cli.api.requests.get", return_value=_resp(404))
    with pytest.raises(ValueError, match="not found"):
        api.get_player("missing")


def test_get_quests_missing_player_raises_friendly_error(isolated_cache, mocker):
    mocker.patch("osrs_cli.api.requests.get", return_value=_resp(400))
    with pytest.raises(ValueError, match="WikiSync"):
        api.get_quests("foo")
