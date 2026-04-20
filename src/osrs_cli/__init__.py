"""osrs-cli — a Wise Old Man CLI.

Usage:
    osrs-cli stats <username>       Show current skill levels + totals.
    osrs-cli activities <username>  Show activities (clues, bounty hunter, LMS...).
    osrs-cli player <username>      Full summary: skills + activities + bosses.
    osrs-cli clear-cache            Drop locally cached responses.

Flags (all query commands):
    --force      Bypass the local cache and hit the API.
    --ttl <sec>  Override cache TTL in seconds (default 300).

The CLI caches responses under ~/.cache/osrs-cli and enforces the public
Wise Old Man rate limit of 20 requests per 60 seconds.
"""

from __future__ import annotations

import fire
from rich.console import Console
from rich.table import Table

from . import api
from .api import OsrsApiClient

console = Console()
client = OsrsApiClient()

SKILL_ORDER = [
    "overall",
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
    "runecrafting",
    "hunter",
    "construction",
]

ACTIVITY_LABELS = {
    "league_points": "League Points",
    "bounty_hunter_hunter": "Bounty Hunter (Hunter)",
    "bounty_hunter_rogue": "Bounty Hunter (Rogue)",
    "clue_scrolls_all": "Clue Scrolls (All)",
    "clue_scrolls_beginner": "Clues (Beginner)",
    "clue_scrolls_easy": "Clues (Easy)",
    "clue_scrolls_medium": "Clues (Medium)",
    "clue_scrolls_hard": "Clues (Hard)",
    "clue_scrolls_elite": "Clues (Elite)",
    "clue_scrolls_master": "Clues (Master)",
    "last_man_standing": "Last Man Standing",
    "pvp_arena": "PvP Arena",
    "soul_wars_zeal": "Soul Wars Zeal",
    "guardians_of_the_rift": "Guardians of the Rift",
    "colosseum_glory": "Colosseum Glory",
    "collections_logged": "Collections Logged",
}


def _fmt(n) -> str:
    if n is None or (isinstance(n, (int, float)) and n == -1):
        return "—"
    return f"{int(n):,}"


def _snapshot(player: dict) -> dict:
    snap = player.get("latestSnapshot") or {}
    return snap.get("data") or {}


def _header(player: dict) -> None:
    name = player.get("displayName", player.get("username", "?"))
    ttype = player.get("type", "?")
    build = player.get("build", "?")
    exp = _fmt(player.get("exp"))
    ehp = player.get("ehp") or 0
    ehb = player.get("ehb") or 0
    cached = " [dim](cached)[/dim]" if player.get("_cached") else ""
    console.print(
        f"[bold cyan]{name}[/bold cyan]  "
        f"[dim]type={ttype} build={build} exp={exp} "
        f"ehp={ehp:.1f} ehb={ehb:.1f}[/dim]{cached}"
    )


def _skills_table(player: dict) -> Table:
    skills = _snapshot(player).get("skills", {})
    table = Table(title="Skills", header_style="bold magenta", expand=False)
    table.add_column("Skill", style="cyan")
    table.add_column("Level", justify="right")
    table.add_column("Experience", justify="right")
    table.add_column("Rank", justify="right", style="dim")

    for key in SKILL_ORDER:
        s = skills.get(key)
        if not s:
            continue
        name = key.capitalize() if key != "overall" else "[bold]Overall[/bold]"
        level = s.get("level", 0) or 0
        level_str = f"[bold green]{level}[/bold green]" if level >= 99 and key != "overall" else str(level)
        table.add_row(name, level_str, _fmt(s.get("experience")), _fmt(s.get("rank")))
    return table


def _activities_table(player: dict) -> Table:
    acts = _snapshot(player).get("activities", {})
    table = Table(title="Activities", header_style="bold magenta", expand=False)
    table.add_column("Activity", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Rank", justify="right", style="dim")

    rows = 0
    for key, a in acts.items():
        score = a.get("score")
        if score is None or score < 0:
            continue
        label = ACTIVITY_LABELS.get(key, key.replace("_", " ").title())
        table.add_row(label, _fmt(score), _fmt(a.get("rank")))
        rows += 1
    if rows == 0:
        table.add_row("[dim]no ranked activities[/dim]", "—", "—")
    return table


def _bosses_table(player: dict, top: int = 15) -> Table:
    bosses = _snapshot(player).get("bosses", {})
    ranked = [(k, b) for k, b in bosses.items() if (b.get("kills") or -1) > 0]
    ranked.sort(key=lambda kv: kv[1].get("kills", 0), reverse=True)
    ranked = ranked[:top]

    table = Table(title=f"Top {len(ranked)} Bosses", header_style="bold magenta", expand=False)
    table.add_column("Boss", style="cyan")
    table.add_column("Kills", justify="right")
    table.add_column("Rank", justify="right", style="dim")
    if not ranked:
        table.add_row("[dim]no ranked kills[/dim]", "—", "—")
    for key, b in ranked:
        label = key.replace("_", " ").title()
        table.add_row(label, _fmt(b.get("kills")), _fmt(b.get("rank")))
    return table


def _render_quests(data: dict, status: str = "all") -> None:
    quests = {k: v for k, v in (data.get("quests") or {}).items() if k != "."}
    total = len(quests)
    complete = sum(1 for v in quests.values() if v == 2)
    in_prog = sum(1 for v in quests.values() if v == 1)
    not_started = sum(1 for v in quests.values() if v == 0)

    cached = " [dim](cached)[/dim]" if data.get("_cached") else ""
    ts = data.get("timestamp", "?")
    console.print(
        f"[bold cyan]{data.get('username', '?')}[/bold cyan] quests  [dim]uploaded={ts}[/dim]{cached}"
    )
    console.print(
        f"[green]{complete}[/green] complete · "
        f"[yellow]{in_prog}[/yellow] in progress · "
        f"[dim]{not_started} not started[/dim] · "
        f"{total} total"
    )

    filters = {
        "all": lambda v: True,
        "complete": lambda v: v == 2,
        "in-progress": lambda v: v == 1,
        "not-started": lambda v: v == 0,
    }
    if status not in filters:
        raise ValueError(f"--status must be one of {list(filters)}")
    items = sorted((k, v) for k, v in quests.items() if filters[status](v))

    icons = {0: r"[dim]\[ ][/dim]", 1: r"[yellow]\[~][/yellow]", 2: r"[green]\[x][/green]"}
    table = Table(title=f"Quests ({status})", header_style="bold magenta", expand=False)
    table.add_column("", width=3)
    table.add_column("Quest", style="cyan")
    for name, v in items:
        table.add_row(icons.get(v, "?"), name)
    if not items:
        table.add_row("", "[dim]— none —[/dim]")
    console.print(table)


class OsrsCli:
    """osrs-cli — query Old School RuneScape players via the Wise Old Man API.

    Commands:
        stats <username>         Current skill levels + XP + ranks.
        activities <username>    Activity scores (clues, BH, LMS, GotR, ...).
        player <username>        Summary: skills + activities + top bosses.
        full <username>          Everything: skills + activities + all bosses + quests.
        quests <username>        Quest completion (requires WikiSync RuneLite plugin).
        clear-cache              Delete locally cached responses.

    Common flags:
        --force       Bypass local cache.
        --ttl N       Cache TTL in seconds (default 300).

    Example:
        osrs-cli player Cyberduck242
    """

    def stats(self, username: str, force: bool = False, ttl: int = api.CACHE_TTL_SECONDS):
        """Show a player's current skill levels, XP, and ranks."""
        player = client.get_player(username, force=force, ttl=ttl)
        _header(player)
        console.print(_skills_table(player))

    def activities(self, username: str, force: bool = False, ttl: int = api.CACHE_TTL_SECONDS):
        """Show a player's activity scores (clues, BH, LMS, GotR, etc.)."""
        player = client.get_player(username, force=force, ttl=ttl)
        _header(player)
        console.print(_activities_table(player))

    def player(self, username: str, force: bool = False, ttl: int = api.CACHE_TTL_SECONDS):
        """Full summary: skills, activities, and top bosses."""
        player = client.get_player(username, force=force, ttl=ttl)
        _header(player)
        console.print(_skills_table(player))
        console.print(_activities_table(player))
        console.print(_bosses_table(player))

    def full(self, username: str, force: bool = False, ttl: int = api.CACHE_TTL_SECONDS):
        """Everything: skills, activities, all bosses with kills, and quest completion.

        Quest data is best-effort — if the player has never run the WikiSync
        RuneLite plugin, quests are skipped with a note.
        """
        player = client.get_player(username, force=force, ttl=ttl)
        _header(player)
        console.print(_skills_table(player))
        console.print(_activities_table(player))
        console.print(_bosses_table(player, top=200))

        try:
            data = client.get_quests(username, force=force, ttl=ttl)
        except ValueError as e:
            console.print(f"[dim]Quests: {e}[/dim]")
            return
        _render_quests(data, status="all")

    def quests(
        self,
        username: str,
        status: str = "all",
        force: bool = False,
        ttl: int = api.CACHE_TTL_SECONDS,
    ):
        """Show quest completion (via WikiSync RuneLite plugin data).

        Args:
            username: OSRS display name.
            status: 'all', 'complete', 'in-progress', or 'not-started'.
            force: If True, bypass local cache.
            ttl: Cache TTL in seconds (default 300).
        """
        data = client.get_quests(username, force=force, ttl=ttl)
        _render_quests(data, status=status)

    def requirements(
        self,
        quest: str,
        force: bool = False,
        ttl: int = api.CACHE_TTL_SECONDS,
    ):
        """Show a quest's requirements (skill levels + prerequisite quests).

        Pulls from the OSRS Wiki. Quest name is matched against the wiki page
        title (redirects are followed), e.g. 'While Guthix Sleeps'.
        """
        data = client.get_quest_requirements(quest, force=force, ttl=ttl)
        cached = " [dim](cached)[/dim]" if data.get("_cached") else ""
        console.print(f"[bold cyan]{data['quest']}[/bold cyan]  [dim]{data['url']}[/dim]{cached}")

        skills = data.get("skills") or []
        quests = data.get("quests") or []
        other = data.get("other") or []

        if skills:
            t = Table(title="Skill requirements", header_style="bold magenta", expand=False)
            t.add_column("Requirement", style="cyan")
            for s in skills:
                t.add_row(s)
            console.print(t)
        if quests:
            t = Table(title="Quest prerequisites (direct)", header_style="bold magenta", expand=False)
            t.add_column("Quest", style="cyan")
            for q in quests:
                t.add_row(q)
            console.print(t)
        transitive = data.get("transitive_quests") or []
        if transitive:
            t = Table(
                title=f"Transitive prereqs ({len(transitive)})",
                header_style="bold magenta",
                expand=False,
            )
            t.add_column("Quest", style="dim")
            for q in transitive:
                t.add_row(q)
            console.print(t)
        if other:
            t = Table(title="Other", header_style="bold magenta", expand=False)
            t.add_column("Requirement", style="cyan")
            for o in other:
                t.add_row(o)
            console.print(t)
        if not (skills or quests or other):
            console.print("[dim]No parseable requirements found.[/dim]")

    def clear_cache(self):
        """Delete all locally cached player responses."""
        n = client.clear_cache()
        console.print(f"Cleared [bold]{n}[/bold] cached file(s).")


def main():
    try:
        fire.Fire(OsrsCli, name="osrs-cli")
    except api.RateLimitError as e:
        console.print(f"[bold red]Rate limit:[/bold red] {e}")
        raise SystemExit(2) from e
    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise SystemExit(1) from e
