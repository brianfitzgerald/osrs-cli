"""Wise Old Man API client with local caching + rate limiting."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://api.wiseoldman.net/v2"
WIKISYNC_URL = "https://sync.runescape.wiki/runelite/player/{username}/STANDARD"
WIKI_API_URL = "https://oldschool.runescape.wiki/api.php"
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


SKILL_NAMES = {
    "attack",
    "defence",
    "strength",
    "hitpoints",
    "ranged",
    "prayer",
    "magic",
    "cooking",
    "woodcutting",
    "fletching",
    "fishing",
    "firemaking",
    "crafting",
    "smithing",
    "mining",
    "herblore",
    "agility",
    "thieving",
    "slayer",
    "farming",
    "runecraft",
    "runecrafting",
    "hunter",
    "construction",
    "combat",
    "quest",
}


def _strip_wiki_markup(s: str) -> str:
    # {{SCP|Skill|Level|...}} → "Level Skill" (skill-check template)
    s = re.sub(
        r"\{\{SCP\|([^|}]+)\|([^|}]+)(?:\|[^}]*)?\}\}",
        lambda m: f"{m.group(2).strip()} {m.group(1).strip()}",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"\{\{[^}]+\}\}", "", s)
    s = re.sub(r"''+", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _extract_requirements_field(wikitext: str) -> str | None:
    """Pull the `requirements =` field out of the {{Quest details}} template."""
    m = re.search(r"\{\{Quest details", wikitext, re.IGNORECASE)
    if not m:
        return None
    body = wikitext[m.end() :]
    m2 = re.search(r"\|\s*requirements\s*=", body, re.IGNORECASE)
    if not m2:
        return None
    rest = body[m2.end() :]
    depth = 0
    out: list[str] = []
    i = 0
    while i < len(rest):
        c = rest[i]
        if c == "{" and rest[i : i + 2] == "{{":
            depth += 1
            out.append("{{")
            i += 2
            continue
        if c == "}" and rest[i : i + 2] == "}}":
            if depth == 0:
                break
            depth -= 1
            out.append("}}")
            i += 2
            continue
        if c == "|" and depth == 0 and (i == 0 or rest[i - 1] == "\n"):
            break
        out.append(c)
        i += 1
    return "".join(out).strip()


def _parse_requirements(field: str) -> dict[str, Any]:
    """Bucket requirement lines into skills, direct prereq quests, transitive, other."""
    skills: list[str] = []
    direct_quests: list[str] = []
    transitive_quests: list[str] = []
    other: list[str] = []
    seen_quest_header = False
    for raw in field.splitlines():
        stripped = raw.lstrip()
        m = re.match(r"^(\*+)\s*(.*)$", stripped)
        if not m:
            continue
        depth = len(m.group(1))
        body = m.group(2).strip()
        if not body or body.startswith("|") or body.startswith("}}"):
            continue
        cleaned = _strip_wiki_markup(body)
        if not cleaned:
            continue
        # Quest-list header like "Completion of the following quests:" — skip;
        # subsequent deeper bullets are the actual list.
        if re.search(r"completion of the following quests", cleaned, re.IGNORECASE):
            seen_quest_header = True
            continue
        quest_link = re.match(r"^\[\[([^\]|]+)(?:\|[^\]]+)?\]\]\s*$", body)
        if quest_link:
            name = quest_link.group(1).strip()
            if seen_quest_header and depth <= 2:
                direct_quests.append(name)
            else:
                transitive_quests.append(name)
            continue
        skill_m = re.match(r"^(\d+)\s+([A-Za-z]+)", cleaned)
        if skill_m and skill_m.group(2).lower() in SKILL_NAMES:
            skills.append(cleaned)
            continue
        other.append(cleaned)
    # Dedupe transitive while preserving order, and drop any already in direct.
    seen = set(direct_quests)
    deduped_transitive: list[str] = []
    for q in transitive_quests:
        if q in seen:
            continue
        seen.add(q)
        deduped_transitive.append(q)
    return {
        "skills": skills,
        "quests": direct_quests,
        "transitive_quests": deduped_transitive,
        "other": other,
    }


def get_quest_requirements(
    quest: str, *, force: bool = False, ttl: int = CACHE_TTL_SECONDS
) -> dict[str, Any]:
    """Fetch a quest's requirements from the OSRS Wiki.

    Returns dict with: quest (resolved title), skills, quests, other, url.
    Raises ValueError if the page does not exist or has no parseable requirements.
    """
    title = quest.strip().replace("_", " ")
    key = f"quest_req_{title}"
    if not force:
        cached = _read_cache(key, ttl)
        if cached is not None:
            cached["_cached"] = True
            return cached

    _check_rate_limit()
    params = {
        "action": "parse",
        "page": title,
        "prop": "wikitext",
        "redirects": "1",
        "format": "json",
    }
    headers = {"User-Agent": "osrs-cli/0.1 (+https://github.com/)"}
    resp = requests.get(WIKI_API_URL, params=params, headers=headers, timeout=15)
    if resp.status_code == 429:
        raise RateLimitError("Wiki returned 429 — you are rate limited.")
    resp.raise_for_status()
    payload = resp.json()
    if "error" in payload:
        info = payload["error"].get("info", "unknown error")
        raise ValueError(f"Wiki: {info}")
    parse = payload.get("parse") or {}
    wikitext = ((parse.get("wikitext") or {}).get("*")) or ""
    if not wikitext:
        raise ValueError(f"No wiki page found for '{quest}'.")

    field = _extract_requirements_field(wikitext)
    if field is None:
        raise ValueError(f"Could not find a requirements section for '{quest}' — is it a quest page?")
    buckets = _parse_requirements(field)
    resolved = parse.get("title") or title
    data: dict[str, Any] = {
        "quest": resolved,
        "url": f"https://oldschool.runescape.wiki/w/{resolved.replace(' ', '_')}",
        **buckets,
    }
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
