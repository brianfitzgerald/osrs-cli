"""Wise Old Man API client with local caching + rate limiting."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://api.wiseoldman.net/v2"
WIKISYNC_URL = "https://sync.runescape.wiki/runelite/player/{username}/STANDARD"
CACHE_DIR = Path.home() / ".cache" / "osrs-cli"
CACHE_TTL_SECONDS = 300
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 20
RATE_STATE_FILE = CACHE_DIR / "_rate.json"


class RateLimitError(RuntimeError):
    pass


def _load_rate_state() -> list[float]:
    if not RATE_STATE_FILE.exists():
        return []
    try:
        return json.loads(RATE_STATE_FILE.read_text())
    except json.JSONDecodeError, OSError:
        return []


def _save_rate_state(stamps: list[float]) -> None:
    RATE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    RATE_STATE_FILE.write_text(json.dumps(stamps))


def _check_rate_limit() -> None:
    now = time.time()
    stamps = [t for t in _load_rate_state() if now - t < RATE_LIMIT_WINDOW]
    if len(stamps) >= RATE_LIMIT_MAX:
        wait = RATE_LIMIT_WINDOW - (now - stamps[0])
        raise RateLimitError(
            f"Rate limit reached ({RATE_LIMIT_MAX}/{RATE_LIMIT_WINDOW}s). "
            f"Try again in {wait:.0f}s, or use cached results."
        )
    stamps.append(now)
    _save_rate_state(stamps)


def _cache_path(key: str) -> Path:
    safe = "".join(c if c.isalnum() else "_" for c in key.lower())
    return CACHE_DIR / f"{safe}.json"


def _read_cache(key: str, ttl: int) -> dict[str, Any] | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    age = time.time() - path.stat().st_mtime
    if age > ttl:
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError, OSError:
        return None


def _write_cache(key: str, data: dict[str, Any]) -> None:
    path = _cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def get_player(username: str, *, force: bool = False, ttl: int = CACHE_TTL_SECONDS) -> dict[str, Any]:
    """Fetch player details from WOM. Uses local cache (default TTL 5 minutes)."""
    key = f"player_{username}"
    if not force:
        cached = _read_cache(key, ttl)
        if cached is not None:
            cached["_cached"] = True
            return cached

    _check_rate_limit()
    resp = requests.get(f"{BASE_URL}/players/{username}", timeout=15)
    if resp.status_code == 404:
        raise ValueError(f"Player '{username}' not found on Wise Old Man.")
    if resp.status_code == 429:
        raise RateLimitError("Server returned 429 — you are rate limited.")
    resp.raise_for_status()
    data = resp.json()
    _write_cache(key, data)
    data["_cached"] = False
    return data


def get_quests(username: str, *, force: bool = False, ttl: int = CACHE_TTL_SECONDS) -> dict[str, Any]:
    """Fetch quest completion from WikiSync (RuneLite plugin data).

    Returns dict with keys: username, timestamp, quests (name -> 0/1/2).
    Raises ValueError if the player has never uploaded via the WikiSync plugin.
    """
    key = f"quests_{username}"
    if not force:
        cached = _read_cache(key, ttl)
        if cached is not None:
            cached["_cached"] = True
            return cached

    _check_rate_limit()
    headers = {"User-Agent": "osrs-cli/0.1 (+https://github.com/)", "Accept": "application/json"}
    resp = requests.get(WIKISYNC_URL.format(username=username), headers=headers, timeout=15)
    if resp.status_code == 404 or resp.status_code == 400:
        raise ValueError(
            f"No WikiSync data for '{username}'. Player must run the WikiSync RuneLite plugin at least once."
        )
    if resp.status_code == 429:
        raise RateLimitError("WikiSync returned 429 — you are rate limited.")
    resp.raise_for_status()
    data = resp.json()
    _write_cache(key, data)
    data["_cached"] = False
    return data


def clear_cache() -> int:
    """Remove all cached player data. Returns number of files removed."""
    if not CACHE_DIR.exists():
        return 0
    count = 0
    for f in CACHE_DIR.glob("*.json"):
        if f.name == "_rate.json":
            continue
        f.unlink()
        count += 1
    return count
