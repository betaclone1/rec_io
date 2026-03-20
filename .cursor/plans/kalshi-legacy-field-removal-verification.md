# Kalshi legacy field removal verification

**Goal:** Verify that the removal of Kalshi legacy price/settlement fields (in favor of *_dollars and *_fp variants) has not introduced regressions in fills, settlements, or downstream consumers.
**Scope:** In: fills and settlements sync paths, one end-to-end order flow, and at least one market data path (e.g. ATS or strike tables) that previously read legacy fields. Out: new feature work on Kalshi APIs beyond verification and minor fallbacks.
**Status:** scheduled (earliest: 2026-04-12; allow ~1 month of fixed-point migration runtime before verification)

## Steps
1. Run the Kalshi fills sync and settlements sync against current data; confirm they complete without errors and write rows as expected.
2. Spot-check at least one complete order flow (place order → fill → settlement) and confirm all internal uses read *_dollars / *_fp fields rather than removed legacy fields.
3. Spot-check at least one market data consumer (e.g. ATS or strike-table generator) to ensure it no longer reads removed legacy price fields and behaves correctly with *_dollars / *_fp values.
4. If any 400/500 responses or missing-field errors are observed, add or adjust *_dollars fallbacks in the relevant code paths (orders, markets, watchdog/ATS) and rerun verification.

## Completion criteria
- [ ] Fills and settlements sync jobs run cleanly with no new errors related to legacy field removal.
- [ ] At least one end-to-end order flow has been verified to use *_dollars / *_fp fields only.
- [ ] At least one market data path has been verified to function correctly without legacy fields.
- [ ] Any necessary fallbacks or code adjustments for *_dollars / *_fp fields are implemented and re-verified.

## Blockers / decisions
- Coordinate with live trading windows to avoid disruptive verification during high-risk periods.

