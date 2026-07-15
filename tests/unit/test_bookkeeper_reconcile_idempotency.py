"""Idempotency guard: only bookkeeper reconcile JEs on the target date match."""

from __future__ import annotations

import backend.bookkeeper.bookkeeper as bk
from backend.bookkeeper.kalshi_reconcile_credits import RECONCILE_NOTE_MARKER


class _Cfg:
    environment = "production"
    realm_id = "123"


def test_existing_reconcile_je_ids_matches_marker_only(monkeypatch) -> None:
    captured = {}

    def fake_query(cfg, access, query, **kwargs):
        captured["query"] = query
        return {
            "QueryResponse": {
                "JournalEntry": [
                    {"Id": "10", "PrivateNote": f"{RECONCILE_NOTE_MARKER} — gap $1.00"},
                    {"Id": "11", "PrivateNote": "Manual adjustment by operator"},
                    {"Id": "12", "PrivateNote": None},
                ]
            }
        }

    monkeypatch.setattr(bk, "run_report_query", fake_query)
    ids = bk.existing_reconcile_je_ids(_Cfg(), "tok", "2026-07-14")
    assert ids == ["10"]
    assert "TxnDate = '2026-07-14'" in captured["query"]


def test_existing_reconcile_je_ids_empty_when_none(monkeypatch) -> None:
    monkeypatch.setattr(
        bk, "run_report_query", lambda *a, **k: {"QueryResponse": {}}
    )
    assert bk.existing_reconcile_je_ids(_Cfg(), "tok", "2026-07-14") == []


def test_existing_reconcile_je_ids_handles_single_dict(monkeypatch) -> None:
    monkeypatch.setattr(
        bk,
        "run_report_query",
        lambda *a, **k: {
            "QueryResponse": {
                "JournalEntry": {
                    "Id": "99",
                    "PrivateNote": f"{RECONCILE_NOTE_MARKER} — gap $0.00; interest $4.90",
                }
            }
        },
    )
    assert bk.existing_reconcile_je_ids(_Cfg(), "tok", "2026-07-14") == ["99"]
