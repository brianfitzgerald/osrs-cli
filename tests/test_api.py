from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
import requests

from osrs_cli import api
from osrs_cli.api import OsrsApiClient


def _resp(status: int, payload: dict | None = None) -> MagicMock:
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.json.return_value = payload or {}
    r.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}") if status >= 400 else None
    return r


def test_cache_respects_ttl(client):
    client._write_cache("k", {"x": 1})
    assert client._read_cache("k", ttl=60) == {"x": 1}
    path = client._cache_path("k")
    os.utime(path, (0, 0))
    assert client._read_cache("k", ttl=60) is None


def test_rate_limit_blocks_after_max(tmp_path):
    c = OsrsApiClient(cache_dir=tmp_path / "cache", rate_limit_max=2)
    c._check_rate_limit()
    c._check_rate_limit()
    with pytest.raises(api.RateLimitError):
        c._check_rate_limit()


def test_get_player_caches_and_force_bypasses(client, mocker):
    get = mocker.patch("osrs_cli.api.requests.get", return_value=_resp(200, {"username": "foo"}))
    client.get_player("foo")
    assert client.get_player("foo")["_cached"] is True
    client.get_player("foo", force=True)
    assert get.call_count == 2


def test_get_player_404_raises_value_error(client, mocker):
    mocker.patch("osrs_cli.api.requests.get", return_value=_resp(404))
    with pytest.raises(ValueError, match="not found"):
        client.get_player("missing")


def test_get_quests_missing_player_raises_friendly_error(client, mocker):
    mocker.patch("osrs_cli.api.requests.get", return_value=_resp(400))
    with pytest.raises(ValueError, match="WikiSync"):
        client.get_quests("foo")


def test_parse_requirements_extracts_scp_skills_and_nested_quests():
    field = (
        "* {{SCP|Thieving|72|link=yes}} {{Boostable|no}}\n"
        "* {{SCP|Magic|67|link=yes}}\n"
        "* Ability to enter the [[Warriors' Guild]]\n"
        "*Completion of the following quests:\n"
        "**[[Defender of Varrock]]\n"
        "***[[Shield of Arrav]]\n"
        "**[[The Path of Glouphrie]]\n"
    )
    out = OsrsApiClient._parse_requirements(field)
    assert "72 Thieving" in out["skills"]
    assert "67 Magic" in out["skills"]
    assert out["quests"] == ["Defender of Varrock", "The Path of Glouphrie"]
    assert "Shield of Arrav" in out["transitive_quests"]
    assert any("Warriors' Guild" in o for o in out["other"])


def test_get_quest_requirements_wiki_error_raises(client, mocker):
    mocker.patch(
        "osrs_cli.api.requests.get",
        return_value=_resp(200, {"error": {"info": "missingtitle"}}),
    )
    with pytest.raises(ValueError, match="missingtitle"):
        client.get_quest_requirements("Nope")


def test_strip_wiki_markup_handles_scp_links_and_templates():
    strip = OsrsApiClient._strip_wiki_markup
    assert strip("{{SCP|Thieving|72|link=yes}}") == "72 Thieving"
    assert strip("[[Warriors' Guild]]") == "Warriors' Guild"
    assert strip("[[Foo|Bar]]") == "Bar"
    assert strip("{{Boostable|no}} text") == "text"
    assert strip("''italic''") == "italic"


def test_extract_requirements_field_stops_at_next_template_field():
    wikitext = (
        "{{Quest details\n"
        "|number = 123\n"
        "|requirements = * {{SCP|Magic|65}}\n"
        "* [[Priest in Peril]]\n"
        "|items = * Coins\n"
        "}}\n"
    )
    field = OsrsApiClient._extract_requirements_field(wikitext)
    assert field is not None
    assert "Magic|65" in field
    assert "Priest in Peril" in field
    assert "Coins" not in field


def test_extract_requirements_field_missing_template_returns_none():
    extract = OsrsApiClient._extract_requirements_field
    assert extract("no template here") is None
    assert extract("{{Quest details\n|foo = bar\n}}") is None


def test_parse_requirements_ignores_header_and_dedupes_transitive():
    field = (
        "*Completion of the following quests:\n"
        "**[[A]]\n"
        "***[[B]]\n"
        "**[[A]]\n"  # duplicate direct should still appear once via dedupe in transitive
        "***[[B]]\n"  # duplicate transitive
    )
    out = OsrsApiClient._parse_requirements(field)
    # A appears twice as a direct; B only once in transitive
    assert out["quests"].count("A") == 2  # direct list preserves duplicates (raw parse)
    assert out["transitive_quests"] == ["B"]


def test_parse_requirements_quest_before_header_is_transitive():
    """Quest links appearing before the quest-list header aren't 'direct prereqs'."""
    field = "*[[Some Quest]]\n"
    out = OsrsApiClient._parse_requirements(field)
    assert out["quests"] == []
    assert out["transitive_quests"] == ["Some Quest"]


def test_get_quest_requirements_caches_and_populates_fields(client, mocker):
    wikitext = (
        "{{Quest details\n"
        "|requirements = * {{SCP|Thieving|72|link=yes}}\n"
        "*Completion of the following quests:\n"
        "**[[Priest in Peril]]\n"
        "***[[The Restless Ghost]]\n"
        "|items = * nothing\n"
        "}}\n"
    )
    payload = {"parse": {"title": "Test Quest", "wikitext": {"*": wikitext}}}
    get = mocker.patch("osrs_cli.api.requests.get", return_value=_resp(200, payload))

    data = client.get_quest_requirements("test quest")
    assert data["quest"] == "Test Quest"
    assert data["url"].endswith("/Test_Quest")
    assert data["skills"] == ["72 Thieving"]
    assert data["quests"] == ["Priest in Peril"]
    assert data["transitive_quests"] == ["The Restless Ghost"]
    assert data["_cached"] is False

    # Second call hits the cache, not the network.
    again = client.get_quest_requirements("test quest")
    assert again["_cached"] is True
    assert get.call_count == 1


def test_get_quest_requirements_empty_wikitext_raises(client, mocker):
    mocker.patch(
        "osrs_cli.api.requests.get",
        return_value=_resp(200, {"parse": {"wikitext": {"*": ""}}}),
    )
    with pytest.raises(ValueError, match="No wiki page"):
        client.get_quest_requirements("Nope")


def test_get_quest_requirements_page_without_quest_template_raises(client, mocker):
    mocker.patch(
        "osrs_cli.api.requests.get",
        return_value=_resp(200, {"parse": {"title": "Bronze axe", "wikitext": {"*": "some item page"}}}),
    )
    with pytest.raises(ValueError, match="requirements section"):
        client.get_quest_requirements("Bronze axe")
