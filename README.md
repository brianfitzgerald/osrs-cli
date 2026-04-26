# osrs-cli

A CLI for querying Old School RuneScape player data via the
[Wise Old Man](https://docs.wiseoldman.net/api) and [WikiSync](https://sync.runescape.wiki/) APIs.

Designed to be used with LLMs / agent harnesses.

## Commands

| Command | Description |
|---|---|
| `stats <username>` | Current skill levels, XP, and ranks. |
| `activities <username>` | Activity scores (clues, BH, LMS, GotR, etc.). |
| `player <username>` | Summary: skills + activities + top bosses. |
| `full <username>` | Everything: skills + activities + all bosses + quests. |
| `quests <username>` | Quest completion (via WikiSync). `--status all\|complete\|in-progress\|not-started`. |
| `requirements "<quest>"` | Skill + quest prerequisites for a quest, scraped from the OSRS Wiki. |
| `wiki "<page title>"` | Fetch an OSRS Wiki page and render its content as markdown. |
| `clear-cache` | Delete locally cached API responses. |

> **Quests note:** the OSRS hiscores don't expose quest completion, so Wise Old
> Man can't provide it. `quests` instead hits
> [WikiSync](https://sync.runescape.wiki/) (`sync.runescape.wiki`), which is fed
> by the RuneLite WikiSync plugin. A player must have run the
> plugin at least once for data to exist.

### Flags (query commands)

- `--force` — bypass the local cache and hit the API.
- `--ttl N` — override cache TTL in seconds (default `300`).

### Help

```sh
uv run osrs-cli --help
uv run osrs-cli stats --help
```

## Examples

```sh
uv run osrs-cli stats Cyberduck242
uv run osrs-cli activities Cyberduck242
uv run osrs-cli player Cyberduck242 --force
uv run osrs-cli requirements "While Guthix Sleeps"
uv run osrs-cli wiki "Tormented Demon"
uv run osrs-cli clear-cache
```

Responses are cached under `~/.cache/osrs-cli/` for 5 minutes by default.

### Wiki page rendering

`wiki` pulls the page wikitext via the OSRS Wiki MediaWiki API and converts it
to markdown: headings, bold/italic, bullet/numbered lists, wiki + external
links, and `{| ... |}` tables. Templates (`{{...}}`) and file embeds are
stripped, with the `{{SCP|Skill|Level}}` skill-check template rendered as
`Level Skill`. `colspan` / `rowspan` are expanded into trailing empty cells in
the same row and blank cells in subsequent rows respectively (markdown can't
represent merged cells, but expansion preserves column alignment).
