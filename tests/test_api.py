from __future__ import annotations

import os
import re
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from osrs_cli import api
from osrs_cli.api import OsrsApiClient
from osrs_cli.wiki import (
    extract_requirements_field,
    parse_requirements,
    strip_wiki_markup,
    wikitext_to_markdown,
)


def _resp(status: int, payload: Any = None) -> MagicMock:
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.json.return_value = payload if payload is not None else {}
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


def test_get_item_price_resolves_name_fetches_latest_and_caches(client, mocker):
    get = mocker.patch(
        "osrs_cli.api.requests.get",
        side_effect=[
            _resp(
                200,
                [
                    {
                        "id": 4151,
                        "name": "Abyssal whip",
                        "members": True,
                        "limit": 70,
                    }
                ],
            ),
            _resp(
                200,
                {
                    "data": {
                        "4151": {
                            "high": 1_600_000,
                            "highTime": 1_700_000_000,
                            "low": 1_590_000,
                            "lowTime": 1_700_000_001,
                        }
                    }
                },
            ),
        ],
    )

    data = client.get_item_price("abyssal WHIP")

    assert data == {
        "item": "Abyssal whip",
        "id": 4151,
        "members": True,
        "limit": 70,
        "high": 1_600_000,
        "high_time": 1_700_000_000,
        "low": 1_590_000,
        "low_time": 1_700_000_001,
        "_cached": False,
    }
    assert client.get_item_price("abyssal WHIP")["_cached"] is True
    assert get.call_count == 2
    assert get.call_args_list[1].kwargs["params"] == {"id": 4151}


def test_get_item_price_reuses_mapping_for_different_items(client, mocker):
    get = mocker.patch(
        "osrs_cli.api.requests.get",
        side_effect=[
            _resp(
                200,
                [
                    {"id": 2, "name": "Cannonball"},
                    {"id": 4151, "name": "Abyssal whip"},
                ],
            ),
            _resp(200, {"data": {"2": {"high": 200, "low": 190}}}),
            _resp(200, {"data": {"4151": {"high": 1_600_000, "low": 1_590_000}}}),
        ],
    )

    client.get_item_price("Cannonball")
    client.get_item_price("Abyssal whip")

    assert get.call_count == 3


@pytest.mark.parametrize("item", ["Missing item", " "])
def test_get_item_price_rejects_unknown_or_empty_item(client, mocker, item):
    get = mocker.patch("osrs_cli.api.requests.get", return_value=_resp(200, []))

    with pytest.raises(ValueError, match="not found|cannot be empty"):
        client.get_item_price(item)

    assert get.call_count == (0 if item.isspace() else 1)


def test_get_item_price_without_trades_raises(client, mocker):
    mocker.patch(
        "osrs_cli.api.requests.get",
        side_effect=[
            _resp(200, [{"id": 4151, "name": "Abyssal whip"}]),
            _resp(200, {"data": {}}),
        ],
    )

    with pytest.raises(ValueError, match="No live Grand Exchange price"):
        client.get_item_price("Abyssal whip")


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
    out = parse_requirements(field)
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
    assert strip_wiki_markup("{{SCP|Thieving|72|link=yes}}") == "72 Thieving"
    assert strip_wiki_markup("[[Warriors' Guild]]") == "Warriors' Guild"
    assert strip_wiki_markup("[[Foo|Bar]]") == "Bar"
    assert strip_wiki_markup("{{Boostable|no}} text") == "text"
    assert strip_wiki_markup("''italic''") == "italic"


def test_extract_requirements_field_stops_at_next_template_field():
    wikitext = (
        "{{Quest details\n"
        "|number = 123\n"
        "|requirements = * {{SCP|Magic|65}}\n"
        "* [[Priest in Peril]]\n"
        "|items = * Coins\n"
        "}}\n"
    )
    field = extract_requirements_field(wikitext)
    assert field is not None
    assert "Magic|65" in field
    assert "Priest in Peril" in field
    assert "Coins" not in field


def test_extract_requirements_field_missing_template_returns_none():
    assert extract_requirements_field("no template here") is None
    assert extract_requirements_field("{{Quest details\n|foo = bar\n}}") is None


def test_parse_requirements_ignores_header_and_dedupes_transitive():
    field = (
        "*Completion of the following quests:\n"
        "**[[A]]\n"
        "***[[B]]\n"
        "**[[A]]\n"  # duplicate direct should still appear once via dedupe in transitive
        "***[[B]]\n"  # duplicate transitive
    )
    out = parse_requirements(field)
    # A appears twice as a direct; B only once in transitive
    assert out["quests"].count("A") == 2  # direct list preserves duplicates (raw parse)
    assert out["transitive_quests"] == ["B"]


def test_parse_requirements_quest_before_header_is_transitive():
    """Quest links appearing before the quest-list header aren't 'direct prereqs'."""
    field = "*[[Some Quest]]\n"
    out = parse_requirements(field)
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


def test_wikitext_to_markdown_converts_common_constructs():

    assert wikitext_to_markdown("==Foo==").startswith("## Foo")
    assert wikitext_to_markdown("===Bar===").startswith("### Bar")
    assert wikitext_to_markdown("'''bold'''") == "**bold**"
    assert wikitext_to_markdown("''italic''") == "*italic*"
    # SCP template → "Level Skill"
    assert "40 Cooking" in wikitext_to_markdown("{{SCP|Cooking|40}}")
    # Wiki link with and without display text
    assert "[Cake](https://oldschool.runescape.wiki/w/Cake)" in wikitext_to_markdown("[[Cake]]")
    assert "[Sweet](https://oldschool.runescape.wiki/w/Cake)" in wikitext_to_markdown("[[Cake|Sweet]]")
    # Bullet conversion
    assert "- one" in wikitext_to_markdown("* one\n* two") and "- two" in wikitext_to_markdown("* one\n* two")
    # External link
    assert wikitext_to_markdown("[https://x.test foo]") == "[foo](https://x.test)"


def test_wikitext_to_markdown_strips_templates_and_files():

    # Generic templates removed
    assert "Hello world" in re.sub(r"\s+", " ", wikitext_to_markdown("Hello {{junk|x|y}} world"))
    # Nested templates removed
    assert "AB" in re.sub(r"\s+", "", wikitext_to_markdown("A{{outer|{{inner|x}}}}B"))
    # File embeds with caption stripped (including nested links)
    assert "after" in wikitext_to_markdown("[[File:foo.png|thumb|see [[link]] here]]after")


def test_wikitext_to_markdown_renders_quest_details_infobox():
    wt = (
        "{{Quest details\n"
        "|difficulty = Intermediate\n"
        "|length = Medium\n"
        "|requirements = * {{SCP|Herblore|31|link=yes}} {{Boostable|yes}}\n"
        "** [[Druidic Ritual]]\n"
        "|rewards = *{{SCP|Herblore|11,000}} [[Herblore]] [[experience]]\n"
        "}}\n"
        "==Walkthrough==\nDo stuff.\n"
    )
    out = wikitext_to_markdown(wt)
    # Reward XP survives (no separate Quest rewards template here, so it renders).
    assert "11,000 Herblore" in out
    # Boostable flag rendered inline on the requirement.
    assert "31 Herblore" in out and "(boostable)" in out
    # Nested prereq bullet kept (single bullet, not doubled).
    assert "- [Druidic Ritual]" in out
    assert "* *" not in out


def test_wikitext_to_markdown_renders_quest_points_and_rewards_template():
    wt = (
        "{{Quest details\n|difficulty = Master\n|requirements = * {{SCP|Magic|65}} {{Boostable|no}}\n}}\n"
        "==Rewards==\n"
        "{{Quest rewards\n|qp = 5\n|rewards = *{{SCP|Magic|5,000}} [[Magic]] [[experience]]\n}}\n"
    )
    out = wikitext_to_markdown(wt)
    # Quest points carried from the rewards template into the details block.
    assert "Quest points:" in out and "5" in out
    assert "5,000 Magic" in out
    assert "(not boostable)" in out


def test_wikitext_to_markdown_renders_simple_table():

    out = wikitext_to_markdown(
        "{| class='wikitable'\n! Name !! Level !! XP\n|-\n| Cake || 40 || 180\n|-\n| Pie || 50 || 220\n|}"
    )
    assert "| Name | Level | XP |" in out
    assert "|---|---|---|" in out
    assert "| Cake | 40 | 180 |" in out
    assert "| Pie | 50 | 220 |" in out


def test_wikitext_to_markdown_table_strips_cell_attrs_and_renders_links():

    out = wikitext_to_markdown(
        "{| class='wikitable'\n! Item !! Source\n|-\n| style='text-align:center' | [[Cake]] || Bakery\n|}"
    )
    assert "[Cake](https://oldschool.runescape.wiki/w/Cake)" in out
    assert "style=" not in out
    assert "Bakery" in out


def test_wikitext_to_markdown_table_with_caption_and_no_header():

    out = wikitext_to_markdown("{| class='wikitable'\n|+ Drop table\n| 1 || 2\n|-\n| 3 || 4\n|}")
    assert "**Drop table**" in out
    # No header row → synthetic empty header
    assert "|  |  |" in out
    assert "|---|---|" in out
    assert "| 1 | 2 |" in out
    assert "| 3 | 4 |" in out


def test_wikitext_to_markdown_table_per_line_cells():
    """MediaWiki allows one cell per line — common alternative to `||` separators."""

    out = wikitext_to_markdown("{| class='wikitable'\n|-\n! H1\n! H2\n|-\n| a\n| b\n|}")
    assert "| H1 | H2 |" in out
    assert "| a | b |" in out


def test_wikitext_to_markdown_nested_table_renders_in_outer_cell():

    out = wikitext_to_markdown("{| class='outer'\n! H1\n|-\n| {| class='inner'\n! X\n|-\n| y\n|}\n|}")
    # Outer header preserved
    assert "| H1 |" in out
    # Inner table flattened into the outer cell with <br> separators
    assert "X" in out and "y" in out
    # Outer cell row exists
    assert "<br>" in out


def test_wikitext_to_markdown_table_colspan_expands_to_trailing_empties():

    out = wikitext_to_markdown("{| class='wikitable'\n! colspan='3' | Top\n|-\n| a || b || c\n|}")
    # Header row width matches body width (3) — `Top` then 2 empty cells.
    assert "| Top |  |  |" in out
    assert "| a | b | c |" in out
    # Separator must have 3 columns.
    assert "|---|---|---|" in out


def test_wikitext_to_markdown_table_rowspan_blanks_subsequent_rows():

    out = wikitext_to_markdown("{| class='wikitable'\n! H1 !! H2\n|-\n| rowspan='2' | A || B\n|-\n| C\n|}")
    assert "| H1 | H2 |" in out
    assert "| A | B |" in out
    # Spanned column on the second body row appears empty, with C shifted into col 2.
    assert "|  | C |" in out


def test_wikitext_to_markdown_table_combined_colspan_and_rowspan():
    out = wikitext_to_markdown(
        "{| class='wikitable'\n| colspan='2' rowspan='2' | A || B\n|-\n| C\n|-\n| D || E || F\n|}"
    )
    # Row 1: A spans cols 1-2, B at col 3.
    assert "| A |  | B |" in out
    # Row 2: A still claims cols 1-2, C at col 3.
    assert "|  |  | C |" in out
    # Row 3: A's rowspan exhausted, normal layout D|E|F.
    assert "| D | E | F |" in out


def test_wikitext_to_markdown_table_colspan_attr_double_quoted():

    out = wikitext_to_markdown('{| class="wikitable"\n! colspan="2" | Heading\n|-\n| a || b\n|}')
    assert "| Heading |  |" in out
    assert "| a | b |" in out


def test_wikitext_to_markdown_def_list_indent_does_not_swallow_following_table():
    """Regression: `:` followed by a table line had \\s* eat the newline, so the
    table's header row got indented onto the same line as the `:` substitution
    and broke markdown rendering."""

    out = wikitext_to_markdown(":{| class='wikitable'\n! H1 !! H2\n|-\n| a || b\n|}")
    # Header row must remain on its own line, no leading 4-space indent.
    assert "| H1 | H2 |" in out
    assert "    | H1" not in out


def test_wikitext_to_markdown_table_pipe_in_cell_is_escaped():

    out = wikitext_to_markdown("{| class='wikitable'\n! A\n|-\n| has a | sign\n|}")
    # The cell `has a | sign` should render with the inner pipe escaped so it
    # doesn't break the markdown table.
    assert r"\|" in out


def test_wikitext_to_markdown_orders_lists_before_headings():
    """Heading conversion emits `#`, which would otherwise re-trigger list parsing."""

    out = wikitext_to_markdown("# numbered\n==Section==")
    assert "1. numbered" in out
    assert "## Section" in out


def test_get_wiki_page_caches_and_renders(client, mocker):
    wikitext = (
        "==Overview==\n"
        "'''Cake''' is a [[food]] that heals 12 [[Hitpoints]].\n"
        "==Stats==\n"
        "* {{SCP|Cooking|40}}\n"
    )
    payload = {"parse": {"title": "Cake", "wikitext": {"*": wikitext}}}
    get = mocker.patch("osrs_cli.api.requests.get", return_value=_resp(200, payload))

    data = client.get_wiki_page("cake")
    assert data["title"] == "Cake"
    assert data["url"].endswith("/Cake")
    assert "## Overview" in data["markdown"]
    assert "**Cake**" in data["markdown"]
    assert "[food](https://oldschool.runescape.wiki/w/food)" in data["markdown"]
    assert "40 Cooking" in data["markdown"]
    assert data["_cached"] is False

    again = client.get_wiki_page("cake")
    assert again["_cached"] is True
    assert get.call_count == 1


def test_get_wiki_page_empty_raises(client, mocker):
    mocker.patch(
        "osrs_cli.api.requests.get",
        return_value=_resp(200, {"parse": {"wikitext": {"*": ""}}}),
    )
    with pytest.raises(ValueError, match="No wiki page"):
        client.get_wiki_page("Nope")


def test_get_wiki_page_wiki_error_raises(client, mocker):
    mocker.patch(
        "osrs_cli.api.requests.get",
        return_value=_resp(200, {"error": {"info": "missingtitle"}}),
    )
    with pytest.raises(ValueError, match="missingtitle"):
        client.get_wiki_page("Nope")
