#!/usr/bin/env python3
"""Tests for flip-sell execution in active_trade_supervisor (strict monitor booleans)."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

os.environ.setdefault("REC_USER_NO", "0001")

# active_trade_supervisor reads argv[0] for monitor id at import time.
if not sys.argv or not sys.argv[0].endswith("active_trade_supervisor.py"):
    sys.argv = ["active_trade_supervisor.py", "0001_10036"] + sys.argv[1:]

from backend.active_trade_supervisor import (
    parse_flip_sell_multiplier,
    _ats_monitor_flip_boolean_strictly_true,
    trigger_flip_sell_open_after_auto_stop,
)


class TestFlipSellMultiplier(unittest.TestCase):
    def test_parse_variants(self):
        self.assertEqual(parse_flip_sell_multiplier(None), 1.0)
        self.assertEqual(parse_flip_sell_multiplier(""), 1.0)
        self.assertEqual(parse_flip_sell_multiplier("1"), 1.0)
        self.assertEqual(parse_flip_sell_multiplier("2"), 2.0)
        self.assertEqual(parse_flip_sell_multiplier("3x"), 3.0)
        self.assertEqual(parse_flip_sell_multiplier("  1.5x "), 1.5)
        self.assertEqual(parse_flip_sell_multiplier("bad"), 1.0)
        self.assertEqual(parse_flip_sell_multiplier("-1"), 1.0)


class TestFlipSellStrictBoolean(unittest.TestCase):
    def test_only_python_true_enables(self):
        self.assertTrue(_ats_monitor_flip_boolean_strictly_true(True))
        self.assertFalse(_ats_monitor_flip_boolean_strictly_true(False))
        self.assertFalse(_ats_monitor_flip_boolean_strictly_true(None))
        self.assertFalse(_ats_monitor_flip_boolean_strictly_true(1))
        self.assertFalse(_ats_monitor_flip_boolean_strictly_true("true"))


class TestTriggerFlipSellOpen(unittest.TestCase):
    def setUp(self):
        self.trade = {
            "trade_id": 42,
            "ticker": "KXBTC15M-TEST",
            "strike": "95000",
            "side": "Y",
            "position": 1000,
            "contract": "BTC 15m",
            "monitor": "mon_0001_10036",
            "current_close_price": 0.42,
            "current_symbol_price": 95100.0,
            "current_probability": 35.0,
            "diff": None,
        }

    @patch("backend.active_trade_supervisor.ATS_UNIFIED_POOL", False)
    @patch("backend.active_trade_supervisor.ATS_HTTP_FALLBACK_ENABLED", True)
    @patch("backend.active_trade_supervisor.scoped_trade_manager_http_port", return_value=9999)
    @patch("backend.active_trade_supervisor.get_service_url", return_value="http://localhost")
    @patch("backend.active_trade_supervisor.evaluate_pipeline_gate_conn", return_value=(True, "ok"))
    @patch("backend.active_trade_supervisor.get_current_monitor_symbol", return_value="BTC")
    @patch("backend.active_trade_supervisor.get_trade_strategy", return_value="Hourly HTC")
    @patch("backend.active_trade_supervisor._ats_get_bankroll_allotment", return_value=1000.0)
    @patch("backend.active_trade_supervisor._ats_get_paper_trade_from_monitor", return_value=False)
    @patch("backend.active_trade_supervisor._ats_get_multiplier_from_monitor", return_value=1.0)
    @patch(
        "backend.active_trade_supervisor._ats_flip_sell_position_after_loss_prevention",
        side_effect=lambda c: (c, False),
    )
    @patch("backend.active_trade_supervisor._ats_trade_log_entry_method", return_value="auto_entry")
    @patch("backend.active_trade_supervisor._ats_fetch_flip_sell_monitor_row")
    @patch("backend.active_trade_supervisor.ctx_user", return_value="0001")
    @patch("backend.active_trade_supervisor.ctx_mid", return_value="10036")
    @patch("backend.active_trade_supervisor.publish_trade_manager_command", return_value=False)
    @patch("backend.active_trade_supervisor.requests.post")
    @patch("backend.active_trade_supervisor.get_db_connection")
    def test_flip_floor_true_sends_open(
        self,
        mock_db,
        mock_post,
        mock_pub,
        mock_fetch,
        *_patches,
    ):
        mock_fetch.return_value = (False, "1x", True, "2x", False)

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": 99}
        mock_post.return_value = mock_resp

        mock_conn = MagicMock()
        mock_db.return_value = mock_conn

        ok = trigger_flip_sell_open_after_auto_stop(
            self.trade, "stop_loss_floor", 1000, "N"
        )
        self.assertTrue(ok)
        mock_post.assert_called_once()
        body = mock_post.call_args[1]["json"]
        self.assertEqual(body.get("entry_method"), "flip_sell")
        self.assertEqual(body.get("side"), "N")
        self.assertEqual(body.get("position"), 2000)

    @patch("backend.active_trade_supervisor._ats_fetch_flip_sell_monitor_row")
    @patch("backend.active_trade_supervisor.ctx_user", return_value="0001")
    @patch("backend.active_trade_supervisor.ctx_mid", return_value="10036")
    def test_flip_floor_not_true_never_posts(self, mock_fetch, *_):
        mock_fetch.return_value = (False, "1x", False, "2x", False)
        ok = trigger_flip_sell_open_after_auto_stop(
            self.trade, "stop_loss_floor", 1000, "N"
        )
        self.assertFalse(ok)

    @patch("backend.active_trade_supervisor._ats_fetch_flip_sell_monitor_row")
    @patch("backend.active_trade_supervisor.ctx_user", return_value="0001")
    @patch("backend.active_trade_supervisor.ctx_mid", return_value="10036")
    def test_prob_stop_requires_flip_prob_true(self, mock_fetch, *_):
        mock_fetch.return_value = (False, "2x", True, "2x", False)
        ok = trigger_flip_sell_open_after_auto_stop(
            self.trade, "probability_auto_stop", 1000, "N"
        )
        self.assertFalse(ok)

    @patch("backend.active_trade_supervisor._ats_fetch_flip_sell_monitor_row")
    @patch("backend.active_trade_supervisor.ctx_user", return_value="0001")
    @patch("backend.active_trade_supervisor.ctx_mid", return_value="10036")
    def test_wrong_trigger_never_posts(self, mock_fetch, *_):
        mock_fetch.return_value = (True, "2x", True, "2x", False)
        ok = trigger_flip_sell_open_after_auto_stop(
            self.trade, "momentum_spike", 1000, "N"
        )
        self.assertFalse(ok)

    @patch("backend.active_trade_supervisor._ats_trade_log_entry_method", return_value="flip_sell")
    @patch("backend.active_trade_supervisor._ats_fetch_flip_sell_monitor_row")
    @patch("backend.active_trade_supervisor.ctx_user", return_value="0001")
    @patch("backend.active_trade_supervisor.ctx_mid", return_value="10036")
    def test_existing_flip_sell_entry_skips(self, mock_fetch, *_):
        mock_fetch.return_value = (False, "1x", True, "1x", False)
        ok = trigger_flip_sell_open_after_auto_stop(
            self.trade, "stop_loss_floor", 1000, "N"
        )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
