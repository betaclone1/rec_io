"""HTTP for Kalshi cfbenchmarks_value experiment (read-only Redis snapshots)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

cfbenchmarks_experiment_router = APIRouter(
    prefix="/api/experiment/cfbenchmarks",
    tags=["cfbenchmarks_experiment"],
)


@cfbenchmarks_experiment_router.get("/status")
async def cfbenchmarks_status(index_id: str = Query(default=None)):
    from backend.core.cfbenchmarks_feed_cache import DEFAULT_INDEX_IDS_CSV

    raw = (index_id or DEFAULT_INDEX_IDS_CSV).strip()
    from backend.core.cfbenchmarks_feed_cache import build_status, build_status_all, parse_index_ids

    if "," in raw or raw.upper() in ("ALL", "*"):
        return JSONResponse(build_status_all(parse_index_ids(raw)))
    return JSONResponse(build_status(raw))


@cfbenchmarks_experiment_router.get("/recent")
async def cfbenchmarks_recent(
    index_id: str = Query(default="BRTI"),
    limit: int = Query(default=50, ge=1, le=200),
):
    from backend.core.cfbenchmarks_feed_cache import get_recent

    return JSONResponse(
        {
            "index_id": (index_id or "BRTI").strip().upper(),
            "ticks": get_recent(index_id, limit=limit),
        }
    )
