"""
Server-side monitor id allocation: numeric ids must start with the last digit of ``user_no``
(e.g. user ``0001`` → ids ``10002``, ``19999``; user ``0004`` → ``40017``).

Use :func:`allocate_next_monitor_id` from API / monitor creation paths only.
"""

from __future__ import annotations

from backend.core.tenant_context import TenantContext, get_api_tenant_context


def _lead_digit(user_no: str) -> str:
    if not user_no or not user_no.isdigit():
        raise ValueError("user_no must be numeric")
    return user_no[-1]


def allocate_next_monitor_id(conn, tenant_user_no: str) -> int:
    """
    Return the next monitor_list id for this tenant, enforcing the leading-digit rule.
    ``conn`` must already be scoped to this tenant (e.g. via get_postgresql_tenant_connection).
    """
    ctx = get_api_tenant_context(tenant_user_no)
    return allocate_next_monitor_id_for_context(conn, ctx)


def allocate_next_monitor_id_for_context(conn, ctx: TenantContext) -> int:
    lead = _lead_digit(ctx.user_no)
    ml = ctx.ut("monitor_list")
    pattern = f"{lead}%"
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COALESCE(MAX(id), 0) FROM {ml} WHERE CAST(id AS TEXT) LIKE %s",
            (pattern,),
        )
        row = cur.fetchone()
        mx = int(row[0]) if row and row[0] is not None else 0
    if mx == 0:
        seed = int(f"{lead}0001")
        return seed
    nxt = mx + 1
    if not str(nxt).startswith(lead):
        raise RuntimeError(
            f"monitor id overflow for user_no={ctx.user_no}: max={mx}, cannot increment in band {lead}*"
        )
    return nxt
