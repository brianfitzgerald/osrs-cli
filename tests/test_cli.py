from __future__ import annotations

import io

import pytest
from rich.console import Console

import osrs_cli as cli

PLAYER_FIXTURE = {
    "latestSnapshot": {
        "data": {
            "activities": {
                "clue_scrolls_all": {"score": 42, "rank": 1000},
                "last_man_standing": {"score": -1, "rank": -1},
            },
        }
    },
}

QUEST_FIXTURE = {
    "username": "x",
    "timestamp": "t",
    "quests": {
        ".": 0,
        "Cook's Assistant": 2,
        "Dragon Slayer I": 1,
        "Monkey Madness I": 0,
    },
}


@pytest.fixture
def capture_console(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buf, width=120, color_system=None))
    return buf


def test_activities_table_filters_unranked(capture_console):
    cli.console.print(cli._activities_table(PLAYER_FIXTURE))
    out = capture_console.getvalue()
    assert "Clue Scrolls (All)" in out
    assert "Last Man Standing" not in out


def test_render_quests_summary_and_filter(capture_console):
    cli._render_quests(QUEST_FIXTURE, status="complete")
    out = capture_console.getvalue()
    assert "1 complete" in out and "1 in progress" in out and "3 total" in out
    assert "Cook's Assistant" in out
    assert "Dragon Slayer I" not in out


def test_render_quests_uses_ascii_markers(capture_console):
    """Regression: Rich markup stripped [x]/[~]/[ ] until brackets were escaped."""
    cli._render_quests(QUEST_FIXTURE, status="all")
    out = capture_console.getvalue()
    assert "[x]" in out and "[~]" in out and "[ ]" in out


def test_requirements_command_renders_all_sections(capture_console, mocker):
    mocker.patch(
        "osrs_cli.client.get_quest_requirements",
        return_value={
            "quest": "While Guthix Sleeps",
            "url": "https://oldschool.runescape.wiki/w/While_Guthix_Sleeps",
            "skills": ["72 Thieving", "67 Magic"],
            "quests": ["Defender of Varrock"],
            "transitive_quests": ["Shield of Arrav"],
            "other": ["Ability to enter the Warriors' Guild"],
            "_cached": True,
        },
    )
    cli.OsrsCli().requirements("While Guthix Sleeps")
    out = capture_console.getvalue()
    assert "While Guthix Sleeps" in out
    assert "(cached)" in out
    assert "72 Thieving" in out and "67 Magic" in out
    assert "Defender of Varrock" in out
    assert "Shield of Arrav" in out
    assert "Warriors' Guild" in out


def test_requirements_command_empty_results_prints_message(capture_console, mocker):
    mocker.patch(
        "osrs_cli.client.get_quest_requirements",
        return_value={
            "quest": "Stub",
            "url": "https://oldschool.runescape.wiki/w/Stub",
            "skills": [],
            "quests": [],
            "transitive_quests": [],
            "other": [],
            "_cached": False,
        },
    )
    cli.OsrsCli().requirements("Stub")
    assert "No parseable requirements" in capture_console.getvalue()
