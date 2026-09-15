# Position Risk Engine — High Water Scalp LVWAP stop

**Status:** Production-capable for **High Water Scalp** only.  
**Canonical plan:** `.cursor/plans/position-risk-engine-stage2-ats-local.md`

## Behavior

- **ATS is the sole closer.** PRE never imports or calls `trade_manager` / `trade_executor`.
- **High Water Scalp** stop trigger is **gross executable LVWAP vs floor** (`buy_price − stop_loss_offset`).
- Persistence: LVWAP `< floor` for **≥250ms and ≥3** valid book gens. Severity labels are audit-only.
- **High Water Test 1** keeps the legacy opposite-ask floor (not PRE).
- PRE **always autostarts** (local and production). No enable/arm/kill-switch env gates.

## Audit UI

- Page: `/position_risk_audit.html?trade_id=…`
- API: `GET /api/position_risk/audit?trade_id=…&tenant_slot=…`
- JSONL: `backend/data/position_risk/audit/`

## Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/unit/position_risk/ -q
```
