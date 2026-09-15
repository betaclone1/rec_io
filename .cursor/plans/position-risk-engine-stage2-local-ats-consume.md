# SUPERSEDED — do not implement from this file

**Canonical Stage 2 plan:** `.cursor/plans/position-risk-engine-stage2-ats-local.md`

This earlier proposal (`position-risk-engine-stage2-local-ats-consume.md`) used a larger operator surface and incorrect/ambiguous NO liquidation language. Retain only as historical notes. All implementation must follow the canonical plan:

- YES → YES bids; NO → implied NO bids from canonical YES asks
- Three controls only: `position_risk_mode`, `position_risk_policy`, `position_risk_book_only_enabled`
- Gross LVWAP vs floor; fee/slippage/net logged separately
- Catastrophic 3¢ / marginal 250ms+3 gens / hysteresis 2¢+500ms+3 gens inside `hws_lvw_v1`
