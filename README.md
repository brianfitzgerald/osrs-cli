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
uv run osrs-cli clear-cache
```

Responses are cached under `~/.cache/osrs-cli/` for 5 minutes by default.
