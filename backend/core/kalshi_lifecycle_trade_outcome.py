"""
Apply Kalshi ``market_lifecycle_v2`` outcomes to ``users.trades_0001``.

``market_result`` (normalized yes/no) is written from WebSocket ``determined`` / ``settled``
messages with a ``result`` field. Expired trades are finalized in ``trade_manager`` from
``market_result`` and ``side`` (not from settlement polling).

See https://docs.kalshi.com/websockets/market-&-event-lifecycle
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Optional

from backend.core.kalshi_event_market_fetch import normalize_market_result_field

logger = logging.getLogger(__name__)


def strike_display_from_floor_strike(floor_strike: Any) -> str:
    """Match ``market_watchdog.format_15m_strike_from_api_floor_strike`` for WS strike column."""
    if floor_strike is None:
        return ""
    try:
        d = Decimal(str(floor_strike))
    except Exception:
        return ""
    if d == d.to_integral_value():
        v = int(d)
        if abs(v) >= 1000:
            return f"${v:,}"
        return f"${v}"
    s = format(d.normalize(), "f")
    return f"${s}"


def _normalize_win_loss_for_confirm(actual) -> Optional[str]:
    if actual is None:
        return None
    a = str(actual).strip().upper()
    if not a:
        return None
    if a in ("D", "DRAW", "TIE", "PUSH"):
        return None
    if a[0] == "W":
        return "W"
    if a[0] == "L":
        return "L"
    if a in ("1", "TRUE", "YES"):
        return "W"
    if a in ("0", "FALSE", "NO"):
        return "L"
    return None


def _expected_win_loss_from_kalshi_yes_no(side, outcome_yes_no: Optional[str]) -> Optional[str]:
    if not outcome_yes_no:
        return None
    o = str(outcome_yes_no).strip().lower()
    if o not in ("yes", "no"):
        return None
    su = str(side or "").strip().upper()
    if su in ("Y", "YES"):
        return "W" if o == "yes" else "L"
    if su in ("N", "NO"):
        return "W" if o == "no" else "L"
    return None


def compute_win_loss_confirmed_from_venue(
    side, market_result_yes_no: Optional[str], win_loss_actual
) -> Optional[bool]:
    """Compare venue ``market_result`` (+ ``side``) to recorded ``win_loss``.

    Expected W/L from Kalshi yes/no resolution vs our recorded W/L; ``None`` if not comparable
    (missing field, draw, unknown side). ``symbol_expiration`` is not used.
    """
    exp = _expected_win_loss_from_kalshi_yes_no(side, market_result_yes_no)
    act = _normalize_win_loss_for_confirm(win_loss_actual)
    if exp is None or act is None:
        return None
    return exp == act


def expiry_win_loss_from_market_result(side, market_result_yes_no: Optional[str]) -> Optional[str]:
    """Binary W/L for a held-to-expiration contract from venue yes/no and our ``side``."""
    return _expected_win_loss_from_kalshi_yes_no(side, market_result_yes_no)


def apply_lifecycle_market_result_for_ticker(market_ticker: str, result_raw: Any) -> int:
    """
    For all active and finalized rows on this Kalshi market ticker, set ``market_result``.

    Kalshi often emits ``determined``/``settled`` while our row is still ``open`` (held to expiry).
    If we only updated ``expired``/``closed``, we would miss the event and later prune the ticker
    from the lifecycle subscription before the row transitions off ``open``.

    When ``win_loss`` is already recorded, sets ``win_loss_confirmed`` from venue ``market_result``
    + ``side`` vs ``win_loss`` (not from ``symbol_expiration``). Mismatch is logged.
    Returns number of trade rows updated for ``market_result``.
    """
    bin_out = normalize_market_result_field(result_raw)
    if bin_out is None:
        return 0
    mt = str(market_ticker).strip()
    if not mt:
        return 0

    from backend.core.config.database import get_postgresql_connection

    conn = get_postgresql_connection()
    if not conn:
        logger.warning("lifecycle outcome: no DB connection for ticker=%s", mt)
        return 0
    n = 0
    trade_log_targets: list[tuple[str, int]] = []
    expired_to_finalize: list[int] = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, ticket_id, side, win_loss, win_loss_confirmed, status
                FROM users.trades_0001
                WHERE ticker = %s
                  AND status IN ('open', 'closing', 'close_failed', 'expired', 'closed')
                """,
                (mt,),
            )
            rows = cur.fetchall()
            for trade_id, ticket_id, side, wl, wlc, status in rows:
                cur.execute(
                    """
                    UPDATE users.trades_0001
                    SET market_result = %s
                    WHERE id = %s
                      AND status IN ('open', 'closing', 'close_failed', 'expired', 'closed')
                    """,
                    (bin_out, trade_id),
                )
                if cur.rowcount:
                    n += 1
                    tid_key = str(ticket_id).strip() if ticket_id else ""
                    if not tid_key:
                        tid_key = f"trade_{trade_id}"
                    trade_log_targets.append((tid_key, trade_id))
                    if status == "expired":
                        expired_to_finalize.append(int(trade_id))
                wlc_new = compute_win_loss_confirmed_from_venue(side, bin_out, wl)
                if wlc_new is not None:
                    cur.execute(
                        """
                        UPDATE users.trades_0001
                        SET win_loss_confirmed = %s
                        WHERE id = %s
                        """,
                        (wlc_new, trade_id),
                    )
                    if not wlc_new:
                        logger.warning(
                            "[OUTCOME_MISMATCH] %s",
                            json.dumps(
                                {
                                    "trade_id": trade_id,
                                    "ticker": mt,
                                    "source": "lifecycle_ws",
                                    "outcome": bin_out,
                                    "side": side,
                                    "win_loss": wl,
                                    "win_loss_confirmed_before": wlc,
                                },
                                default=str,
                            ),
                        )
        conn.commit()
    except Exception as e:
        logger.exception("lifecycle outcome apply failed ticker=%s: %s", mt, e)
        try:
            conn.rollback()
        except Exception:
            pass
        trade_log_targets.clear()
        expired_to_finalize.clear()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    for eid in expired_to_finalize:
        try:
            import backend.trade_manager as tm

            tm.finalize_expired_trade_from_market_result(eid)
        except Exception as fin_exc:
            logger.warning(
                "finalize expired trade after lifecycle failed trade_id=%s ticker=%s: %s",
                eid,
                mt,
                fin_exc,
            )
    if n:
        logger.info(
            "lifecycle_ws: market_result=%s applied to %s trade row(s) ticker=%s",
            bin_out,
            n,
            mt,
        )
        if trade_log_targets:
            try:
                from backend.util.trade_logger import log_trade_event

                for tid_key, trade_id in trade_log_targets:
                    log_trade_event(
                        tid_key,
                        f"Venue market_result={bin_out} (Kalshi lifecycle_ws) ticker={mt} trade_id={trade_id}",
                        service="market_watchdog_ws",
                    )
            except Exception as log_exc:
                logger.warning(
                    "trade_logs write after lifecycle outcome failed ticker=%s: %s",
                    mt,
                    log_exc,
                )
    return n
