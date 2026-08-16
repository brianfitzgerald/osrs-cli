from __future__ import annotations

import io
import json

import pytest
from rich.console import Console

import osrs_cli as cli
from osrs_cli.runelite import RuneLiteSnapshotStore


@pytest.fixture
def snapshot_data():
    return {
        "schema_version": 1,
        "updated_at": "2026-08-07T12:00:03Z",
        "account": {
            "username": "Cyberduck242",
            "account_hash": "1234",
            "profile_type": "STANDARD",
        },
        "session": {"logged_in": True},
        "containers": {
            "bank": {
                "observed_at": "2026-08-07T12:00:00Z",
                "items": [{"slot": 0, "id": 4151, "name": "Abyssal whip", "quantity": 1}],
            },
            "inventory": {
                "observed_at": "2026-08-07T12:00:01Z",
                "items": [{"slot": 4, "id": 385, "name": "Shark", "quantity": 12}],
            },
            "equipment": {
                "observed_at": "2026-08-07T12:00:02Z",
                "items": [
                    {
                        "slot": "weapon",
                        "slot_index": 3,
                        "id": 4151,
                        "name": "Abyssal whip",
                        "quantity": 1,
                    }
                ],
            },
        },
        "layouts": [
            {
                "name": "slayer",
                "source": "banktags",
                "items": [
                    {"slot": 0, "id": 4151, "name": "Abyssal whip"},
                    {"slot": 8, "id": 4151, "name": "Abyssal whip"},
                ],
            }
        ],
    }


@pytest.fixture
def snapshot_store(tmp_path, snapshot_data):
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "standard.json").write_text(json.dumps(snapshot_data))
    return RuneLiteSnapshotStore(snapshot_dir)


@pytest.fixture
def capture_console(monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr(cli, "console", Console(file=output, width=140, color_system=None))
    return output


def test_snapshot_store_selects_username_case_insensitively(snapshot_store):
    snapshot = snapshot_store.get_snapshot("cyberDUCK242")
    assert snapshot["account"]["profile_type"] == "STANDARD"


def test_snapshot_store_requires_profile_type_for_multiple_matches(tmp_path, snapshot_data):
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "standard.json").write_text(json.dumps(snapshot_data))
    seasonal = snapshot_data | {
        "account": snapshot_data["account"] | {"profile_type": "SEASONAL"},
    }
    (snapshot_dir / "seasonal.json").write_text(json.dumps(seasonal))
    store = RuneLiteSnapshotStore(snapshot_dir)

    with pytest.raises(ValueError, match="Multiple RuneLite snapshots"):
        store.get_snapshot("Cyberduck242")
    assert store.get_snapshot("Cyberduck242", "seasonal")["account"]["profile_type"] == "SEASONAL"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("not-json", "not valid JSON"),
        (json.dumps({"schema_version": 2}), "schema version 2"),
        (json.dumps({"schema_version": 1}), "account metadata"),
    ],
)
def test_snapshot_store_rejects_invalid_files(tmp_path, payload, message):
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "bad.json").write_text(payload)

    with pytest.raises(ValueError, match=message):
        RuneLiteSnapshotStore(snapshot_dir).list_snapshots()


def test_snapshot_store_missing_account_has_friendly_error(tmp_path):
    with pytest.raises(ValueError, match="Install OSRS CLI Exporter"):
        RuneLiteSnapshotStore(tmp_path).get_snapshot("Cyberduck242")


def test_runelite_bank_renders_items_and_status(snapshot_store, capture_console):
    cli.RuneliteCli(snapshot_store).bank("Cyberduck242")
    output = capture_console.getvalue()
    assert "Abyssal whip" in output
    assert "logged in" in output
    assert "2026-08-07T12:00:00Z" in output


def test_runelite_snapshot_renders_all_sections(snapshot_store, capture_console):
    cli.RuneliteCli(snapshot_store).snapshot("Cyberduck242")
    output = capture_console.getvalue()
    assert "Bank" in output
    assert "Inventory" in output
    assert "Equipment" in output
    assert "Named bank layouts" in output


@pytest.mark.parametrize("command", ["bank", "inventory", "gear", "layouts"])
def test_runelite_subcommands_emit_json(snapshot_store, capture_console, command):
    getattr(cli.RuneliteCli(snapshot_store), command)("Cyberduck242", json=True)
    assert '"observed_at"' in capture_console.getvalue() or '"source"' in capture_console.getvalue()


def test_runelite_container_requires_observed_data(tmp_path, snapshot_data):
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    snapshot_data["containers"]["bank"] = {"observed_at": None, "items": []}
    (snapshot_dir / "standard.json").write_text(json.dumps(snapshot_data))

    with pytest.raises(ValueError, match="not observed bank"):
        cli.RuneliteCli(RuneLiteSnapshotStore(snapshot_dir)).bank("Cyberduck242")


def test_runelite_list_renders_logged_out_snapshot(snapshot_store, snapshot_data, capture_console):
    snapshot_data["session"]["logged_in"] = False
    snapshot_store.snapshot_dir.joinpath("standard.json").write_text(json.dumps(snapshot_data))
    cli.RuneliteCli(snapshot_store).list()
    assert "logged out" in capture_console.getvalue()


def test_layout_duplicates_are_preserved(snapshot_store):
    layouts = snapshot_store.get_snapshot("Cyberduck242")["layouts"]
    assert [item["id"] for item in layouts[0]["items"]] == [4151, 4151]
