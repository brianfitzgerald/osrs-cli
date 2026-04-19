# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Package + env managed by `uv` (Python 3.14+).

- Run the CLI: `uv run osrs-cli <command> <username>` (e.g. `uv run osrs-cli player Cyberduck242`)
- Run all tests: `uv run pytest`
- Run a single test: `uv run pytest tests/test_api.py::test_name -q`
- Lint / autofix: `uv run ruff check --fix` and `uv run ruff format`
- Type check: `uv run ty check` (Astral's `ty`, configured to include `src` and `tests`)
- Pre-commit (runs ruff + ty): `uv run pre-commit run --all-files`

## Architecture

Two-module package in `src/osrs_cli/`:

- `api.py` — HTTP client layer. Wraps two upstream services:
  - Wise Old Man v2 (`api.wiseoldman.net`) for player skills/activities/bosses via `get_player`.
  - WikiSync (`sync.runescape.wiki`) for quest completion via `get_quests`. WikiSync data only exists for players who have run the RuneLite WikiSync plugin — a 404/400 surfaces as a `ValueError` with a user-facing message.
  - On-disk JSON cache under `~/.cache/osrs-cli/` (default TTL 300s; override with `--ttl`, bypass with `--force`). Cache files are keyed by a sanitized `{kind}_{username}` name.
  - Cross-invocation rate limiting: sliding window of 20 requests / 60s persisted in `~/.cache/osrs-cli/_rate.json`. Exceeding it raises `RateLimitError` before the HTTP call. `clear_cache()` deliberately skips `_rate.json`.
  - The `_cached` boolean is injected into returned dicts so the renderer can show a `(cached)` hint.

- `__init__.py` — CLI + presentation. `OsrsCli` is a [python-fire](https://github.com/google/python-fire) class; each public method becomes a subcommand. Rendering uses `rich` tables. `main()` is the `osrs-cli` console script entry point and maps `RateLimitError` → exit 2, `ValueError` → exit 1.
  - `SKILL_ORDER` defines the canonical display order (fire/cooking/etc.) — don't rely on dict iteration order from the API.
  - `ACTIVITY_LABELS` maps WOM snake_case activity keys to human labels; unknown keys fall back to title-cased keys.
  - Negative scores / `-1` ranks from WOM mean "unranked" and are filtered or rendered as `—` via `_fmt`.

## Testing notes

- `tests/conftest.py` sets a temporary `CACHE_DIR` and patches `requests` so tests never hit the network. When adding API tests, reuse that fixture rather than mocking `requests` ad-hoc.
