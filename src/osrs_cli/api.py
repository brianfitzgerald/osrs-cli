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
USER_AGENT = "osrs-cli/0.1 (+https://github.com/)"

SKILL_GROUP_NAMES = {
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
    "sailing",
}


class RateLimitError(RuntimeError):
    pass


class OsrsApiClient:
    """Client for Wise Old Man, WikiSync, and the OSRS Wiki.

    Wraps three upstream services behind a single on-disk cache and a shared
    sliding-window rate limiter. Construct with custom paths for tests; the
    module exposes a default instance and thin functional wrappers.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        rate_state_file: Path | None = None,
        default_ttl: int = CACHE_TTL_SECONDS,
        rate_limit_max: int = RATE_LIMIT_MAX,
        rate_limit_window: int = RATE_LIMIT_WINDOW,
    ) -> None:
        self.cache_dir = cache_dir if cache_dir is not None else CACHE_DIR
        self.rate_state_file = (
            rate_state_file if rate_state_file is not None else self.cache_dir / "_rate.json"
        )
        self.default_ttl = default_ttl
        self.rate_limit_max = rate_limit_max
        self.rate_limit_window = rate_limit_window

    # ---- rate limiting -------------------------------------------------

    def _load_rate_state(self) -> list[float]:
        if not self.rate_state_file.exists():
            return []
        try:
            return json.loads(self.rate_state_file.read_text())
        except json.JSONDecodeError, OSError:
            return []

    def _save_rate_state(self, stamps: list[float]) -> None:
        self.rate_state_file.parent.mkdir(parents=True, exist_ok=True)
        self.rate_state_file.write_text(json.dumps(stamps))

    def _check_rate_limit(self) -> None:
        now = time.time()
        stamps = [t for t in self._load_rate_state() if now - t < self.rate_limit_window]
        if len(stamps) >= self.rate_limit_max:
            wait = self.rate_limit_window - (now - stamps[0])
            raise RateLimitError(
                f"Rate limit reached ({self.rate_limit_max}/{self.rate_limit_window}s). "
                f"Try again in {wait:.0f}s, or use cached results."
            )
        stamps.append(now)
        self._save_rate_state(stamps)

    # ---- cache ---------------------------------------------------------

    def _cache_path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() else "_" for c in key.lower())
        return self.cache_dir / f"{safe}.json"

    def _read_cache(self, key: str, ttl: int) -> dict[str, Any] | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > ttl:
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError, OSError:
            return None

    def _write_cache(self, key: str, data: dict[str, Any]) -> None:
        path = self._cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def clear_cache(self) -> int:
        """Remove all cached player data. Returns number of files removed."""
        if not self.cache_dir.exists():
            return 0
        count = 0
        for f in self.cache_dir.glob("*.json"):
            if f.name == "_rate.json":
                continue
            f.unlink()
            count += 1
        return count

    # ---- HTTP fetchers -------------------------------------------------

    def get_player(self, username: str, *, force: bool = False, ttl: int | None = None) -> dict[str, Any]:
        """Fetch player details from WOM. Uses local cache (default TTL 5 minutes)."""
        ttl = self.default_ttl if ttl is None else ttl
        key = f"player_{username}"
        if not force:
            cached = self._read_cache(key, ttl)
            if cached is not None:
                cached["_cached"] = True
                return cached

        self._check_rate_limit()
        resp = requests.get(f"{BASE_URL}/players/{username}", timeout=15)
        if resp.status_code == 404:
            raise ValueError(f"Player '{username}' not found on Wise Old Man.")
        if resp.status_code == 429:
            raise RateLimitError("Server returned 429 — you are rate limited.")
        resp.raise_for_status()
        data = resp.json()
        self._write_cache(key, data)
        data["_cached"] = False
        return data

    def get_quests(self, username: str, *, force: bool = False, ttl: int | None = None) -> dict[str, Any]:
        """Fetch quest completion from WikiSync (RuneLite plugin data).

        Returns dict with keys: username, timestamp, quests (name -> 0/1/2).
        Raises ValueError if the player has never uploaded via the WikiSync plugin.
        """
        ttl = self.default_ttl if ttl is None else ttl
        key = f"quests_{username}"
        if not force:
            cached = self._read_cache(key, ttl)
            if cached is not None:
                cached["_cached"] = True
                return cached

        self._check_rate_limit()
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        resp = requests.get(WIKISYNC_URL.format(username=username), headers=headers, timeout=15)
        if resp.status_code == 404 or resp.status_code == 400:
            raise ValueError(
                f"No WikiSync data for '{username}'. "
                "Player must run the WikiSync RuneLite plugin at least once."
            )
        if resp.status_code == 429:
            raise RateLimitError("WikiSync returned 429 — you are rate limited.")
        resp.raise_for_status()
        data = resp.json()
        self._write_cache(key, data)
        data["_cached"] = False
        return data

    def get_quest_requirements(
        self, quest: str, *, force: bool = False, ttl: int | None = None
    ) -> dict[str, Any]:
        """Fetch a quest's requirements from the OSRS Wiki.

        Returns dict with: quest (resolved title), skills, quests, other, url.
        Raises ValueError if the page does not exist or has no parseable requirements.
        """
        ttl = self.default_ttl if ttl is None else ttl
        title = quest.strip().replace("_", " ")
        key = f"quest_req_{title}"
        if not force:
            cached = self._read_cache(key, ttl)
            if cached is not None:
                cached["_cached"] = True
                return cached

        self._check_rate_limit()
        params = {
            "action": "parse",
            "page": title,
            "prop": "wikitext",
            "redirects": "1",
            "format": "json",
        }
        headers = {"User-Agent": USER_AGENT}
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

        field = self._extract_requirements_field(wikitext)
        if field is None:
            raise ValueError(f"Could not find a requirements section for '{quest}' — is it a quest page?")
        buckets = self._parse_requirements(field)
        resolved = parse.get("title") or title
        data: dict[str, Any] = {
            "quest": resolved,
            "url": f"https://oldschool.runescape.wiki/w/{resolved.replace(' ', '_')}",
            **buckets,
        }
        self._write_cache(key, data)
        data["_cached"] = False
        return data

    # ---- wiki parsing (pure) ------------------------------------------

    @staticmethod
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

    @staticmethod
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

    @classmethod
    def _parse_requirements(cls, field: str) -> dict[str, Any]:
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
            cleaned = cls._strip_wiki_markup(body)
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
            if skill_m and skill_m.group(2).lower() in SKILL_GROUP_NAMES:
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


default_client = OsrsApiClient()
