"""
Opt-in tradeflow decision diagnostics (Stage 0).

When enabled, emits structured ``[TRADEFLOW TRACE]`` log lines for AES/ATS
comparison across hosts. Does not change gate outcomes or submit/close paths.

Enable with ``TRADEFLOW_DECISION_TRACE=1`` (or true/yes/on).
Verbose strike-level gate failures: ``TRADEFLOW_DECISION_TRACE_VERBOSE=1``.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any, Callable, Dict, Optional

_LogFn = Callable[[str], None]

_lock = threading.Lock()
_pass_seq = 0
_pass_id: Optional[str] = None
_pass_t0: float = 0.0
_logger: Optional[_LogFn] = None


def decision_trace_enabled() -> bool:
    return os.getenv("TRADEFLOW_DECISION_TRACE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def decision_trace_verbose() -> bool:
    if not decision_trace_enabled():
        return False
    return os.getenv("TRADEFLOW_DECISION_TRACE_VERBOSE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def set_trace_logger(fn: Optional[_LogFn]) -> None:
    """AES/ATS bind their process log() so traces land in the same files."""
    global _logger
    _logger = fn


def _emit(line: str) -> None:
    if not decision_trace_enabled():
        return
    fn = _logger
    if fn is not None:
        try:
            fn(line)
            return
        except Exception:
            pass
    try:
        import logging

        logging.getLogger("tradeflow_decision_trace").info(line)
    except Exception:
        pass


def begin_pass(*, service: str = "aes") -> str:
    """Start a unified evaluation pass; returns pass_id for correlation."""
    global _pass_seq, _pass_id, _pass_t0
    if not decision_trace_enabled():
        return ""
    with _lock:
        _pass_seq += 1
        _pass_id = f"{service}-{_pass_seq}-{int(time.time() * 1000)}"
        _pass_t0 = time.perf_counter()
        pid = _pass_id
    _emit(f"[TRADEFLOW TRACE] pass_begin service={service} pass_id={pid}")
    return pid


def end_pass(**extra: Any) -> None:
    global _pass_id, _pass_t0
    if not decision_trace_enabled():
        return
    with _lock:
        pid = _pass_id
        t0 = _pass_t0
        _pass_id = None
        _pass_t0 = 0.0
    elapsed = (time.perf_counter() - t0) if t0 else 0.0
    bits = " ".join(f"{k}={_fmt(v)}" for k, v in extra.items())
    _emit(
        f"[TRADEFLOW TRACE] pass_end pass_id={pid or '-'} elapsed_s={elapsed:.3f}"
        + (f" {bits}" if bits else "")
    )


def current_pass_id() -> str:
    with _lock:
        return _pass_id or ""


def ladder_identity(snap: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Stable-enough identity fields for comparing the same evaluate across hosts."""
    if not snap or not isinstance(snap, dict):
        return {"ok": False}
    strikes = snap.get("strikes") or []
    if not isinstance(strikes, list):
        strikes = []
    digest = hashlib.sha1()
    for row in strikes[:64]:
        if not isinstance(row, dict):
            continue
        digest.update(
            f"{row.get('ticker')}|{row.get('yes_ask_dollars')}|{row.get('no_ask_dollars')}|"
            f"{row.get('probability')}|{row.get('active_side')}\n".encode("utf-8", errors="replace")
        )
    return {
        "ok": True,
        "event_ticker": snap.get("event_ticker"),
        "ttc": snap.get("ttc") if snap.get("ttc") is not None else snap.get("ttc_seconds"),
        "ttc_15m": snap.get("ttc_15m"),
        "strike_n": len(strikes),
        "generation_id": snap.get("generation_id"),
        "asks_sha1": digest.hexdigest()[:12],
    }


def ladder_identity_with_envelope(
    *,
    exchange: str,
    symbol: str,
    market: str,
    snap: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    ident = ladder_identity(snap)
    try:
        from backend.core import live_state_cache
        from backend.core.live_state_cache import cache_age_sec

        env = live_state_cache.get_strike_ladder(exchange, market, symbol)
        if env:
            ident["envelope_updated_at"] = env.get("updated_at")
            ident["envelope_age_s"] = round(cache_age_sec(env), 3)
            data = env.get("data") if isinstance(env.get("data"), dict) else {}
            if data.get("generation_id") and not ident.get("generation_id"):
                ident["generation_id"] = data.get("generation_id")
    except Exception:
        pass
    return ident


def trace(kind: str, **fields: Any) -> None:
    if not decision_trace_enabled():
        return
    pid = current_pass_id()
    parts = [f"[TRADEFLOW TRACE] {kind}"]
    if pid:
        parts.append(f"pass_id={pid}")
    for k, v in fields.items():
        parts.append(f"{k}={_fmt(v)}")
    _emit(" ".join(parts))


def trace_verbose(kind: str, **fields: Any) -> None:
    if decision_trace_verbose():
        trace(kind, **fields)


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.4g}"
    if isinstance(v, (dict, list)):
        try:
            return json.dumps(v, separators=(",", ":"), default=str)
        except Exception:
            return str(v)
    s = str(v)
    if " " in s or "=" in s:
        return json.dumps(s)
    return s
