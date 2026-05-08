"""Session-scoped user slot and MON_/numeric monitor id parsing for main_app routes."""

from typing import Optional

from fastapi import HTTPException

from backend.core.tenant_context import resolved_tenant_user_no_for_app


def session_user_number_from_optional_user_id(user_id: Optional[str]) -> str:
    """Authenticated tenant slot; optional ``user_id`` must match session (cross-tenant guard)."""
    slot = resolved_tenant_user_no_for_app()
    if user_id is None or not str(user_id).strip():
        return slot
    s = str(user_id).strip()
    low = s.lower()
    if low.startswith("user_"):
        s = s.split("_", 1)[-1]
    s = s.strip().zfill(4)
    if len(s) != 4 or not s.isdigit():
        raise HTTPException(status_code=400, detail="invalid user_id")
    if s != slot:
        raise HTTPException(status_code=403, detail="user_id does not match session")
    return s


def monitor_slot_and_db_id_from_monitor_id(
    monitor_id: str, body_user_id: Optional[str]
) -> tuple[str, str]:
    """
    Parse MON_/mon_ / numeric monitor id. Numeric id uses session slot.
    Embedded tenant in prefixed ids must match session.
    """
    slot = session_user_number_from_optional_user_id(body_user_id)
    mid = str(monitor_id).strip()
    if (mid.startswith("MON_") or mid.startswith("mon_")) and "_" in mid:
        parts = mid.split("_")
        if len(parts) >= 3:
            un = parts[1].strip().zfill(4)
            db_id = parts[2].strip()
            if len(un) != 4 or not un.isdigit() or not db_id.isdigit():
                raise HTTPException(status_code=400, detail="Invalid monitor ID format")
            if un != slot:
                raise HTTPException(
                    status_code=403, detail="monitor_id tenant does not match session"
                )
            return un, db_id
        raise HTTPException(status_code=400, detail="Invalid monitor ID format")
    if mid.isdigit():
        return slot, mid
    raise HTTPException(status_code=400, detail="Invalid monitor ID format")
