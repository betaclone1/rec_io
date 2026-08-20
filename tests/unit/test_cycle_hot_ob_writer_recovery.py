"""OB cycle writer recovery when packager drops tables in another process."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.core import cycle_hot_tables as cht


@pytest.fixture(autouse=True)
def _reset_writer_state():
    with cht._ddl_lock:
        cht._ensured_tables.clear()
        cht._ob_skip_tickers.clear()
    with cht._hot_lock:
        cht._hot_tickers.clear()
    yield
    with cht._ddl_lock:
        cht._ensured_tables.clear()
        cht._ob_skip_tickers.clear()
    with cht._hot_lock:
        cht._hot_tickers.clear()


def test_is_undefined_relation_detects_pgcode_and_message():
    class FakeUndef(Exception):
        pgcode = "42P01"

    assert cht._is_undefined_relation(FakeUndef("x"))
    assert cht._is_undefined_relation(
        Exception('relation "historical_data.FOO_deltas" does not exist')
    )
    assert not cht._is_undefined_relation(Exception("connection reset"))


def test_flush_delta_batch_skips_packaged_ticker_on_missing_table():
    mt = "KXBTC15M-26AUG201000-00"
    row = (mt, "yes", "0.50", "1.00", 1, None, "2026-08-20T14:21:00Z")
    conn = MagicMock()
    undef = Exception('relation "historical_data.KXBTC15M-26AUG201000-00_deltas" does not exist')
    undef.pgcode = "42P01"  # type: ignore[attr-defined]

    with patch.object(cht, "ensure_cycle_tables", return_value=cht.all_table_names(mt)):
        with patch.object(cht, "_insert_delta_group", side_effect=undef):
            with patch.object(cht, "_cycle_package_exists", return_value=True):
                cht._flush_delta_batch(conn, [row])

    assert cht._should_skip_ob_ticker(mt)
    # Second flush must not raise / must no-op for skipped ticker
    cht._flush_delta_batch(conn, [row])


def test_flush_delta_batch_recreates_when_not_packaged():
    mt = "KXBTC15M-26AUG201130-30"
    row = (mt, "yes", "0.40", "2.00", 2, None, "2026-08-20T15:17:00Z")
    conn = MagicMock()
    undef = Exception('relation "historical_data.KXBTC15M-26AUG201130-30_deltas" does not exist')
    undef.pgcode = "42P01"  # type: ignore[attr-defined]

    calls = {"n": 0}

    def _insert(_conn, _mt, _group):
        calls["n"] += 1
        if calls["n"] == 1:
            raise undef

    with patch.object(cht, "ensure_cycle_tables", return_value=cht.all_table_names(mt)) as ensure:
        with patch.object(cht, "_insert_delta_group", side_effect=_insert):
            with patch.object(cht, "_cycle_package_exists", return_value=False):
                cht._flush_delta_batch(conn, [row])

    assert calls["n"] == 2
    assert ensure.call_args_list[-1].kwargs.get("force") is True
    assert not cht._should_skip_ob_ticker(mt)


def test_enqueue_delta_respects_skip_set():
    mt = "KXBTC15M-26AUG201000-00"
    cht._mark_ob_skip_ticker(mt, "test")
    with patch.object(cht, "recorder_enabled", return_value=True):
        with patch.object(cht, "_get_ob_queue") as get_q:
            cht.enqueue_delta(mt, side="yes", price="0.5", delta="1", seq=1)
            get_q.assert_not_called()
