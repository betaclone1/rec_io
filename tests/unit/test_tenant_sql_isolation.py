"""Unit tests for tenant SQL isolation (no cross-tenant schema tokens on TenantConnection)."""

from __future__ import annotations

import pytest

from backend.core.tenant_context import (
    TenantContext,
    TenantIsolationError,
    assert_sql_and_params_target_only_connection_tenant,
    rewrite_users_qualified_sql,
)
from backend.core.tenant_legacy_sql import legacy_users_trades


@pytest.fixture
def ctx_0001() -> TenantContext:
    return TenantContext.from_schema("users_0001")


def test_assert_allows_own_schema(ctx_0001: TenantContext) -> None:
    assert_sql_and_params_target_only_connection_tenant(
        'SELECT 1 FROM users_0001.trades_0001 WHERE x = 1',
        ctx_0001,
        None,
    )


def test_assert_rejects_alien_schema(ctx_0001: TenantContext) -> None:
    with pytest.raises(TenantIsolationError, match="users_0002"):
        assert_sql_and_params_target_only_connection_tenant(
            "SELECT 1 FROM users_0002.trades_0002",
            ctx_0001,
            None,
        )


def test_assert_rejects_legacy_users_dot(ctx_0001: TenantContext) -> None:
    legacy_trades = legacy_users_trades(ctx_0001.user_no)
    with pytest.raises(TenantIsolationError, match="legacy"):
        assert_sql_and_params_target_only_connection_tenant(
            f"SELECT 1 FROM {legacy_trades}",
            ctx_0001,
            None,
        )


def test_rewrite_then_assert_ok(ctx_0001: TenantContext) -> None:
    legacy_trades = legacy_users_trades(ctx_0001.user_no)
    q = rewrite_users_qualified_sql(
        f"SELECT 1 FROM {legacy_trades}",
        ctx_0001,
    )
    assert "users_0001" in q
    assert "users." not in q
    assert_sql_and_params_target_only_connection_tenant(q, ctx_0001, None)


def test_param_rejects_qualified_alien_schema(ctx_0001: TenantContext) -> None:
    with pytest.raises(TenantIsolationError, match="bind parameter"):
        assert_sql_and_params_target_only_connection_tenant(
            "SELECT to_regclass(%s)",
            ctx_0001,
            ("users_0002.trades_0002",),
        )


def test_param_allows_prose_mention_other_user(ctx_0001: TenantContext) -> None:
    """Free text without schema-dot qualification is not blocked."""
    assert_sql_and_params_target_only_connection_tenant(
        "INSERT INTO users_0001.notes_0001 (body) VALUES (%s)",
        ctx_0001,
        ("mentioned users_0002 in chat",),
    )
