"""Minimal position-risk audit read API for local Stage 2."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

position_risk_router = APIRouter(tags=["position_risk"])


@position_risk_router.get("/api/position_risk/audit")
async def position_risk_audit(
    trade_id: int = Query(..., description="Trade id"),
    tenant_slot: Optional[str] = Query(None),
    limit: Optional[int] = Query(500, ge=1, le=5000),
):
    from backend.core.position_risk.audit import get_audit

    events = get_audit().query_by_trade_id(
        int(trade_id),
        tenant_slot=tenant_slot,
        limit=limit,
    )
    return {
        "status": "ok",
        "trade_id": int(trade_id),
        "tenant_slot": tenant_slot,
        "count": len(events),
        "events": events,
    }
