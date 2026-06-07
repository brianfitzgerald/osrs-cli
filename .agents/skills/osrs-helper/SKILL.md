---
name: osrs-helper
description: Plan an optimal path for an Old School RuneScape goal (finishing a quest, unlocking content, hitting a skill milestone) for a specific player. Use when the user asks what they should do next in OSRS, how to complete a quest, what's blocking them, or how to efficiently reach a goal. Pulls live player state and quest requirements via the `osrs-cli` tool in this repo.
---

# OSRS goal planner

You have access to the `osrs-cli` command in this repository, which reads live player data from Wise Old Man + WikiSync and quest requirements from the OSRS Wiki. Use it to answer "what should <player> do next to accomplish <goal>" — don't guess from memory when the CLI can give you ground truth.

## When to invoke this skill

Triggers: the user mentions an OSRS player name alongside a goal, asks what to do next, asks how to reach a quest/skill/diary/unlock, asks what's blocking them, or asks for an optimal ordering of content.

Do NOT invoke for questions that aren't about a specific player's progress (e.g. generic meta discussion, item prices, drop tables) — the CLI doesn't cover those.

## The CLI

All commands run with `uv run osrs-cli <...>` from the repo root. Cached for 300s under `~/.cache/osrs-cli/`; add `--force` to bypass, `--ttl N` to change. Rate-limited at 20 req/60s across all calls (WOM + WikiSync + Wiki).

| Command | Use it when |
|---|---|
| `stats <user>` | You need skill levels / XP only. |
| `activities <user>` | You need clue/minigame scores. |
| `player <user>` | Skills + activities + top 15 bosses (default go-to for a snapshot). |
| `full <user>` | Skills + activities + all bosses + every quest status. Use when goal depends on quest state. |
| `quests <user> [--status complete\|in-progress\|not-started\|all]` | Filter the quest log. |
| `requirements "<Quest Name>"` | Skill + quest prereqs for a specific quest (scraped from the wiki). Quote multi-word names. |
| `clear-cache` | Only if the user explicitly asks for a fresh fetch and `--force` isn't enough. |

Quest names are wiki page titles. Redirects are followed, so "Dragon Slayer 1" will resolve to "Dragon Slayer I", but prefer the canonical name.

## Recommended workflow

1. **Get current state.** If the goal touches quests or anything quest-gated, run `full <user>`. Otherwise `player <user>` is cheaper. Do this once up front — reuse the output rather than re-querying.
2. **Get the goal's requirements.** Run `requirements "<Goal Quest>"`. The output has three buckets: `Skill requirements`, `Quest prerequisites (direct)`, and `Transitive prereqs`. Direct prereqs are the ones listed at the top level of the quest's prereq tree on the wiki — they're what actually unlocks the target. Transitive prereqs are their dependencies.
3. **Expand unknown prereqs.** For each direct prereq the player hasn't completed, optionally run `requirements` again to surface its own skill requirements. Do this when you suspect a prereq has its own nasty wall (e.g. Desert Treasure I, Monkey Madness II). Stop expanding once you've covered every skill gate the player doesn't already clear — don't enumerate the whole tree.
4. **Diff player vs. requirements.**
   - Skills: `player level < required level` → gap, include the delta.
   - Quests: `quest status != 2` → not done. Status `1` = in progress, `0` = not started, `2` = complete. Flag in-progress quests as quick wins.
5. **Produce the plan.**

## What "optimal" means here

There's no single right ordering — be explicit about the tradeoff you're applying. Default heuristic:

1. **Finish in-progress quests first** — they're usually one or two steps from done.
2. **Prereq quests before their dependents** — obviously, but also prefer quests whose rewards feed the biggest skill gap (XP lamps, skill XP rewards). Call these out: e.g. "Defender of Varrock gives 20k Smithing, closes ~10% of that gap."
3. **Train skills in parallel with questing** when the training unlocks are quest rewards (ancient spellbook from Desert Treasure for Magic, Blast Furnace from Giant Dwarf for Smithing, blackjacking from The Feud for Thieving).
4. **Worst single grind last** — identify the tallest skill wall and save the raw training for after questing has chipped away at it.
5. **Do not recommend grinding a skill past what the goal needs** unless the user asked for efficiency across multiple goals.

## Presenting the plan

- Lead with a one-sentence summary of the biggest blocker.
- Show a skill-gap table (have → need → delta) for skills that don't clear.
- List direct quest prereqs with completion status. Mark in-progress ones as quick wins.
- Give a numbered ordering that interleaves quests with training milestones. Be concrete: name the quest, name the training method, name the unlock.
- If a quest reward materially closes a skill gap, say so with numbers.
- Don't dump the whole transitive prereq tree unless the user asks — summarize as "N transitive prereqs auto-covered by the direct ones above."

## Things to watch out for

- **WikiSync staleness.** Quest state comes from the RuneLite WikiSync plugin. If `uploaded=` in the `quests` output is days old, warn the user that quests completed since then won't show. Prefer the `uploaded` timestamp over WOM's snapshot time for quest-related answers.
- **Skill reqs from the wiki vs. what I remember.** The wiki infobox is the source of truth. If the CLI output conflicts with what you recall about a quest, trust the CLI — wiki values shift when Jagex reworks a quest.
- **Boostable skills.** The CLI does not currently distinguish boostable from non-boostable requirements. If a skill gap is small (≤4 levels), mention that it *may* be boostable (stew / spicy stew / dwarven rock cake / etc.) as a caveat rather than asserting it.
- **Combat / Quest-points aren't real skills.** The `Quest` row in the skill table from `requirements` is Quest Points. Surface it separately from skill levels — don't tell the user to "train Quest to 180."
- **Caching.** Don't re-run the same query inside one response. If you already have a player snapshot, reference it.

## Example interaction

User: "What's the fastest way for Cyberduck242 to finish Desert Treasure I?"

Good flow:
1. `uv run osrs-cli full Cyberduck242` → note skills + quest log.
2. `uv run osrs-cli requirements "Desert Treasure I"` → read required skills + direct prereqs.
3. For each direct prereq not yet complete, decide whether to expand (e.g. `requirements "Troll Stronghold"`) — usually only expand if you suspect a hidden skill wall.
4. Respond with: biggest blocker in one line, skill-gap table, ordered action list, and which prereqs are already done so the user isn't told to redo them.
