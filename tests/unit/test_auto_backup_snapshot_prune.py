"""Unit tests for DO snapshot prune helpers (no live API)."""

from __future__ import annotations

from datetime import datetime, timezone

from scripts.do import auto_backup_snapshot as ab


def test_parse_created_at_zulu():
    dt = ab._parse_created_at("2026-10-19T18:21:42Z")
    assert dt is not None
    assert dt == datetime(2026, 10, 19, 18, 21, 42, tzinfo=timezone.utc)


def test_pre_update_filter_and_age_cutoff(monkeypatch):
    snaps = [
        {
            "id": 1,
            "name": "rec-io-prod-pre-update-2026-10-19",
            "created_at": "2026-10-19T18:21:42Z",
        },
        {
            "id": 2,
            "name": "rec-io-prod-pre-update-2026-10-31",
            "created_at": "2026-10-31T22:16:55Z",
        },
        {
            "id": 3,
            "name": "auto_backup_2026-10-20_0100",
            "created_at": "2026-10-20T05:00:00Z",
        },
    ]
    assert [s["id"] for s in ab._pre_update_snapshots(snaps)] == [1, 2]

    deleted: list[int] = []

    monkeypatch.setattr(ab, "_list_droplet_snapshots", lambda _t: snaps)
    monkeypatch.setattr(
        ab, "_delete_snapshot", lambda _t, sid: deleted.append(int(sid))
    )

    now = datetime(2026, 10, 31, 20, 0, 0, tzinfo=timezone.utc)
    ab._prune_old_pre_update("tok", keep_days=7, dry_run=False, now=now)
    # 19th is >7 days before 31st; 31st is kept.
    assert deleted == [1]


def test_pre_update_dry_run_does_not_delete(monkeypatch):
    snaps = [
        {
            "id": 9,
            "name": "rec-io-prod-pre-update-2026-10-01",
            "created_at": "2026-10-01T12:00:00Z",
        }
    ]
    deleted: list[int] = []
    monkeypatch.setattr(ab, "_list_droplet_snapshots", lambda _t: snaps)
    monkeypatch.setattr(
        ab, "_delete_snapshot", lambda _t, sid: deleted.append(int(sid))
    )
    now = datetime(2026, 10, 31, tzinfo=timezone.utc)
    ab._prune_old_pre_update("tok", keep_days=7, dry_run=True, now=now)
    assert deleted == []
