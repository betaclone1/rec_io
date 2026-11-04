"""Lower Tail wakes on fills only — not orderbook/tradeflow live_state."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import backend.lower_tail_agent as lt


def test_start_listeners_does_not_subscribe_tradeflow_ob():
    started = {"tradeflow": False, "positions": False}

    def _fake_tradeflow(*_a, **_k):
        started["tradeflow"] = True
        return True

    fake_redis = MagicMock()
    fake_pubsub = MagicMock()
    fake_redis.pubsub.return_value = fake_pubsub
    fake_pubsub.get_message.side_effect = KeyboardInterrupt  # stop worker quickly

    with (
        patch(
            "backend.core.tradeflow_live_state_trigger.start_tradeflow_live_state_listener",
            side_effect=_fake_tradeflow,
        ),
        patch(
            "backend.core.trading_redis_comms.redis_client_optional",
            return_value=fake_redis,
        ),
        patch(
            "backend.core.trading_redis_comms.channel_tm_positions_updated",
            return_value="rec_io:tm:positions_updated:test",
        ),
        patch.object(lt.threading, "Thread") as thread_cls,
    ):
        # Thread should still be constructed for positions worker only.
        lt._start_listeners()
        assert started["tradeflow"] is False
        assert thread_cls.call_count == 1
        kwargs = thread_cls.call_args.kwargs
        assert kwargs.get("name") == "lt_positions_wake"
