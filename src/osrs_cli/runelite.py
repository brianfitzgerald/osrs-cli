"""Read local snapshots written by the OSRS CLI Exporter RuneLite plugin."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_DIR = Path.home() / ".runelite" / "osrs-cli" / "snapshots"


class RuneLiteSnapshotStore:
    """Find and validate local RuneLite snapshots."""

    def __init__(self, snapshot_dir: Path | None = None) -> None:
        self.snapshot_dir = snapshot_dir if snapshot_dir is not None else SNAPSHOT_DIR

    def list_snapshots(self) -> list[dict[str, Any]]:
        """Return all valid snapshots in newest-first order."""
        if not self.snapshot_dir.exists():
            return []

        snapshots = []
        for path in self.snapshot_dir.glob("*.json"):
            snapshot = self._read(path)
            snapshots.append(snapshot)
        return sorted(snapshots, key=lambda value: value.get("updated_at") or "", reverse=True)

    def get_snapshot(self, username: str, profile_type: str | None = None) -> dict[str, Any]:
        """Return one snapshot selected by username and optional profile type."""
        username = username.strip()
        if not username:
            raise ValueError("RuneLite username cannot be empty.")

        matches = [
            snapshot
            for snapshot in self.list_snapshots()
            if (snapshot.get("account") or {}).get("username", "").casefold() == username.casefold()
        ]
        if profile_type is not None:
            matches = [
                snapshot
                for snapshot in matches
                if (snapshot.get("account") or {}).get("profile_type", "").casefold()
                == profile_type.casefold()
            ]

        if not matches:
            suffix = f" with profile type '{profile_type}'" if profile_type else ""
            raise ValueError(
                f"No RuneLite snapshot found for '{username}'{suffix}. "
                "Install OSRS CLI Exporter, log in, and open your bank once."
            )
        if len(matches) > 1:
            types = sorted(
                {(snapshot.get("account") or {}).get("profile_type", "unknown") for snapshot in matches}
            )
            raise ValueError(
                f"Multiple RuneLite snapshots found for '{username}': {', '.join(types)}. "
                "Select one with --profile-type."
            )
        return matches[0]

    def _read(self, path: Path) -> dict[str, Any]:
        try:
            snapshot = json.loads(path.read_text())
        except OSError as error:
            raise ValueError(f"Cannot read RuneLite snapshot '{path}': {error}") from error
        except json.JSONDecodeError as error:
            raise ValueError(f"RuneLite snapshot '{path}' is not valid JSON: {error}") from error

        if not isinstance(snapshot, dict):
            raise ValueError(f"RuneLite snapshot '{path}' must contain a JSON object.")
        version = snapshot.get("schema_version")
        if version != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(
                f"RuneLite snapshot '{path}' uses schema version {version}; "
                f"this CLI supports version {SNAPSHOT_SCHEMA_VERSION}."
            )
        account = snapshot.get("account")
        if not isinstance(account, dict) or not account.get("username") or not account.get("profile_type"):
            raise ValueError(f"RuneLite snapshot '{path}' has no valid account metadata.")
        if not isinstance(snapshot.get("containers"), dict):
            raise ValueError(f"RuneLite snapshot '{path}' has no container data.")
        if not isinstance(snapshot.get("layouts", []), list):
            raise ValueError(f"RuneLite snapshot '{path}' has invalid layout data.")
        return snapshot
